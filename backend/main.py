"""
Gestion Locative - Backend API
FastAPI + SQLAlchemy + SQLite (dev) / PostgreSQL (prod via DATABASE_URL)

Un seul propriétaire pour l'instant. Rôle actif : gérant.
Paiements en espèces. Génération de quittance PDF après chaque encaissement.
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
from reportlab.lib.pagesizes import A4
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
    role = Column(String, default="gerant")


class Maison(Base):
    __tablename__ = "maisons"
    id = Column(Integer, primary_key=True, index=True)
    adresse = Column(String, nullable=False)
    proprietaire = Column(String, nullable=True)
    nb_pieces = Column(Integer, default=1)
    loyer_reference = Column(Float, default=0)
    statut = Column(String, default="libre")  # libre / occupee / travaux

    baux = relationship("Bail", back_populates="maison")
    tickets = relationship("Ticket", back_populates="maison")


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

# ---------------------------------------------------------------------------
# Schémas Pydantic
# ---------------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MaisonIn(BaseModel):
    adresse: str
    proprietaire: Optional[str] = None
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


def ensure_default_admin():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == ADMIN_EMAIL).first():
            admin = User(
                nom="Gérant",
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
app = FastAPI(title="Gestion Locative")

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


# ---------- Maisons ----------
@app.get("/api/maisons", response_model=List[MaisonOut])
def list_maisons(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Maison).all()


@app.post("/api/maisons", response_model=MaisonOut)
def create_maison(data: MaisonIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    maison = Maison(**data.model_dump())
    db.add(maison)
    db.commit()
    db.refresh(maison)
    return maison


@app.put("/api/maisons/{maison_id}", response_model=MaisonOut)
def update_maison(maison_id: int, data: MaisonIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    maison = db.query(Maison).get(maison_id)
    if not maison:
        raise HTTPException(404, "Maison introuvable")
    for k, v in data.model_dump().items():
        setattr(maison, k, v)
    db.commit()
    db.refresh(maison)
    return maison


@app.delete("/api/maisons/{maison_id}")
def delete_maison(maison_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    maison = db.query(Maison).get(maison_id)
    if not maison:
        raise HTTPException(404, "Maison introuvable")
    db.delete(maison)
    db.commit()
    return {"ok": True}


# ---------- Locataires ----------
@app.get("/api/locataires", response_model=List[LocataireOut])
def list_locataires(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Locataire).all()


@app.post("/api/locataires", response_model=LocataireOut)
def create_locataire(data: LocataireIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    locataire = Locataire(**data.model_dump())
    db.add(locataire)
    db.commit()
    db.refresh(locataire)
    return locataire


@app.put("/api/locataires/{locataire_id}", response_model=LocataireOut)
def update_locataire(locataire_id: int, data: LocataireIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    locataire = db.query(Locataire).get(locataire_id)
    if not locataire:
        raise HTTPException(404, "Locataire introuvable")
    for k, v in data.model_dump().items():
        setattr(locataire, k, v)
    db.commit()
    db.refresh(locataire)
    return locataire


@app.delete("/api/locataires/{locataire_id}")
def delete_locataire(locataire_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    locataire = db.query(Locataire).get(locataire_id)
    if not locataire:
        raise HTTPException(404, "Locataire introuvable")
    db.delete(locataire)
    db.commit()
    return {"ok": True}

# ---------- Baux ----------
@app.get("/api/baux", response_model=List[BailOut])
def list_baux(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Bail).all()


@app.post("/api/baux", response_model=BailOut)
def create_bail(data: BailIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    bail = Bail(**data.model_dump())
    db.add(bail)
    maison = db.query(Maison).get(data.maison_id)
    if maison:
        maison.statut = "occupee"
    db.commit()
    db.refresh(bail)
    return bail


@app.put("/api/baux/{bail_id}", response_model=BailOut)
def update_bail(bail_id: int, data: BailIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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
def delete_bail(bail_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    bail = db.query(Bail).get(bail_id)
    if not bail:
        raise HTTPException(404, "Bail introuvable")
    db.delete(bail)
    db.commit()
    return {"ok": True}


# ---------- Paiements ----------
@app.get("/api/paiements", response_model=List[PaiementOut])
def list_paiements(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Paiement).all()


@app.post("/api/paiements", response_model=PaiementOut)
def create_paiement(data: PaiementIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    paiement = Paiement(**data.model_dump())
    db.add(paiement)
    db.commit()
    db.refresh(paiement)
    return paiement


@app.get("/api/paiements/{paiement_id}/quittance")
def quittance_pdf(paiement_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    paiement = db.query(Paiement).get(paiement_id)
    if not paiement:
        raise HTTPException(404, "Paiement introuvable")
    bail = db.query(Bail).get(paiement.bail_id)
    maison = db.query(Maison).get(bail.maison_id) if bail else None
    locataire = db.query(Locataire).get(bail.locataire_id) if bail else None

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 80

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Quittance de loyer")
    y -= 40

    c.setFont("Helvetica", 11)
    lignes = [
        f"Quittance n° {paiement.id}",
        f"Date d'émission : {date.today().isoformat()}",
        "",
        f"Locataire : {locataire.nom if locataire else '-'}",
        f"Maison : {maison.adresse if maison else '-'}",
        "",
        f"Mois concerné : {paiement.mois_concerne}",
        f"Montant payé : {paiement.montant:.0f}",
        f"Mode de paiement : {paiement.mode}",
        f"Date de paiement : {paiement.date_paiement or '-'}",
        f"Statut : {paiement.statut}",
    ]
    for ligne in lignes:
        c.drawString(50, y, ligne)
        y -= 22

    c.showPage()
    c.save()
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=quittance_{paiement.id}.pdf"},
    )

# ---------- Tickets maintenance ----------
@app.get("/api/tickets", response_model=List[TicketOut])
def list_tickets(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Ticket).all()


@app.post("/api/tickets", response_model=TicketOut)
def create_ticket(data: TicketIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ticket = Ticket(**data.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.put("/api/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, data: TicketIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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
def delete_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ticket = db.query(Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket introuvable")
    db.delete(ticket)
    db.commit()
    return {"ok": True}


# ---------- Tableau de bord ----------
@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    mois_courant = date.today().strftime("%Y-%m")
    total_maisons = db.query(Maison).count()
    maisons_occupees = db.query(Maison).filter(Maison.statut == "occupee").count()

    paiements_mois = db.query(Paiement).filter(Paiement.mois_concerne == mois_courant).all()
    total_encaisse = sum(p.montant for p in paiements_mois if p.statut == "paye")

    baux_actifs = db.query(Bail).filter(Bail.statut == "actif").all()
    total_attendu = sum(b.loyer_mensuel for b in baux_actifs)

    bail_ids_payes = {p.bail_id for p in paiements_mois if p.statut == "paye"}
    impayes = [b for b in baux_actifs if b.id not in bail_ids_payes]

    tickets_ouverts = db.query(Ticket).filter(Ticket.statut != "resolu").count()

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
