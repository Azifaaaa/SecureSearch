"""
config.py — Application configuration for SecureSearch Cloud
Reads settings from environment variables or .env file.
"""
import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()


class Config:
    """Base configuration shared by all modes."""

    # Flask core
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "CHANGE_ME_before_production")
    DEBUG = False
    TESTING = False

    # Request limits
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Session cookie security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set to True in production with HTTPS
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

    # Storage mode: "local" or "cloud"
    STORAGE_MODE = os.environ.get("STORAGE_MODE", "local").lower()

    # ── Cryptographic keys ──────────────────────────────────────────────────
    # These must be base64-encoded 32-byte (256-bit) random values.
    # Generate with: python scripts/generate_keys.py
    # NEVER commit real key values to Git.
    ENCRYPTION_KEY_B64 = os.environ.get("ENCRYPTION_KEY_B64", "")
    SEARCH_KEY_B64 = os.environ.get("SEARCH_KEY_B64", "")
    INTEGRITY_KEY_B64 = os.environ.get("INTEGRITY_KEY_B64", "")

    # ── Local mode ──────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///securesearch_local.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    LOCAL_STORAGE_PATH = os.environ.get("LOCAL_STORAGE_PATH", "storage/encrypted_objects")

    # ── Supabase / Cloud mode ───────────────────────────────────────────────
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
    SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "secure-sensor-data")

    # PostgreSQL connection for Supabase (used only in cloud mode)
    SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "")

    # ── Simulator ───────────────────────────────────────────────────────────
    SIMULATOR_DEFAULT_INTERVAL = int(os.environ.get("SIMULATOR_DEFAULT_INTERVAL", "5"))

    # ── Pagination ──────────────────────────────────────────────────────────
    RECORDS_PER_PAGE = int(os.environ.get("RECORDS_PER_PAGE", "20"))
    SEARCH_RESULTS_LIMIT = int(os.environ.get("SEARCH_RESULTS_LIMIT", "100"))

    # ── Numeric bucket configuration ────────────────────────────────────────
    TEMP_BUCKET_MIN = -20      # °C
    TEMP_BUCKET_MAX = 80       # °C
    TEMP_BUCKET_WIDTH = 1      # °C per bucket

    HUMIDITY_BUCKET_MIN = 0    # %
    HUMIDITY_BUCKET_MAX = 100  # %
    HUMIDITY_BUCKET_WIDTH = 1  # % per bucket

    # Key version for future rotation support
    ENCRYPTION_VERSION = int(os.environ.get("ENCRYPTION_VERSION", "1"))


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    # Use a temporary in-memory SQLite for tests
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    LOCAL_STORAGE_PATH = "storage/test_encrypted_objects"
    # Provide dummy keys so key_manager doesn't fail during tests
    ENCRYPTION_KEY_B64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    SEARCH_KEY_B64 = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
    INTEGRITY_KEY_B64 = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC="
    # Force local mode in tests
    STORAGE_MODE = "local"
    WTF_CSRF_ENABLED = False


# Map name → class
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
