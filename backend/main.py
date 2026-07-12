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

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, field_validator
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import Boolean, Column, Date as SADate, DateTime, Float, ForeignKey, Integer, LargeBinary, String, create_engine
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

# Logo TOURÉ IMMOBILIER encodé en base64 (reutilise sur les documents PDF : quittances, contrats).
# Decode une seule fois au chargement du module pour eviter de repeter le decodage a chaque generation.
import base64 as _base64
_LOGO_TOURE_B64 = "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"
LOGO_TOURE_BYTES = _base64.b64decode(_LOGO_TOURE_B64)
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


class Batiment(Base):
    """Immeuble/bâtiment regroupant plusieurs logements. L'adresse et le propriétaire
    sont définis une seule fois ici et hérités par tous les logements rattachés."""
    __tablename__ = "batiments"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String, nullable=False)  # ex. "Immeuble Marcory Remblais"
    adresse = Column(String, nullable=False)
    proprietaire = Column(String, nullable=True)  # nom libre (affichage)
    proprietaire_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    maisons = relationship("Maison", back_populates="batiment")
    proprietaire_user = relationship("User")


class Maison(Base):
    __tablename__ = "maisons"
    id = Column(Integer, primary_key=True, index=True)
    adresse = Column(String, nullable=False)
    proprietaire = Column(String, nullable=True)  # nom libre (affichage / historique)
    proprietaire_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    batiment_id = Column(Integer, ForeignKey("batiments.id"), nullable=True)  # logement rattaché à un bâtiment
    nom_logement = Column(String, nullable=True)  # ex. "Appartement 3", "Porte A" (court, dans un bâtiment)
    nb_pieces = Column(Integer, default=1)
    loyer_reference = Column(Float, default=0)
    statut = Column(String, default="libre")  # libre / occupee / travaux

    baux = relationship("Bail", back_populates="maison")
    tickets = relationship("Ticket", back_populates="maison")
    proprietaire_user = relationship("User", back_populates="maisons")
    batiment = relationship("Batiment", back_populates="maisons")


class Locataire(Base):
    __tablename__ = "locataires"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String, nullable=False)
    telephone = Column(String, nullable=True)
    piece_identite = Column(String, nullable=True)
    contact_urgence = Column(String, nullable=True)
    archive = Column(Boolean, default=False)  # ancien locataire conservé pour l'historique par maison
    portail_token = Column(String, nullable=True, unique=True, index=True)  # lien privé d'accès au portail

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
    maison_id = Column(Integer, ForeignKey("maisons.id"), nullable=True)  # dépense rattachée à une maison (optionnel)
    created_at = Column(DateTime, default=datetime.utcnow)


class PieceJustificative(Base):
    """Pièce justificative (facture, reçu, photo...) téléversée par le gérant.
    Le contenu est stocké en base (bytea sur PostgreSQL) car le disque de Render
    est éphémère : seul le stockage en base survit aux redéploiements."""
    __tablename__ = "pieces_justificatives"
    id = Column(Integer, primary_key=True, index=True)
    maison_id = Column(Integer, ForeignKey("maisons.id"), nullable=True)  # null = document général (visible gérant seul)
    titre = Column(String, nullable=False)
    description = Column(String, nullable=True)
    montant = Column(Float, nullable=True)  # montant de l'achat justifié (optionnel)
    nom_fichier = Column(String, nullable=False)
    type_mime = Column(String, nullable=False)
    taille = Column(Integer, default=0)  # en octets
    contenu = Column(LargeBinary, nullable=False)
    date_upload = Column(DateTime, default=datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    maison = relationship("Maison")


class Photo(Base):
    """Photo d'un logement ou d'un bâtiment. Stockée en base (le disque Render est éphémère)."""
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True, index=True)
    maison_id = Column(Integer, ForeignKey("maisons.id"), nullable=True)
    batiment_id = Column(Integer, ForeignKey("batiments.id"), nullable=True)
    legende = Column(String, nullable=True)
    nom_fichier = Column(String, nullable=False)
    type_mime = Column(String, nullable=False)
    taille = Column(Integer, default=0)
    contenu = Column(LargeBinary, nullable=False)
    date_upload = Column(DateTime, default=datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)


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


class JournalActivite(Base):
    """Journal d'activité : trace les actions importantes (création, modification, suppression,
    connexion) pour audit et traçabilité."""
    __tablename__ = "journal_activite"
    id = Column(Integer, primary_key=True, index=True)
    date_action = Column(DateTime, default=datetime.utcnow, index=True)
    utilisateur_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    utilisateur_nom = Column(String, nullable=True)  # figé au moment de l'action (survit à la suppression du compte)
    action = Column(String, nullable=False)  # creation / modification / suppression / connexion / paiement ...
    objet = Column(String, nullable=True)     # maison / locataire / bail / paiement ...
    details = Column(String, nullable=True)


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
    _add_column_if_missing("depenses", "maison_id", "INTEGER")
    _add_column_if_missing("locataires", "portail_token", "VARCHAR")
    _add_column_if_missing("maisons", "batiment_id", "INTEGER")
    _add_column_if_missing("maisons", "nom_logement", "VARCHAR")
    # La table photos est créée par create_all ; rien à migrer de plus.
except Exception:
    pass


def _cle_adresse(txt: str) -> str:
    """Normalise une adresse pour comparaison : minuscules, sans accents, espaces/ponctuation réduits."""
    import unicodedata
    s = (txt or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    # Remplace toute ponctuation par des espaces, puis compacte les espaces
    s = "".join(c if c.isalnum() else " " for c in s)
    return " ".join(s.split())


def fusionner_batiments_doublons():
    """Fusionne les bâtiments dont le nom OU l'adresse normalisée sont identiques :
    on garde le plus ancien, on y rattache tous les logements, on supprime les doublons."""
    db = SessionLocal()
    try:
        batiments = db.query(Batiment).order_by(Batiment.id).all()
        if len(batiments) < 2:
            return
        garde_par_cle = {}
        for b in batiments:
            cle = _cle_adresse(b.nom) + "||" + _cle_adresse(b.adresse)
            if cle in garde_par_cle:
                principal = garde_par_cle[cle]
                # Rattache les logements du doublon au bâtiment principal
                db.query(Maison).filter(Maison.batiment_id == b.id).update({"batiment_id": principal.id})
                db.delete(b)
            else:
                garde_par_cle[cle] = b
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def nettoyer_noms_logements():
    """Pour chaque bâtiment, renomme en 'Appartement N' les logements dont le nom est vide
    ou identique au nom/adresse du bâtiment (ex. 'MARCORY REMBLAI' répété). Préserve les
    logements ayant déjà un vrai nom distinct (ex. 'SOUMAHORO. STA — Étage 1 porte 3')."""
    import re as _re
    db = SessionLocal()
    try:
        batiments = db.query(Batiment).all()
        for bat in batiments:
            cle_bat = _cle_adresse(bat.nom)
            cle_adr = _cle_adresse(bat.adresse)
            logements = db.query(Maison).filter(Maison.batiment_id == bat.id).order_by(Maison.id).all()
            compteur = 0
            a_renommer = []
            for m in logements:
                nom = (m.nom_logement or "").strip()
                cle_nom = _cle_adresse(nom)
                if not nom or cle_nom == cle_bat or cle_nom == cle_adr:
                    a_renommer.append(m)
                else:
                    match = _re.match(r"appartement\s+(\d+)", nom.lower())
                    if match:
                        compteur = max(compteur, int(match.group(1)))
            for m in a_renommer:
                compteur += 1
                m.nom_logement = f"Appartement {compteur}"
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def migrer_maisons_vers_batiments():
    """Regroupe les maisons existantes sans bâtiment sous des bâtiments créés à partir
    de leur adresse. Les maisons de même adresse (insensible casse/accents/espaces) sont
    rassemblées sous un même bâtiment. Idempotent : ne touche pas aux maisons déjà rattachées."""
    db = SessionLocal()
    try:
        orphelines = db.query(Maison).filter(Maison.batiment_id.is_(None)).all()
        if not orphelines:
            return
        # Index des bâtiments existants par clé normalisée (pour réutilisation robuste)
        existants = {}
        for b in db.query(Batiment).all():
            existants[_cle_adresse(b.adresse)] = b
        # Regrouper les orphelines par clé d'adresse normalisée
        groupes = {}
        for m in orphelines:
            groupes.setdefault(_cle_adresse(m.adresse), []).append(m)
        for cle, maisons in groupes.items():
            ref = maisons[0]
            batiment = existants.get(cle)
            if not batiment:
                batiment = Batiment(
                    nom=ref.adresse,
                    adresse=ref.adresse,
                    proprietaire=ref.proprietaire,
                    proprietaire_id=ref.proprietaire_id,
                )
                db.add(batiment)
                db.flush()
                existants[cle] = batiment
            for m in maisons:
                m.batiment_id = batiment.id
                if batiment.proprietaire_id and not m.proprietaire_id:
                    m.proprietaire_id = batiment.proprietaire_id
                    m.proprietaire = batiment.proprietaire
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


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


class UserUpdateIn(BaseModel):
    nom: str
    email: str
    role: str = "proprietaire"
    password: Optional[str] = None  # si fourni, remplace le mot de passe


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class MaisonIn(BaseModel):
    adresse: str
    proprietaire: Optional[str] = None
    proprietaire_id: Optional[int] = None
    batiment_id: Optional[int] = None
    nom_logement: Optional[str] = None
    nb_pieces: int = 1
    loyer_reference: float = 0
    statut: str = "libre"

    @field_validator("loyer_reference")
    @classmethod
    def loyer_reference_non_negatif(cls, v):
        if v < 0:
            raise ValueError("Le loyer de référence ne peut pas être négatif")
        return v

    @field_validator("nb_pieces")
    @classmethod
    def nb_pieces_positif(cls, v):
        if v < 1:
            raise ValueError("Le nombre de pièces doit être au moins 1")
        return v


class MaisonOut(MaisonIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BatimentIn(BaseModel):
    nom: str
    adresse: str
    proprietaire: Optional[str] = None
    proprietaire_id: Optional[int] = None


class BatimentOut(BatimentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nb_logements: int = 0


class LocataireIn(BaseModel):
    nom: str
    telephone: Optional[str] = None
    piece_identite: Optional[str] = None
    contact_urgence: Optional[str] = None


class LocataireOut(LocataireIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    archive: bool = False
    portail_token: Optional[str] = None


class BailIn(BaseModel):
    maison_id: int
    locataire_id: int
    date_debut: date
    date_fin: Optional[date] = None
    loyer_mensuel: float
    caution: float = 0
    statut: str = "actif"

    @field_validator("loyer_mensuel")
    @classmethod
    def loyer_positif(cls, v):
        if v <= 0:
            raise ValueError("Le loyer mensuel doit être strictement positif")
        return v

    @field_validator("caution")
    @classmethod
    def caution_non_negative(cls, v):
        if v < 0:
            raise ValueError("La caution ne peut pas être négative")
        return v


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

    @field_validator("montant")
    @classmethod
    def montant_positif(cls, v):
        if v <= 0:
            raise ValueError("Le montant doit être strictement positif")
        return v


class PaiementOut(PaiementIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TicketIn(BaseModel):
    maison_id: int
    locataire_id: Optional[int] = None
    description: str
    statut: str = "ouvert"
    cout: float = 0

    @field_validator("cout")
    @classmethod
    def cout_non_negatif(cls, v):
        if v < 0:
            raise ValueError("Le coût ne peut pas être négatif")
        return v


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
    maison_id: Optional[int] = None

    @field_validator("montant")
    @classmethod
    def montant_positif(cls, v):
        if v <= 0:
            raise ValueError("Le montant doit être strictement positif")
        return v


class DepenseOut(DepenseIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PieceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    maison_id: Optional[int] = None
    titre: str
    description: Optional[str] = None
    montant: Optional[float] = None
    nom_fichier: str
    type_mime: str
    taille: int
    date_upload: datetime
    uploaded_by: Optional[int] = None


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    maison_id: Optional[int] = None
    batiment_id: Optional[int] = None
    legende: Optional[str] = None
    nom_fichier: str
    type_mime: str
    taille: int
    date_upload: datetime


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


def libelle_logement(maison, db: Session) -> str:
    """Retourne 'Nom du bâtiment — Nom du logement' pour un affichage sans répétition d'adresse."""
    if not maison:
        return "—"
    base = maison.adresse
    if maison.batiment_id:
        bat = db.query(Batiment).get(maison.batiment_id)
        if bat:
            base = bat.nom
    if maison.nom_logement:
        return f"{base} — {maison.nom_logement}"
    return base


def journaliser(db: Session, user: Optional[User], action: str, objet: str = None, details: str = None) -> None:
    """Enregistre une action dans le journal d'activité (best-effort, ne bloque jamais l'opération)."""
    try:
        entree = JournalActivite(
            utilisateur_id=user.id if user else None,
            utilisateur_nom=user.nom if user else "Système",
            action=action,
            objet=objet,
            details=details,
        )
        db.add(entree)
        db.commit()
    except Exception:
        db.rollback()


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
migrer_maisons_vers_batiments()
fusionner_batiments_doublons()
nettoyer_noms_logements()


@app.post("/api/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.mot_de_passe_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    token = create_access_token({"sub": user.email})
    journaliser(db, user, "connexion", "session", f"Connexion de {user.email}")
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
    if len(data.new_password) < 6:
        raise HTTPException(400, "Le mot de passe doit contenir au moins 6 caractères.")
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


@app.put("/api/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdateIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    if data.role not in ("gerant", "proprietaire"):
        raise HTTPException(400, "Rôle invalide")
    if user_id == current.id and data.role != "gerant":
        raise HTTPException(400, "Impossible de retirer votre propre rôle de gérant")
    existant = db.query(User).filter(User.email == data.email, User.id != user_id).first()
    if existant:
        raise HTTPException(400, "Cet email est déjà utilisé par un autre compte")
    user.nom = data.nom
    user.email = data.email
    user.role = data.role
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Le mot de passe doit contenir au moins 6 caractères")
        user.mot_de_passe_hash = pwd_context.hash(data.password)
    # Garde le nom d'affichage du propriétaire synchronisé sur ses maisons
    db.query(Maison).filter(Maison.proprietaire_id == user_id).update({"proprietaire": data.nom})
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

    # Détacher toutes les données qui référencent cet utilisateur (clé étrangère),
    # pour permettre sa suppression sans violer les contraintes d'intégrité
    # (strictement appliquées par PostgreSQL en production, contrairement à SQLite en dev).
    # On conserve les données elles-mêmes : seule la référence au compte est retirée.
    db.query(Maison).filter(Maison.proprietaire_id == user_id).update(
        {"proprietaire_id": None, "proprietaire": None}
    )
    db.query(Batiment).filter(Batiment.proprietaire_id == user_id).update(
        {"proprietaire_id": None, "proprietaire": None}
    )
    db.query(PieceJustificative).filter(PieceJustificative.uploaded_by == user_id).update(
        {"uploaded_by": None}
    )
    db.query(Photo).filter(Photo.uploaded_by == user_id).update(
        {"uploaded_by": None}
    )
    # Le journal garde une trace lisible (utilisateur_nom) même après suppression du compte
    db.query(JournalActivite).filter(JournalActivite.utilisateur_id == user_id).update(
        {"utilisateur_id": None}
    )
    if user.role == "proprietaire":
        # Un propriétaire peut avoir des observations (auteur obligatoire) : elles sont
        # supprimées avec lui, la conversation n'ayant plus de sens sans son auteur.
        db.query(Observation).filter(Observation.proprietaire_id == user_id).delete()

    try:
        db.delete(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Impossible de supprimer cet utilisateur : des données liées existent encore. "
            "Contactez le support si le problème persiste."
        )
    return {"ok": True}


# ---------- Bâtiments ----------
def _batiment_out(b: Batiment, db: Session) -> dict:
    nb = db.query(Maison).filter(Maison.batiment_id == b.id).count()
    return {
        "id": b.id, "nom": b.nom, "adresse": b.adresse,
        "proprietaire": b.proprietaire, "proprietaire_id": b.proprietaire_id,
        "nb_logements": nb,
    }


@app.get("/api/batiments", response_model=List[BatimentOut])
def list_batiments(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Batiment)
    if current_user.role == "proprietaire":
        q = q.filter(Batiment.proprietaire_id == current_user.id)
    return [_batiment_out(b, db) for b in q.order_by(Batiment.nom).all()]


@app.post("/api/batiments", response_model=BatimentOut)
def create_batiment(data: BatimentIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    payload = data.model_dump()
    if payload.get("proprietaire_id") and not payload.get("proprietaire"):
        owner = db.query(User).get(payload["proprietaire_id"])
        if owner:
            payload["proprietaire"] = owner.nom
    batiment = Batiment(**payload)
    db.add(batiment)
    db.commit()
    db.refresh(batiment)
    journaliser(db, current, "creation", "batiment", f"Bâtiment « {batiment.nom} »")
    return _batiment_out(batiment, db)


@app.put("/api/batiments/{batiment_id}", response_model=BatimentOut)
def update_batiment(batiment_id: int, data: BatimentIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    batiment = db.query(Batiment).get(batiment_id)
    if not batiment:
        raise HTTPException(404, "Bâtiment introuvable")
    payload = data.model_dump()
    if payload.get("proprietaire_id"):
        owner = db.query(User).get(payload["proprietaire_id"])
        payload["proprietaire"] = owner.nom if owner else payload.get("proprietaire")
    for k, v in payload.items():
        setattr(batiment, k, v)
    # Répercuter propriétaire et adresse sur tous les logements du bâtiment
    db.query(Maison).filter(Maison.batiment_id == batiment_id).update({
        "proprietaire_id": batiment.proprietaire_id,
        "proprietaire": batiment.proprietaire,
        "adresse": batiment.adresse,
    })
    db.commit()
    db.refresh(batiment)
    journaliser(db, current, "modification", "batiment", f"Bâtiment « {batiment.nom} »")
    return _batiment_out(batiment, db)


@app.delete("/api/batiments/{batiment_id}")
def delete_batiment(batiment_id: int, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    batiment = db.query(Batiment).get(batiment_id)
    if not batiment:
        raise HTTPException(404, "Bâtiment introuvable")
    nb = db.query(Maison).filter(Maison.batiment_id == batiment_id).count()
    if nb > 0:
        raise HTTPException(400, f"Ce bâtiment contient {nb} logement(s). Déplacez ou supprimez-les d'abord.")
    # Les photos rattachées au bâtiment lui-même (pas à un logement) n'empêchent pas
    # la suppression : elles sont supprimées avec lui.
    db.query(Photo).filter(Photo.batiment_id == batiment_id).delete()
    try:
        db.delete(batiment)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Impossible de supprimer ce bâtiment : des données liées existent encore.")
    journaliser(db, current, "suppression", "batiment", f"Bâtiment « {batiment.nom} »")
    return {"ok": True}


# ---------- Maisons ----------
@app.get("/api/maisons", response_model=List[MaisonOut])
def list_maisons(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Maison)
    if current_user.role == "proprietaire":
        q = q.filter(Maison.proprietaire_id == current_user.id)
    return q.all()


@app.post("/api/maisons", response_model=MaisonOut)
def create_maison(data: MaisonIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    payload = data.model_dump()
    # Si rattaché à un bâtiment, hériter de son adresse et de son propriétaire
    if payload.get("batiment_id"):
        batiment = db.query(Batiment).get(payload["batiment_id"])
        if not batiment:
            raise HTTPException(404, "Bâtiment introuvable")
        payload["adresse"] = batiment.adresse
        payload["proprietaire_id"] = batiment.proprietaire_id
        payload["proprietaire"] = batiment.proprietaire
    elif payload.get("proprietaire_id") and not payload.get("proprietaire"):
        owner = db.query(User).get(payload["proprietaire_id"])
        if owner:
            payload["proprietaire"] = owner.nom
    maison = Maison(**payload)
    db.add(maison)
    db.commit()
    db.refresh(maison)
    label = maison.adresse
    journaliser(db, current, "creation", "maison", f"Logement « {label} »")
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
def create_bail(data: BailIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
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
    loc = db.query(Locataire).get(bail.locataire_id)
    journaliser(db, current, "creation", "bail", f"Bail {maison.adresse if maison else ''} — {loc.nom if loc else ''}")
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
def create_paiement(data: PaiementIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    paiement = Paiement(**data.model_dump())
    paiement.verification_code = generate_verification_code()
    db.add(paiement)
    db.commit()
    db.refresh(paiement)
    journaliser(db, current, "paiement", "paiement", f"{paiement.montant:.0f} {DEVISE} — {paiement.mois_concerne} ({paiement.statut})")
    return paiement


# ---------- Gain de temps : encaissement en masse & quittances groupées ----------
class EncaissementMasseIn(BaseModel):
    mois_concerne: str
    bail_ids: List[int]
    mode: str = "especes"
    date_paiement: Optional[date] = None


@app.get("/api/paiements/etat-mois")
def etat_paiements_mois(mois: str = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Liste tous les baux actifs avec leur état de paiement pour le mois (pour l'encaissement en masse)."""
    if not mois:
        mois = date.today().strftime("%Y-%m")
    baux = db.query(Bail).filter(Bail.statut == "actif").all()
    paiements = db.query(Paiement).filter(Paiement.mois_concerne == mois).all()
    paye_par_bail = {}
    for p in paiements:
        if p.statut == "paye":
            paye_par_bail[p.bail_id] = paye_par_bail.get(p.bail_id, 0) + p.montant
    lignes = []
    for b in baux:
        maison = db.query(Maison).get(b.maison_id)
        locataire = db.query(Locataire).get(b.locataire_id)
        deja_paye = paye_par_bail.get(b.id, 0)
        lignes.append({
            "bail_id": b.id,
            "maison": libelle_logement(maison, db) if maison else "—",
            "locataire": locataire.nom if locataire else "—",
            "loyer_mensuel": b.loyer_mensuel,
            "deja_paye": deja_paye,
            "solde": deja_paye >= b.loyer_mensuel,
        })
    ordre = lambda x: (x["solde"], x["maison"])
    lignes.sort(key=ordre)
    return {"mois": mois, "lignes": lignes}


@app.post("/api/paiements/encaisser-masse")
def encaisser_masse(data: EncaissementMasseIn, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    """Enregistre en une fois le paiement du loyer complet pour plusieurs baux (mois donné).
    Ignore les baux déjà soldés pour ce mois."""
    if not data.bail_ids:
        raise HTTPException(400, "Aucun bail sélectionné")
    date_p = data.date_paiement or date.today()
    # Baux déjà soldés à exclure
    paiements_existants = db.query(Paiement).filter(
        Paiement.mois_concerne == data.mois_concerne,
        Paiement.bail_id.in_(data.bail_ids),
        Paiement.statut == "paye",
    ).all()
    paye_par_bail = {}
    for p in paiements_existants:
        paye_par_bail[p.bail_id] = paye_par_bail.get(p.bail_id, 0) + p.montant

    crees = 0
    total = 0.0
    for bail_id in data.bail_ids:
        bail = db.query(Bail).get(bail_id)
        if not bail or bail.statut != "actif":
            continue
        if paye_par_bail.get(bail_id, 0) >= bail.loyer_mensuel:
            continue  # déjà soldé
        reste = bail.loyer_mensuel - paye_par_bail.get(bail_id, 0)
        paiement = Paiement(
            bail_id=bail_id,
            mois_concerne=data.mois_concerne,
            montant=reste,
            date_paiement=date_p,
            mode=data.mode,
            statut="paye",
            verification_code=generate_verification_code(),
        )
        db.add(paiement)
        crees += 1
        total += reste
    db.commit()
    journaliser(db, current, "paiement", "encaissement_masse",
                f"{crees} loyer(s) encaissé(s) pour {data.mois_concerne} — total {total:.0f} {DEVISE}")
    return {"ok": True, "paiements_crees": crees, "total_encaisse": total, "mois": data.mois_concerne}


@app.get("/api/paiements/quittances-mois")
def quittances_mois(mois: str, request: Request, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    """Génère un PDF unique regroupant toutes les quittances des paiements soldés du mois."""
    from pypdf import PdfWriter, PdfReader
    paiements = db.query(Paiement).filter(Paiement.mois_concerne == mois, Paiement.statut == "paye").all()
    if not paiements:
        raise HTTPException(404, "Aucune quittance à générer pour ce mois")

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    base_url = f"{proto}://{host}"

    writer = PdfWriter()
    nb = 0
    for p in paiements:
        bail = db.query(Bail).get(p.bail_id)
        if not bail:
            continue
        maison = db.query(Maison).get(bail.maison_id)
        locataire = db.query(Locataire).get(bail.locataire_id)
        if not p.verification_code:
            p.verification_code = generate_verification_code()
            db.commit()
            db.refresh(p)
        verify_url = f"{base_url}/verifier.html?code={p.verification_code}"
        buf = generer_quittance_pdf(p, bail, maison, locataire, verify_url)
        reader = PdfReader(buf)
        for page in reader.pages:
            writer.add_page(page)
        nb += 1

    if nb == 0:
        raise HTTPException(404, "Aucune quittance générée")

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    journaliser(db, current, "sauvegarde", "quittances_mois", f"{nb} quittance(s) générée(s) pour {mois}")
    return StreamingResponse(
        out,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="quittances_{mois}.pdf"'},
    )



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

    # Logo (encart blanc arrondi, façon cachet, à gauche du bandeau)
    logo_size = 20 * mm
    logo_x = margin
    logo_y = height - header_h / 2 - logo_size / 2
    c.setFillColor(colors.white)
    c.roundRect(logo_x, logo_y, logo_size, logo_size, 3, stroke=0, fill=1)
    c.drawImage(ImageReader(io.BytesIO(LOGO_TOURE_BYTES)), logo_x + 1, logo_y + 1,
                width=logo_size - 2, height=logo_size - 2, mask="auto", preserveAspectRatio=True)
    text_x = logo_x + logo_size + 6

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(text_x, height - 15 * mm, SOCIETE_NOM)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(text_x, height - 21 * mm, SOCIETE_TAGLINE)

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


# ---------- Pièces justificatives (factures, reçus, photos d'achats) ----------
PIECE_MAX_TAILLE = 10 * 1024 * 1024  # 10 Mo
PIECE_TYPES_AUTORISES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def piece_visible_par(piece: PieceJustificative, user: User, db: Session) -> bool:
    if user.role == "gerant":
        return True
    if piece.maison_id is None:
        return False  # document général : gérant uniquement
    return piece.maison_id in owned_maison_ids(db, user)


@app.get("/api/pieces", response_model=List[PieceOut])
def list_pieces(maison_id: Optional[int] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(PieceJustificative)
    if current_user.role != "gerant":
        ids = owned_maison_ids(db, current_user)
        q = q.filter(PieceJustificative.maison_id.in_(ids))
    if maison_id:
        q = q.filter(PieceJustificative.maison_id == maison_id)
    return q.order_by(PieceJustificative.date_upload.desc()).all()


@app.post("/api/pieces", response_model=PieceOut)
async def upload_piece(
    titre: str = Form(...),
    maison_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    montant: Optional[str] = Form(None),
    fichier: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_gerant),
):
    type_mime = (fichier.content_type or "").lower()
    if type_mime not in PIECE_TYPES_AUTORISES:
        raise HTTPException(400, "Type de fichier non autorisé (PDF ou image : JPG, PNG, WEBP, GIF)")
    contenu = await fichier.read()
    if len(contenu) > PIECE_MAX_TAILLE:
        raise HTTPException(400, "Fichier trop volumineux (maximum 10 Mo)")
    if not contenu:
        raise HTTPException(400, "Fichier vide")

    m_id: Optional[int] = None
    if maison_id not in (None, "", "null"):
        try:
            m_id = int(maison_id)
        except ValueError:
            raise HTTPException(400, "Maison invalide")
        if not db.query(Maison).get(m_id):
            raise HTTPException(404, "Maison introuvable")

    mt: Optional[float] = None
    if montant not in (None, "", "null"):
        try:
            mt = float(montant)
        except ValueError:
            raise HTTPException(400, "Montant invalide")

    piece = PieceJustificative(
        maison_id=m_id,
        titre=titre.strip(),
        description=(description or "").strip() or None,
        montant=mt,
        nom_fichier=fichier.filename or f"piece{PIECE_TYPES_AUTORISES[type_mime]}",
        type_mime=type_mime,
        taille=len(contenu),
        contenu=contenu,
        uploaded_by=current.id,
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)
    return piece


@app.get("/api/pieces/{piece_id}/fichier")
def telecharger_piece(piece_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    piece = db.query(PieceJustificative).get(piece_id)
    if not piece:
        raise HTTPException(404, "Pièce introuvable")
    if not piece_visible_par(piece, current_user, db):
        raise HTTPException(403, "Accès refusé à cette pièce")
    nom_ascii = "".join(c if c.isascii() and c not in '"\\' else "_" for c in piece.nom_fichier)
    return Response(
        content=piece.contenu,
        media_type=piece.type_mime,
        headers={"Content-Disposition": f'inline; filename="{nom_ascii}"'},
    )


@app.delete("/api/pieces/{piece_id}")
def delete_piece(piece_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    piece = db.query(PieceJustificative).get(piece_id)
    if not piece:
        raise HTTPException(404, "Pièce introuvable")
    db.delete(piece)
    db.commit()
    return {"ok": True}


# ---------- Photos des logements & bâtiments ----------
PHOTO_TYPES_AUTORISES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


@app.get("/api/photos", response_model=List[PhotoOut])
def list_photos(maison_id: Optional[int] = None, batiment_id: Optional[int] = None,
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Photo)
    if maison_id is not None:
        q = q.filter(Photo.maison_id == maison_id)
    if batiment_id is not None:
        q = q.filter(Photo.batiment_id == batiment_id)
    # Un propriétaire ne voit que les photos de son périmètre
    if current_user.role == "proprietaire":
        mes_maisons = set(owned_maison_ids(db, current_user))
        mes_batiments = {b.id for b in db.query(Batiment.id).filter(Batiment.proprietaire_id == current_user.id).all()}
        photos = [p for p in q.order_by(Photo.date_upload.desc()).all()
                  if (p.maison_id in mes_maisons) or (p.batiment_id in mes_batiments)]
        return photos
    return q.order_by(Photo.date_upload.desc()).all()


@app.post("/api/photos", response_model=PhotoOut)
async def upload_photo(
    maison_id: Optional[str] = Form(None),
    batiment_id: Optional[str] = Form(None),
    legende: Optional[str] = Form(None),
    fichier: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_gerant),
):
    type_mime = (fichier.content_type or "").lower()
    if type_mime not in PHOTO_TYPES_AUTORISES:
        raise HTTPException(400, "Format non autorisé (image JPG, PNG, WEBP ou GIF)")
    contenu = await fichier.read()
    if len(contenu) > PIECE_MAX_TAILLE:
        raise HTTPException(400, "Image trop volumineuse (maximum 10 Mo)")
    if not contenu:
        raise HTTPException(400, "Fichier vide")

    m_id = None
    b_id = None
    if maison_id not in (None, "", "null"):
        m_id = int(maison_id)
        if not db.query(Maison).get(m_id):
            raise HTTPException(404, "Logement introuvable")
    if batiment_id not in (None, "", "null"):
        b_id = int(batiment_id)
        if not db.query(Batiment).get(b_id):
            raise HTTPException(404, "Bâtiment introuvable")
    if not m_id and not b_id:
        raise HTTPException(400, "Précisez un logement ou un bâtiment")

    photo = Photo(
        maison_id=m_id,
        batiment_id=b_id,
        legende=(legende or "").strip() or None,
        nom_fichier=fichier.filename or f"photo{PHOTO_TYPES_AUTORISES[type_mime]}",
        type_mime=type_mime,
        taille=len(contenu),
        contenu=contenu,
        uploaded_by=current.id,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    journaliser(db, current, "creation", "photo", f"Photo ajoutée ({photo.legende or photo.nom_fichier})")
    return photo


@app.get("/api/photos/{photo_id}/fichier")
def voir_photo(photo_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    photo = db.query(Photo).get(photo_id)
    if not photo:
        raise HTTPException(404, "Photo introuvable")
    if current_user.role == "proprietaire":
        mes_maisons = set(owned_maison_ids(db, current_user))
        mes_batiments = {b.id for b in db.query(Batiment.id).filter(Batiment.proprietaire_id == current_user.id).all()}
        if photo.maison_id not in mes_maisons and photo.batiment_id not in mes_batiments:
            raise HTTPException(403, "Accès refusé")
    nom_ascii = "".join(c if c.isascii() and c not in '"\\' else "_" for c in photo.nom_fichier)
    return Response(
        content=photo.contenu,
        media_type=photo.type_mime,
        headers={"Content-Disposition": f'inline; filename="{nom_ascii}"'},
    )


@app.delete("/api/photos/{photo_id}")
def delete_photo(photo_id: int, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    photo = db.query(Photo).get(photo_id)
    if not photo:
        raise HTTPException(404, "Photo introuvable")
    db.delete(photo)
    db.commit()
    journaliser(db, current, "suppression", "photo", f"Photo #{photo_id} supprimée")
    return {"ok": True}


@app.get("/api/locataires/{locataire_id}/fiche")
def fiche_locataire(locataire_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Fiche complète d'un locataire : ses baux, tous ses paiements, ses signalements."""
    loc = db.query(Locataire).get(locataire_id)
    if not loc:
        raise HTTPException(404, "Locataire introuvable")

    baux = db.query(Bail).filter(Bail.locataire_id == locataire_id).order_by(Bail.date_debut.desc()).all()
    baux_data = []
    total_paye = 0.0
    for b in baux:
        maison = db.query(Maison).get(b.maison_id)
        paiements = db.query(Paiement).filter(Paiement.bail_id == b.id).order_by(Paiement.mois_concerne.desc()).all()
        p_data = []
        for p in paiements:
            if p.statut == "paye":
                total_paye += p.montant
            p_data.append({
                "id": p.id, "mois_concerne": p.mois_concerne, "montant": p.montant,
                "statut": p.statut, "date_paiement": p.date_paiement.isoformat() if p.date_paiement else None,
                "mode": p.mode,
            })
        baux_data.append({
            "bail_id": b.id,
            "logement": libelle_logement(maison, db) if maison else "—",
            "statut": b.statut,
            "date_debut": b.date_debut.isoformat() if b.date_debut else None,
            "date_fin": b.date_fin.isoformat() if b.date_fin else None,
            "loyer_mensuel": b.loyer_mensuel,
            "caution": b.caution,
            "paiements": p_data,
        })

    tickets = db.query(Ticket).filter(Ticket.locataire_id == locataire_id).order_by(Ticket.date_creation.desc()).all()
    tickets_data = [{
        "id": t.id, "description": t.description, "statut": t.statut,
        "date_creation": t.date_creation.isoformat() if t.date_creation else None,
        "cout": t.cout,
    } for t in tickets]

    return {
        "locataire": {
            "id": loc.id, "nom": loc.nom, "telephone": loc.telephone,
            "piece_identite": loc.piece_identite, "contact_urgence": loc.contact_urgence,
            "archive": loc.archive,
        },
        "baux": baux_data,
        "tickets": tickets_data,
        "resume": {
            "nb_baux": len(baux),
            "nb_baux_actifs": sum(1 for b in baux if b.statut == "actif"),
            "total_paye": round(total_paye, 2),
            "nb_signalements": len(tickets),
        },
    }


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


@app.get("/api/dashboard/alertes")
def dashboard_alertes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Alertes intelligentes : baux arrivant à échéance, logements vacants, retards répétés."""
    is_owner = current_user.role == "proprietaire"
    maison_ids = owned_maison_ids(db, current_user) if is_owner else None
    aujourd_hui = date.today()
    mois_courant = aujourd_hui.strftime("%Y-%m")

    alertes = []

    # 1. Baux arrivant à échéance dans les 60 jours
    q_baux = db.query(Bail).filter(Bail.statut == "actif", Bail.date_fin.isnot(None))
    if is_owner:
        q_baux = q_baux.filter(Bail.maison_id.in_(maison_ids))
    for b in q_baux.all():
        if b.date_fin:
            jours = (b.date_fin - aujourd_hui).days
            if 0 <= jours <= 60:
                maison = db.query(Maison).get(b.maison_id)
                locataire = db.query(Locataire).get(b.locataire_id)
                alertes.append({
                    "type": "echeance",
                    "niveau": "warning" if jours > 15 else "danger",
                    "titre": "Bail bientôt à échéance",
                    "detail": f"{libelle_logement(maison, db)} — {locataire.nom if locataire else ''} : fin dans {jours} jour(s) ({b.date_fin.strftime('%d/%m/%Y')})",
                })

    # 2. Logements vacants (statut libre)
    q_maisons = db.query(Maison).filter(Maison.statut == "libre")
    if is_owner:
        q_maisons = q_maisons.filter(Maison.id.in_(maison_ids))
    vacants = q_maisons.all()
    if vacants:
        noms = ", ".join(libelle_logement(m, db) for m in vacants[:5])
        suffixe = f" et {len(vacants) - 5} autre(s)" if len(vacants) > 5 else ""
        alertes.append({
            "type": "vacant",
            "niveau": "info",
            "titre": f"{len(vacants)} logement(s) vacant(s)",
            "detail": noms + suffixe,
        })

    # 3. Locataires en retard répété (impayés sur 2 des 3 derniers mois)
    trois_mois = _mois_range(3)
    q_baux_actifs = db.query(Bail).filter(Bail.statut == "actif")
    if is_owner:
        q_baux_actifs = q_baux_actifs.filter(Bail.maison_id.in_(maison_ids))
    for b in q_baux_actifs.all():
        paiements = db.query(Paiement).filter(
            Paiement.bail_id == b.id,
            Paiement.mois_concerne.in_(trois_mois),
            Paiement.statut == "paye",
        ).all()
        mois_payes = {p.mois_concerne for p in paiements}
        nb_impayes = len(trois_mois) - len(mois_payes)
        if nb_impayes >= 2:
            maison = db.query(Maison).get(b.maison_id)
            locataire = db.query(Locataire).get(b.locataire_id)
            alertes.append({
                "type": "retard_repete",
                "niveau": "danger",
                "titre": "Retard de paiement répété",
                "detail": f"{locataire.nom if locataire else ''} ({libelle_logement(maison, db)}) : {nb_impayes} mois impayés sur les 3 derniers",
            })

    # Tri par gravité
    ordre = {"danger": 0, "warning": 1, "info": 2}
    alertes.sort(key=lambda a: ordre.get(a["niveau"], 3))
    return {"mois": mois_courant, "nombre": len(alertes), "alertes": alertes}


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


# ---------- Finances : rentabilité, évolution, export comptable ----------
def _periode_mois(annee: int) -> tuple:
    """Premier et dernier jour de l'année demandée."""
    return date(annee, 1, 1), date(annee, 12, 31)


@app.get("/api/finances/rentabilite")
def finances_rentabilite(annee: int = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Rentabilité par maison sur une année : loyers encaissés, dépenses, résultat net, rendement."""
    if annee is None:
        annee = date.today().year
    debut, fin = _periode_mois(annee)
    mois_annee = [f"{annee}-{m:02d}" for m in range(1, 13)]

    maisons = db.query(Maison).all()
    lignes = []
    total_encaisse_global = 0.0
    total_depenses_global = 0.0
    for maison in maisons:
        bail_ids = {b.id for b in db.query(Bail.id).filter(Bail.maison_id == maison.id).all()}
        # Loyers encaissés (paiements payés de l'année pour les baux de cette maison)
        encaisse = 0.0
        if bail_ids:
            paiements = db.query(Paiement).filter(
                Paiement.mois_concerne.in_(mois_annee),
                Paiement.statut == "paye",
                Paiement.bail_id.in_(bail_ids),
            ).all()
            encaisse = sum(p.montant for p in paiements)
        # Dépenses de la maison sur l'année
        depenses = db.query(Depense).filter(
            Depense.maison_id == maison.id,
            Depense.date_depense >= debut,
            Depense.date_depense <= fin,
        ).all()
        total_dep = sum(d.montant for d in depenses)
        # Coût des tickets de maintenance de la maison sur l'année
        tickets = db.query(Ticket).filter(
            Ticket.maison_id == maison.id,
            Ticket.date_creation >= datetime.combine(debut, datetime.min.time()),
            Ticket.date_creation <= datetime.combine(fin, datetime.max.time()),
        ).all()
        cout_tickets = sum(t.cout for t in tickets)
        charges = total_dep + cout_tickets
        net = encaisse - charges
        rendement = round(net / encaisse * 100, 1) if encaisse else None
        total_encaisse_global += encaisse
        total_depenses_global += charges
        lignes.append({
            "maison_id": maison.id,
            "adresse": libelle_logement(maison, db),
            "proprietaire": maison.proprietaire,
            "statut": maison.statut,
            "loyer_reference": maison.loyer_reference,
            "encaisse": round(encaisse, 2),
            "depenses": round(total_dep, 2),
            "cout_tickets": round(cout_tickets, 2),
            "charges_totales": round(charges, 2),
            "resultat_net": round(net, 2),
            "rendement_pct": rendement,
        })
    lignes.sort(key=lambda x: x["resultat_net"], reverse=True)
    return {
        "annee": annee,
        "lignes": lignes,
        "total_encaisse": round(total_encaisse_global, 2),
        "total_charges": round(total_depenses_global, 2),
        "resultat_net_global": round(total_encaisse_global - total_depenses_global, 2),
    }


@app.get("/api/finances/evolution")
def finances_evolution(mois: int = 12, maison_id: Optional[int] = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Évolution mensuelle : loyers encaissés, dépenses et résultat net, sur n mois."""
    n = max(1, min(mois, 24))
    periode = _mois_range(n)

    if maison_id:
        bail_ids_perimetre = {b.id for b in db.query(Bail.id).filter(Bail.maison_id == maison_id).all()}
    else:
        bail_ids_perimetre = None

    resultats = []
    for m in periode:
        q_pay = db.query(Paiement).filter(Paiement.mois_concerne == m, Paiement.statut == "paye")
        paiements = q_pay.all()
        if bail_ids_perimetre is not None:
            paiements = [p for p in paiements if p.bail_id in bail_ids_perimetre]
        encaisse = sum(p.montant for p in paiements)

        try:
            an, mo = (int(x) for x in m.split("-"))
            d1 = date(an, mo, 1)
            d2 = date(an, mo, calendar.monthrange(an, mo)[1])
        except Exception:
            d1 = d2 = None
        depenses = 0.0
        if d1:
            q_dep = db.query(Depense).filter(Depense.date_depense >= d1, Depense.date_depense <= d2)
            if maison_id:
                q_dep = q_dep.filter(Depense.maison_id == maison_id)
            depenses = sum(d.montant for d in q_dep.all())

        resultats.append({
            "mois": m,
            "encaisse": round(encaisse, 2),
            "depenses": round(depenses, 2),
            "resultat_net": round(encaisse - depenses, 2),
        })
    return {"maison_id": maison_id, "evolution": resultats}


@app.get("/api/finances/export")
def finances_export(annee: int = None, type: str = "paiements", db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Export comptable CSV des paiements ou des dépenses d'une année."""
    if annee is None:
        annee = date.today().year
    debut, fin = _periode_mois(annee)
    mois_annee = [f"{annee}-{m:02d}" for m in range(1, 13)]

    def csv_line(cols):
        out = []
        for c in cols:
            s = "" if c is None else str(c)
            # Neutraliser une éventuelle formule Excel/LibreOffice (protection contre l'injection CSV)
            if s[:1] in ("=", "+", "-", "@"):
                s = "'" + s
            if any(ch in s for ch in [",", '"', "\n"]):
                s = '"' + s.replace('"', '""') + '"'
            out.append(s)
        return ";".join(out)

    lignes = []
    if type == "depenses":
        lignes.append(csv_line(["Date", "Categorie", "Libelle", "Maison", "Montant"]))
        depenses = db.query(Depense).filter(Depense.date_depense >= debut, Depense.date_depense <= fin).order_by(Depense.date_depense).all()
        maison_map = {m.id: m.adresse for m in db.query(Maison).all()}
        for d in depenses:
            lignes.append(csv_line([d.date_depense, d.categorie, d.libelle, maison_map.get(d.maison_id, "Général"), d.montant]))
        nom = f"depenses_{annee}.csv"
    else:
        lignes.append(csv_line(["Date paiement", "Mois concerne", "Maison", "Locataire", "Mode", "Statut", "Montant"]))
        baux = {b.id: b for b in db.query(Bail).all()}
        maison_map = {m.id: m.adresse for m in db.query(Maison).all()}
        loc_map = {l.id: l.nom for l in db.query(Locataire).all()}
        paiements = db.query(Paiement).filter(Paiement.mois_concerne.in_(mois_annee)).order_by(Paiement.mois_concerne).all()
        for p in paiements:
            bail = baux.get(p.bail_id)
            maison = maison_map.get(bail.maison_id, "") if bail else ""
            locataire = loc_map.get(bail.locataire_id, "") if bail else ""
            lignes.append(csv_line([p.date_paiement, p.mois_concerne, maison, locataire, p.mode, p.statut, p.montant]))
        nom = f"paiements_{annee}.csv"

    contenu = "\ufeff" + "\n".join(lignes)  # BOM UTF-8 pour Excel
    return Response(
        content=contenu,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@app.get("/api/finances/rentabilite-batiments")
def finances_rentabilite_batiments(annee: int = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Rentabilité consolidée par bâtiment sur une année (somme de tous ses logements)."""
    if annee is None:
        annee = date.today().year
    debut, fin = _periode_mois(annee)
    mois_annee = [f"{annee}-{m:02d}" for m in range(1, 13)]

    batiments = db.query(Batiment).all()
    lignes = []
    for bat in batiments:
        logements = db.query(Maison).filter(Maison.batiment_id == bat.id).all()
        maison_ids = [m.id for m in logements]
        nb_occupes = sum(1 for m in logements if m.statut == "occupee")
        encaisse = 0.0
        charges = 0.0
        if maison_ids:
            bail_ids = {b.id for b in db.query(Bail.id).filter(Bail.maison_id.in_(maison_ids)).all()}
            if bail_ids:
                paiements = db.query(Paiement).filter(
                    Paiement.mois_concerne.in_(mois_annee),
                    Paiement.statut == "paye",
                    Paiement.bail_id.in_(bail_ids),
                ).all()
                encaisse = sum(p.montant for p in paiements)
            depenses = db.query(Depense).filter(
                Depense.maison_id.in_(maison_ids),
                Depense.date_depense >= debut,
                Depense.date_depense <= fin,
            ).all()
            tickets = db.query(Ticket).filter(
                Ticket.maison_id.in_(maison_ids),
                Ticket.date_creation >= datetime.combine(debut, datetime.min.time()),
                Ticket.date_creation <= datetime.combine(fin, datetime.max.time()),
            ).all()
            charges = sum(d.montant for d in depenses) + sum(t.cout for t in tickets)
        net = encaisse - charges
        lignes.append({
            "batiment_id": bat.id,
            "nom": bat.nom,
            "proprietaire": bat.proprietaire,
            "nb_logements": len(logements),
            "nb_occupes": nb_occupes,
            "taux_occupation": round(nb_occupes / len(logements) * 100, 1) if logements else 0,
            "encaisse": round(encaisse, 2),
            "charges": round(charges, 2),
            "resultat_net": round(net, 2),
            "rendement_pct": round(net / encaisse * 100, 1) if encaisse else None,
        })
    lignes.sort(key=lambda x: x["resultat_net"], reverse=True)
    return {
        "annee": annee,
        "lignes": lignes,
        "total_encaisse": round(sum(l["encaisse"] for l in lignes), 2),
        "total_charges": round(sum(l["charges"] for l in lignes), 2),
        "resultat_net_global": round(sum(l["resultat_net"] for l in lignes), 2),
    }


@app.get("/api/finances/previsionnel")
def finances_previsionnel(mois: int = 6, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Prévisionnel de trésorerie : projette les loyers attendus des baux actifs sur les prochains mois,
    en tenant compte des dates de fin de bail. Compare au réalisé du mois en cours."""
    n = max(1, min(mois, 12))
    aujourd_hui = date.today()
    baux_actifs = db.query(Bail).filter(Bail.statut == "actif").all()

    # Générer les n prochains mois (à partir du mois courant)
    projection = []
    an, m = aujourd_hui.year, aujourd_hui.month
    for i in range(n):
        mois_str = f"{an}-{m:02d}"
        # Dernier jour du mois pour vérifier si le bail court encore
        dernier_jour = date(an, m, calendar.monthrange(an, m)[1])
        attendu = 0.0
        nb_baux = 0
        for b in baux_actifs:
            # Le bail contribue si sa date de fin est nulle ou postérieure au début du mois
            debut_mois = date(an, m, 1)
            if b.date_fin and b.date_fin < debut_mois:
                continue
            if b.date_debut and b.date_debut > dernier_jour:
                continue
            attendu += b.loyer_mensuel
            nb_baux += 1
        # Réalisé (uniquement pour le mois courant et les mois passés)
        realise = None
        if mois_str <= aujourd_hui.strftime("%Y-%m"):
            paiements = db.query(Paiement).filter(
                Paiement.mois_concerne == mois_str, Paiement.statut == "paye",
            ).all()
            realise = round(sum(p.montant for p in paiements), 2)
        projection.append({
            "mois": mois_str,
            "attendu": round(attendu, 2),
            "nb_baux": nb_baux,
            "realise": realise,
        })
        m += 1
        if m > 12:
            m = 1
            an += 1

    total_attendu = sum(p["attendu"] for p in projection)
    return {
        "mois_projetes": n,
        "projection": projection,
        "total_attendu": round(total_attendu, 2),
        "moyenne_mensuelle": round(total_attendu / n, 2) if n else 0,
    }


# ---------- Automatisation : impayés, échéancier, contrats ----------
def _telephone_wa(tel: Optional[str]) -> Optional[str]:
    """Nettoie un numéro pour un lien wa.me (Côte d'Ivoire : préfixe 225 par défaut)."""
    if not tel:
        return None
    chiffres = "".join(c for c in tel if c.isdigit())
    if not chiffres:
        return None
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if not chiffres.startswith("225") and len(chiffres) <= 10:
        chiffres = "225" + chiffres
    return chiffres


@app.get("/api/impayes")
def liste_impayes(mois: str = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Locataires n'ayant pas soldé leur loyer pour le mois donné (défaut : mois courant),
    avec un message de relance pré-rédigé et un lien WhatsApp cliquable."""
    from urllib.parse import quote
    if not mois:
        mois = date.today().strftime("%Y-%m")
    baux_actifs = db.query(Bail).filter(Bail.statut == "actif").all()
    paiements_mois = db.query(Paiement).filter(Paiement.mois_concerne == mois).all()
    paye_par_bail = {}
    for p in paiements_mois:
        if p.statut == "paye":
            paye_par_bail[p.bail_id] = paye_par_bail.get(p.bail_id, 0) + p.montant

    resultats = []
    for b in baux_actifs:
        deja_paye = paye_par_bail.get(b.id, 0)
        reste = b.loyer_mensuel - deja_paye
        if reste <= 0:
            continue
        maison = db.query(Maison).get(b.maison_id)
        locataire = db.query(Locataire).get(b.locataire_id)
        nom_loc = locataire.nom if locataire else "Locataire"
        adresse = maison.adresse if maison else "votre logement"
        message = (
            f"Bonjour {nom_loc}, nous vous rappelons que le loyer de {reste:,.0f} {DEVISE} "
            f"pour {adresse} (période {mois}) reste à régler. "
            f"Merci de bien vouloir procéder au paiement dans les meilleurs délais. "
            f"Cordialement, {SOCIETE_NOM}."
        ).replace(",", " ")
        wa = _telephone_wa(locataire.telephone if locataire else None)
        resultats.append({
            "bail_id": b.id,
            "locataire": nom_loc,
            "telephone": locataire.telephone if locataire else None,
            "maison": adresse,
            "loyer_mensuel": b.loyer_mensuel,
            "deja_paye": deja_paye,
            "reste_a_payer": reste,
            "message_relance": message,
            "lien_whatsapp": f"https://wa.me/{wa}?text={quote(message)}" if wa else None,
        })
    resultats.sort(key=lambda x: x["reste_a_payer"], reverse=True)
    return {
        "mois": mois,
        "nombre_impayes": len(resultats),
        "total_du": sum(r["reste_a_payer"] for r in resultats),
        "impayes": resultats,
    }


@app.get("/api/echeancier")
def echeancier(mois: str = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """État de paiement de chaque bail actif pour le mois : payé / partiel / dû."""
    if not mois:
        mois = date.today().strftime("%Y-%m")
    baux_actifs = db.query(Bail).filter(Bail.statut == "actif").all()
    paiements_mois = db.query(Paiement).filter(Paiement.mois_concerne == mois).all()
    paye_par_bail = {}
    for p in paiements_mois:
        if p.statut == "paye":
            paye_par_bail[p.bail_id] = paye_par_bail.get(p.bail_id, 0) + p.montant

    lignes = []
    total_attendu = 0.0
    total_encaisse = 0.0
    for b in baux_actifs:
        maison = db.query(Maison).get(b.maison_id)
        locataire = db.query(Locataire).get(b.locataire_id)
        paye = paye_par_bail.get(b.id, 0)
        total_attendu += b.loyer_mensuel
        total_encaisse += min(paye, b.loyer_mensuel)
        if paye >= b.loyer_mensuel:
            etat = "paye"
        elif paye > 0:
            etat = "partiel"
        else:
            etat = "du"
        lignes.append({
            "bail_id": b.id,
            "maison": libelle_logement(maison, db) if maison else "—",
            "locataire": locataire.nom if locataire else "—",
            "loyer_mensuel": b.loyer_mensuel,
            "paye": paye,
            "reste": max(0, b.loyer_mensuel - paye),
            "etat": etat,
        })
    ordre = {"du": 0, "partiel": 1, "paye": 2}
    lignes.sort(key=lambda x: ordre.get(x["etat"], 3))
    return {
        "mois": mois,
        "total_attendu": total_attendu,
        "total_encaisse": total_encaisse,
        "taux": round(total_encaisse / total_attendu * 100, 1) if total_attendu else 0,
        "lignes": lignes,
    }


def generer_contrat_pdf(bail, maison, locataire) -> io.BytesIO:
    """Contrat de bail d'habitation à la charte TOURÉ IMMOBILIER."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 15 * mm

    c.setStrokeColor(BORDER)
    c.setLineWidth(1)
    c.rect(margin - 6, margin - 6, width - 2 * (margin - 6), height - 2 * (margin - 6))

    header_h = 32 * mm
    c.setFillColor(NAVY)
    c.rect(0, height - header_h, width, header_h, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(0, height - header_h - 2, width, 2, stroke=0, fill=1)

    # Logo (encart blanc arrondi, façon cachet, à gauche du bandeau)
    logo_size = 20 * mm
    logo_x = margin
    logo_y = height - header_h / 2 - logo_size / 2
    c.setFillColor(colors.white)
    c.roundRect(logo_x, logo_y, logo_size, logo_size, 3, stroke=0, fill=1)
    c.drawImage(ImageReader(io.BytesIO(LOGO_TOURE_BYTES)), logo_x + 1, logo_y + 1,
                width=logo_size - 2, height=logo_size - 2, mask="auto", preserveAspectRatio=True)
    text_x = logo_x + logo_size + 6

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(text_x, height - 15 * mm, SOCIETE_NOM)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(text_x, height - 21 * mm, SOCIETE_TAGLINE)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(width - margin, height - 14 * mm, "CONTRAT DE BAIL")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin, height - 20 * mm, f"N° {bail.id:05d}")
    c.drawRightString(width - margin, height - 25 * mm, f"Établi le {date.today().strftime('%d/%m/%Y')}")

    y = height - header_h - 14 * mm
    c.setFillColor(colors.black)

    def para(titre, lignes, y):
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, titre)
        y -= 6 * mm
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 10)
        for ligne in lignes:
            c.drawString(margin + 4, y, ligne)
            y -= 5.5 * mm
        return y - 3 * mm

    caution_txt = f"{bail.caution:,.0f} {DEVISE}".replace(",", " ") if bail.caution else "Néant"
    loyer_txt = f"{bail.loyer_mensuel:,.0f} {DEVISE}".replace(",", " ")
    y = para("ENTRE LES SOUSSIGNÉS", [
        f"Le Bailleur : {SOCIETE_NOM}, représenté par {SOCIETE_GERANT}.",
        f"Le Locataire : {locataire.nom if locataire else '-'}"
        + (f", tél. {locataire.telephone}" if locataire and locataire.telephone else ""),
    ], y)
    y = para("DÉSIGNATION DU BIEN LOUÉ", [
        f"Adresse : {maison.adresse if maison else '-'}",
        f"Nombre de pièces : {maison.nb_pieces if maison else '-'}",
    ], y)
    y = para("CONDITIONS FINANCIÈRES", [
        f"Loyer mensuel : {loyer_txt}, payable d'avance.",
        f"Dépôt de garantie (caution) : {caution_txt}.",
        f"Date de prise d'effet : {bail.date_debut.strftime('%d/%m/%Y') if bail.date_debut else '-'}"
        + (f"     Échéance : {bail.date_fin.strftime('%d/%m/%Y')}" if bail.date_fin else "     Durée : indéterminée"),
    ], y)
    y = para("OBLIGATIONS DES PARTIES", [
        "Le locataire s'engage à payer le loyer aux échéances convenues, à user paisiblement",
        "des lieux et à les entretenir. Le bailleur s'engage à délivrer un logement décent et",
        "à en garantir la jouissance paisible pendant toute la durée du bail.",
    ], y)

    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Fait à Abidjan, le {date.today().strftime('%d/%m/%Y')}, en deux exemplaires.")
    y -= 18 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Le Bailleur")
    c.drawRightString(width - margin, y, "Le Locataire")
    c.setStrokeColor(BORDER)
    c.line(margin, y - 2, margin + 55 * mm, y - 2)
    c.line(width - margin - 55 * mm, y - 2, width - margin, y - 2)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


@app.get("/api/baux/{bail_id}/contrat")
def contrat_bail(bail_id: int, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    bail = db.query(Bail).get(bail_id)
    if not bail:
        raise HTTPException(404, "Bail introuvable")
    maison = db.query(Maison).get(bail.maison_id)
    locataire = db.query(Locataire).get(bail.locataire_id)
    pdf = generer_contrat_pdf(bail, maison, locataire)
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="contrat_bail_{bail_id:05d}.pdf"'},
    )


# ---------- Robustesse : journal d'activité & sauvegarde ----------
@app.get("/api/journal")
def liste_journal(limit: int = 200, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    """Dernières entrées du journal d'activité (les plus récentes d'abord)."""
    limit = max(1, min(limit, 1000))
    entrees = db.query(JournalActivite).order_by(JournalActivite.date_action.desc()).limit(limit).all()
    return [{
        "id": e.id,
        "date_action": e.date_action.isoformat() if e.date_action else None,
        "utilisateur": e.utilisateur_nom or "—",
        "action": e.action,
        "objet": e.objet,
        "details": e.details,
    } for e in entrees]


@app.get("/api/sauvegarde")
def sauvegarde_base(db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    """Export complet de la base (hors contenus binaires des pièces) au format JSON,
    pour archivage local par le gérant."""
    def serial(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return v

    def dump(model, exclude=()):
        lignes = []
        for obj in db.query(model).all():
            d = {}
            for col in model.__table__.columns:
                if col.name in exclude:
                    continue
                d[col.name] = serial(getattr(obj, col.name))
            lignes.append(d)
        return lignes

    data = {
        "meta": {
            "societe": SOCIETE_NOM,
            "genere_le": datetime.utcnow().isoformat(),
            "genere_par": current.nom,
            "version": 1,
        },
        "users": dump(User, exclude=("mot_de_passe_hash", "reset_token", "reset_token_expiry")),
        "maisons": dump(Maison),
        "locataires": dump(Locataire),
        "baux": dump(Bail),
        "paiements": dump(Paiement),
        "tickets": dump(Ticket),
        "depenses": dump(Depense),
        "observations": dump(Observation),
        # Pièces justificatives : métadonnées seulement (le binaire "contenu" est exclu pour garder un fichier léger)
        "pieces_justificatives": dump(PieceJustificative, exclude=("contenu",)),
    }
    import json
    contenu = json.dumps(data, ensure_ascii=False, indent=2)
    nom = f"sauvegarde_{date.today().strftime('%Y%m%d')}.json"
    journaliser(db, current, "sauvegarde", "base", "Export JSON complet")
    return Response(
        content=contenu,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


# ---------- Portail locataire (accès par lien privé, sans authentification) ----------
class TicketPortailIn(BaseModel):
    description: str


def _locataire_par_token(db: Session, token: str) -> Locataire:
    if not token:
        raise HTTPException(404, "Lien invalide")
    loc = db.query(Locataire).filter(Locataire.portail_token == token).first()
    if not loc:
        raise HTTPException(404, "Lien invalide ou expiré")
    return loc


@app.post("/api/locataires/{locataire_id}/portail-token")
def generer_portail_token(locataire_id: int, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    """(Ré)génère le lien privé du portail pour un locataire."""
    loc = db.query(Locataire).get(locataire_id)
    if not loc:
        raise HTTPException(404, "Locataire introuvable")
    loc.portail_token = secrets.token_urlsafe(24)
    db.commit()
    db.refresh(loc)
    journaliser(db, current, "modification", "locataire", f"Lien portail généré pour {loc.nom}")
    return {"locataire_id": loc.id, "portail_token": loc.portail_token}


@app.delete("/api/locataires/{locataire_id}/portail-token")
def revoquer_portail_token(locataire_id: int, db: Session = Depends(get_db), current: User = Depends(require_gerant)):
    """Révoque le lien privé (le rend inutilisable)."""
    loc = db.query(Locataire).get(locataire_id)
    if not loc:
        raise HTTPException(404, "Locataire introuvable")
    loc.portail_token = None
    db.commit()
    journaliser(db, current, "modification", "locataire", f"Lien portail révoqué pour {loc.nom}")
    return {"ok": True}


@app.get("/api/portail/{token}")
def portail_data(token: str, db: Session = Depends(get_db)):
    """Données du portail locataire (lecture seule) accessibles via le lien privé."""
    loc = _locataire_par_token(db, token)
    baux = db.query(Bail).filter(Bail.locataire_id == loc.id).order_by(Bail.date_debut.desc()).all()
    baux_data = []
    for b in baux:
        maison = db.query(Maison).get(b.maison_id)
        paiements = db.query(Paiement).filter(Paiement.bail_id == b.id).order_by(Paiement.mois_concerne.desc()).all()
        baux_data.append({
            "bail_id": b.id,
            "maison_adresse": libelle_logement(maison, db) if maison else "—",
            "statut": b.statut,
            "date_debut": b.date_debut.isoformat() if b.date_debut else None,
            "date_fin": b.date_fin.isoformat() if b.date_fin else None,
            "loyer_mensuel": b.loyer_mensuel,
            "caution": b.caution,
            "paiements": [{
                "id": p.id,
                "mois_concerne": p.mois_concerne,
                "montant": p.montant,
                "statut": p.statut,
                "date_paiement": p.date_paiement.isoformat() if p.date_paiement else None,
                "quittance_disponible": p.statut == "paye",
            } for p in paiements],
        })
    # Tickets déjà signalés par ce locataire
    tickets = db.query(Ticket).filter(Ticket.locataire_id == loc.id).order_by(Ticket.date_creation.desc()).all()
    return {
        "societe": SOCIETE_NOM,
        "locataire": {"nom": loc.nom, "telephone": loc.telephone},
        "baux": baux_data,
        "tickets": [{
            "id": t.id,
            "description": t.description,
            "statut": t.statut,
            "date_creation": t.date_creation.isoformat() if t.date_creation else None,
        } for t in tickets],
    }


@app.get("/api/portail/{token}/quittance/{paiement_id}")
def portail_quittance(token: str, paiement_id: int, request: Request, db: Session = Depends(get_db)):
    """Téléchargement d'une quittance depuis le portail (vérifie que le paiement appartient bien au locataire)."""
    loc = _locataire_par_token(db, token)
    paiement = db.query(Paiement).get(paiement_id)
    if not paiement:
        raise HTTPException(404, "Paiement introuvable")
    bail = db.query(Bail).get(paiement.bail_id)
    if not bail or bail.locataire_id != loc.id:
        raise HTTPException(403, "Accès refusé à ce document")
    if paiement.statut != "paye":
        raise HTTPException(400, "Quittance disponible uniquement pour un paiement soldé")
    maison = db.query(Maison).get(bail.maison_id) if bail else None
    locataire = loc
    if not paiement.verification_code:
        paiement.verification_code = generate_verification_code()
        db.commit()
        db.refresh(paiement)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    verify_url = f"{proto}://{host}/verifier.html?code={paiement.verification_code}"
    buffer = generer_quittance_pdf(paiement, bail, maison, locataire, verify_url)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=quittance_{paiement.id}.pdf"},
    )


@app.post("/api/portail/{token}/ticket")
def portail_creer_ticket(token: str, data: TicketPortailIn, db: Session = Depends(get_db)):
    """Le locataire signale un problème depuis son portail (crée un ticket de maintenance)."""
    loc = _locataire_par_token(db, token)
    if not data.description or not data.description.strip():
        raise HTTPException(400, "La description ne peut pas être vide")
    # Rattache le ticket au bail actif du locataire (sinon au plus récent)
    bail = db.query(Bail).filter(Bail.locataire_id == loc.id, Bail.statut == "actif").first()
    if not bail:
        bail = db.query(Bail).filter(Bail.locataire_id == loc.id).order_by(Bail.date_debut.desc()).first()
    if not bail:
        raise HTTPException(400, "Aucun bail associé à votre compte")
    ticket = Ticket(
        maison_id=bail.maison_id,
        locataire_id=loc.id,
        description=data.description.strip(),
        statut="ouvert",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    journaliser(db, None, "creation", "ticket", f"Signalement portail de {loc.nom}")
    return {"ok": True, "ticket_id": ticket.id}


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
            + (f"Périmètre : uniquement la maison « {stats['maison_adresse']} ».\n" if stats.get("maison_adresse") else "Périmètre : l'ensemble du parc immobilier.\n")
            + f"Données du mois {stats['mois']} :\n"
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
def bilan_mensuel(mois: str, maison_id: Optional[int] = None, batiment_id: Optional[int] = None, db: Session = Depends(get_db), _: User = Depends(require_gerant)):
    # Périmètre : tout le parc, un logement précis (maison_id), ou tout un bâtiment (batiment_id)
    maison_cible = None
    batiment_cible = None
    perimetre_ids = None  # None = tout le parc ; sinon liste d'ids de logements
    if maison_id:
        maison_cible = db.query(Maison).get(maison_id)
        if not maison_cible:
            raise HTTPException(404, "Logement introuvable")
        perimetre_ids = [maison_id]
    elif batiment_id:
        batiment_cible = db.query(Batiment).get(batiment_id)
        if not batiment_cible:
            raise HTTPException(404, "Bâtiment introuvable")
        perimetre_ids = [m.id for m in db.query(Maison.id).filter(Maison.batiment_id == batiment_id).all()]
        if not perimetre_ids:
            perimetre_ids = [-1]  # bâtiment vide : aucun logement

    q_maisons = db.query(Maison)
    if perimetre_ids is not None:
        q_maisons = q_maisons.filter(Maison.id.in_(perimetre_ids))
    total_maisons = q_maisons.count()
    maisons_occupees = q_maisons.filter(Maison.statut == "occupee").count()
    taux_occupation = round(maisons_occupees / total_maisons * 100, 1) if total_maisons else 0

    q_baux = db.query(Bail).filter(Bail.statut == "actif")
    if perimetre_ids is not None:
        q_baux = q_baux.filter(Bail.maison_id.in_(perimetre_ids))
    baux_actifs = q_baux.all()
    total_attendu = sum(b.loyer_mensuel for b in baux_actifs)

    # Ids des baux du périmètre (tous statuts confondus) pour filtrer les paiements
    if perimetre_ids is not None:
        bail_ids_perimetre = {b.id for b in db.query(Bail.id).filter(Bail.maison_id.in_(perimetre_ids)).all()}
    else:
        bail_ids_perimetre = None

    paiements_mois = db.query(Paiement).filter(Paiement.mois_concerne == mois).all()
    if bail_ids_perimetre is not None:
        paiements_mois = [p for p in paiements_mois if p.bail_id in bail_ids_perimetre]
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

    q_depenses = db.query(Depense).filter(Depense.date_depense >= premier_jour, Depense.date_depense <= dernier_jour)
    if perimetre_ids is not None:
        q_depenses = q_depenses.filter(Depense.maison_id.in_(perimetre_ids))
    depenses_mois = q_depenses.all()
    total_depenses = sum(d.montant for d in depenses_mois)
    depenses_par_categorie = {}
    for d in depenses_mois:
        depenses_par_categorie[d.categorie] = depenses_par_categorie.get(d.categorie, 0) + d.montant

    resultat_net = total_encaisse - total_depenses

    q_tickets = db.query(Ticket).filter(Ticket.date_creation >= datetime.combine(premier_jour, datetime.min.time()),
                                        Ticket.date_creation <= datetime.combine(dernier_jour, datetime.max.time()))
    if perimetre_ids is not None:
        q_tickets = q_tickets.filter(Ticket.maison_id.in_(perimetre_ids))
    tickets_mois = q_tickets.all()
    cout_tickets_mois = sum(t.cout for t in tickets_mois)

    # Pièces justificatives rattachées au périmètre sur la période
    q_pieces = db.query(PieceJustificative).filter(
        PieceJustificative.date_upload >= datetime.combine(premier_jour, datetime.min.time()),
        PieceJustificative.date_upload <= datetime.combine(dernier_jour, datetime.max.time()),
    )
    if perimetre_ids is not None:
        q_pieces = q_pieces.filter(PieceJustificative.maison_id.in_(perimetre_ids))
    nb_pieces_mois = q_pieces.count()

    mois_prec = mois_precedent(mois)
    paiements_mois_prec = db.query(Paiement).filter(Paiement.mois_concerne == mois_prec, Paiement.statut == "paye").all()
    if bail_ids_perimetre is not None:
        paiements_mois_prec = [p for p in paiements_mois_prec if p.bail_id in bail_ids_perimetre]
    total_encaisse_prec = sum(p.montant for p in paiements_mois_prec)
    variation_encaisse_pct = round((total_encaisse - total_encaisse_prec) / total_encaisse_prec * 100, 1) if total_encaisse_prec else None

    stats = {
        "mois": mois,
        "maison_id": maison_id,
        "batiment_id": batiment_id,
        "maison_adresse": (libelle_logement(maison_cible, db) if maison_cible
                           else (f"Bâtiment {batiment_cible.nom}" if batiment_cible else None)),
        "nb_pieces_justificatives": nb_pieces_mois,
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
