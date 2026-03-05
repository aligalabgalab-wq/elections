# config.py
import os
from datetime import timedelta
from dotenv import load_dotenv

# Charger un `.env` local (au même niveau que ce fichier) + fallback sur le CWD
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv()

class Config:
    # Sécurité
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Base de données MySQL
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '3306')
    DB_NAME = os.environ.get('DB_NAME', 'election_simulation')
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    
    SQLALCHEMY_DATABASE_URI = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 299,
        'pool_pre_ping': True,
    }
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'static/uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'webp'}
    
    # Application
    MIN_VOTER_AGE = int(os.environ.get('MIN_VOTER_AGE', 18))
    MIN_CANDIDATE_AGE = int(os.environ.get('MIN_CANDIDATE_AGE', 40))
    VOTE_LIMIT_PER_USER = 1
    MAX_LOGIN_ATTEMPTS = 3
    LOCKOUT_TIME = 900
    # Branding (utilisé dans la barre de navigation, footer, emails...)
    APP_NAME = os.environ.get("APP_NAME", "Élection Nationale")
    APP_TAGLINE = os.environ.get("APP_TAGLINE", "Simulation • Djibouti")
    ELECTION_NAME = os.environ.get("ELECTION_NAME", f"{APP_NAME} 2025")

    # Liens (optionnels) — si vides, on n'affiche pas les icônes sociales.
    SOCIAL_FACEBOOK_URL = os.environ.get("SOCIAL_FACEBOOK_URL", "").strip()
    SOCIAL_TWITTER_URL = os.environ.get("SOCIAL_TWITTER_URL", "").strip()
    SOCIAL_LINKEDIN_URL = os.environ.get("SOCIAL_LINKEDIN_URL", "").strip()

    # Email / Contact (SMTP)
    # Pour activer l'envoi depuis /contact, configurez ces variables dans un fichier .env ou dans l'environnement.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0").strip().lower() in {"1", "true", "yes", "on"}
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip().lower() in {"1", "true", "yes", "on"}
    SMTP_SENDER = os.environ.get("SMTP_SENDER", "")  # optionnel (sinon SMTP_USERNAME)
    # Ne pas exposer d'email perso par défaut : définissez CONTACT_RECIPIENT dans `.env`.
    CONTACT_RECIPIENT = os.environ.get("CONTACT_RECIPIENT", "")
    
    # Admin
    # Les identifiants d'administrateur ne sont plus configurés statiquement
    # via les variables d'environnement. Le compte est créé dynamiquement via
    # l'interface d'inscription (une seule création autorisée), donc il n'y a
    # plus de valeur par défaut ni de création automatique au démarrage.
    # ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
    # ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
    # ADMIN_AUTO_CREATE = False  # géré depuis le code plutôt qu'ici
    
    # Chemins
    STATIC_FOLDER = 'static'
    TEMPLATES_FOLDER = 'templates'

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True

class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
