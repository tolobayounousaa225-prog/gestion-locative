"""
Gestion Locative - Backend API — TOURÉ IMMOBILIER
FastAPI + SQLAlchemy + SQLite (dev) / PostgreSQL (prod via DATABASE_URL)

Rôles : gérant (accès complet) et propriétaire (accès en lecture à ses propres biens).
Paiements en espèces. Génération de quittance PDF professionnelle après chaque encaissement.
"""
import io
import os
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
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
from reportlab.pdfgen import canvas
from sqlalchemy import Column, Date as SADate, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

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


Base.metadata.create_all(bind=engine)

# Migration légère : ajoute proprietaire_id si la table maisons existait déjà sans cette colonne.
try:
    with engine.connect() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(maisons)")] if DATABASE_URL.startswith("sqlite") else None
        if cols is not None and "proprietaire_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE maisons ADD COLUMN proprietaire_id INTEGER")
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
    db.query(Maison).filter(Maison.proprietaire_id == user_id).update({"proprietaire_id": None})
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
    db.delete(maison)
    db.commit()
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
    db.delete(locataire)
    db.commit()
    return {"ok": True}


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
    db.delete(bail)
    db.commit()
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


def generer_quittance_pdf(paiement, bail, maison, locataire) -> io.BytesIO:
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
            f"Gestionnaire du bien loué",
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

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


@app.get("/api/paiements/{paiement_id}/quittance")
def quittance_pdf(paiement_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    paiement = db.query(Paiement).get(paiement_id)
    if not paiement:
        raise HTTPException(404, "Paiement introuvable")
    bail = db.query(Bail).get(paiement.bail_id)
    maison = db.query(Maison).get(bail.maison_id) if bail else None
    locataire = db.query(Locataire).get(bail.locataire_id) if bail else None

    if current_user.role == "proprietaire":
        if not maison or maison.proprietaire_id != current_user.id:
            raise HTTPException(403, "Accès refusé à ce document")

    buffer = generer_quittance_pdf(paiement, bail, maison, locataire)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=quittance_{paiement.id}.pdf"},
    )


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


# ---------- Fichiers statiques (frontend) ----------
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
