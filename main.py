# app.py - APPLICATION DE SIMULATION ÉLECTORALE
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, UTC
from functools import wraps
from io import BytesIO
import base64
import hmac
import json
import os
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
import enum
import hashlib
import secrets
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from markupsafe import Markup, escape
from sqlalchemy import inspect, text, or_
from sqlalchemy.exc import IntegrityError
from config import Config, DevelopmentConfig, ProductionConfig, TestingConfig

try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
except Exception:
    CSRFProtect = None

    class CSRFError(Exception):
        def __init__(self, description="Jeton CSRF invalide"):
            super().__init__(description)
            self.description = description

    def generate_csrf():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

try:
    from email_validator import validate_email, EmailNotValidError  # pyright: ignore[reportMissingImports]
except Exception:  # Dépendance optionnelle (installée via `requirements.txt`)
    validate_email = None

    class EmailNotValidError(Exception):
        pass

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None

try:
    import qrcode
except Exception:
    qrcode = None

# ========== CONFIGURATION ==========
app = Flask(__name__)

# Configuration de l'application
app_env = (os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "").strip().lower()
config_object = {
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
}.get(app_env, Config)
app.config.from_object(config_object)

# Optionnel: URL DB unique (12-factor). Ex: mysql+mysqlconnector://...
database_url = os.environ.get("DATABASE_URL")
if database_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url

# Valeurs de compatibilité (certains templates s'appuient dessus)
app.config.setdefault("REMEMBER_COOKIE_HTTPONLY", True)
app.config.setdefault("REMEMBER_COOKIE_DURATION", timedelta(days=7))

# Normaliser le dossier d'upload en chemin absolu (évite les soucis de cwd avec Code Runner).
upload_folder = app.config.get("UPLOAD_FOLDER", "static/uploads")
if upload_folder and not os.path.isabs(upload_folder):
    upload_folder = os.path.join(app.root_path, upload_folder)
app.config["UPLOAD_FOLDER"] = upload_folder

def _allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower().strip()
    allowed = app.config.get("ALLOWED_EXTENSIONS") or {"png", "jpg", "jpeg", "gif", "webp"}
    try:
        return ext in set(allowed)
    except Exception:
        return ext in {"png", "jpg", "jpeg", "gif", "webp"}

# Initialisation des extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app) if CSRFProtect else None

# Configuration du gestionnaire de connexion
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = None  # Messages personnalisés dans les templates
login_manager.session_protection = "strong"

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if str(app.config.get("SECRET_KEY") or "").startswith("dev-secret-key"):
    logger.warning("SECRET_KEY de développement détectée. Définissez une clé forte en production.")

def mask_sensitive(value, show_last=4, mask_char="•"):
    if not value:
        return ""
    s = str(value).strip()
    if len(s) <= show_last:
        return mask_char * len(s)
    return (mask_char * (len(s) - show_last)) + s[-show_last:]

def calculate_age(birth_date: date) -> int:
    today = date.today()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )

def _clean_header_value(value: str, max_len: int = 180) -> str:
    """Nettoie une valeur de header email (anti injection via CRLF)."""
    if value is None:
        return ""
    s = str(value).strip().replace("\r", " ").replace("\n", " ")
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s

def _normalize_email_address(value: str, *, check_deliverability: bool = False) -> str:
    email = (value or "").strip()
    if not email:
        raise EmailNotValidError("Email vide")

    if validate_email:
        return validate_email(email, check_deliverability=check_deliverability).email

    # Fallback minimal si `email_validator` n'est pas disponible.
    if "@" not in email:
        raise EmailNotValidError("Email invalide")
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        raise EmailNotValidError("Email invalide")
    if any(ch.isspace() for ch in email):
        raise EmailNotValidError("Email invalide")
    return email

def _verification_email_enabled() -> bool:
    host = (app.config.get("SMTP_HOST") or "").strip()
    sender = (app.config.get("SMTP_SENDER") or app.config.get("SMTP_USERNAME") or "").strip()
    return bool(host and sender)

def _verification_redirect(email: str):
    return redirect(url_for("login", email=email, email_verification="1"))

def _public_upload_dir(*segments: str) -> str:
    return os.path.join(app.static_folder, "uploads", *segments)

def _send_system_email(*, to_email: str, subject: str, text_content: str, reply_to: str | None = None) -> None:
    host = (app.config.get("SMTP_HOST") or "").strip()
    if not host:
        raise RuntimeError("Envoi email non activé sur ce serveur (configuration SMTP manquante).")

    port = int(app.config.get("SMTP_PORT") or 587)
    use_ssl = bool(app.config.get("SMTP_USE_SSL", False))
    use_tls = bool(app.config.get("SMTP_USE_TLS", True))

    username = (app.config.get("SMTP_USERNAME") or "").strip()
    password = app.config.get("SMTP_PASSWORD") or ""
    sender = (app.config.get("SMTP_SENDER") or username).strip()
    if not sender:
        raise RuntimeError("Adresse expéditrice SMTP manquante.")

    from_name = _clean_header_value(
        app.config.get("ELECTION_NAME") or app.config.get("APP_NAME") or "Élection Nationale",
        max_len=80,
    )
    safe_subject = _clean_header_value(subject, max_len=140)
    msg = EmailMessage()
    msg["Subject"] = safe_subject
    msg["From"] = formataddr((from_name, sender))
    msg["To"] = _clean_header_value(to_email, max_len=180)
    if reply_to:
        msg["Reply-To"] = _clean_header_value(reply_to, max_len=180)
    msg.set_content((text_content or "").strip() + "\n")

    timeout_seconds = 20
    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    smtp_kwargs = {"timeout": timeout_seconds}
    if use_ssl:
        smtp_kwargs["context"] = ssl.create_default_context()

    with smtp_cls(host, port, **smtp_kwargs) as smtp:
        smtp.ehlo()
        if (not use_ssl) and use_tls:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)

def _send_contact_email(*, full_name: str, email: str, subject: str, message: str, phone: str | None = None) -> None:
    recipient = (app.config.get("CONTACT_RECIPIENT") or "").strip()
    if not recipient:
        raise RuntimeError("Envoi email non activé sur ce serveur (adresse de réception non définie).")

    safe_name = _clean_header_value(full_name, max_len=120)
    safe_email = _clean_header_value(email, max_len=180)
    safe_phone = (phone or "").strip()
    if len(safe_phone) > 60:
        safe_phone = safe_phone[:60].rstrip()

    _send_system_email(
        to_email=recipient,
        subject=f"[Contact] {_clean_header_value(subject, max_len=140)}",
        reply_to=safe_email,
        text_content=(
            "Nouveau message depuis le formulaire de contact.\n\n"
            f"Nom: {safe_name}\n"
            f"Email: {safe_email}\n"
            f"Téléphone: {safe_phone or '-'}\n\n"
            "Message:\n"
            f"{(message or '').strip()}"
        ),
    )

def _generate_email_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

def _hash_email_verification_code(user, code: str) -> str:
    secret = str(app.config.get("SECRET_KEY") or "")
    raw = f"email-verify|{getattr(user, 'id', '')}|{(getattr(user, 'email', '') or '').lower()}|{code}|{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _issue_email_verification(user) -> None:
    if not user:
        raise RuntimeError("Utilisateur introuvable pour la vérification email.")
    if not _verification_email_enabled():
        raise RuntimeError("La vérification email n'est pas configurée sur ce serveur.")
    if getattr(user, "id", None) is None:
        db.session.flush()

    ttl_minutes = max(5, int(app.config.get("EMAIL_VERIFICATION_CODE_TTL_MINUTES", 15) or 15))
    issued_at = datetime.now(UTC)
    code = _generate_email_verification_code()

    user.email_verified_at = None
    user.email_verification_code_hash = _hash_email_verification_code(user, code)
    user.email_verification_sent_at = issued_at
    user.email_verification_expires_at = issued_at + timedelta(minutes=ttl_minutes)

    election_name = app.config.get("ELECTION_NAME") or app.config.get("APP_NAME") or "Élection Nationale"
    _send_system_email(
        to_email=user.email,
        subject=f"{election_name} - Code de confirmation",
        text_content=(
            f"Bonjour,\n\n"
            f"Votre code de confirmation pour {election_name} est : {code}\n\n"
            f"Ce code expire dans {ttl_minutes} minutes.\n"
            "Saisissez-le sur la page de connexion pour activer votre compte.\n\n"
            "Si vous n'êtes pas à l'origine de cette inscription, ignorez cet email."
        ),
    )

def _confirm_user_email(user, code: str) -> tuple[bool, str]:
    if not user:
        return False, "Compte introuvable."
    if user.is_email_verified:
        return True, "Cet email est déjà confirmé."

    submitted_code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(submitted_code) != 6:
        return False, "Le code de confirmation doit contenir 6 chiffres."
    if not user.email_verification_code_hash:
        return False, "Aucun code de confirmation n'est disponible. Demandez un nouveau code."
    if not user.email_verification_expires_at or user.email_verification_expires_at < datetime.utcnow():
        return False, "Le code de confirmation a expiré. Demandez un nouveau code."

    expected_hash = _hash_email_verification_code(user, submitted_code)
    if not hmac.compare_digest(user.email_verification_code_hash, expected_hash):
        return False, "Code de confirmation invalide."

    user.email_verified_at = datetime.utcnow()
    user.email_verification_code_hash = None
    user.email_verification_expires_at = None
    user.email_verification_sent_at = None
    return True, "Email confirmé. Vous pouvez maintenant vous connecter."

def _build_voter_card_token(voter) -> str:
    """
    Token stable (simulation) pour vérifier une carte d'électeur via QR code.
    Ne révèle pas la CNI en clair : on utilise un hash + SECRET_KEY.
    """
    secret = str(app.config.get("SECRET_KEY") or "")
    voter_id = getattr(voter, "id", "")
    cni_number = getattr(voter, "cni_number", "")
    raw = f"voter-card|{voter_id}|{cni_number}|{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()

def _build_voter_card_verify_url(voter, token: str) -> str:
    try:
        voter_id = int(getattr(voter, "id", 0) or 0)
    except Exception:
        voter_id = 0
    return url_for("verify_voter_card", voter_id=voter_id, token=token, _external=True)

def _qr_png_bytes(data: str, *, box_size: int = 7, border: int = 2) -> bytes | None:
    """Génère un QR code PNG (bytes). Retourne None si la lib `qrcode` est absente."""
    if not qrcode:
        return None

    try:
        qr = qrcode.QRCode(
            version=None,
            box_size=box_size,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        if hasattr(img, "convert"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        logger.exception("Erreur génération QR code")
        return None

def _qr_data_uri(data: str, *, box_size: int = 7, border: int = 2) -> str | None:
    png = _qr_png_bytes(data, box_size=box_size, border=border)
    if not png:
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

# ========== MODÈLES ==========
class UserRole(enum.Enum):
    VISITOR = "visitor"
    VOTER = "voter"
    CANDIDATE = "candidate"
    ADMIN = "admin"

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='visitor', nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    display_name = db.Column(db.String(120))
    phone_number = db.Column(db.String(30))
    avatar_filename = db.Column(db.String(255))
    email_verified_at = db.Column(db.DateTime)
    email_verification_code_hash = db.Column(db.String(128))
    email_verification_expires_at = db.Column(db.DateTime)
    email_verification_sent_at = db.Column(db.DateTime)
    
    # Relations
    voter_profile = db.relationship('Voter', backref='user', uselist=False, cascade='all, delete-orphan')
    candidate_profile = db.relationship('Candidate', backref='user', uselist=False, cascade='all, delete-orphan')
    announcements = db.relationship('Announcement', backref='author', lazy='dynamic', foreign_keys='Announcement.author_id')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    @property
    def login_count(self):
        # Champ attendu par certains templates (placeholder).
        return 0

    @property
    def profile_name(self):
        return (self.display_name or "").strip() or self.email.split("@")[0]
    
    def __repr__(self):
        return f'<User {self.email}>'

class Voter(db.Model):
    __tablename__ = 'voters'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    
    # Informations personnelles
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    cni_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    date_of_birth = db.Column(db.Date, nullable=False)
    place_of_birth = db.Column(db.String(100), nullable=False)
    gender = db.Column(db.String(1))
    
    # Vote
    has_voted = db.Column(db.Boolean, default=False, index=True)
    voted_at = db.Column(db.DateTime)
    vote_for_id = db.Column(db.Integer, db.ForeignKey('candidates.id'))
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    details = db.relationship(
        "VoterDetails",
        backref="voter",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def _ensure_details(self):
        if not self.details:
            self.details = VoterDetails()
        return self.details
    
    @property
    def age(self):
        today = date.today()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def cni_masked(self):
        return mask_sensitive(self.cni_number, show_last=4)

    @property
    def phone_number(self):
        return self.details.phone_number if self.details else None

    @phone_number.setter
    def phone_number(self, value):
        self._ensure_details().phone_number = (value or "").strip() or None

    @property
    def is_eligible(self):
        if self.details and self.details.is_eligible is not None:
            return bool(self.details.is_eligible)
        try:
            min_age = int(app.config.get("MIN_VOTER_AGE", 18))
        except Exception:
            min_age = 18
        return self.age >= min_age

    @is_eligible.setter
    def is_eligible(self, value):
        self._ensure_details().is_eligible = bool(value)

    @property
    def eligibility_reason(self):
        return self.details.eligibility_reason if self.details else None

    @eligibility_reason.setter
    def eligibility_reason(self, value):
        self._ensure_details().eligibility_reason = (value or "").strip() or None

    @property
    def eligibility_checked_at(self):
        return self.details.eligibility_checked_at if self.details else None

    @eligibility_checked_at.setter
    def eligibility_checked_at(self, value):
        self._ensure_details().eligibility_checked_at = value
    
    def __repr__(self):
        return f'<Voter {self.full_name}>'

class VoterDetails(db.Model):
    __tablename__ = "voter_details"

    voter_id = db.Column(db.Integer, db.ForeignKey("voters.id"), primary_key=True)

    phone_number = db.Column(db.String(30))
    is_eligible = db.Column(db.Boolean)  # None => calcul automatique
    eligibility_reason = db.Column(db.String(255))
    eligibility_checked_at = db.Column(db.DateTime)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Candidate(db.Model):
    __tablename__ = 'candidates'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    
    # Informations personnelles
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    cni_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    date_of_birth = db.Column(db.Date, nullable=False)
    
    # Informations candidature
    party_name = db.Column(db.String(100))
    party_acronym = db.Column(db.String(20))
    
    # Statut
    is_approved = db.Column(db.Boolean, default=False, index=True)
    approved_at = db.Column(db.DateTime)
    
    # Statistiques
    vote_count = db.Column(db.Integer, default=0, index=True)
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    details = db.relationship(
        "CandidateDetails",
        backref="candidate",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def _ensure_details(self):
        if not self.details:
            self.details = CandidateDetails()
        return self.details
    
    @property
    def age(self):
        today = date.today()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def cni_masked(self):
        return mask_sensitive(self.cni_number, show_last=4)

    @property
    def place_of_birth(self):
        return self.details.place_of_birth if self.details else ""

    @place_of_birth.setter
    def place_of_birth(self, value):
        self._ensure_details().place_of_birth = (value or "").strip() or None

    @property
    def campaign_slogan(self):
        return self.details.campaign_slogan if self.details else None

    @campaign_slogan.setter
    def campaign_slogan(self, value):
        self._ensure_details().campaign_slogan = (value or "").strip() or None

    @property
    def political_program(self):
        return self.details.political_program if self.details else None

    @political_program.setter
    def political_program(self, value):
        self._ensure_details().political_program = (value or "").strip() or None

    @property
    def biography(self):
        return self.details.biography if self.details else None

    @biography.setter
    def biography(self, value):
        self._ensure_details().biography = (value or "").strip() or None

    @property
    def profile_image(self):
        if not self.details or not self.details.profile_image:
            return "default-candidate.jpg"
        return self.details.profile_image

    @profile_image.setter
    def profile_image(self, filename):
        self._ensure_details().profile_image = (filename or "").strip() or None

    @property
    def website_url(self):
        return self.details.website_url if self.details else None

    @website_url.setter
    def website_url(self, value):
        self._ensure_details().website_url = (value or "").strip() or None

    @property
    def facebook_url(self):
        return self.details.facebook_url if self.details else None

    @facebook_url.setter
    def facebook_url(self, value):
        self._ensure_details().facebook_url = (value or "").strip() or None

    @property
    def twitter_url(self):
        return self.details.twitter_url if self.details else None

    @twitter_url.setter
    def twitter_url(self, value):
        self._ensure_details().twitter_url = (value or "").strip() or None

    @property
    def campaign_video_url(self):
        return self.details.campaign_video_url if self.details else None

    @campaign_video_url.setter
    def campaign_video_url(self, value):
        self._ensure_details().campaign_video_url = (value or "").strip() or None

    @property
    def is_rejected(self):
        return bool(self.details.is_rejected) if self.details else False

    @is_rejected.setter
    def is_rejected(self, value):
        self._ensure_details().is_rejected = bool(value)

    @property
    def is_eligible(self):
        if self.details and self.details.is_eligible is not None:
            return bool(self.details.is_eligible)
        try:
            min_age = int(app.config.get("MIN_CANDIDATE_AGE", 40))
        except Exception:
            min_age = 40
        return self.age >= min_age

    @is_eligible.setter
    def is_eligible(self, value):
        self._ensure_details().is_eligible = bool(value)

    @property
    def eligibility_notes(self):
        return self.details.eligibility_notes if self.details else None

    @eligibility_notes.setter
    def eligibility_notes(self, value):
        self._ensure_details().eligibility_notes = (value or "").strip() or None

    @property
    def eligibility_checked_at(self):
        return self.details.eligibility_checked_at if self.details else None

    @eligibility_checked_at.setter
    def eligibility_checked_at(self, value):
        self._ensure_details().eligibility_checked_at = value

    @property
    def eligibility_reason(self):
        return self.details.eligibility_reason if self.details else None

    @eligibility_reason.setter
    def eligibility_reason(self, value):
        self._ensure_details().eligibility_reason = (value or "").strip() or None

    @property
    def application_status(self):
        if self.is_approved:
            return "approved"
        if self.is_rejected:
            return "rejected"
        return "pending"
    
    def __repr__(self):
        return f'<Candidate {self.full_name}>'

class CandidateDetails(db.Model):
    __tablename__ = "candidate_details"

    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id"), primary_key=True)

    place_of_birth = db.Column(db.String(100))
    campaign_slogan = db.Column(db.String(255))
    political_program = db.Column(db.Text)
    biography = db.Column(db.Text)

    profile_image = db.Column(db.String(255), default="default-candidate.jpg")

    website_url = db.Column(db.String(255))
    facebook_url = db.Column(db.String(255))
    twitter_url = db.Column(db.String(255))
    campaign_video_url = db.Column(db.String(255))

    is_rejected = db.Column(db.Boolean, default=False, index=True)
    is_eligible = db.Column(db.Boolean)  # None => calcul automatique
    eligibility_notes = db.Column(db.Text)
    eligibility_reason = db.Column(db.String(255))
    eligibility_checked_at = db.Column(db.DateTime)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Election(db.Model):
    __tablename__ = 'elections'
    PHASE_PREPARATION = "preparation"
    PHASE_VOTE_OUVERT = "vote_ouvert"
    PHASE_VOTE_FERME = "vote_ferme"
    PHASE_DEPOUILLEMENT = "depouillement"
    PHASE_PROCLAMATION = "resultats_proclames"
    PHASE_FLOW = [
        PHASE_PREPARATION,
        PHASE_VOTE_OUVERT,
        PHASE_VOTE_FERME,
        PHASE_DEPOUILLEMENT,
        PHASE_PROCLAMATION,
    ]
    LEGACY_STATUS_MAP = {
        "planned": PHASE_PREPARATION,
        "candidatures_ouvertes": PHASE_PREPARATION,
        "campagne_electorale": PHASE_VOTE_OUVERT,
        "proclamation_vainqueur": PHASE_PROCLAMATION,
        "registration_open": PHASE_PREPARATION,
        "registration_closed": PHASE_VOTE_OUVERT,
        "open": PHASE_VOTE_OUVERT,
        "vote_open": PHASE_VOTE_OUVERT,
        "vote_closed": PHASE_VOTE_FERME,
        "closed": PHASE_VOTE_FERME,
        "results_published": PHASE_PROCLAMATION,
    }
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default="Élection Nationale")
    year = db.Column(db.Integer, default=lambda: datetime.now(UTC).year)
    
    # Dates
    registration_start = db.Column(db.DateTime)
    registration_end = db.Column(db.DateTime)
    voting_start = db.Column(db.DateTime)
    voting_end = db.Column(db.DateTime)
    
    # Configuration
    status = db.Column(db.String(20), default='planned')
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    settings = db.relationship(
        "ElectionSettings",
        backref="election",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def _ensure_settings(self):
        if not self.settings:
            self.settings = ElectionSettings()
        return self.settings

    @property
    def description(self):
        return self.settings.description if self.settings else ""

    @description.setter
    def description(self, value):
        self._ensure_settings().description = (value or "").strip() or None

    @property
    def max_candidates(self):
        if self.settings and self.settings.max_candidates is not None:
            return int(self.settings.max_candidates)
        return 10

    @max_candidates.setter
    def max_candidates(self, value):
        try:
            self._ensure_settings().max_candidates = int(value)
        except Exception:
            self._ensure_settings().max_candidates = None

    @property
    def is_test_mode(self):
        return bool(self.settings.is_test_mode) if self.settings else False

    @is_test_mode.setter
    def is_test_mode(self, value):
        self._ensure_settings().is_test_mode = bool(value)

    @property
    def auto_approve_candidates(self):
        return bool(self.settings.auto_approve_candidates) if self.settings else False

    @auto_approve_candidates.setter
    def auto_approve_candidates(self, value):
        self._ensure_settings().auto_approve_candidates = bool(value)

    @property
    def phase(self):
        raw = (self.status or "").strip().lower()
        normalized = self.LEGACY_STATUS_MAP.get(raw, raw)
        if normalized in self.PHASE_FLOW:
            return normalized
        return self.PHASE_PREPARATION

    @phase.setter
    def phase(self, value):
        target = (value or "").strip().lower()
        if target not in self.PHASE_FLOW:
            raise ValueError("Phase électorale invalide")
        self.status = target

    @property
    def phase_label(self):
        labels = {
            self.PHASE_PREPARATION: "Préparation des élections",
            self.PHASE_VOTE_OUVERT: "Vote ouvert",
            self.PHASE_VOTE_FERME: "Vote fermé",
            self.PHASE_DEPOUILLEMENT: "Dépouillement",
            self.PHASE_PROCLAMATION: "Résultats proclamés",
        }
        return labels.get(self.phase, "Préparation des élections")

    def can_transition(self, action):
        current = self.phase
        transitions = {
            "openVoting": (self.PHASE_PREPARATION, self.PHASE_VOTE_OUVERT),
            "closeVoting": (self.PHASE_VOTE_OUVERT, self.PHASE_VOTE_FERME),
            "startCounting": (self.PHASE_VOTE_FERME, self.PHASE_DEPOUILLEMENT),
            "publishResults": (self.PHASE_DEPOUILLEMENT, self.PHASE_PROCLAMATION),
        }
        expected = transitions.get(action)
        if not expected:
            return False, "Action inconnue"

        # Accept idempotent transition if already in expected target phase.
        if current == expected[1]:
            return True, None

        if current == self.PHASE_VOTE_OUVERT and action == 'startCounting':
            # cas d'usage rapide : on lance le dépouillement directement sans repasser par vote fermé.
            return True, None

        if current != expected[0]:
            return False, f"Transition impossible depuis l'état « {self.phase_label} »"

        if action == "openVoting":
            if Candidate.query.filter_by(is_approved=True).count() <= 0:
                return False, "Au moins un candidat approuvé est requis avant l'ouverture du vote."
            if Voter.query.count() <= 0:
                return False, "Au moins un électeur est requis avant l'ouverture du vote."
        return True, None

    def apply_transition(self, action):
        transitions = {
            "openVoting": self.PHASE_VOTE_OUVERT,
            "closeVoting": self.PHASE_VOTE_FERME,
            "startCounting": self.PHASE_DEPOUILLEMENT,
            "publishResults": self.PHASE_PROCLAMATION,
        }
        ok, reason = self.can_transition(action)
        if not ok:
            raise ValueError(reason or "Transition refusée")

        now = datetime.utcnow()
        target = transitions[action]

        # Pas d'opération si la cible est déjà atteinte
        if self.phase == target:
            return

        self.phase = target

        if action == "openVoting":
            self.registration_end = self.registration_end or now
            self.voting_start = self.voting_start or now
        elif action == "closeVoting":
            self.voting_end = now
        elif action == "startCounting":
            self.voting_end = self.voting_end or now
    
    @property
    def is_registration_open(self):
        return self.phase == self.PHASE_PREPARATION
    
    @property
    def is_voting_open(self):
        now = datetime.utcnow()
        if self.phase != self.PHASE_VOTE_OUVERT:
            return False
        if self.voting_start and now < self.voting_start:
            return False
        if self.voting_end and now > self.voting_end:
            return False
        return True

    @property
    def total_votes_cast(self):
        try:
            return VoteLog.query.filter_by(election_id=self.id).count()
        except Exception:
            return 0

    @property
    def total_voters_registered(self):
        # Dans ce modèle simplifié, les électeurs ne sont pas liés à une élection précise.
        try:
            return Voter.query.count()
        except Exception:
            return 0

    @property
    def participation_rate(self):
        voters = self.total_voters_registered
        if voters <= 0:
            return 0.0
        return (self.total_votes_cast / voters) * 100

    @property
    def time_remaining(self):
        if not self.voting_end:
            return ''
        remaining = self.voting_end - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            return "Terminé"
        days = remaining.days
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes = remainder // 60
        return f"{days}j {hours}h {minutes}min"
    
    @classmethod
    def get_current_election(cls):
        """Get the current election (most recent active election)"""
        current_year = datetime.utcnow().year
        # First try to get election for current year
        election = cls.query.filter_by(year=current_year).first()
        if election:
            return election
        # Fallback to most recent election
        return cls.query.order_by(cls.year.desc()).first()
    
    def __repr__(self):
        return f'<Election {self.name} {self.year}>'

class ElectionSettings(db.Model):
    __tablename__ = "election_settings"

    election_id = db.Column(db.Integer, db.ForeignKey("elections.id"), primary_key=True)

    description = db.Column(db.Text)
    max_candidates = db.Column(db.Integer)
    is_test_mode = db.Column(db.Boolean, default=False)
    auto_approve_candidates = db.Column(db.Boolean, default=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Announcement(db.Model):
    __tablename__ = 'announcements'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    audience = db.Column(db.String(20), default='all', nullable=False)
    priority = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_urgent = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Announcement "{self.title[:30]}...">'

class VoteLog(db.Model):
    __tablename__ = 'vote_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    voter_id = db.Column(db.Integer, db.ForeignKey('voters.id'), nullable=False, index=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidates.id'), nullable=False, index=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False)
    
    vote_hash = db.Column(db.String(64), unique=True, nullable=False)
    ip_address = db.Column(db.String(45))
    vote_timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.Index('idx_vote_logs_composite', 'voter_id', 'election_id', unique=True),
    )
    
    @classmethod
    def generate_vote_hash(cls, voter_id, candidate_id, election_id, salt):
        data = f"{voter_id}-{candidate_id}-{election_id}-{salt}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def __repr__(self):
        return f'<VoteLog Voter:{self.voter_id} -> Candidate:{self.candidate_id}>'

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", backref=db.backref("audit_logs", lazy="dynamic"))

class ElectionArchive(db.Model):
    __tablename__ = "election_archives"

    id = db.Column(db.Integer, primary_key=True)
    archive_type = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    summary = db.Column(db.String(255))
    file_path = db.Column(db.String(255), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    created_by = db.relationship("User", backref=db.backref("election_archives", lazy="dynamic"))

# ========== FONCTIONS D'AIDE ==========
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def _ensure_announcements_schema():
    """Ajoute les colonnes manquantes de `announcements` pour les bases existantes."""
    inspector = inspect(db.engine)
    if 'announcements' not in inspector.get_table_names():
        return

    existing = {c.get('name') for c in inspector.get_columns('announcements')}
    dialect = (db.engine.dialect.name or "").lower()
    datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    statements = []
    if 'audience' not in existing:
        statements.append("ALTER TABLE announcements ADD COLUMN audience VARCHAR(20) NOT NULL DEFAULT 'all'")
    if 'priority' not in existing:
        statements.append("ALTER TABLE announcements ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
    if 'expires_at' not in existing:
        statements.append(f"ALTER TABLE announcements ADD COLUMN expires_at {datetime_type}")

    if not statements:
        return

    for stmt in statements:
        db.session.execute(text(stmt))
    db.session.commit()

def _ensure_users_schema():
    """Ajoute les colonnes manquantes de `users` pour la vérification email."""
    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return

    existing = {c.get('name') for c in inspector.get_columns('users')}
    dialect = (db.engine.dialect.name or "").lower()
    datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    statements = []
    if 'display_name' not in existing:
        statements.append("ALTER TABLE users ADD COLUMN display_name VARCHAR(120)")
    if 'phone_number' not in existing:
        statements.append("ALTER TABLE users ADD COLUMN phone_number VARCHAR(30)")
    if 'avatar_filename' not in existing:
        statements.append("ALTER TABLE users ADD COLUMN avatar_filename VARCHAR(255)")
    if 'email_verified_at' not in existing:
        statements.append(f"ALTER TABLE users ADD COLUMN email_verified_at {datetime_type}")
    if 'email_verification_code_hash' not in existing:
        statements.append("ALTER TABLE users ADD COLUMN email_verification_code_hash VARCHAR(128)")
    if 'email_verification_expires_at' not in existing:
        statements.append(f"ALTER TABLE users ADD COLUMN email_verification_expires_at {datetime_type}")
    if 'email_verification_sent_at' not in existing:
        statements.append(f"ALTER TABLE users ADD COLUMN email_verification_sent_at {datetime_type}")

    if statements:
        for stmt in statements:
            db.session.execute(text(stmt))
        db.session.commit()

    db.session.execute(
        text(
            "UPDATE users "
            "SET email_verified_at = created_at "
            "WHERE email_verified_at IS NULL AND email_verification_code_hash IS NULL"
        )
    )
    db.session.commit()

def _archive_dir() -> str:
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), "archives")

def _ensure_archive_dir() -> str:
    path = _archive_dir()
    os.makedirs(path, exist_ok=True)
    return path

def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)

def _log_audit(action: str, details: str | None = None, *, user=None) -> None:
    actor = user if user is not None else (current_user if current_user.is_authenticated else None)
    db.session.add(
        AuditLog(
            user_id=getattr(actor, "id", None),
            action=(action or "").strip()[:80],
            details=(details or "").strip()[:5000] or None,
        )
    )

def _election_snapshot(*, archive_type: str, title: str) -> tuple[str, str]:
    election = Election.get_current_election()
    users = User.query.order_by(User.id.asc()).all()
    voters = Voter.query.order_by(Voter.id.asc()).all()
    candidates = Candidate.query.order_by(Candidate.id.asc()).all()
    vote_logs = VoteLog.query.order_by(VoteLog.id.asc()).all()
    announcements = Announcement.query.order_by(Announcement.id.asc()).all()

    snapshot = {
        "archive_type": archive_type,
        "title": title,
        "created_at": datetime.utcnow().isoformat(),
        "election": {
            "id": election.id if election else None,
            "name": election.name if election else None,
            "year": election.year if election else None,
            "status": election.status if election else None,
            "phase": election.phase if election else None,
            "registration_start": election.registration_start if election else None,
            "registration_end": election.registration_end if election else None,
            "voting_start": election.voting_start if election else None,
            "voting_end": election.voting_end if election else None,
            "description": election.description if election else None,
            "max_candidates": election.max_candidates if election else None,
            "is_test_mode": election.is_test_mode if election else None,
            "auto_approve_candidates": election.auto_approve_candidates if election else None,
        },
        "counts": {
            "users": len(users),
            "voters": len(voters),
            "candidates": len(candidates),
            "votes": len(vote_logs),
            "announcements": len(announcements),
        },
        "users": [
            {
                "id": user.id,
                "email": user.email,
                "password_hash": user.password_hash,
                "role": user.role,
                "is_active": user.is_active,
                "display_name": user.display_name,
                "phone_number": user.phone_number,
                "avatar_filename": user.avatar_filename,
                "created_at": user.created_at,
                "last_login": user.last_login,
                "email_verified_at": user.email_verified_at,
            }
            for user in users
        ],
        "voters": [
            {
                "id": voter.id,
                "user_id": voter.user_id,
                "first_name": voter.first_name,
                "last_name": voter.last_name,
                "cni_number": voter.cni_number,
                "date_of_birth": voter.date_of_birth,
                "place_of_birth": voter.place_of_birth,
                "gender": voter.gender,
                "has_voted": voter.has_voted,
                "voted_at": voter.voted_at,
                "vote_for_id": voter.vote_for_id,
                "phone_number": voter.phone_number,
                "is_eligible": voter.is_eligible,
                "eligibility_reason": voter.eligibility_reason,
                "created_at": voter.created_at,
                "updated_at": voter.updated_at,
            }
            for voter in voters
        ],
        "candidates": [
            {
                "id": candidate.id,
                "user_id": candidate.user_id,
                "first_name": candidate.first_name,
                "last_name": candidate.last_name,
                "cni_number": candidate.cni_number,
                "date_of_birth": candidate.date_of_birth,
                "place_of_birth": candidate.place_of_birth,
                "party_name": candidate.party_name,
                "party_acronym": candidate.party_acronym,
                "campaign_slogan": candidate.campaign_slogan,
                "political_program": candidate.political_program,
                "biography": candidate.biography,
                "profile_image": candidate.profile_image,
                "website_url": candidate.website_url,
                "facebook_url": candidate.facebook_url,
                "twitter_url": candidate.twitter_url,
                "campaign_video_url": candidate.campaign_video_url,
                "is_approved": candidate.is_approved,
                "is_rejected": candidate.is_rejected,
                "vote_count": candidate.vote_count,
                "created_at": candidate.created_at,
                "updated_at": candidate.updated_at,
            }
            for candidate in candidates
        ],
        "vote_logs": [
            {
                "id": vote.id,
                "voter_id": vote.voter_id,
                "candidate_id": vote.candidate_id,
                "election_id": vote.election_id,
                "vote_hash": vote.vote_hash,
                "ip_address": vote.ip_address,
                "vote_timestamp": vote.vote_timestamp,
            }
            for vote in vote_logs
        ],
        "announcements": [
            {
                "id": announcement.id,
                "title": announcement.title,
                "content": announcement.content,
                "author_id": announcement.author_id,
                "audience": announcement.audience,
                "priority": announcement.priority,
                "is_active": announcement.is_active,
                "is_urgent": announcement.is_urgent,
                "expires_at": announcement.expires_at,
                "created_at": announcement.created_at,
                "updated_at": announcement.updated_at,
            }
            for announcement in announcements
        ],
    }

    archive_dir = _ensure_archive_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{archive_type}.json"
    abs_path = os.path.join(archive_dir, filename)
    with open(abs_path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, default=_json_default)

    summary = (
        f"{len(users)} utilisateurs, {len(voters)} électeurs, "
        f"{len(candidates)} candidats, {len(vote_logs)} votes"
    )
    return filename, summary

def init_database():
    """Initialise la base de données en silence"""
    with app.app_context():
        try:
            db.create_all()
            _ensure_users_schema()
            _ensure_announcements_schema()
            _ensure_archive_dir()
            
            # NOTE: l'administration ne doit plus être configurée automatiquement
            # via les variables d'environnement. Le premier compte admin est créé
            # manuellement via la page d'inscription. Aucune logique supplémentaire
            # n'est requise ici.
            
            # Créer élection par défaut
            current_year = datetime.utcnow().year
            if not Election.query.filter_by(year=current_year).first():
                now = datetime.utcnow()
                election = Election(
                    name=f"Élection Nationale {current_year}",
                    year=current_year,
                    registration_start=now - timedelta(days=30),
                    registration_end=now + timedelta(days=60),
                    voting_start=now,
                    voting_end=now + timedelta(days=90),
                    status=Election.PHASE_PREPARATION
                )
                db.session.add(election)
                db.session.commit()
                logger.info("Default election created")
                
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise

# ========== FILTRES TEMPLATE ==========
@app.template_filter('datetime_format')
def datetime_format(value, format='%d/%m/%Y %H:%M'):
    if not value:
        return ''
    return value.strftime(format)

@app.template_filter('date_format')
def date_format(value, format='%d/%m/%Y'):
    if not value:
        return ''
    return value.strftime(format)

@app.template_filter('time_ago')
def time_ago(value):
    """Retourne une représentation lisible (FR) du temps écoulé depuis `value`."""
    if not value:
        return ''

    try:
        now_dt = datetime.utcnow()
        diff = now_dt - value
    except Exception:
        return ''

    # Futur
    if diff.total_seconds() < 0:
        return "dans le futur"

    seconds = int(diff.total_seconds())
    minutes = seconds // 60
    hours = minutes // 60
    days = diff.days

    if seconds < 10:
        return "à l'instant"
    if minutes < 1:
        return f"il y a {seconds} seconde{'s' if seconds > 1 else ''}"
    if hours < 1:
        return f"il y a {minutes} minute{'s' if minutes > 1 else ''}"
    if days < 1:
        return f"il y a {hours} heure{'s' if hours > 1 else ''}"
    if days < 30:
        return f"il y a {days} jour{'s' if days > 1 else ''}"

    months = days // 30
    if months < 12:
        return f"il y a {months} mois"

    years = days // 365
    return f"il y a {years} an{'s' if years > 1 else ''}"

@app.template_filter('nl2br')
def nl2br(value):
    """Convertit les sauts de ligne en <br> en échappant le HTML."""
    if value is None:
        return ''
    # `escape` protège contre l'injection HTML, puis on remplace les retours.
    return Markup(escape(str(value)).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>\n'))

# ========== CONTEXTE GLOBAL ==========
@app.context_processor
def inject_global_vars():
    try:
        election = Election.get_current_election()
    except Exception:
        election = None
    try:
        admin_exists = User.query.filter_by(role='admin').first() is not None
    except Exception:
        admin_exists = False
    return {
        'current_year': datetime.now().year,
        'election': election,
        'now': datetime.utcnow(),
        'config': app.config,
        'admin_exists': admin_exists
    }

@app.context_processor
def inject_user_profiles():
    """Expose `voter` / `candidate` à la navbar sans devoir les passer dans chaque render_template()."""
    voter = None
    candidate = None
    if not current_user.is_authenticated:
        return {"voter": None, "candidate": None}

    try:
        if current_user.role == "voter":
            voter = Voter.query.filter_by(user_id=current_user.id).first()
        elif current_user.role == "candidate":
            candidate = Candidate.query.filter_by(user_id=current_user.id).first()
    except Exception:
        voter = None
        candidate = None

    return {"voter": voter, "candidate": candidate}

@app.context_processor
def inject_csrf_token():
    def csrf_token():
        return generate_csrf()
    return {'csrf_token': csrf_token}

@app.before_request
def protect_csrf_fallback():
    if csrf is not None:
        return None
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return None
    token = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRFToken")
        or request.headers.get("X-CSRF-Token")
    )
    expected = session.get("_csrf_token")
    if not token or not expected or not hmac.compare_digest(str(token), str(expected)):
        raise CSRFError("Jeton CSRF manquant ou invalide")
    return None

@app.after_request
def apply_security_headers(response):
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    try:
        response.set_cookie(
            "csrf_token",
            generate_csrf(),
            secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
            httponly=False,
            samesite=app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        )
    except Exception:
        pass
    return response

@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    message = "La session de sécurité a expiré ou la requête est invalide. Rechargez la page puis réessayez."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.best == "application/json":
        return jsonify(success=False, message=message, reason=error.description), 400
    flash(message, "warning")
    return redirect(request.referrer or url_for("index"))

@app.context_processor
def inject_helpers():
    # Palette de couleurs utilisée dans plusieurs graphiques/templates.
    palette = [
        "#0066b3",  # bleu
        "#12ad2b",  # vert
        "#d21034",  # rouge
        "#ffc107",  # jaune
        "#6f42c1",  # violet
        "#0dcaf0",  # cyan
    ]

    def get_candidate_color(index: int):
        try:
            return palette[int(index) % len(palette)]
        except Exception:
            return palette[0]

    def candidate_photo_url(candidate):
        """
        Retourne une URL exploitable pour la photo d'un candidat, ou None.
        - Priorité: `static/uploads/candidates/<filename>`
        - Fallback:  `static/images/<filename>` (utile si les images sont livrées avec le projet)
        - Supporte aussi les URLs externes (http/https) si jamais stockées en DB.
        """
        if not candidate:
            return None

        filename = getattr(candidate, "profile_image", None)
        if not filename:
            return None

        try:
            filename = str(filename).strip()
        except Exception:
            return None

        if not filename or filename == "default-candidate.jpg":
            return None

        lower = filename.lower()
        if lower.startswith("http://") or lower.startswith("https://"):
            return filename

        for rel in (f"uploads/candidates/{filename}", f"images/{filename}"):
            abs_path = os.path.join(app.static_folder, rel.replace("/", os.sep))
            if os.path.exists(abs_path):
                try:
                    version = int(os.path.getmtime(abs_path))
                    return url_for("static", filename=rel, v=version)
                except Exception:
                    return url_for("static", filename=rel)

        return None

    def voter_avatar_url(voter):
        """
        Retourne une URL exploitable pour la photo d'un électeur, ou None.
        Stockage (sans migration DB) :
        - `static/uploads/avatars/voter_<id>.<ext>`
        """
        if not voter:
            return None

        try:
            voter_id = int(getattr(voter, "id", 0) or 0)
        except Exception:
            voter_id = 0
        if voter_id <= 0:
            return None

        for ext in ("webp", "png", "jpg", "jpeg", "gif"):
            rel = f"uploads/avatars/voter_{voter_id}.{ext}"
            abs_path = os.path.join(app.static_folder, rel.replace("/", os.sep))
            if not os.path.exists(abs_path):
                continue
            try:
                version = int(os.path.getmtime(abs_path))
                return url_for("static", filename=rel, v=version)
            except Exception:
                return url_for("static", filename=rel)

        return None

    def admin_avatar_url(user):
        if not user:
            return None

        filename = (getattr(user, "avatar_filename", None) or "").strip()
        if not filename:
            return None

        rel = f"uploads/admins/{filename}"
        abs_path = os.path.join(app.static_folder, rel.replace("/", os.sep))
        if not os.path.exists(abs_path):
            return None
        try:
            version = int(os.path.getmtime(abs_path))
            return url_for("static", filename=rel, v=version)
        except Exception:
            return url_for("static", filename=rel)

    return {
        'get_candidate_color': get_candidate_color,
        'candidate_photo_url': candidate_photo_url,
        'voter_avatar_url': voter_avatar_url,
        'admin_avatar_url': admin_avatar_url,
    }

# ========== DÉCORATEURS ==========
def role_required(required_role):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role != required_role:
                flash('Accès non autorisé', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

voter_required = role_required('voter')
candidate_required = role_required('candidate')
admin_required = role_required('admin')

# ========== ROUTES PUBLIQUES ==========
@app.route('/')
def index():
    election = Election.get_current_election()
    candidates = (
        Candidate.query.filter_by(is_approved=True)
        .order_by(Candidate.vote_count.desc())
        .limit(3)
        .all()
    )

    total_voters = Voter.query.count()
    approved_candidates = Candidate.query.filter_by(is_approved=True).count()
    total_votes = election.total_votes_cast if election else VoteLog.query.count()

    stats = {
        "total_voters": total_voters,
        "approved_candidates": approved_candidates,
        "total_votes": total_votes,
        "participation_rate": round(election.participation_rate, 1) if election else 0.0,
    }

    now_utc = datetime.utcnow()
    announcements = (
        Announcement.query.filter(
            Announcement.is_active.is_(True),
            or_(Announcement.audience == 'all', Announcement.audience.is_(None)),
            or_(Announcement.expires_at.is_(None), Announcement.expires_at >= now_utc),
        )
        .order_by(Announcement.is_urgent.desc(), Announcement.created_at.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "visitor/index.html",
        candidates=candidates,
        announcements=announcements,
        stats=stats,
        page_title="Accueil",
        show_footer_cta=True,
    )

@app.route('/candidates')
def candidates_list():
    candidates = Candidate.query.filter_by(is_approved=True).all()
    total_votes = sum(int(c.vote_count or 0) for c in candidates)
    return render_template(
        'visitor/candidates.html',
        candidates=candidates,
        total_votes=total_votes,
        page_title="Candidats",
    )

@app.route('/candidate/<int:candidate_id>')
def candidate_public_profile(candidate_id):
    candidate = Candidate.query.filter_by(id=candidate_id, is_approved=True).first_or_404()
    return render_template(
        'visitor/candidate_profile.html',
        candidate=candidate,
        page_title=f"Profil de {candidate.full_name}",
    )

@app.route('/vote/<int:candidate_id>', methods=['POST'])
@login_required
def vote_for_candidate(candidate_id):
    if current_user.role != 'voter':
        flash('Seuls les électeurs peuvent voter', 'danger')
        return redirect(url_for('index'))
    
    voter = Voter.query.filter_by(user_id=current_user.id).first()
    if not voter:
        flash('Profil électeur non trouvé', 'danger')
        return redirect(url_for('index'))
    
    election = Election.get_current_election()
    if not election or not election.is_voting_open:
        flash('Le vote n\'est pas ouvert actuellement', 'warning')
        return redirect(url_for('index'))
    
    if voter.has_voted:
        flash('Vous avez déjà voté', 'warning')
        return redirect(url_for('index'))

    if not voter.is_eligible:
        reason = voter.eligibility_reason or "Votre éligibilité est en cours de vérification."
        flash(reason, 'warning')
        return redirect(url_for('index'))
    
    candidate = Candidate.query.filter_by(id=candidate_id, is_approved=True).first()
    if not candidate:
        flash('Candidat invalide', 'danger')
        return redirect(url_for('index'))
    if candidate.is_rejected or not candidate.is_eligible:
        flash("Ce candidat n'est pas autorisé à recevoir des votes.", "warning")
        return redirect(url_for('index'))
    
    # Enregistrement du vote
    voter.has_voted = True
    voter.voted_at = datetime.utcnow()
    voter.vote_for_id = candidate_id
    candidate.vote_count += 1
    
    # Log du vote
    vote_hash = VoteLog.generate_vote_hash(
        voter.id, 
        candidate.id, 
        election.id, 
        secrets.token_hex(16)
    )
    
    vote_log = VoteLog(
        voter_id=voter.id,
        candidate_id=candidate.id,
        election_id=election.id,
        vote_hash=vote_hash,
        ip_address=request.remote_addr
    )
    
    db.session.add(vote_log)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Un vote existe déjà pour cet électeur dans cette élection.", "warning")
        return redirect(url_for('index'))
    
    flash(f'Votre vote pour {candidate.full_name} a été enregistré avec succès', 'success')
    return redirect(url_for('index'))

@app.route('/about')
def about():
    stats = {
        "total_voters": Voter.query.count(),
        "total_candidates": Candidate.query.filter_by(is_approved=True).count(),
        "votes_cast": VoteLog.query.count(),
        "announcements": Announcement.query.filter_by(is_active=True).count(),
    }
    return render_template('visitor/about.html',
                         stats=stats,
                         page_title="À propos",
                         show_footer_cta=False)

@app.route('/faq')
def faq():
    return render_template('visitor/information.html',
                         page='faq',
                         page_title="FAQ")

@app.route("/reglement")
def reglement():
    return render_template("visitor/legal.html", page="reglement", page_title="Règlement (simulation)")

@app.route("/conditions")
def terms():
    return render_template("visitor/legal.html", page="terms", page_title="Conditions d'utilisation")

@app.route("/confidentialite")
def privacy():
    return render_template("visitor/legal.html", page="privacy", page_title="Politique de confidentialité")

@app.route("/conditions-candidature")
def candidate_terms():
    return render_template("visitor/legal.html", page="candidate", page_title="Conditions de candidature")

@app.route("/mot-de-passe-oublie")
def forgot_password():
    return render_template("visitor/legal.html", page="password", page_title="Mot de passe oublié")

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()

        form_data = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "subject": subject,
            "message": message,
        }

        if not full_name or not email or not subject or not message:
            flash("Merci de compléter tous les champs obligatoires.", "danger")
            return render_template("visitor/contact.html", page_title="Contact", form_data=form_data)

        try:
            email = _normalize_email_address(email)
        except EmailNotValidError:
            flash("Adresse email invalide.", "danger")
            return render_template("visitor/contact.html", page_title="Contact", form_data=form_data)

        try:
            _send_contact_email(
                full_name=full_name,
                email=email,
                subject=subject,
                message=message,
                phone=phone,
            )
        except RuntimeError as exc:
            flash(str(exc), "danger")
            return render_template("visitor/contact.html", page_title="Contact", form_data=form_data)
        except smtplib.SMTPAuthenticationError:
            logger.exception("Authentification SMTP refusée (contact)")
            if app.debug:
                flash(
                    "Authentification SMTP refusée. Vérifiez SMTP_USERNAME/SMTP_PASSWORD (Gmail : utilisez un mot de passe d’application).",
                    "danger",
                )
            else:
                flash("Impossible d'envoyer le message pour le moment. Réessayez plus tard.", "danger")
            return render_template("visitor/contact.html", page_title="Contact", form_data=form_data)
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError):
            logger.exception("Erreur de connexion SMTP (contact)")
            flash("Service de messagerie temporairement indisponible. Réessayez plus tard.", "danger")
            return render_template("visitor/contact.html", page_title="Contact", form_data=form_data)
        except Exception:
            logger.exception("Erreur lors de l'envoi du message de contact")
            flash("Impossible d'envoyer le message pour le moment. Réessayez plus tard.", "danger")
            return render_template("visitor/contact.html", page_title="Contact", form_data=form_data)

        flash("Merci ! Votre message a été envoyé.", "success")
        return redirect(url_for("contact"))

    return render_template("visitor/contact.html", page_title="Contact", form_data=None)

# ========== AUTHENTIFICATION ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    show_email_verification = (request.args.get("email_verification") or "").strip() == "1"
    prefill_email = (request.args.get("email") or "").strip().lower()

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        prefill_email = email
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password) and user.is_active:
            if not user.is_email_verified:
                if (
                    app.config.get("EMAIL_VERIFICATION_REQUIRED", True)
                    and (
                        not user.email_verification_code_hash
                        or not user.email_verification_expires_at
                        or user.email_verification_expires_at <= datetime.utcnow()
                    )
                ):
                    try:
                        _issue_email_verification(user)
                        db.session.commit()
                        flash("Un nouveau code de confirmation a été envoyé à votre adresse email.", "info")
                    except Exception:
                        db.session.rollback()
                        logger.exception("Impossible de renvoyer le code de confirmation à la connexion")
                flash("Confirmez votre email avant de vous connecter.", "warning")
                return _verification_redirect(email)

            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            flash('Connexion réussie', 'success')
            
            if user.role == 'voter':
                return redirect(url_for('voter_dashboard'))
            elif user.role == 'candidate':
                return redirect(url_for('candidate_dashboard'))
            elif user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Identifiants incorrects', 'danger')

    return render_template(
        'auth/login.html',
        page_title="Connexion",
        show_email_verification=show_email_verification,
        prefill_email=prefill_email,
    )

@app.route('/verify-email', methods=['POST'])
def verify_email():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    email = (request.form.get('email') or '').strip().lower()
    code = request.form.get('verification_code') or ''

    user = User.query.filter_by(email=email).first()
    ok, message = _confirm_user_email(user, code)
    if ok and user and not user.email_verification_code_hash:
        db.session.commit()
        flash(message, 'info' if message.startswith("Cet email est déjà confirmé") else 'success')
        return redirect(url_for('login', email=email))

    flash(message, 'danger')
    return _verification_redirect(email)

@app.route('/verify-email/resend', methods=['POST'])
def resend_email_verification():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    email = (request.form.get('email') or '').strip().lower()
    user = User.query.filter_by(email=email).first()

    if not user:
        flash("Aucun compte trouvé pour cette adresse email.", "danger")
        return _verification_redirect(email)
    if user.is_email_verified:
        flash("Cet email est déjà confirmé.", "info")
        return redirect(url_for('login', email=email))

    try:
        _issue_email_verification(user)
        db.session.commit()
        flash("Un nouveau code de confirmation a été envoyé.", "success")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Erreur lors du renvoi du code de confirmation")
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            flash("Authentification SMTP refusée. Vérifiez la configuration de l'email d'envoi.", "danger")
        else:
            flash("Impossible d'envoyer le code de confirmation pour le moment.", "danger")

    return _verification_redirect(email)

@app.route('/register')
def register():
    # point d'entrée principal pour l'inscription : on montre directement
    # les différentes options (électeur / candidat / administrateur si
    # aucun admin n'existe encore) afin que l'utilisateur n'ait pas à
    # remplir un champ de type de compte.
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    has_admin = User.query.filter_by(role='admin').first() is not None
    return render_template(
        'auth/register_choice.html',
        admin_exists=has_admin,
        page_title="Choisir le type d'inscription",
    )

@app.route('/register/form/<string:user_type>')
def register_form(user_type):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    normalized = (user_type or "").strip().lower()
    has_admin = User.query.filter_by(role='admin').first() is not None
    # si on tente d'aller sur la page d'administration alors qu'un admin existe déjà,
    # on renvoie vers le choix principal (le formulaire n'est pas accessible).
    if normalized == 'admin' and has_admin:
        flash("Un administrateur existe déjà.", "warning")
        return redirect(url_for('register'))
    return render_template(
        'auth/register_form.html',
        user_type=normalized,
        admin_exists=has_admin,
        page_title="Inscription",
    )

@app.route('/register/<string:user_type>', methods=['GET', 'POST'])
def register_with_type(user_type):
    normalized = (user_type or "").strip().lower()
    if normalized == "voter":
        return register_voter()
    if normalized == "candidate":
        return register_candidate()
    if normalized == "admin":
        return register_admin()
    flash("Type d'inscription invalide.", "danger")
    return redirect(url_for("register"))

@app.route('/register/admin', methods=['GET', 'POST'])
def register_admin():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    has_admin = User.query.filter_by(role='admin').first() is not None
    if has_admin:
        flash("Un administrateur existe déjà. Cette création n'est autorisée qu'une seule fois.", "warning")
        return redirect(url_for('register'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not email or not password or not confirm_password:
            flash("Veuillez remplir tous les champs obligatoires.", "danger")
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas.', 'danger')
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères.', 'danger')
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        try:
            email = _normalize_email_address(
                email,
                check_deliverability=bool(app.config.get("EMAIL_VALIDATION_CHECK_DELIVERABILITY", True)),
            ).lower()
        except EmailNotValidError as exc:
            flash(str(exc), 'danger')
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        if app.config.get("EMAIL_VERIFICATION_REQUIRED", True) and not _verification_email_enabled():
            flash("La vérification email n'est pas configurée sur ce serveur.", "danger")
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        if User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé.', 'danger')
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        try:
            user = User(email=email, role='admin', is_active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            _issue_email_verification(user)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.exception("Erreur lors de l'inscription administrateur")
            if isinstance(exc, smtplib.SMTPAuthenticationError):
                flash("Authentification SMTP refusée. Vérifiez SMTP_USERNAME / SMTP_PASSWORD.", "danger")
            elif isinstance(exc, EmailNotValidError):
                flash(str(exc), "danger")
            else:
                flash("Impossible d'envoyer l'email de confirmation. Vérifiez la configuration SMTP.", "danger")
            return render_template('auth/register_admin.html', page_title="Créer un administrateur")

        flash("Compte administrateur créé. Vérifiez votre email puis confirmez le code sur la page de connexion.", "success")
        return _verification_redirect(email)

    return render_template('auth/register_admin.html', page_title="Créer un administrateur")

@app.route('/register/voter', methods=['GET', 'POST'])
def register_voter():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    election = Election.get_current_election()
    if election and not election.is_registration_open:
        flash("Les inscriptions électeurs sont actuellement fermées.", "warning")
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        
        # Validation de base
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('auth/register_voter.html')
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return render_template('auth/register_voter.html')

        try:
            email = _normalize_email_address(
                email,
                check_deliverability=bool(app.config.get("EMAIL_VALIDATION_CHECK_DELIVERABILITY", True)),
            ).lower()
        except EmailNotValidError as exc:
            flash(str(exc), 'danger')
            return render_template('auth/register_voter.html')

        if app.config.get("EMAIL_VERIFICATION_REQUIRED", True) and not _verification_email_enabled():
            flash("La vérification email n'est pas configurée sur ce serveur.", "danger")
            return render_template('auth/register_voter.html')
        
        if User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé', 'danger')
            return render_template('auth/register_voter.html')
        
        try:
            date_of_birth = datetime.strptime(request.form.get('date_of_birth'), '%Y-%m-%d').date()
            age = calculate_age(date_of_birth)
            try:
                min_age = int(app.config.get("MIN_VOTER_AGE", 18))
            except Exception:
                min_age = 18
            if age < min_age:
                flash(f'Vous devez avoir au moins {min_age} ans pour voter', 'danger')
                return render_template('auth/register_voter.html')
        except Exception:
            flash('Date de naissance invalide', 'danger')
            return render_template('auth/register_voter.html')
        
        cni_number = request.form.get('cni_number')
        if Voter.query.filter_by(cni_number=cni_number).first():
            flash('Cette CNI est déjà enregistrée', 'danger')
            return render_template('auth/register_voter.html')
        
        # Création de l'utilisateur
        try:
            user = User(
                email=email,
                role='voter',
                is_active=True
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            
            voter = Voter(
                user_id=user.id,
                first_name=request.form.get('first_name'),
                last_name=request.form.get('last_name'),
                cni_number=cni_number,
                date_of_birth=date_of_birth,
                place_of_birth=request.form.get('place_of_birth'),
                gender=request.form.get('gender')
            )
            voter.phone_number = request.form.get("phone")
            db.session.add(voter)
            _issue_email_verification(user)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.exception("Erreur lors de l'inscription électeur")
            if isinstance(exc, smtplib.SMTPAuthenticationError):
                flash("Authentification SMTP refusée. Vérifiez SMTP_USERNAME / SMTP_PASSWORD.", "danger")
            else:
                flash("Impossible d'envoyer l'email de confirmation. Vérifiez la configuration SMTP.", "danger")
            return render_template('auth/register_voter.html')
        
        flash("Inscription réussie. Un code de confirmation a été envoyé à votre email.", 'success')
        return _verification_redirect(email)
    
    return render_template('auth/register_voter.html', page_title="Inscription Électeur")

@app.route('/register/candidate', methods=['GET', 'POST'])
def register_candidate():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    election = Election.get_current_election()
    if election and not election.is_registration_open:
        flash("Les candidatures sont actuellement fermées.", "warning")
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('auth/register_candidate.html')
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return render_template('auth/register_candidate.html')

        try:
            email = _normalize_email_address(
                email,
                check_deliverability=bool(app.config.get("EMAIL_VALIDATION_CHECK_DELIVERABILITY", True)),
            ).lower()
        except EmailNotValidError as exc:
            flash(str(exc), 'danger')
            return render_template('auth/register_candidate.html')

        if app.config.get("EMAIL_VERIFICATION_REQUIRED", True) and not _verification_email_enabled():
            flash("La vérification email n'est pas configurée sur ce serveur.", "danger")
            return render_template('auth/register_candidate.html')
        
        if User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé', 'danger')
            return render_template('auth/register_candidate.html')
        
        try:
            date_of_birth = datetime.strptime(request.form.get('date_of_birth'), '%Y-%m-%d').date()
            age = calculate_age(date_of_birth)
            try:
                min_age = int(app.config.get("MIN_CANDIDATE_AGE", 40))
            except Exception:
                min_age = 40
            if age < min_age:
                flash(f'Vous devez avoir au moins {min_age} ans pour être candidat', 'danger')
                return render_template('auth/register_candidate.html')
        except Exception:
            flash('Date de naissance invalide', 'danger')
            return render_template('auth/register_candidate.html')
        
        cni_number = request.form.get('cni_number')
        if Candidate.query.filter_by(cni_number=cni_number).first():
            flash('Cette CNI est déjà enregistrée comme candidat', 'danger')
            return render_template('auth/register_candidate.html')
        
        # Création de l'utilisateur
        try:
            user = User(
                email=email,
                role='candidate',
                is_active=True
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            
            candidate = Candidate(
                user_id=user.id,
                first_name=request.form.get('first_name'),
                last_name=request.form.get('last_name'),
                cni_number=cni_number,
                date_of_birth=date_of_birth,
                party_name=request.form.get('party_name'),
                party_acronym=request.form.get('party_acronym'),
                is_approved=False
            )
            candidate.place_of_birth = request.form.get("place_of_birth")
            candidate.campaign_slogan = request.form.get("slogan")
            candidate.political_program = request.form.get("program")
            candidate.is_rejected = False

            election = Election.get_current_election()
            if election and election.auto_approve_candidates:
                candidate.is_approved = True
                candidate.approved_at = datetime.utcnow()
            db.session.add(candidate)
            _issue_email_verification(user)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.exception("Erreur lors de l'inscription candidat")
            if isinstance(exc, smtplib.SMTPAuthenticationError):
                flash("Authentification SMTP refusée. Vérifiez SMTP_USERNAME / SMTP_PASSWORD.", "danger")
            else:
                flash("Impossible d'envoyer l'email de confirmation. Vérifiez la configuration SMTP.", "danger")
            return render_template('auth/register_candidate.html')
        
        flash("Candidature enregistrée. Confirmez d'abord votre email, puis connectez-vous.", 'success')
        return _verification_redirect(email)
    
    return render_template('auth/register_candidate.html', page_title="Inscription Candidat")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('index'))

# ========== ROUTES ÉLECTEUR ==========
@app.route('/voter/dashboard')
@voter_required
def voter_dashboard():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()

    candidates = Candidate.query.filter_by(is_approved=True).order_by(Candidate.vote_count.desc()).all()
    total_votes = sum(c.vote_count for c in candidates)
    for c in candidates:
        c.percentage = (c.vote_count / total_votes * 100) if total_votes > 0 else 0

    top_candidates = candidates[:5]
    my_candidate = Candidate.query.get(voter.vote_for_id) if voter.has_voted and voter.vote_for_id else None

    total_voters = Voter.query.count()
    voters_voted = Voter.query.filter_by(has_voted=True).count()
    participation_rate = (voters_voted / total_voters * 100) if total_voters > 0 else 0.0

    stats = {
        'approved_candidates': len(candidates),
        'total_votes': total_votes,
        'total_voters': total_voters,
        'voters_voted': voters_voted,
        'participation_rate': participation_rate
    }
    
    return render_template('voter/dashboard.html',
                          voter=voter,
                          election=election,
                          stats=stats,
                          top_candidates=top_candidates,
                          total_votes=total_votes,
                          my_candidate=my_candidate,
                          page_title="Tableau de bord")

@app.route('/voter/vote', methods=['GET', 'POST'])
@voter_required
def voter_vote():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()
    
    # Vérifications
    if not election or not election.is_voting_open:
        flash('Le vote n\'est pas ouvert actuellement', 'warning')
        return redirect(url_for('voter_dashboard'))
    
    if voter.has_voted:
        flash('Vous avez déjà voté', 'warning')
        return redirect(url_for('voter_dashboard'))

    if not voter.is_eligible:
        reason = voter.eligibility_reason or "Votre éligibilité est en cours de vérification."
        flash(reason, 'warning')
        return redirect(url_for('voter_dashboard'))
    
    if request.method == 'POST':
        candidate_id = request.form.get('candidate_id')
        candidate = Candidate.query.filter_by(id=candidate_id, is_approved=True).first()
        
        if not candidate:
            flash('Candidat invalide', 'danger')
            return redirect(url_for('voter_vote'))
        if candidate.is_rejected or not candidate.is_eligible:
            flash("Ce candidat n'est pas autorisé à recevoir des votes.", "warning")
            return redirect(url_for('voter_vote'))
        
        # Enregistrement du vote
        voter.has_voted = True
        voter.voted_at = datetime.utcnow()
        voter.vote_for_id = candidate_id
        candidate.vote_count += 1
        
        # Log du vote
        vote_hash = VoteLog.generate_vote_hash(
            voter.id, 
            candidate.id, 
            election.id, 
            secrets.token_hex(16)
        )
        
        vote_log = VoteLog(
            voter_id=voter.id,
            candidate_id=candidate.id,
            election_id=election.id,
            vote_hash=vote_hash,
            ip_address=request.remote_addr
        )
        
        db.session.add(vote_log)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un vote existe déjà pour cet électeur dans cette élection.", "warning")
            return redirect(url_for('voter_dashboard'))
        
        flash('Votre vote a été enregistré', 'success')
        flash(
            "Important : pensez à imprimer votre carte d’électeur depuis votre profil et à la présenter "
            "pour vérification (commissariat / service de population).",
            "info",
        )
        return redirect(url_for('voter_dashboard'))
    
    candidates = Candidate.query.filter_by(is_approved=True).all()
    return render_template('voter/vote.html',
                         voter=voter,
                         election=election,
                         candidates=candidates,
                         page_title="Bulletin de vote")

@app.route('/voter/profile')
@voter_required
def voter_profile():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()

    card_token = _build_voter_card_token(voter)
    verify_url = _build_voter_card_verify_url(voter, card_token)
    qr_data_uri = _qr_data_uri(verify_url, box_size=7, border=2)

    return render_template(
        "voter/profile.html",
        voter=voter,
        card_token=card_token,
        verify_url=verify_url,
        qr_data_uri=qr_data_uri,
        page_title="Mon profil",
    )

@app.route('/voter/profile/avatar', methods=['POST'])
@voter_required
def update_voter_avatar():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()

    avatar = request.files.get("avatar")
    if not avatar or not getattr(avatar, "filename", ""):
        flash("Veuillez sélectionner une image.", "warning")
        return redirect(url_for("voter_profile"))

    original_name = secure_filename(avatar.filename or "")
    ext = original_name.rsplit(".", 1)[-1].lower().strip() if "." in original_name else ""
    allowed = {"png", "jpg", "jpeg", "gif", "webp"}
    if ext not in allowed:
        flash("Format d'image invalide. Utilisez PNG/JPG/JPEG/GIF/WEBP.", "danger")
        return redirect(url_for("voter_profile"))

    upload_dir = _public_upload_dir("avatars")
    os.makedirs(upload_dir, exist_ok=True)

    try:
        raw = avatar.read()
    except Exception:
        raw = b""
    if not raw:
        flash("Fichier invalide.", "danger")
        return redirect(url_for("voter_profile"))
    if len(raw) > 2 * 1024 * 1024:
        flash("L'image ne doit pas dépasser 2MB.", "warning")
        return redirect(url_for("voter_profile"))

    # Nettoyer les anciennes versions (cache + extensions multiples)
    for old_ext in ("webp", "png", "jpg", "jpeg", "gif"):
        old_path = os.path.join(upload_dir, f"voter_{voter.id}.{old_ext}")
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    # Si Pillow est dispo, on normalise l'avatar en WEBP (pro + léger)
    if Image:
        try:
            img = Image.open(BytesIO(raw))
            if ImageOps:
                img = ImageOps.exif_transpose(img)

            # Préserver l'alpha si présent
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")

            img.thumbnail((512, 512))

            save_path = os.path.join(upload_dir, f"voter_{voter.id}.webp")
            img.save(save_path, "WEBP", quality=86, method=6)
            flash("Photo de profil mise à jour.", "success")
            return redirect(url_for("voter_profile"))
        except Exception:
            logger.exception("Erreur lors du traitement de l'avatar électeur")

    # Fallback: sauvegarde brute si Pillow indisponible/échoue
    save_path = os.path.join(upload_dir, f"voter_{voter.id}.{ext}")
    try:
        with open(save_path, "wb") as f:
            f.write(raw)
        flash("Photo de profil mise à jour.", "success")
    except Exception:
        logger.exception("Erreur lors de l'enregistrement de l'avatar électeur")
        flash("Impossible d'enregistrer l'image. Réessayez.", "danger")

    return redirect(url_for("voter_profile"))

@app.route('/voter/card')
@voter_required
def voter_card():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()

    card_token = _build_voter_card_token(voter)
    verify_url = _build_voter_card_verify_url(voter, card_token)
    qr_data_uri = _qr_data_uri(verify_url, box_size=7, border=2)

    return render_template(
        "voter/card.html",
        voter=voter,
        election=election,
        card_token=card_token,
        verify_url=verify_url,
        qr_data_uri=qr_data_uri,
        page_title="Carte d'électeur",
    )

@app.route("/voter/card/qr.png")
@voter_required
def voter_card_qr_png():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()
    token = _build_voter_card_token(voter)
    verify_url = _build_voter_card_verify_url(voter, token)

    png = _qr_png_bytes(verify_url, box_size=7, border=2)
    if not png:
        abort(404)

    resp = Response(png, mimetype="image/png")
    resp.headers["Content-Disposition"] = "attachment; filename=qr-carte-electeur.png"
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/verify/voter-card/<int:voter_id>/<token>")
def verify_voter_card(voter_id: int, token: str):
    voter = Voter.query.get(voter_id)
    provided = (token or "").strip().upper()

    if not voter:
        return render_template(
            "visitor/verify_voter_card.html",
            is_valid=False,
            voter=None,
            checked_at=datetime.utcnow(),
            page_title="Vérification carte",
        )

    expected = _build_voter_card_token(voter)
    is_valid = bool(provided) and hmac.compare_digest(expected, provided)

    election = Election.get_current_election()

    return render_template(
        "visitor/verify_voter_card.html",
        is_valid=is_valid,
        voter=voter if is_valid else None,
        election=election,
        checked_at=datetime.utcnow(),
        page_title="Vérification carte",
    )

@app.route('/voter/profile/update', methods=['POST'])
@voter_required
def update_voter_profile():
    voter = Voter.query.filter_by(user_id=current_user.id).first_or_404()

    # Mise à jour téléphone (si la colonne existe dans le modèle)
    phone = (request.form.get('phone') or '').strip()
    if phone and hasattr(Voter, 'phone_number'):
        voter.phone_number = phone

    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    # Changement de mot de passe (optionnel)
    if new_password or confirm_password:
        if not current_password or not current_user.check_password(current_password):
            flash("Mot de passe actuel incorrect", "danger")
            return redirect(url_for('voter_profile'))
        if new_password != confirm_password:
            flash("Les nouveaux mots de passe ne correspondent pas", "warning")
            return redirect(url_for('voter_profile'))

        current_user.set_password(new_password)
        flash("Mot de passe mis à jour", "success")

    db.session.commit()
    flash("Profil mis à jour", "success")
    return redirect(url_for('voter_profile'))

# ========== ROUTES CANDIDAT ==========
@app.route('/candidate/dashboard')
@candidate_required
def candidate_dashboard():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()
    now_utc = datetime.utcnow()
    announcements = (
        Announcement.query.filter(
            Announcement.is_active.is_(True),
            or_(Announcement.audience.in_(['all', 'candidates']), Announcement.audience.is_(None)),
            or_(Announcement.expires_at.is_(None), Announcement.expires_at >= now_utc),
        )
        .order_by(Announcement.is_urgent.desc(), Announcement.created_at.desc())
        .limit(8)
        .all()
    )
    
    return render_template('candidate/dashboardc.html',
                         candidate=candidate,
                         election=election,
                         announcements=announcements,
                         page_title="Tableau de bord")

@app.route('/candidate/profile')
@candidate_required
def candidate_profile():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()

    competitors = Candidate.query.filter_by(is_approved=True).order_by(Candidate.vote_count.desc()).all()
    total_candidates = len(competitors)
    ranking = None
    for idx, c in enumerate(competitors, start=1):
        if c.id == candidate.id:
            ranking = idx
            break

    return render_template(
        'candidate/profile_candidate.html',
        candidate=candidate,
        election=election,
        total_candidates=total_candidates,
        ranking=ranking,
        page_title="Mon profil",
    )

@app.route("/candidate/profile/photo", methods=["POST"])
@candidate_required
def candidate_update_photo():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()

    photo = request.files.get("profile_image") or request.files.get("photo")
    if not photo or not getattr(photo, "filename", ""):
        flash("Veuillez sélectionner une image.", "warning")
        return redirect(url_for("candidate_profile"))

    original_name = secure_filename(photo.filename or "")
    ext = original_name.rsplit(".", 1)[-1].lower().strip() if "." in original_name else ""
    allowed_ext = {"png", "jpg", "jpeg", "gif", "webp"}
    if ext not in allowed_ext:
        flash("Format d'image invalide. Utilisez PNG/JPG/JPEG/GIF/WEBP.", "danger")
        return redirect(url_for("candidate_profile"))

    try:
        raw = photo.read()
    except Exception:
        raw = b""
    if not raw:
        flash("Fichier invalide.", "danger")
        return redirect(url_for("candidate_profile"))
    if len(raw) > 2 * 1024 * 1024:
        flash("L'image ne doit pas dépasser 2MB.", "warning")
        return redirect(url_for("candidate_profile"))

    upload_dir = _public_upload_dir("candidates")
    os.makedirs(upload_dir, exist_ok=True)

    # Supprimer l'ancienne photo si elle existe
    old_name = (candidate.profile_image or "").strip()
    if old_name and old_name != "default-candidate.jpg":
        old_path = os.path.join(upload_dir, secure_filename(old_name))
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    saved_name = None
    if Image:
        try:
            img = Image.open(BytesIO(raw))
            if ImageOps:
                img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")
            img.thumbnail((1024, 1024))

            saved_name = f"cand_{candidate.id}_{secrets.token_hex(8)}.webp"
            save_path = os.path.join(upload_dir, saved_name)
            img.save(save_path, "WEBP", quality=86, method=6)
        except Exception:
            logger.exception("Erreur traitement image profil candidat (profile page)")

    if not saved_name:
        saved_name = f"cand_{candidate.id}_{secrets.token_hex(8)}.{ext}"
        save_path = os.path.join(upload_dir, saved_name)
        try:
            with open(save_path, "wb") as out:
                out.write(raw)
        except Exception:
            logger.exception("Erreur écriture image profil candidat (profile page)")
            flash("Impossible d'enregistrer l'image. Réessayez.", "danger")
            return redirect(url_for("candidate_profile"))

    candidate.profile_image = saved_name
    db.session.commit()
    flash("Photo de profil mise à jour.", "success")
    return redirect(url_for("candidate_profile"))

@app.route("/candidate/profile/password", methods=["POST"])
@candidate_required
def candidate_change_password():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not current_password or not current_user.check_password(current_password):
        flash("Mot de passe actuel incorrect", "danger")
        return redirect(url_for("candidate_profile"))

    if not new_password or len(new_password) < 8:
        flash("Le nouveau mot de passe doit contenir au moins 8 caractères", "warning")
        return redirect(url_for("candidate_profile"))

    if new_password != confirm_password:
        flash("Les nouveaux mots de passe ne correspondent pas", "warning")
        return redirect(url_for("candidate_profile"))

    current_user.set_password(new_password)
    db.session.commit()
    logout_user()
    flash("Mot de passe mis à jour. Veuillez vous reconnecter.", "success")
    return redirect(url_for("login"))

@app.route("/candidate/profile/export")
@candidate_required
def candidate_export_profile():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()

    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "candidate": {
            "id": candidate.id,
            "full_name": candidate.full_name,
            "cni_masked": candidate.cni_masked,
            "age": candidate.age,
            "place_of_birth": candidate.place_of_birth,
            "party_name": candidate.party_name,
            "party_acronym": candidate.party_acronym,
            "is_approved": bool(candidate.is_approved),
            "vote_count": int(candidate.vote_count or 0),
            "campaign_slogan": candidate.campaign_slogan,
            "biography": candidate.biography,
            "political_program": candidate.political_program,
            "website_url": candidate.website_url,
            "facebook_url": candidate.facebook_url,
            "twitter_url": candidate.twitter_url,
            "campaign_video_url": candidate.campaign_video_url,
        },
        "election": {
            "year": election.year if election else datetime.utcnow().year,
            "name": election.name if election else (app.config.get("ELECTION_NAME") or ""),
        },
    }

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    resp = Response(content, mimetype="application/json; charset=utf-8")
    resp.headers["Content-Disposition"] = f"attachment; filename=profil_candidat_{candidate.id}.json"
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/candidate/profile/delete", methods=["POST"])
@candidate_required
def candidate_delete_account():
    confirm_text = (request.form.get("confirm_text") or "").strip().upper()
    current_password = request.form.get("current_password") or ""

    if confirm_text != "SUPPRIMER":
        flash("Confirmation invalide. Tapez SUPPRIMER.", "warning")
        return redirect(url_for("candidate_profile"))

    if not current_password or not current_user.check_password(current_password):
        flash("Mot de passe actuel incorrect", "danger")
        return redirect(url_for("candidate_profile"))

    candidate = Candidate.query.filter_by(user_id=current_user.id).first()
    if candidate:
        candidate.is_approved = False
        candidate.is_rejected = True

    current_user.is_active = False
    db.session.commit()

    logout_user()
    flash("Votre compte a été désactivé.", "success")
    return redirect(url_for("index"))

@app.route('/candidate/campaign', methods=['GET', 'POST'])
@candidate_required
def candidate_campaign():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()

    upload_dir = os.path.join(app.config.get('UPLOAD_FOLDER', 'static/uploads'), 'candidates')

    def list_gallery_images(limit: int = 5):
        images = []
        prefix = f"cand_{candidate.id}_gallery_"
        if not os.path.isdir(upload_dir):
            return images
        try:
            for name in os.listdir(upload_dir):
                if not name.startswith(prefix):
                    continue
                abs_path = os.path.join(upload_dir, name)
                if not os.path.isfile(abs_path):
                    continue
                try:
                    mtime = int(os.path.getmtime(abs_path))
                except Exception:
                    mtime = 0
                images.append((name, mtime))
        except Exception:
            return []

        images.sort(key=lambda t: t[1], reverse=True)
        result = []
        for name, mtime in images[: max(0, int(limit or 0))]:
            result.append(
                {
                    "filename": name,
                    "url": url_for("static", filename=f"uploads/candidates/{name}", v=mtime or None),
                }
            )
        return result

    allowed_ext = {"png", "jpg", "jpeg", "gif", "webp"}

    if request.method == 'POST':
        os.makedirs(upload_dir, exist_ok=True)

        # Mettre à jour uniquement les champs disponibles dans le modèle actuel
        candidate.party_name = (request.form.get('party_name') or candidate.party_name or '').strip() or None
        candidate.party_acronym = (request.form.get('party_acronym') or candidate.party_acronym or '').strip() or None
        candidate.campaign_slogan = request.form.get('campaign_slogan') or candidate.campaign_slogan
        candidate.political_program = request.form.get('political_program') or candidate.political_program
        candidate.biography = request.form.get('biography') or candidate.biography
        candidate.website_url = request.form.get('website_url') or candidate.website_url
        candidate.facebook_url = request.form.get('facebook_url') or candidate.facebook_url
        candidate.twitter_url = request.form.get('twitter_url') or candidate.twitter_url
        candidate.campaign_video_url = request.form.get('campaign_video_url') or candidate.campaign_video_url

        # Suppression de la photo de profil (si demandé)
        remove_profile_image = (request.form.get("remove_profile_image") or "").strip().lower() in {"1", "true", "yes", "on"}
        if remove_profile_image:
            old_name = (candidate.profile_image or "").strip()
            if old_name and old_name != "default-candidate.jpg":
                old_path = os.path.join(upload_dir, secure_filename(old_name))
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            candidate.profile_image = None

        profile_image = request.files.get('profile_image')
        if profile_image and getattr(profile_image, 'filename', ''):
            original_name = secure_filename(profile_image.filename)
            ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
            if ext not in allowed_ext:
                flash("Format d'image invalide. Utilisez PNG/JPG/JPEG/GIF/WEBP.", 'danger')
                return redirect(url_for('candidate_campaign'))

            # Supprimer l'ancienne photo si elle existe
            old_name = (candidate.profile_image or "").strip()
            if old_name and old_name != "default-candidate.jpg":
                old_path = os.path.join(upload_dir, secure_filename(old_name))
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

            # Enregistrer en WEBP si possible (plus pro + léger)
            raw = b""
            try:
                raw = profile_image.read()
            except Exception:
                raw = b""

            if not raw:
                flash("Fichier image invalide.", "danger")
                return redirect(url_for("candidate_campaign"))

            saved_name = None
            if Image:
                try:
                    img = Image.open(BytesIO(raw))
                    if ImageOps:
                        img = ImageOps.exif_transpose(img)
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA" if "A" in img.mode else "RGB")
                    img.thumbnail((1024, 1024))

                    unique_name = f"cand_{candidate.id}_{secrets.token_hex(8)}.webp"
                    save_path = os.path.join(upload_dir, unique_name)
                    img.save(save_path, "WEBP", quality=86, method=6)
                    saved_name = unique_name
                except Exception:
                    logger.exception("Erreur traitement image profil candidat")

            if not saved_name:
                unique_name = f"cand_{candidate.id}_{secrets.token_hex(8)}.{ext}"
                save_path = os.path.join(upload_dir, unique_name)
                try:
                    with open(save_path, "wb") as out:
                        out.write(raw)
                    saved_name = unique_name
                except Exception:
                    logger.exception("Erreur écriture image profil candidat")

            if saved_name:
                candidate.profile_image = saved_name

        # Images supplémentaires (gallery sans migration DB)
        additional_files = request.files.getlist("additional_images") or []
        if additional_files:
            existing = list_gallery_images(limit=10)
            remaining = max(0, 5 - len(existing))
            if remaining <= 0:
                flash("Vous avez déjà 5 images de campagne. Supprimez-en une pour en ajouter.", "warning")
            else:
                for f in additional_files[:remaining]:
                    if not f or not getattr(f, "filename", ""):
                        continue
                    original_name = secure_filename(f.filename or "")
                    ext = original_name.rsplit(".", 1)[-1].lower().strip() if "." in original_name else ""
                    if ext not in allowed_ext:
                        continue

                    try:
                        raw = f.read()
                    except Exception:
                        raw = b""
                    if not raw:
                        continue
                    if len(raw) > 2 * 1024 * 1024:
                        flash(f"Image trop lourde ignorée : {original_name} (max 2MB).", "warning")
                        continue

                    saved = False
                    if Image:
                        try:
                            img = Image.open(BytesIO(raw))
                            if ImageOps:
                                img = ImageOps.exif_transpose(img)
                            if img.mode not in ("RGB", "RGBA"):
                                img = img.convert("RGBA" if "A" in img.mode else "RGB")
                            img.thumbnail((1600, 1600))

                            unique_name = f"cand_{candidate.id}_gallery_{secrets.token_hex(8)}.webp"
                            save_path = os.path.join(upload_dir, unique_name)
                            img.save(save_path, "WEBP", quality=84, method=6)
                            saved = True
                        except Exception:
                            logger.exception("Erreur traitement image gallery candidat")

                    if not saved:
                        unique_name = f"cand_{candidate.id}_gallery_{secrets.token_hex(8)}.{ext}"
                        save_path = os.path.join(upload_dir, unique_name)
                        try:
                            with open(save_path, "wb") as out:
                                out.write(raw)
                        except Exception:
                            logger.exception("Erreur écriture image gallery candidat")

        db.session.commit()
        flash('Campagne mise à jour', 'success')
        return redirect(url_for('candidate_campaign'))

    return render_template('candidate/campaign.html',
                         candidate=candidate,
                         gallery_images=list_gallery_images(limit=5),
                         page_title="Gestion de campagne")

@app.route("/candidate/campaign/gallery/delete", methods=["POST"])
@candidate_required
def candidate_campaign_gallery_delete():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()
    filename = secure_filename((request.form.get("filename") or "").strip())
    if not filename:
        flash("Image invalide.", "danger")
        return redirect(url_for("candidate_campaign"))

    prefix = f"cand_{candidate.id}_gallery_"
    if not filename.startswith(prefix):
        flash("Suppression non autorisée.", "danger")
        return redirect(url_for("candidate_campaign"))

    upload_dir = os.path.join(app.config.get("UPLOAD_FOLDER", "static/uploads"), "candidates")
    abs_path = os.path.join(upload_dir, filename)
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
            flash("Image supprimée.", "success")
        except Exception:
            logger.exception("Erreur suppression image gallery candidat")
            flash("Impossible de supprimer l'image.", "danger")
    else:
        flash("Image introuvable.", "warning")

    return redirect(url_for("candidate_campaign"))

@app.route('/candidate/statistics')
@candidate_required
def candidate_statistics():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first_or_404()
    election = Election.get_current_election()

    competitors = Candidate.query.filter_by(is_approved=True).order_by(Candidate.vote_count.desc()).all()
    total_candidates = len(competitors)
    total_votes = sum(c.vote_count for c in competitors)
    ranking = None
    for idx, c in enumerate(competitors, start=1):
        if c.id == candidate.id:
            ranking = idx
            break

    return render_template('candidate/statistics.html',
                          candidate=candidate,
                          election=election,
                          competitors=competitors,
                          total_candidates=total_candidates,
                          total_votes=total_votes,
                          ranking=ranking,
                          daily_change=0,
                          target_votes=1000,
                          strengths=[],
                          recommendations=[],
                          last_update=datetime.utcnow(),
                          page_title="Statistiques")

# ========== ROUTES ADMIN ==========
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    stats = {
        'total_users': User.query.count(),
        'total_voters': Voter.query.count(),
        'total_candidates': Candidate.query.count(),
        'approved_candidates': Candidate.query.filter_by(is_approved=True).count(),
        'pending_candidates': Candidate.query.filter_by(is_approved=False).count(),
        'votes_cast': VoteLog.query.count()
    }
    
    return render_template('admin/dashboardad.html',
                         stats=stats,
                         page_title="Administration")

@app.route('/admin/profile')
@admin_required
def admin_profile():
    recent_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()
    recent_archives = ElectionArchive.query.order_by(ElectionArchive.created_at.desc()).limit(5).all()
    return render_template(
        'admin/profile.html',
        admin_user=current_user,
        recent_logs=recent_logs,
        recent_archives=recent_archives,
        page_title="Profil administrateur",
    )

@app.route('/admin/profile/update', methods=['POST'])
@admin_required
def admin_profile_update():
    current_user.display_name = (request.form.get('display_name') or '').strip() or None
    current_user.phone_number = (request.form.get('phone_number') or '').strip() or None

    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if new_password or confirm_password:
        if not current_password or not current_user.check_password(current_password):
            flash("Mot de passe actuel incorrect.", "danger")
            return redirect(url_for('admin_profile'))
        if len(new_password) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "warning")
            return redirect(url_for('admin_profile'))
        if new_password != confirm_password:
            flash("Les nouveaux mots de passe ne correspondent pas.", "warning")
            return redirect(url_for('admin_profile'))
        current_user.set_password(new_password)

    _log_audit(
        "admin_profile_update",
        f"Mise à jour du profil administrateur ({current_user.profile_name}).",
    )
    db.session.commit()
    flash("Profil administrateur mis à jour.", "success")
    return redirect(url_for('admin_profile'))

@app.route('/admin/profile/avatar', methods=['POST'])
@admin_required
def admin_profile_avatar():
    photo = request.files.get("avatar")
    if not photo or not getattr(photo, "filename", ""):
        flash("Veuillez sélectionner une image.", "warning")
        return redirect(url_for('admin_profile'))

    original_name = secure_filename(photo.filename or "")
    ext = original_name.rsplit(".", 1)[-1].lower().strip() if "." in original_name else ""
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        flash("Format d'image invalide. Utilisez PNG, JPG, JPEG, GIF ou WEBP.", "danger")
        return redirect(url_for('admin_profile'))

    try:
        raw = photo.read()
    except Exception:
        raw = b""

    if not raw:
        flash("Fichier image invalide.", "danger")
        return redirect(url_for('admin_profile'))
    if len(raw) > 2 * 1024 * 1024:
        flash("L'image ne doit pas dépasser 2MB.", "warning")
        return redirect(url_for('admin_profile'))

    upload_dir = _public_upload_dir("admins")
    os.makedirs(upload_dir, exist_ok=True)

    old_name = (current_user.avatar_filename or "").strip()
    if old_name:
        old_path = os.path.join(upload_dir, secure_filename(old_name))
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    saved_name = None
    if Image:
        try:
            img = Image.open(BytesIO(raw))
            if ImageOps:
                img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")
            img.thumbnail((512, 512))
            saved_name = f"admin_{current_user.id}_{secrets.token_hex(8)}.webp"
            img.save(os.path.join(upload_dir, saved_name), "WEBP", quality=86, method=6)
        except Exception:
            logger.exception("Erreur traitement avatar administrateur")

    if not saved_name:
        saved_name = f"admin_{current_user.id}_{secrets.token_hex(8)}.{ext}"
        try:
            with open(os.path.join(upload_dir, saved_name), "wb") as handle:
                handle.write(raw)
        except Exception:
            logger.exception("Erreur écriture avatar administrateur")
            flash("Impossible d'enregistrer l'image.", "danger")
            return redirect(url_for('admin_profile'))

    current_user.avatar_filename = saved_name
    _log_audit("admin_avatar_update", "Nouvel avatar administrateur enregistré.")
    db.session.commit()
    flash("Photo de profil administrateur mise à jour.", "success")
    return redirect(url_for('admin_profile'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/manage_users.html',
                         users=users,
                         page_title="Gestion des utilisateurs")

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    role = (request.form.get('role') or 'voter').strip().lower()
    is_active = bool(request.form.get('is_active'))
    allowed_roles = {'admin', 'voter', 'candidate'}

    if not email or not password:
        flash("Email et mot de passe requis", "danger")
        return redirect(url_for('admin_users'))

    if role not in allowed_roles:
        flash("Rôle utilisateur invalide", "danger")
        return redirect(url_for('admin_users'))

    if len(password) < 8:
        flash("Le mot de passe doit contenir au moins 8 caractères", "warning")
        return redirect(url_for('admin_users'))

    try:
        email = _normalize_email_address(email).lower()
    except EmailNotValidError as exc:
        flash(str(exc), "danger")
        return redirect(url_for('admin_users'))

    if User.query.filter_by(email=email).first():
        flash("Cet email est déjà utilisé", "warning")
        return redirect(url_for('admin_users'))

    profile_factory = None
    success_message = "Utilisateur créé avec succès"

    if role == 'voter':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        cni_number = (request.form.get('cni_number') or '').strip()
        place_of_birth = (request.form.get('place_of_birth') or '').strip()
        gender = (request.form.get('gender') or '').strip() or None
        phone = (request.form.get('phone') or '').strip() or None
        raw_birth_date = (request.form.get('date_of_birth') or '').strip()

        if not all([first_name, last_name, cni_number, place_of_birth, raw_birth_date]):
            flash("Le formulaire électeur est incomplet", "danger")
            return redirect(url_for('admin_users'))

        try:
            date_of_birth = datetime.strptime(raw_birth_date, '%Y-%m-%d').date()
        except Exception:
            flash("Date de naissance invalide", "danger")
            return redirect(url_for('admin_users'))

        min_age = int(app.config.get("MIN_VOTER_AGE", 18) or 18)
        if calculate_age(date_of_birth) < min_age:
            flash(f"L'électeur doit avoir au moins {min_age} ans", "warning")
            return redirect(url_for('admin_users'))

        if Voter.query.filter_by(cni_number=cni_number).first():
            flash("Cette CNI est déjà enregistrée pour un électeur", "warning")
            return redirect(url_for('admin_users'))

        def profile_factory(user_id):
            voter = Voter(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                cni_number=cni_number,
                date_of_birth=date_of_birth,
                place_of_birth=place_of_birth,
                gender=gender,
            )
            voter.phone_number = phone
            return voter

        success_message = "Électeur créé avec succès"

    elif role == 'candidate':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        cni_number = (request.form.get('cni_number') or '').strip()
        place_of_birth = (request.form.get('place_of_birth') or '').strip()
        party_name = (request.form.get('party_name') or '').strip()
        party_acronym = (request.form.get('party_acronym') or '').strip() or None
        slogan = (request.form.get('slogan') or '').strip()
        program = (request.form.get('program') or '').strip()
        raw_birth_date = (request.form.get('date_of_birth') or '').strip()
        is_approved = bool(request.form.get('is_approved'))

        if not all([first_name, last_name, cni_number, place_of_birth, party_name, slogan, program, raw_birth_date]):
            flash("Le formulaire candidat est incomplet", "danger")
            return redirect(url_for('admin_users'))

        try:
            date_of_birth = datetime.strptime(raw_birth_date, '%Y-%m-%d').date()
        except Exception:
            flash("Date de naissance invalide", "danger")
            return redirect(url_for('admin_users'))

        min_age = int(app.config.get("MIN_CANDIDATE_AGE", 40) or 40)
        if calculate_age(date_of_birth) < min_age:
            flash(f"Le candidat doit avoir au moins {min_age} ans", "warning")
            return redirect(url_for('admin_users'))

        if Candidate.query.filter_by(cni_number=cni_number).first():
            flash("Cette CNI est déjà enregistrée pour un candidat", "warning")
            return redirect(url_for('admin_users'))

        election = Election.get_current_election()

        def profile_factory(user_id):
            candidate = Candidate(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                cni_number=cni_number,
                date_of_birth=date_of_birth,
                party_name=party_name,
                party_acronym=party_acronym,
                is_approved=is_approved,
            )
            candidate.place_of_birth = place_of_birth
            candidate.campaign_slogan = slogan
            candidate.political_program = program
            candidate.is_rejected = False
            if candidate.is_approved or (election and election.auto_approve_candidates):
                candidate.is_approved = True
                candidate.approved_at = datetime.utcnow()
            return candidate

        success_message = "Candidat créé avec succès"

    user = User(email=email, role=role, is_active=is_active)
    user.set_password(password)
    user.email_verified_at = datetime.utcnow()
    db.session.add(user)
    db.session.flush()

    if profile_factory:
        db.session.add(profile_factory(user.id))

    db.session.commit()

    flash(success_message, "success")
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash("Vous ne pouvez pas supprimer votre propre compte", "warning")
        return redirect(url_for('admin_users'))

    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()

    flash("Utilisateur supprimé", "success")
    return redirect(url_for('admin_users'))

@app.route('/admin/election')
@admin_required
def admin_election():
    election = Election.get_current_election()
    audit_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()
    recent_archives = ElectionArchive.query.order_by(ElectionArchive.created_at.desc()).limit(5).all()
    return render_template('admin/election_settings.html',
                         election=election,
                         audit_logs=audit_logs,
                         recent_archives=recent_archives,
                         now=datetime.now(UTC),
                         page_title="Paramètres de l'élection")

def _parse_datetime_local(value):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None

@app.route('/admin/election/save', methods=['POST'])
@admin_required
def admin_election_save():
    current_year = datetime.now(UTC).year
    election = Election.query.filter_by(year=current_year).first()
    if not election:
        election = Election(year=current_year, status=Election.PHASE_PREPARATION)
        db.session.add(election)

    name = (request.form.get('name') or '').strip()
    year_raw = (request.form.get('year') or '').strip()
    if not name:
        return jsonify(success=False, message="Le nom de l'élection est obligatoire"), 400

    try:
        year = int(year_raw or str(datetime.now(UTC).year))
    except Exception:
        return jsonify(success=False, message="Année invalide"), 400

    registration_start = _parse_datetime_local(request.form.get('registration_start'))
    registration_end = _parse_datetime_local(request.form.get('registration_end'))
    voting_start = _parse_datetime_local(request.form.get('voting_start'))
    voting_end = _parse_datetime_local(request.form.get('voting_end'))

    if not all([registration_start, registration_end, voting_start, voting_end]):
        return jsonify(success=False, message="Toutes les dates sont obligatoires"), 400
    if registration_start >= registration_end:
        return jsonify(success=False, message="La fermeture des candidatures doit être après l'ouverture"), 400
    if voting_start >= voting_end:
        return jsonify(success=False, message="La fermeture du vote doit être après l'ouverture"), 400
    if registration_end >= voting_start:
        return jsonify(success=False, message="Le vote doit commencer après la phase de candidature"), 400

    election.name = name
    election.year = year
    election.description = request.form.get('description')
    election.registration_start = registration_start
    election.registration_end = registration_end
    election.voting_start = voting_start
    election.voting_end = voting_end
    election.max_candidates = request.form.get('max_candidates') or 10
    election.is_test_mode = (request.form.get('is_test_mode') == 'true')
    election.auto_approve_candidates = bool(request.form.get('auto_approve_candidates'))

    try:
        _log_audit(
            "save_election_settings",
            f"Paramètres mis à jour pour {election.name} {election.year} ({election.phase_label})",
        )
        db.session.commit()
        return jsonify(success=True, message="Paramètres enregistrés avec succès")
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur admin_election_save")
        return jsonify(success=False, message=f"Impossible d'enregistrer: {e}"), 500

def _create_archive_entry(archive_type: str, title: str) -> ElectionArchive:
    filename, summary = _election_snapshot(archive_type=archive_type, title=title)
    archive = ElectionArchive(
        archive_type=archive_type,
        title=title,
        summary=summary,
        file_path=filename,
        created_by_id=current_user.id,
    )
    db.session.add(archive)
    db.session.flush()
    return archive

def _reset_election_runtime(election):
    VoteLog.query.delete(synchronize_session=False)
    Announcement.query.delete(synchronize_session=False)

    removable_users = User.query.filter(User.role != 'admin').all()
    for user in removable_users:
        db.session.delete(user)

    if not election:
        current_year = datetime.now(UTC).year
        election = Election(year=current_year, status=Election.PHASE_PREPARATION)
        db.session.add(election)

    election.phase = Election.PHASE_PREPARATION
    election.registration_start = None
    election.registration_end = None
    election.voting_start = None
    election.voting_end = None
    return election

def _clear_all_system_data(election):
    election = _reset_election_runtime(election)
    current_year = datetime.now(UTC).year
    election.name = f"Élection Nationale {current_year}"
    election.year = current_year
    election.description = ""
    election.max_candidates = 10
    election.is_test_mode = False
    election.auto_approve_candidates = False
    return election

@app.route('/admin/election/action', methods=['POST'])
@admin_required
def admin_election_action():
    election = Election.get_current_election()

    action = (request.form.get('action') or '').strip()
    try:
        if action in {'openVoting', 'closeVoting', 'startCounting', 'publishResults'}:
            if not election:
                return jsonify(success=False, message="Aucune élection configurée"), 404
            previous_phase = election.phase_label
            election.apply_transition(action)
            archive = None
            _log_audit(
                action,
                f"Transition admin: {previous_phase} -> {election.phase_label}",
            )
            success_message = f"Transition appliquée: {election.phase_label}"
        elif action == 'resetElection':
            archive = _create_archive_entry(
                "reset",
                f"Archive avant réinitialisation - {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}",
            )
            election = _reset_election_runtime(election)
            _log_audit(
                action,
                f"Réinitialisation complète des données électorales. Archive #{archive.id} créée.",
            )
            success_message = "Élection réinitialisée. Les anciennes données ont été archivées."
        elif action == 'clearAllData':
            archive = _create_archive_entry(
                "purge",
                f"Archive avant suppression totale - {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}",
            )
            election = _clear_all_system_data(election)
            _log_audit(
                action,
                f"Suppression totale des données non-admin. Archive #{archive.id} créée.",
            )
            success_message = "Toutes les données opérationnelles ont été supprimées. Une archive a été créée."
        else:
            return jsonify(success=False, message="Action inconnue"), 400

        db.session.commit()
        return jsonify(
            success=True,
            message=success_message,
            phase=election.phase if election else None,
            phase_label=election.phase_label if election else None,
            archive_id=archive.id if archive else None,
        )
    except ValueError as e:
        return jsonify(success=False, message=str(e)), 400
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur admin_election_action")
        return jsonify(success=False, message=f"Transition échouée: {e}"), 500

@app.route('/admin/election/transition', methods=['POST'])
@admin_required
def admin_election_transition():
    return admin_election_action()

@app.route('/admin/archives/<int:archive_id>/download')
@admin_required
def download_election_archive(archive_id):
    archive = ElectionArchive.query.get_or_404(archive_id)
    abs_path = os.path.join(_ensure_archive_dir(), archive.file_path)
    if not os.path.exists(abs_path):
        abort(404)
    return send_file(abs_path, as_attachment=True, download_name=os.path.basename(abs_path))

@app.route('/admin/announcements')
@admin_required
def admin_announcements():
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template('admin/announcements.html',
                         announcements=announcements,
                         now=datetime.utcnow(),
                         page_title="Gestion des annonces")

def _parse_checkbox(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'on', 'yes'}

def _parse_expiration_date(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        # Date incluse jusqu'à 23:59:59 UTC.
        day = datetime.strptime(value, '%Y-%m-%d')
        return day + timedelta(days=1) - timedelta(seconds=1)
    except Exception:
        return None

@app.route('/candidate/announcements')
@candidate_required
def candidate_announcements():
    announcements = (
        Announcement.query.filter_by(author_id=current_user.id)
        .order_by(Announcement.created_at.desc())
        .all()
    )
    return render_template(
        'candidate/announcements.html',
        announcements=announcements,
        now=datetime.utcnow(),
        page_title="Mes annonces",
    )

@app.route('/candidate/api/announcements/<int:announcement_id>')
@candidate_required
def api_candidate_announcement_detail(announcement_id):
    announcement = Announcement.query.filter_by(id=announcement_id, author_id=current_user.id).first_or_404()
    return jsonify(
        id=announcement.id,
        title=announcement.title,
        content=announcement.content,
        audience=announcement.audience or 'all',
        priority=int(announcement.priority or 0),
        is_active=bool(announcement.is_active),
        is_urgent=bool(announcement.is_urgent),
        expires_at=(announcement.expires_at.strftime('%Y-%m-%d') if announcement.expires_at else ''),
    )

@app.route('/candidate/announcements/create', methods=['POST'])
@candidate_required
def candidate_create_announcement():
    title = (request.form.get('title') or '').strip()
    content = request.form.get('content') or ''
    audience = (request.form.get('audience') or 'all').strip().lower()
    priority_raw = (request.form.get('priority') or '0').strip()

    if not title:
        return jsonify(success=False, message="Le titre est obligatoire"), 400
    if not Markup(content).striptags().strip():
        return jsonify(success=False, message="Le contenu est obligatoire"), 400
    if audience not in {'all', 'voters', 'candidates'}:
        audience = 'all'

    try:
        priority = int(priority_raw)
    except Exception:
        priority = 0
    priority = max(0, min(3, priority))

    announcement = Announcement(
        title=title,
        content=content,
        author_id=current_user.id,
        audience=audience,
        priority=priority,
        is_urgent=_parse_checkbox(request.form.get('is_urgent')),
        is_active=_parse_checkbox(request.form.get('is_active'), default=True),
        expires_at=_parse_expiration_date(request.form.get('expires_at')),
    )

    try:
        db.session.add(announcement)
        db.session.commit()
        return jsonify(success=True, message="Annonce publiée avec succès", id=announcement.id)
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur candidate_create_announcement")
        return jsonify(success=False, message=f"Erreur lors de la création: {e}"), 500

@app.route('/candidate/announcements/update/<int:announcement_id>', methods=['POST'])
@candidate_required
def candidate_update_announcement(announcement_id):
    announcement = Announcement.query.filter_by(id=announcement_id, author_id=current_user.id).first_or_404()
    title = (request.form.get('title') or '').strip()
    content = request.form.get('content') or ''
    audience = (request.form.get('audience') or 'all').strip().lower()
    priority_raw = (request.form.get('priority') or '0').strip()

    if not title:
        return jsonify(success=False, message="Le titre est obligatoire"), 400
    if not Markup(content).striptags().strip():
        return jsonify(success=False, message="Le contenu est obligatoire"), 400
    if audience not in {'all', 'voters', 'candidates'}:
        audience = 'all'

    try:
        priority = int(priority_raw)
    except Exception:
        priority = 0
    priority = max(0, min(3, priority))

    announcement.title = title
    announcement.content = content
    announcement.audience = audience
    announcement.priority = priority
    announcement.is_urgent = _parse_checkbox(request.form.get('is_urgent'))
    announcement.is_active = _parse_checkbox(request.form.get('is_active'), default=True)
    announcement.expires_at = _parse_expiration_date(request.form.get('expires_at'))

    try:
        db.session.commit()
        return jsonify(success=True, message="Annonce mise à jour avec succès")
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur candidate_update_announcement")
        return jsonify(success=False, message=f"Erreur lors de la mise à jour: {e}"), 500

@app.route('/candidate/announcements/toggle/<int:announcement_id>', methods=['POST'])
@candidate_required
def candidate_toggle_announcement(announcement_id):
    announcement = Announcement.query.filter_by(id=announcement_id, author_id=current_user.id).first_or_404()
    announcement.is_active = not bool(announcement.is_active)
    try:
        db.session.commit()
        status = "activée" if announcement.is_active else "désactivée"
        return jsonify(success=True, message=f"Annonce {status} avec succès")
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur candidate_toggle_announcement")
        return jsonify(success=False, message=f"Erreur lors du changement de statut: {e}"), 500

@app.route('/candidate/announcements/delete/<int:announcement_id>', methods=['POST'])
@candidate_required
def candidate_delete_announcement(announcement_id):
    announcement = Announcement.query.filter_by(id=announcement_id, author_id=current_user.id).first_or_404()
    try:
        db.session.delete(announcement)
        db.session.commit()
        return jsonify(success=True, message="Annonce supprimée avec succès")
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur candidate_delete_announcement")
        return jsonify(success=False, message=f"Erreur lors de la suppression: {e}"), 500

@app.route('/admin/api/announcements/<int:announcement_id>')
@admin_required
def api_admin_announcement_detail(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    return jsonify(
        id=announcement.id,
        title=announcement.title,
        content=announcement.content,
        audience=announcement.audience or 'all',
        priority=int(announcement.priority or 0),
        is_active=bool(announcement.is_active),
        is_urgent=bool(announcement.is_urgent),
        expires_at=(announcement.expires_at.strftime('%Y-%m-%d') if announcement.expires_at else ''),
        created_at=_iso(announcement.created_at),
    )

@app.route('/admin/announcements/create', methods=['POST'])
@admin_required
def create_announcement():
    title = (request.form.get('title') or '').strip()
    content = request.form.get('content') or ''
    audience = (request.form.get('audience') or 'all').strip().lower()
    priority_raw = (request.form.get('priority') or '0').strip()

    if not title:
        return jsonify(success=False, message="Le titre est obligatoire"), 400
    if not Markup(content).striptags().strip():
        return jsonify(success=False, message="Le contenu est obligatoire"), 400

    if audience not in {'all', 'voters', 'candidates', 'admin'}:
        audience = 'all'

    try:
        priority = int(priority_raw)
    except Exception:
        priority = 0
    priority = max(0, min(3, priority))

    announcement = Announcement(
        title=title,
        content=content,
        author_id=current_user.id,
        audience=audience,
        priority=priority,
        is_urgent=_parse_checkbox(request.form.get('is_urgent')),
        is_active=_parse_checkbox(request.form.get('is_active'), default=True),
        expires_at=_parse_expiration_date(request.form.get('expires_at')),
    )

    try:
        db.session.add(announcement)
        db.session.commit()
        return jsonify(success=True, message="Annonce créée avec succès", id=announcement.id)
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur create_announcement")
        return jsonify(success=False, message=f"Erreur lors de la création: {e}"), 500

@app.route('/admin/announcements/update/<int:announcement_id>', methods=['POST'])
@admin_required
def update_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    title = (request.form.get('title') or '').strip()
    content = request.form.get('content') or ''
    audience = (request.form.get('audience') or 'all').strip().lower()
    priority_raw = (request.form.get('priority') or '0').strip()

    if not title:
        return jsonify(success=False, message="Le titre est obligatoire"), 400
    if not Markup(content).striptags().strip():
        return jsonify(success=False, message="Le contenu est obligatoire"), 400
    if audience not in {'all', 'voters', 'candidates', 'admin'}:
        audience = 'all'

    try:
        priority = int(priority_raw)
    except Exception:
        priority = 0
    priority = max(0, min(3, priority))

    announcement.title = title
    announcement.content = content
    announcement.audience = audience
    announcement.priority = priority
    announcement.is_urgent = _parse_checkbox(request.form.get('is_urgent'))
    announcement.is_active = _parse_checkbox(request.form.get('is_active'), default=True)
    announcement.expires_at = _parse_expiration_date(request.form.get('expires_at'))

    try:
        db.session.commit()
        return jsonify(success=True, message="Annonce mise à jour avec succès")
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur update_announcement")
        return jsonify(success=False, message=f"Erreur lors de la mise à jour: {e}"), 500

@app.route('/admin/announcements/toggle/<int:announcement_id>', methods=['POST'])
@admin_required
def toggle_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    announcement.is_active = not bool(announcement.is_active)
    try:
        db.session.commit()
        status = "activée" if announcement.is_active else "désactivée"
        return jsonify(success=True, message=f"Annonce {status} avec succès", is_active=bool(announcement.is_active))
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur toggle_announcement")
        return jsonify(success=False, message=f"Erreur lors du changement de statut: {e}"), 500

@app.route('/admin/announcements/delete/<int:announcement_id>', methods=['POST'])
@admin_required
def delete_announcement(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    try:
        db.session.delete(announcement)
        db.session.commit()
        return jsonify(success=True, message="Annonce supprimée avec succès")
    except Exception as e:
        db.session.rollback()
        logger.exception("Erreur delete_announcement")
        return jsonify(success=False, message=f"Erreur lors de la suppression: {e}"), 500

@app.route('/admin/candidates')
@admin_required
def admin_candidates():
    candidates = Candidate.query.all()
    return render_template('admin/manage_candidates.html',
                         candidates=candidates,
                         page_title="Gestion des candidats")

@app.route('/admin/candidates/delete/<int:candidate_id>', methods=['GET', 'POST'])
@admin_required
def delete_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    db.session.delete(candidate)
    try:
        db.session.commit()
        flash("Candidat supprimé", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Impossible de supprimer le candidat: {e}", "danger")
    return redirect(url_for('admin_candidates'))

@app.route('/admin/candidate/approve/<int:candidate_id>')
@admin_required
def approve_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    candidate.is_approved = True
    candidate.approved_at = datetime.utcnow()
    db.session.commit()
    
    flash(f'Candidat {candidate.full_name} approuvé', 'success')
    return redirect(url_for('admin_candidates'))

RESULTS_PALETTE = ["#0d6efd", "#198754", "#ffc107", "#dc3545", "#6f42c1", "#0dcaf0"]

def _results_are_public(election):
    if not election:
        return False
    return election.phase == Election.PHASE_PROCLAMATION

def _build_results_context():
    election = Election.get_current_election()
    candidates = Candidate.query.filter_by(is_approved=True).order_by(Candidate.vote_count.desc()).all()

    total_votes = sum(int(c.vote_count or 0) for c in candidates)
    ranked_candidates = []
    gradient_parts = []
    cursor = 0.0

    for index, candidate in enumerate(candidates):
        votes = int(candidate.vote_count or 0)
        percentage = round((votes / total_votes * 100), 1) if total_votes > 0 else 0.0
        candidate.percentage = percentage
        color = RESULTS_PALETTE[index % len(RESULTS_PALETTE)]
        ranked_candidates.append({
            "candidate": candidate,
            "votes": votes,
            "percentage": percentage,
            "color": color,
            "rank": index + 1,
        })

        if percentage > 0:
            next_cursor = min(100.0, cursor + percentage)
            gradient_parts.append(f"{color} {cursor:.2f}% {next_cursor:.2f}%")
            cursor = next_cursor

    if cursor < 100.0:
        gradient_parts.append(f"#e9ecef {cursor:.2f}% 100%")

    total_voters = Voter.query.count()
    voters_voted = Voter.query.filter_by(has_voted=True).count()
    participation_rate = round((voters_voted / total_voters * 100), 1) if total_voters > 0 else 0.0
    winner = ranked_candidates[0] if ranked_candidates else None

    current_year = datetime.utcnow().year
    return {
        "election": election,
        "candidates": candidates,
        "ranked_candidates": ranked_candidates,
        "candidates_json": [
            {
                "id": item["candidate"].id,
                "full_name": item["candidate"].full_name,
                "vote_count": item["votes"],
                "percentage": item["percentage"],
                "color": item["color"],
            }
            for item in ranked_candidates
        ],
        "pie_gradient": f"conic-gradient({', '.join(gradient_parts)})" if gradient_parts else "conic-gradient(#e9ecef 0% 100%)",
        "winner": winner,
        "total_votes": total_votes,
        "results_available": _results_are_public(election),
        "stats": {
            "total_voters": total_voters,
            "voters_voted": voters_voted,
            "participation_rate": participation_rate,
            "total_votes": total_votes,
        },
    }

@app.route('/admin/results')
@admin_required
def admin_results():
    context = _build_results_context()
    return render_template('admin/results_admin.html', page_title="Résultats", **context)

@app.route('/results')
def public_results():
    if current_user.is_authenticated and current_user.role == 'admin':
        return redirect(url_for('admin_results'))
    if app.config.get("RESULTS_REQUIRE_AUTHENTICATION", True) and not current_user.is_authenticated:
        flash("Connectez-vous pour consulter les résultats.", "warning")
        return redirect(url_for('login'))

    context = _build_results_context()
    if not context["results_available"]:
        flash("Les résultats seront publiés à la fin du scrutin.", "info")
        if current_user.is_authenticated and current_user.role == 'candidate':
            return redirect(url_for('candidate_dashboard'))
        if current_user.is_authenticated and current_user.role == 'voter':
            return redirect(url_for('voter_dashboard'))
        return redirect(url_for('index'))
    return render_template('visitor/results.html', page_title="Résultats", **context)

# ========== API (AJAX) ==========
def _iso(value):
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)

@app.route('/api/admin/system/health')
@admin_required
def api_admin_system_health():
    try:
        # Ping DB via une requête simple
        _ = User.query.limit(1).all()
        return jsonify(status="healthy", message="OK")
    except Exception as e:
        return jsonify(status="unhealthy", message=str(e)), 500

@app.route('/api/election/status')
@admin_required
def api_election_status():
    election = Election.get_current_election()
    sig = None
    payload = {
        "exists": bool(election),
        "status": election.status if election else None,
        "phase": election.phase if election else None,
        "phase_label": election.phase_label if election else None,
        "is_voting_open": bool(election and election.is_voting_open),
        "is_registration_open": bool(election and election.is_registration_open),
        "updated_at": _iso(election.updated_at) if election else None,
    }
    if election:
        sig = f"{payload['status']}|{payload['is_voting_open']}|{payload['is_registration_open']}|{payload['updated_at']}"

    prev = session.get("election_status_sig")
    status_changed = prev is not None and prev != sig
    session["election_status_sig"] = sig
    payload["status_changed"] = status_changed
    return jsonify(payload)

@app.route('/api/election/results/live')
@admin_required
def api_election_results_live():
    election = Election.get_current_election()
    total_votes = 0
    if election:
        total_votes = VoteLog.query.filter_by(election_id=election.id).count()

    prev = session.get("live_total_votes")
    try:
        prev_int = int(prev) if prev is not None else None
    except Exception:
        prev_int = None

    new_votes = 0
    if prev_int is not None and total_votes > prev_int:
        new_votes = total_votes - prev_int

    updated = prev_int is not None and total_votes != prev_int
    session["live_total_votes"] = total_votes

    return jsonify(
        updated=updated,
        total_votes=int(total_votes),
        new_votes=int(new_votes),
    )

@app.route('/api/candidate/announcements/latest')
@candidate_required
def api_candidate_latest_announcement():
    now_utc = datetime.utcnow()
    latest = (
        Announcement.query.filter(
            Announcement.is_active.is_(True),
            or_(Announcement.audience.in_(['all', 'candidates']), Announcement.audience.is_(None)),
            or_(Announcement.expires_at.is_(None), Announcement.expires_at >= now_utc),
        )
        .order_by(Announcement.is_urgent.desc(), Announcement.created_at.desc())
        .first()
    )
    if not latest:
        return jsonify(id=None, title=None, is_urgent=False, created_at=None)

    return jsonify(
        id=latest.id,
        title=latest.title,
        is_urgent=bool(latest.is_urgent),
        created_at=_iso(latest.created_at),
    )

@app.route('/api/candidate/status')
@candidate_required
def api_candidate_status():
    candidate = Candidate.query.filter_by(user_id=current_user.id).first()
    if not candidate:
        return jsonify(status_changed=False)

    sig = f"{candidate.application_status}|{bool(candidate.is_approved)}|{bool(candidate.is_rejected)}|{_iso(candidate.updated_at)}|{_iso(candidate.details.updated_at) if candidate.details else ''}"
    key = f"candidate_status_sig_{candidate.id}"

    prev = session.get(key)
    changed = prev is not None and prev != sig
    session[key] = sig

    return jsonify(
        status_changed=changed,
        status=candidate.application_status,
        is_approved=bool(candidate.is_approved),
        is_rejected=bool(candidate.is_rejected),
        updated_at=_iso(candidate.updated_at),
    )

@app.route('/admin/api/user/<int:user_id>')
@admin_required
def api_admin_user(user_id):
    user = User.query.get_or_404(user_id)
    payload = {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": bool(user.is_active),
        "is_email_verified": bool(user.is_email_verified),
        "created_at": _iso(user.created_at),
        "last_login": _iso(user.last_login),
        "login_count": int(user.login_count or 0),
        "display_name": user.profile_name,
        "phone_number": user.phone_number,
        "voter_profile": None,
        "candidate_profile": None,
    }

    if user.voter_profile:
        v = user.voter_profile
        payload["voter_profile"] = {
            "id": v.id,
            "full_name": v.full_name,
            "first_name": v.first_name,
            "last_name": v.last_name,
            "cni_masked": v.cni_masked,
            "date_of_birth": _iso(v.date_of_birth),
            "age": int(v.age or 0),
            "place_of_birth": v.place_of_birth,
            "gender": v.gender,
            "is_eligible": bool(v.is_eligible),
            "phone_number": v.phone_number,
            "has_voted": bool(v.has_voted),
            "voted_at": _iso(v.voted_at),
            "eligibility_checked_at": _iso(v.eligibility_checked_at),
            "eligibility_reason": v.eligibility_reason,
        }

    if user.candidate_profile:
        c = user.candidate_profile
        payload["candidate_profile"] = {
            "id": c.id,
            "full_name": c.full_name,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "party_name": c.party_name,
            "party_acronym": c.party_acronym,
            "campaign_slogan": c.campaign_slogan,
            "is_approved": bool(c.is_approved),
            "is_eligible": bool(c.is_eligible),
            "is_rejected": bool(c.is_rejected),
            "age": int(c.age or 0),
            "place_of_birth": c.place_of_birth,
            "vote_count": int(c.vote_count or 0),
            "created_at": _iso(c.created_at),
            "approved_at": _iso(c.approved_at),
            "eligibility_checked_at": _iso(c.eligibility_checked_at),
            "eligibility_notes": c.eligibility_notes,
            "cni_masked": c.cni_masked,
            "political_program": c.political_program,
            "biography": c.biography,
        }

    return jsonify(payload)

@app.route('/admin/api/candidate/<int:candidate_id>')
@admin_required
def api_admin_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    return jsonify(
        id=candidate.id,
        full_name=candidate.full_name,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        age=int(candidate.age or 0),
        place_of_birth=candidate.place_of_birth,
        cni_masked=candidate.cni_masked,
        party_name=candidate.party_name,
        party_acronym=candidate.party_acronym,
        campaign_slogan=candidate.campaign_slogan,
        political_program=candidate.political_program,
        biography=candidate.biography,
        vote_count=int(candidate.vote_count or 0),
        created_at=_iso(candidate.created_at),
        approved_at=_iso(candidate.approved_at),
        eligibility_checked_at=_iso(candidate.eligibility_checked_at),
        is_approved=bool(candidate.is_approved),
        is_eligible=bool(candidate.is_eligible),
        eligibility_notes=candidate.eligibility_notes,
        is_rejected=bool(candidate.is_rejected),
        website_url=candidate.website_url,
        facebook_url=candidate.facebook_url,
        twitter_url=candidate.twitter_url,
        email=(candidate.user.email if candidate.user else None),
    )

@app.route('/admin/candidate/<int:candidate_id>/update', methods=['POST'])
@admin_required
def admin_update_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)

    candidate.first_name = (request.form.get("first_name") or candidate.first_name).strip()
    candidate.last_name = (request.form.get("last_name") or candidate.last_name).strip()
    candidate.party_name = (request.form.get("party_name") or "").strip() or None
    candidate.party_acronym = (request.form.get("party_acronym") or "").strip() or None
    candidate.campaign_slogan = request.form.get("campaign_slogan")
    candidate.political_program = request.form.get("political_program")

    candidate.is_eligible = bool(request.form.get("is_eligible"))
    candidate.eligibility_notes = request.form.get("eligibility_notes")
    candidate.eligibility_checked_at = datetime.utcnow()

    is_approved = bool(request.form.get("is_approved"))
    candidate.is_approved = is_approved
    if is_approved:
        candidate.is_rejected = False
        candidate.approved_at = candidate.approved_at or datetime.utcnow()
    else:
        candidate.approved_at = None

    db.session.commit()
    flash("Candidat mis à jour", "success")
    return redirect(url_for("admin_candidates"))

@app.route('/admin/api/candidates/bulk-action', methods=['POST'])
@admin_required
def api_admin_candidates_bulk_action():
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    candidate_ids = data.get("candidate_ids") or []

    try:
        candidate_ids = [int(x) for x in candidate_ids]
    except Exception:
        return jsonify(success=False, message="IDs invalides"), 400

    candidates = Candidate.query.filter(Candidate.id.in_(candidate_ids)).all() if candidate_ids else []

    if action == "approve":
        for c in candidates:
            c.is_approved = True
            c.is_rejected = False
            c.approved_at = c.approved_at or datetime.utcnow()
        db.session.commit()
        return jsonify(success=True)

    if action == "reject":
        for c in candidates:
            c.is_approved = False
            c.approved_at = None
            c.is_rejected = True
        db.session.commit()
        return jsonify(success=True)

    if action == "delete":
        for c in candidates:
            db.session.delete(c)
        db.session.commit()
        return jsonify(success=True)

    return jsonify(success=False, message="Action non supportée"), 400

# ========== GESTION D'ERREURS ==========
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html', page_title="Page non trouvée"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html', page_title="Accès interdit"), 403

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Server error: {e}")
    return render_template('errors/500.html', page_title="Erreur serveur"), 500

# ========== POINT D'ENTRÉE ==========
if __name__ == '__main__':
    # Création silencieuse des dossiers nécessaires
    os.makedirs(_public_upload_dir(), exist_ok=True)
    os.makedirs(_public_upload_dir('candidates'), exist_ok=True)
    os.makedirs(_public_upload_dir('avatars'), exist_ok=True)
    os.makedirs(_public_upload_dir('admins'), exist_ok=True)
    _ensure_archive_dir()
    
    # Initialisation silencieuse de la base de données
    try:
        init_database()
    except Exception as e:
        print(f"Erreur d'initialisation: {e}")
        exit(1)
    
    # Démarrage de l'application
    app.run(
        debug=True,
        host='127.0.0.1',
        port=5000,
        threaded=True
    )


