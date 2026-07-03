"""
Gestion Locative - Backend API — TOURÉ IMMOBILIER
FastAPI + SQLAlchemy + SQLite (dev) / PostgreSQL (prod via DATABASE_URL)

Rôles : gérant (accès complet) et propriétaire (accès en lecture à ses propres biens).
Paiements en espèces. Génération de quittance PDF professionnelle après chaque encaissement.
"""
import io
import os
import secrets
import calendar
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import Boolean, Column, Date as SADate, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from sqlalchemy.exc import IntegrityError

try:
    import qrcode
except ImportError:
    qrcode = None

try:
    import requests as http_requests
except ImportError:
    http_requests = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./gestion_locative.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-moi-en-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 jours

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@gestion-locative.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeMoi123")
ADMIN_NOM = os.environ.get("ADMIN_NOM", "TOURÉ")

SOCIETE_NOM = os.environ.get("SOCIETE_NOM", "TOURÉ IMMOBILIER")
SOCIETE_TAGLINE = os.environ.get("SOCIETE_TAGLINE", "Gestion locative professionnelle")
SOCIETE_GERANT = os.environ.get("SOCIETE_GERANT", "M. TOURÉ")
DEVISE = os.environ.get("DEVISE", "FCFA")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# ---------------------------------------------------------------------------
# Modèles SQLAlchemy
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    mot_de_passe_hash = Column(String, nullable=False)
    role = Column(String, default="proprietaire")  # gerant / proprietaire
    reset_token = Column(String, nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)

    maisons = relationship("Maison", back_populates="proprietaire_user")


class Maison(Base):
    __tablename__ = "maisons"
    id = Column(Integer, primary_key=True, index=True)
    adresse = Column(String, nullable=False)
    proprietaire = Column(String, nullable=True)  # nom libre (affichage / historique)
    proprietaire_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    nb_pieces = Column(Integer, default=1)
    loyer_reference = Column(Float, default=0)
    statut = Column(String, default="libre")  # libre / occupee / travaux

    baux = relationship("Bail", back_populates="maison")
    tickets = relationship("Ticket", back_populates="maison")
    proprietaire_user = relationship("User", back_populates="maisons")


class Locataire(Base):
    __tablename__ = "locataires"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String, nullable=False)
    telephone = Column(String, nullable=True)
    piece_identite = Column(String, nullable=True)
    contact_urgence = Column(String, nullable=True)
    archive = Column(Boolean, default=False)  # ancien locataire conservé pour l'historique par maison

    baux = relationship("Bail", back_populates="locataire")


class Bail(Base):
    __tablename__ = "baux"
    id = Column(Integer, primary_key=True, index=True)
    maison_id = Column(Integer, ForeignKey("maisons.id"), nullable=False)
    locataire_id = Column(Integer, ForeignKey("locataires.id"), nullable=False)
    date_debut = Column(SADate, nullable=False)
    date_fin = Column(SADate, nullable=True)
    loyer_mensuel = Column(Float, nullable=False)
    caution = Column(Float, default=0)
    statut = Column(String, default="actif")  # actif / resilie

    maison = relationship("Maison", back_populates="baux")
    locataire = relationship("Locataire", back_populates="baux")
    paiements = relationship("Paiement", back_populates="bail")


class Paiement(Base):
    __tablename__ = "paiements"
    id = Column(Integer, primary_key=True, index=True)
    bail_id = Column(Integer, ForeignKey("baux.id"), nullable=False)
    mois_concerne = Column(String, nullable=False)  # "2026-07"
    montant = Column(Float, nullable=False)
    date_paiement = Column(SADate, nullable=True)
    mode = Column(String, default="especes")
    statut = Column(String, default="en_attente")  # paye / partiel / en_retard / en_attente
    verification_code = Column(String, nullable=True, unique=True)

    bail = relationship("Bail", back_populates="paiements")


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, index=True)
    maison_id = Column(Integer, ForeignKey("maisons.id"), nullable=False)
    locataire_id = Column(Integer, ForeignKey("locataires.id"), nullable=True)
    description = Column(String, nullable=False)
    statut = Column(String, default="ouvert")  # ouvert / en_cours / resolu
    cout = Column(Float, default=0)
    date_creation = Column(DateTime, default=datetime.utcnow)
    date_resolution = Column(DateTime, nullable=True)

    maison = relationship("Maison", back_populates="tickets")


class Depense(Base):
    __tablename__ = "depenses"
    id = Column(Integer, primary_key=True, index=True)
    categorie = Column(String, nullable=False)  # salaire_gerant / entretien / taxes / autre ...
    libelle = Column(String, nullable=False)
    montant = Column(Float, nullable=False)
    date_depense = Column(SADate, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Observation(Base):
    __tablename__ = "observations"
    id = Column(Integer, primary_key=True, index=True)
    proprietaire_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    maison_id = Column(Integer, ForeignKey("maisons.id"), nullable=True)
    message = Column(String, nullable=False)
    date_creation = Column(DateTime, default=datetime.utcnow)
    lu = Column(Boolean, default=False)
    reponse = Column(String, nullable=True)
    date_reponse = Column(DateTime, nullable=True)

    proprietaire = relationship("User")
    maison = relationship("Maison")


Base.metadata.create_all(bind=engine)

# Migration légère : ajoute les colonnes manquantes si les tables existaient déjà sans elles.
# Compatible SQLite (dev) et PostgreSQL (prod sur Render) — utilise l'inspecteur SQLAlchemy
# plutôt que PRAGMA (spécifique SQLite) pour fonctionner quel que soit le moteur de base.
try:
    from sqlalchemy import inspect as _sa_inspect

    _inspector = _sa_inspect(engine)
    _existing_tables = _inspector.get_table_names()

    def _add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
        if table not in _existing_tables:
            return
        try:
            cols = [c["name"] for c in _inspector.get_columns(table)]
        except Exception:
            return
        if column in cols:
            return
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        except Exception:
            pass

    _add_column_if_missing("maisons", "proprietaire_id", "INTEGER")
    _add_column_if_missing("paiements", "verification_code", "VARCHAR")
    _add_column_if_missing("locataires", "archive", "BOOLEAN")
    _add_column_if_missing("users", "reset_token", "VARCHAR")
    _add_column_if_missing("users", "reset_token_expiry", "TIMESTAMP")
except Exception:
    pass


# ---------------------------------------------------------------------------
# Schémas Pydantic
# ---------------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserIn(BaseModel):
    nom: str
    email: str
    password: str
    role: str = "proprietaire"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    email: str
    role: str


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class MaisonIn(BaseModel):
    adresse: str
    proprietaire: Optional[str] = None
    proprietaire_id: Optional[int] = None
    nb_pieces: int = 1
    loyer_reference: float = 0
    statut: str = "libre"


class MaisonOut(MaisonIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LocataireIn(BaseModel):
    nom: str
    telephone: Optional[str] = None
    piece_identite: Optional[str] = None
    contact_urgence: Optional[str] = None


class LocataireOut(LocataireIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    archive: bool = False


class BailIn(BaseModel):
    maison_id: int
    locataire_id: int
    date_debut: date
    date_fin: Optional[date] = None
    loyer_mensuel: float
    caution: float = 0
    statut: str = "actif"


class BailOut(BailIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PaiementIn(BaseModel):
    bail_id: int
    mois_concerne: str
    montant: float
    date_paiement: Optional[date] = None
    mode: str = "especes"
    statut: str = "paye"


class PaiementOut(PaiementIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TicketIn(BaseModel):
    maison_id: int
    locataire_id: Optional[int] = None
    description: str
    statut: str = "ouvert"
    cout: float = 0


class TicketOut(TicketIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date_creation: datetime
    date_resolution: Optional[datetime] = None


class DepenseIn(BaseModel):
    categorie: str
    libelle: str
    montant: float
    date_depense: date


class DepenseOut(DepenseIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ObservationIn(BaseModel):
    maison_id: Optional[int] = None
    message: str


class ObservationReponseIn(BaseModel):
    reponse: str


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    proprietaire_id: int
    maison_id: Optional[int] = None
    message: str
    date_creation: datetime
    lu: bool
    reponse: Optional[str] = None
    date_reponse: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Utilitaires auth
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Identifiants invalides",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


def require_gerant(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "gerant":
        raise HTTPException(status_code=403, detail="Réservé au gérant")
    return current_user


def owned_maison_ids(db: Session, user: User) -> List[int]:
    return [m.id for m in db.query(Maison.id).filter(Maison.proprietaire_id == user.id).all()]


def generate_verification_code() -> str:
    return secrets.token_hex(8)  # 16 caractères hexadécimaux


def mois_precedent(mois: str) -> str:
    annee, m = (int(x) for x in mois.split("-"))
    if m == 1:
        return f"{annee - 1}-12"
    return f"{annee}-{m - 1:02d}"


def ensure_default_admin():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == ADMIN_EMAIL).first():
            admin = User(
                nom=ADMIN_NOM,
                email=ADMIN_EMAIL,
                mot_de_passe_hash=pwd_context.hash(ADMIN_PASSWORD),
                role="gerant",
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Gestion Locative — TOURÉ IMMOBILIER")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_default_admin()


@app.post("/api/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.mot_de_passe_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    token = create_access_token({"sub": user.email})
    return Token(access_token=token)


@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "nom": current_user.nom, "email": current_user.email, "role": current_user.role}


# ---------- Mot de passe oublié (auto-service) ----------
@app.post("/api/auth/forgot-password")
def forgot_password(data: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(404, "Aucun compte trouvé avec cet email.")
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    # Reconstruit l'URL publique en tenant compte du proxy Render (voir quittance_pdf pour le même souci https/http).
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    base_url = f"{proto}://{host}"
    reset_url = f"{base_url}/reset-password.html?token={token}"
    return {"reset_url": reset_url, "expire_dans_minutes": 60}


@app.post("/api/auth/reset-password")
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == data.token).first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        raise HTTPException(400, "Lien de réinitialisation invalide ou expiré. Refaites une demande.")
    if len(data.new_password) < 4:
        raise HTTPException(400, "Le mot de passe doit contenir au moins 4 caractères.")
    user.mot_de_passe_hash = pwd_context.hash(data.new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.commit()
    return {"ok": True}


# ---------- Utilisateurs (gérant uniquement) ----------
@app.get("/api/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    return db.query(User).order_by(User.id).all()


@app.post("/api/users", response_model=UserOut)
def create_user(data: UserIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Cet email est déjà utilisé")
    if data.role not in ("gerant", "proprietaire"):
        raise HTTPException(400, "Rôle invalide")
    user = User(
        nom=data.nom,
        email=data.email,
        mot_de_passe_hash=pwd_context.hash(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    if user_id == current.id:
        raise HTTPException(400, "Impossible de supprimer votre propre compte")
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    db.query(Maison).filter(Maison.proprietaire_id == user_id).update({"proprietaire_id": None, "proprietaire": None})
    db.delete(user)
    db.commit()
    return {"ok": True}


# ---------- Maisons ----------
@app.get("/api/maisons", response_model=List[MaisonOut])
def list_maisons(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Maison)
    if current_user.role == "proprietaire":
        q = q.filter(Maison.proprietaire_id == current_user.id)
    return q.all()


@app.post("/api/maisons", response_model=MaisonOut)
def create_maison(data: MaisonIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    payload = data.model_dump()
    if payload.get("proprietaire_id") and not payload.get("proprietaire"):
        owner = db.query(User).get(payload["proprietaire_id"])
        if owner:
            payload["proprietaire"] = owner.nom
    maison = Maison(**payload)
    db.add(maison)
    db.commit()
    db.refresh(maison)
    return maison


@app.put("/api/maisons/{maison_id}", response_model=MaisonOut)
def update_maison(maison_id: int, data: MaisonIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    maison = db.query(Maison).get(maison_id)
    if not maison:
        raise HTTPException(404, "Maison introuvable")
    payload = data.model_dump()
    if payload.get("proprietaire_id") and not payload.get("proprietaire"):
        owner = db.query(User).get(payload["proprietaire_id"])
        if owner:
            payload["proprietaire"] = owner.nom
    for k, v in payload.items():
        setattr(maison, k, v)
    db.commit()
    db.refresh(maison)
    return maison


@app.delete("/api/maisons/{maison_id}")
def delete_maison(maison_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    maison = db.query(Maison).get(maison_id)
    if not maison:
        raise HTTPException(404, "Maison introuvable")
    try:
        db.delete(maison)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Impossible de supprimer cette maison : elle a encore des baux ou des tickets liés. Supprimez-les (ou résiliez les baux) avant de continuer.")
    return {"ok": True}


# ---------- Locataires ----------
@app.get("/api/locataires", response_model=List[LocataireOut])
def list_locataires(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "proprietaire":
        maison_ids = owned_maison_ids(db, current_user)
        locataire_ids = {b.locataire_id for b in db.query(Bail).filter(Bail.maison_id.in_(maison_ids)).all()}
        return db.query(Locataire).filter(Locataire.id.in_(locataire_ids)).all()
    return db.query(Locataire).all()


@app.post("/api/locataires", response_model=LocataireOut)
def create_locataire(data: LocataireIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    locataire = Locataire(**data.model_dump())
    db.add(locataire)
    db.commit()
    db.refresh(locataire)
    return locataire


@app.put("/api/locataires/{locataire_id}", response_model=LocataireOut)
def update_locataire(locataire_id: int, data: LocataireIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    locataire = db.query(Locataire).get(locataire_id)
    if not locataire:
        raise HTTPException(404, "Locataire introuvable")
    for k, v in data.model_dump().items():
        setattr(locataire, k, v)
    db.commit()
    db.refresh(locataire)
    return locataire


@app.delete("/api/locataires/{locataire_id}")
def delete_locataire(locataire_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    locataire = db.query(Locataire).get(locataire_id)
    if not locataire:
        raise HTTPException(404, "Locataire introuvable")
    a_des_baux = db.query(Bail).filter(Bail.locataire_id == locataire_id).first() is not None
    if a_des_baux:
        # On ne supprime pas réellement : on archive, pour conserver la trace de ce locataire
        # dans l'historique des occupants de la ou des maisons concernées.
        locataire.archive = True
        db.commit()
        return {"ok": True, "archive": True}
    try:
        db.delete(locataire)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Impossible de supprimer ce locataire.")
    return {"ok": True, "archive": False}


# ---------- Historique des locataires (anciens occupants) ----------
@app.get("/api/historique-locataires")
def historique_locataires(maison_id: Optional[int] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Bail).join(Locataire, Bail.locataire_id == Locataire.id).filter(Locataire.archive == True)
    if current_user.role == "proprietaire":
        maison_ids = owned_maison_ids(db, current_user)
        q = q.filter(Bail.maison_id.in_(maison_ids))
    if maison_id:
        q = q.filter(Bail.maison_id == maison_id)
    resultats = []
    for bail in q.order_by(Bail.date_debut.desc()).all():
        loc = db.query(Locataire).get(bail.locataire_id)
        maison = db.query(Maison).get(bail.maison_id)
        resultats.append({
            "locataire_id": loc.id if loc else None,
            "nom": loc.nom if loc else "—",
            "telephone": loc.telephone if loc else None,
            "piece_identite": loc.piece_identite if loc else None,
            "maison_id": bail.maison_id,
            "adresse": maison.adresse if maison else "—",
            "date_debut": bail.date_debut,
            "date_fin": bail.date_fin,
            "statut_bail": bail.statut,
        })
    return resultats


# ---------- Baux ----------
@app.get("/api/baux", response_model=List[BailOut])
def list_baux(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Bail)
    if current_user.role == "proprietaire":
        maison_ids = owned_maison_ids(db, current_user)
        q = q.filter(Bail.maison_id.in_(maison_ids))
    return q.all()


@app.post("/api/baux", response_model=BailOut)
def create_bail(data: BailIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    if data.statut == "actif":
        bail_existant = db.query(Bail).filter(Bail.maison_id == data.maison_id, Bail.statut == "actif").first()
        if bail_existant:
            raise HTTPException(409, "Cette maison a déjà un bail actif. Résiliez-le avant d'en créer un nouveau.")
    bail = Bail(**data.model_dump())
    db.add(bail)
    maison = db.query(Maison).get(data.maison_id)
    if maison:
        maison.statut = "occupee"
    db.commit()
    db.refresh(bail)
    return bail


@app.put("/api/baux/{bail_id}", response_model=BailOut)
def update_bail(bail_id: int, data: BailIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    bail = db.query(Bail).get(bail_id)
    if not bail:
        raise HTTPException(404, "Bail introuvable")
    for k, v in data.model_dump().items():
        setattr(bail, k, v)
    if data.statut == "resilie":
        maison = db.query(Maison).get(data.maison_id)
        if maison:
            maison.statut = "libre"
    db.commit()
    db.refresh(bail)
    return bail


@app.delete("/api/baux/{bail_id}")
def delete_bail(bail_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    bail = db.query(Bail).get(bail_id)
    if not bail:
        raise HTTPException(404, "Bail introuvable")
    try:
        db.delete(bail)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Impossible de supprimer ce bail : des paiements y sont rattachés. Supprimez-les d'abord (ou conservez le bail pour l'historique).")
    return {"ok": True}


# ---------- Paiements ----------
@app.get("/api/paiements", response_model=List[PaiementOut])
def list_paiements(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Paiement)
    if current_user.role == "proprietaire":
        maison_ids = owned_maison_ids(db, current_user)
        bail_ids = [b.id for b in db.query(Bail.id).filter(Bail.maison_id.in_(maison_ids)).all()]
        q = q.join(Bail).filter(Paiement.bail_id.in_(bail_ids))
    return q.all()


@app.post("/api/paiements", response_model=PaiementOut)
def create_paiement(data: PaiementIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    paiement = Paiement(**data.model_dump())
    paiement.verification_code = generate_verification_code()
    db.add(paiement)
    db.commit()
    db.refresh(paiement)
    return paiement


# ---------- Génération PDF — quittance professionnelle ----------
FRENCH_UNITS = ["", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
                "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
FRENCH_TENS = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante", "soixante-dix", "quatre-vingt", "quatre-vingt-dix"]


def _below_100_en_lettres(n: int) -> str:
    if n < 20:
        return FRENCH_UNITS[n]
    dizaine, unite = divmod(n, 10)
    if dizaine in (7, 9):
        dizaine -= 1
        unite += 10
    mot = FRENCH_TENS[dizaine]
    if unite == 1 and dizaine not in (8,):
        mot += " et un"
    elif unite:
        mot += "-" + FRENCH_UNITS[unite]
    if dizaine == 8 and unite == 0:
        mot += "s"
    return mot


def _below_1000_en_lettres(n: int) -> str:
    centaine, reste = divmod(n, 100)
    mot = ""
    if centaine:
        mot += ("cent" if centaine == 1 else FRENCH_UNITS[centaine] + " cent")
        if reste == 0 and centaine > 1:
            mot += "s"
    if reste:
        mot += (" " if mot else "") + _below_100_en_lettres(reste)
    return mot or "zéro"


def montant_en_lettres(montant: float) -> str:
    n = int(round(montant))
    if n == 0:
        return "zéro"
    parts = []
    millions, reste = divmod(n, 1_000_000)
    milliers, unites = divmod(reste, 1000)
    if millions:
        parts.append(("un million" if millions == 1 else _below_1000_en_lettres(millions) + " millions"))
    if milliers:
        parts.append(("mille" if milliers == 1 else _below_1000_en_lettres(milliers) + " mille"))
    if unites or not parts:
        parts.append(_below_1000_en_lettres(unites))
    return " ".join(parts).strip()


NAVY = colors.HexColor("#12314F")
NAVY_DARK = colors.HexColor("#0B1F35")
GOLD = colors.HexColor("#C9A227")
LIGHT = colors.HexColor("#F4F6F8")
BORDER = colors.HexColor("#D6DCE3")
TEXT_DARK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")


def generer_quittance_pdf(paiement, bail, maison, locataire, verify_url: str = "") -> io.BytesIO:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 15 * mm

    # Cadre général
    c.setStrokeColor(BORDER)
    c.setLineWidth(1)
    c.rect(margin - 6, margin - 6, width - 2 * (margin - 6), height - 2 * (margin - 6))

    # Bandeau d'en-tête
    header_h = 32 * mm
    c.setFillColor(NAVY)
    c.rect(0, height - header_h, width, header_h, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(0, height - header_h - 2, width, 2, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(margin, height - 15 * mm, SOCIETE_NOM)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(margin, height - 21 * mm, SOCIETE_TAGLINE)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(width - margin, height - 14 * mm, "QUITTANCE DE LOYER")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin, height - 20 * mm, f"N° {paiement.id:05d}")
    c.drawRightString(width - margin, height - 25 * mm, f"Émise le {date.today().strftime('%d/%m/%Y')}")

    y = height - header_h - 12 * mm

    # Boîtes Bailleur / Locataire
    box_w = (width - 2 * margin - 8) / 2
    box_h = 30 * mm
    for i, (titre, lignes) in enumerate([
        ("BAILLEUR", [
            SOCIETE_NOM,
            f"Représenté par {SOCIETE_GERANT}",
            "Gestionnaire du bien loué",
        ]),
        ("LOCATAIRE", [
            locataire.nom if locataire else "-",
            f"Tél. : {locataire.telephone}" if locataire and locataire.telephone else "Tél. : -",
            f"Pièce d'identité : {locataire.piece_identite}" if locataire and locataire.piece_identite else "Pièce d'identité : -",
        ]),
    ]):
        x = margin + i * (box_w + 8)
        c.setFillColor(LIGHT)
        c.setStrokeColor(BORDER)
        c.roundRect(x, y - box_h, box_w, box_h, 4, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + 8, y - 10, titre)
        c.setFillColor(TEXT_DARK)
        c.setFont("Helvetica", 9.5)
        ly = y - 22
        for ligne in lignes:
            c.drawString(x + 8, ly, ligne)
            ly -= 13

    y -= box_h + 10 * mm

    # Bien loué
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, y, "BIEN LOUÉ")
    y -= 14
    c.setFillColor(TEXT_DARK)
    c.setFont("Helvetica", 9.5)
    c.drawString(margin, y, f"Adresse : {maison.adresse if maison else '-'}")
    y -= 20

    # Tableau détail paiement
    table_top = y
    col_x = [margin, margin + 90 * mm, margin + 140 * mm, width - margin]
    row_h = 9 * mm

    c.setFillColor(NAVY)
    c.rect(margin, table_top - row_h, width - 2 * margin, row_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(col_x[0] + 6, table_top - row_h + 6.5, "Désignation")
    c.drawString(col_x[1] + 6, table_top - row_h + 6.5, "Période")
    c.drawRightString(col_x[3] - 6, table_top - row_h + 6.5, f"Montant ({DEVISE})")

    y2 = table_top - row_h
    c.setFillColor(colors.white)
    c.setStrokeColor(BORDER)
    c.rect(margin, y2 - row_h, width - 2 * margin, row_h, stroke=1, fill=1)
    c.setFillColor(TEXT_DARK)
    c.setFont("Helvetica", 9.5)
    c.drawString(col_x[0] + 6, y2 - row_h + 6.5, "Loyer mensuel")
    c.drawString(col_x[1] + 6, y2 - row_h + 6.5, paiement.mois_concerne)
    c.drawRightString(col_x[3] - 6, y2 - row_h + 6.5, f"{paiement.montant:,.0f}".replace(",", " "))

    y3 = y2 - row_h
    c.setFillColor(LIGHT)
    c.rect(margin, y3 - row_h, width - 2 * margin, row_h, stroke=1, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_x[0] + 6, y3 - row_h + 6.5, "TOTAL PAYÉ")
    c.drawRightString(col_x[3] - 6, y3 - row_h + 6.5, f"{paiement.montant:,.0f} {DEVISE}".replace(",", " "))

    y = y3 - row_h - 8 * mm

    c.setFillColor(TEXT_DARK)
    c.setFont("Helvetica-Oblique", 9)
    lettres = montant_en_lettres(paiement.montant)
    c.drawString(margin, y, f"Arrêtée la présente quittance à la somme de : {lettres} {DEVISE}.")
    y -= 16

    c.setFont("Helvetica", 9.5)
    mode_lisible = {"especes": "Espèces", "mobile_money": "Mobile money", "virement": "Virement"}.get(paiement.mode, paiement.mode)
    c.drawString(margin, y, f"Mode de paiement : {mode_lisible}      Date de paiement : {paiement.date_paiement or '-'}      Statut : {paiement.statut}")
    y -= 26

    # Mentions légales + signature
    c.setStrokeColor(BORDER)
    c.line(margin, y, width - margin, y)
    y -= 14
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawString(margin, y, "Cette quittance annule tous les reçus provisoires établis précédemment pour la même période.")
    y -= 10
    c.drawString(margin, y, "À conserver pendant trois ans (délai de prescription légale en matière de loyers).")
    y -= 22

    c.setFillColor(TEXT_DARK)
    c.setFont("Helvetica", 9)
    c.drawString(margin, y, f"Fait le {date.today().strftime('%d/%m/%Y')}")
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(width - margin, y, "Signature du gérant")
    y -= 28
    c.setStrokeColor(BORDER)
    c.line(width - margin - 60 * mm, y, width - margin, y)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(width - margin, y - 10, SOCIETE_GERANT)

    # QR code d'authenticité — placé sous le bloc signature, avec une marge de sécurité
    # pour ne chevaucher ni le texte "Fait le...", ni la ligne de signature.
    bas_bloc_signature = y - 10
    if qrcode is not None and verify_url:
        try:
            qr_img = qrcode.make(verify_url, box_size=4, border=1)
            qr_buf = io.BytesIO()
            qr_img.save(qr_buf, format="PNG")
            qr_buf.seek(0)
            qr_size = 22 * mm
            qr_x = margin
            qr_y = bas_bloc_signature - 12 * mm - qr_size
            if qr_y - 17 < margin:
                qr_y = margin + 17
            c.drawImage(ImageReader(qr_buf), qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 6.5)
            c.drawString(qr_x, qr_y - 9, "Scannez pour vérifier")
            c.drawString(qr_x, qr_y - 17, "l'authenticité du document")
        except Exception:
            pass

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


@app.get("/api/paiements/{paiement_id}/quittance")
def quittance_pdf(paiement_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    paiement = db.query(Paiement).get(paiement_id)
    if not paiement:
        raise HTTPException(404, "Paiement introuvable")
    bail = db.query(Bail).get(paiement.bail_id)
    maison = db.query(Maison).get(bail.maison_id) if bail else None
    locataire = db.query(Locataire).get(bail.locataire_id) if bail else None

    if current_user.role == "proprietaire":
        if not maison or maison.proprietaire_id != current_user.id:
            raise HTTPException(403, "Accès refusé à ce document")

    if not paiement.verification_code:
        paiement.verification_code = generate_verification_code()
        db.commit()
        db.refresh(paiement)

    # Render termine le HTTPS au niveau du proxy et transmet la requête en HTTP en interne :
    # sans ceci, l'URL encodée dans le QR code commence par http:// (non sécurisé), ce qui
    # déclenche l'avertissement "site dangereux" de certains scanners de QR code.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    base_url = f"{proto}://{host}"
    verify_url = f"{base_url}/verifier.html?code={paiement.verification_code}"

    buffer = generer_quittance_pdf(paiement, bail, maison, locataire, verify_url)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=quittance_{paiement.id}.pdf"},
    )


@app.get("/api/verifier/{code}")
def verifier_quittance(code: str, db: Session = Depends(get_db)):
    paiement = db.query(Paiement).filter(Paiement.verification_code == code).first()
    if not paiement:
        return {"valide": False}
    bail = db.query(Bail).get(paiement.bail_id)
    maison = db.query(Maison).get(bail.maison_id) if bail else None
    locataire = db.query(Locataire).get(bail.locataire_id) if bail else None
    return {
        "valide": True,
        "societe": SOCIETE_NOM,
        "quittance_id": paiement.id,
        "locataire": locataire.nom if locataire else "-",
        "maison": maison.adresse if maison else "-",
        "mois_concerne": paiement.mois_concerne,
        "montant": paiement.montant,
        "devise": DEVISE,
        "date_paiement": str(paiement.date_paiement) if paiement.date_paiement else None,
        "mode": paiement.mode,
        "statut": paiement.statut,
    }


# ---------- Tickets maintenance ----------
@app.get("/api/tickets", response_model=List[TicketOut])
def list_tickets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Ticket)
    if current_user.role == "proprietaire":
        maison_ids = owned_maison_ids(db, current_user)
        q = q.filter(Ticket.maison_id.in_(maison_ids))
    return q.all()


@app.post("/api/tickets", response_model=TicketOut)
def create_ticket(data: TicketIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    ticket = Ticket(**data.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.put("/api/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, data: TicketIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    ticket = db.query(Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket introuvable")
    for k, v in data.model_dump().items():
        setattr(ticket, k, v)
    if data.statut == "resolu" and not ticket.date_resolution:
        ticket.date_resolution = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return ticket


@app.delete("/api/tickets/{ticket_id}")
def delete_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    ticket = db.query(Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket introuvable")
    db.delete(ticket)
    db.commit()
    return {"ok": True}


# ---------- Dépenses (gérant uniquement) ----------
@app.get("/api/depenses", response_model=List[DepenseOut])
def list_depenses(db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    return db.query(Depense).order_by(Depense.date_depense.desc()).all()


@app.post("/api/depenses", response_model=DepenseOut)
def create_depense(data: DepenseIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    depense = Depense(**data.model_dump())
    db.add(depense)
    db.commit()
    db.refresh(depense)
    return depense


@app.put("/api/depenses/{depense_id}", response_model=DepenseOut)
def update_depense(depense_id: int, data: DepenseIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    depense = db.query(Depense).get(depense_id)
    if not depense:
        raise HTTPException(404, "Dépense introuvable")
    for k, v in data.model_dump().items():
        setattr(depense, k, v)
    db.commit()
    db.refresh(depense)
    return depense


@app.delete("/api/depenses/{depense_id}")
def delete_depense(depense_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    depense = db.query(Depense).get(depense_id)
    if not depense:
        raise HTTPException(404, "Dépense introuvable")
    db.delete(depense)
    db.commit()
    return {"ok": True}


# ---------- Observations (messages propriétaire -> gérant) ----------
@app.get("/api/observations", response_model=List[ObservationOut])
def list_observations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Observation)
    if current_user.role == "proprietaire":
        q = q.filter(Observation.proprietaire_id == current_user.id)
    return q.order_by(Observation.date_creation.desc()).all()


@app.post("/api/observations", response_model=ObservationOut)
def create_observation(data: ObservationIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "proprietaire":
        raise HTTPException(403, "Réservé aux propriétaires")
    if data.maison_id:
        maison = db.query(Maison).get(data.maison_id)
        if not maison or maison.proprietaire_id != current_user.id:
            raise HTTPException(403, "Ce bien ne vous appartient pas")
    observation = Observation(proprietaire_id=current_user.id, maison_id=data.maison_id, message=data.message)
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return observation


@app.put("/api/observations/{observation_id}/repondre", response_model=ObservationOut)
def repondre_observation(observation_id: int, data: ObservationReponseIn, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    observation = db.query(Observation).get(observation_id)
    if not observation:
        raise HTTPException(404, "Observation introuvable")
    observation.reponse = data.reponse
    observation.date_reponse = datetime.utcnow()
    observation.lu = True
    db.commit()
    db.refresh(observation)
    return observation


@app.put("/api/observations/{observation_id}/lu", response_model=ObservationOut)
def marquer_lu_observation(observation_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    observation = db.query(Observation).get(observation_id)
    if not observation:
        raise HTTPException(404, "Observation introuvable")
    observation.lu = True
    db.commit()
    db.refresh(observation)
    return observation


@app.delete("/api/observations/{observation_id}")
def delete_observation(observation_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    observation = db.query(Observation).get(observation_id)
    if not observation:
        raise HTTPException(404, "Observation introuvable")
    db.delete(observation)
    db.commit()
    return {"ok": True}


# ---------- Tableau de bord ----------
@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    mois_courant = date.today().strftime("%Y-%m")
    is_owner = current_user.role == "proprietaire"
    maison_ids = owned_maison_ids(db, current_user) if is_owner else None

    q_maisons = db.query(Maison)
    if is_owner:
        q_maisons = q_maisons.filter(Maison.id.in_(maison_ids))
    total_maisons = q_maisons.count()
    maisons_occupees = q_maisons.filter(Maison.statut == "occupee").count()

    q_paiements_mois = db.query(Paiement).filter(Paiement.mois_concerne == mois_courant)
    q_baux_actifs = db.query(Bail).filter(Bail.statut == "actif")
    q_tickets_ouverts = db.query(Ticket).filter(Ticket.statut != "resolu")
    if is_owner:
        q_baux_actifs = q_baux_actifs.filter(Bail.maison_id.in_(maison_ids))
        bail_ids_owner = [b.id for b in q_baux_actifs.all()]
        q_paiements_mois = q_paiements_mois.filter(Paiement.bail_id.in_(bail_ids_owner))
        q_tickets_ouverts = q_tickets_ouverts.filter(Ticket.maison_id.in_(maison_ids))

    paiements_mois = q_paiements_mois.all()
    total_encaisse = sum(p.montant for p in paiements_mois if p.statut == "paye")

    baux_actifs = q_baux_actifs.all()
    total_attendu = sum(b.loyer_mensuel for b in baux_actifs)

    bail_ids_payes = {p.bail_id for p in paiements_mois if p.statut == "paye"}
    impayes = [b for b in baux_actifs if b.id not in bail_ids_payes]

    tickets_ouverts = q_tickets_ouverts.count()

    return {
        "mois": mois_courant,
        "total_maisons": total_maisons,
        "maisons_occupees": maisons_occupees,
        "taux_occupation": round(maisons_occupees / total_maisons * 100, 1) if total_maisons else 0,
        "total_attendu": total_attendu,
        "total_encaisse": total_encaisse,
        "nombre_impayes": len(impayes),
        "impayes": [
            {"bail_id": b.id, "maison_id": b.maison_id, "locataire_id": b.locataire_id, "loyer_mensuel": b.loyer_mensuel}
            for b in impayes
        ],
        "tickets_ouverts": tickets_ouverts,
    }


# ---------- Évolution mensuelle (pour graphique dashboard) ----------
def _mois_range(n: int) -> List[str]:
    """Retourne les n derniers mois (dont le mois courant), du plus ancien au plus récent, format AAAA-MM."""
    today = date.today()
    mois_list = []
    annee, m = today.year, today.month
    for _ in range(n):
        mois_list.append(f"{annee}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            annee -= 1
    return list(reversed(mois_list))


@app.get("/api/dashboard/evolution")
def dashboard_evolution(mois: int = 6, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    is_owner = current_user.role == "proprietaire"
    maison_ids = owned_maison_ids(db, current_user) if is_owner else None

    q_baux_actifs = db.query(Bail).filter(Bail.statut == "actif")
    if is_owner:
        q_baux_actifs = q_baux_actifs.filter(Bail.maison_id.in_(maison_ids))
    bail_ids = [b.id for b in q_baux_actifs.all()]
    total_attendu = sum(b.loyer_mensuel for b in q_baux_actifs.all())

    resultats = []
    for m in _mois_range(max(1, min(mois, 24))):
        q = db.query(Paiement).filter(Paiement.mois_concerne == m, Paiement.bail_id.in_(bail_ids) if bail_ids else False)
        paiements_mois = q.all()
        total_encaisse = sum(p.montant for p in paiements_mois if p.statut == "paye")
        taux = round(total_encaisse / total_attendu * 100, 1) if total_attendu else 0
        resultats.append({
            "mois": m,
            "total_attendu": total_attendu,
            "total_encaisse": total_encaisse,
            "taux_encaissement": taux,
        })
    return resultats


# ---------- Bilan mensuel (analyse assistée par IA) ----------
def analyse_reglebasee(stats: dict) -> str:
    phrases = []
    taux = stats["taux_encaissement"]
    if taux >= 95:
        phrases.append(f"Le taux d'encaissement du mois est excellent ({taux}%), les loyers ont été majoritairement recouvrés dans les délais.")
    elif taux >= 75:
        phrases.append(f"Le taux d'encaissement du mois est correct ({taux}%), mais une partie des loyers reste à recouvrer.")
    else:
        phrases.append(f"Le taux d'encaissement du mois est préoccupant ({taux}%) : une part importante des loyers attendus n'a pas été encaissée.")

    if stats["nombre_impayes"] > 0:
        phrases.append(f"{stats['nombre_impayes']} bail(aux) actif(s) présentent un impayé ce mois-ci ; un suivi rapproché des locataires concernés est recommandé.")
    else:
        phrases.append("Aucun impayé n'est à signaler ce mois-ci.")

    if stats["resultat_net"] >= 0:
        phrases.append(f"Après déduction des dépenses ({stats['total_depenses']:.0f} {DEVISE}), le résultat net du mois est positif : {stats['resultat_net']:.0f} {DEVISE}.")
    else:
        phrases.append(f"Après déduction des dépenses ({stats['total_depenses']:.0f} {DEVISE}), le résultat net du mois est négatif : {stats['resultat_net']:.0f} {DEVISE}. Une vigilance sur les charges est conseillée.")

    var = stats.get("variation_encaisse_pct")
    if var is not None:
        if var > 5:
            phrases.append(f"Les encaissements progressent de {var}% par rapport au mois précédent.")
        elif var < -5:
            phrases.append(f"Les encaissements reculent de {abs(var)}% par rapport au mois précédent, à surveiller.")
        else:
            phrases.append("Les encaissements sont globalement stables par rapport au mois précédent.")

    if stats["tickets_ouverts_periode"] > 0:
        phrases.append(f"{stats['tickets_ouverts_periode']} ticket(s) de maintenance ont été ouverts ce mois-ci, pour un coût cumulé de {stats['cout_tickets_mois']:.0f} {DEVISE}.")

    return " ".join(phrases)


def analyse_ia(stats: dict) -> Optional[str]:
    if not ANTHROPIC_API_KEY or http_requests is None:
        return None
    try:
        prompt = (
            "Tu es un assistant de gestion locative. Rédige une analyse concise (4 à 6 phrases, en français) "
            "du bilan mensuel suivant, avec un ton professionnel destiné au gérant d'un parc immobilier. "
            "Mets en avant les points positifs, les points de vigilance (impayés, résultat net, évolution) "
            "et une recommandation concrète si pertinent. Ne répète pas les chiffres bruts sans les interpréter.\n\n"
            f"Données du mois {stats['mois']} :\n"
            f"- Loyers attendus : {stats['total_attendu']} {DEVISE}\n"
            f"- Loyers encaissés : {stats['total_encaisse']} {DEVISE}\n"
            f"- Taux d'encaissement : {stats['taux_encaissement']}%\n"
            f"- Nombre d'impayés : {stats['nombre_impayes']}\n"
            f"- Dépenses du mois : {stats['total_depenses']} {DEVISE}\n"
            f"- Résultat net : {stats['resultat_net']} {DEVISE}\n"
            f"- Variation des encaissements vs mois précédent : {stats.get('variation_encaisse_pct')}%\n"
            f"- Tickets de maintenance ouverts ce mois : {stats['tickets_ouverts_periode']} (coût : {stats['cout_tickets_mois']} {DEVISE})\n"
            f"- Taux d'occupation actuel du parc : {stats['taux_occupation']}%\n"
        )
        resp = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            blocks = data.get("content", [])
            texte = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return texte.strip() or None
    except Exception:
        return None
    return None


@app.get("/api/bilan/{mois}")
def bilan_mensuel(mois: str, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    total_maisons = db.query(Maison).count()
    maisons_occupees = db.query(Maison).filter(Maison.statut == "occupee").count()
    taux_occupation = round(maisons_occupees / total_maisons * 100, 1) if total_maisons else 0

    baux_actifs = db.query(Bail).filter(Bail.statut == "actif").all()
    total_attendu = sum(b.loyer_mensuel for b in baux_actifs)

    paiements_mois = db.query(Paiement).filter(Paiement.mois_concerne == mois).all()
    total_encaisse = sum(p.montant for p in paiements_mois if p.statut == "paye")
    taux_encaissement = round(total_encaisse / total_attendu * 100, 1) if total_attendu else 0

    bail_ids_payes = {p.bail_id for p in paiements_mois if p.statut == "paye"}
    impayes = [b for b in baux_actifs if b.id not in bail_ids_payes]

    try:
        annee, m = (int(x) for x in mois.split("-"))
        premier_jour = date(annee, m, 1)
        dernier_jour = date(annee, m, calendar.monthrange(annee, m)[1])
    except Exception:
        raise HTTPException(400, "Format de mois invalide (attendu AAAA-MM)")

    depenses_mois = db.query(Depense).filter(Depense.date_depense >= premier_jour, Depense.date_depense <= dernier_jour).all()
    total_depenses = sum(d.montant for d in depenses_mois)
    depenses_par_categorie = {}
    for d in depenses_mois:
        depenses_par_categorie[d.categorie] = depenses_par_categorie.get(d.categorie, 0) + d.montant

    resultat_net = total_encaisse - total_depenses

    tickets_mois = db.query(Ticket).filter(Ticket.date_creation >= datetime.combine(premier_jour, datetime.min.time()),
                                            Ticket.date_creation <= datetime.combine(dernier_jour, datetime.max.time())).all()
    cout_tickets_mois = sum(t.cout for t in tickets_mois)

    mois_prec = mois_precedent(mois)
    paiements_mois_prec = db.query(Paiement).filter(Paiement.mois_concerne == mois_prec, Paiement.statut == "paye").all()
    total_encaisse_prec = sum(p.montant for p in paiements_mois_prec)
    variation_encaisse_pct = round((total_encaisse - total_encaisse_prec) / total_encaisse_prec * 100, 1) if total_encaisse_prec else None

    stats = {
        "mois": mois,
        "total_maisons": total_maisons,
        "taux_occupation": taux_occupation,
        "total_attendu": total_attendu,
        "total_encaisse": total_encaisse,
        "taux_encaissement": taux_encaissement,
        "nombre_impayes": len(impayes),
        "impayes": [
            {"bail_id": b.id, "maison_id": b.maison_id, "locataire_id": b.locataire_id, "loyer_mensuel": b.loyer_mensuel}
            for b in impayes
        ],
        "total_depenses": total_depenses,
        "depenses_par_categorie": depenses_par_categorie,
        "resultat_net": resultat_net,
        "tickets_ouverts_periode": len(tickets_mois),
        "cout_tickets_mois": cout_tickets_mois,
        "variation_encaisse_pct": variation_encaisse_pct,
    }

    analyse = analyse_ia(stats)
    source_analyse = "ia"
    if not analyse:
        analyse = analyse_reglebasee(stats)
        source_analyse = "regles"

    stats["analyse"] = analyse
    stats["analyse_source"] = source_analyse
    stats["genere_le"] = datetime.utcnow().isoformat()
    stats["societe"] = SOCIETE_NOM
    return stats


# ---------- Fichiers statiques (frontend) ----------
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
