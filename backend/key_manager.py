"""
backend/key_manager.py — Secure key management for SecureSearch Cloud

This module loads cryptographic keys from environment variables and
provides them to other backend modules.

IMPORTANT:
  - Keys are base64-encoded 32-byte (256-bit) random values.
  - Generate keys once using:  python scripts/generate_keys.py
  - Store keys in .env (never in this file, never in the database).
  - If keys are missing and encrypted data already exists, the
    application will raise an error rather than silently re-generate
    keys (which would make all stored data unreadable).
"""
import os
import base64
import secrets
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


class KeyManagerError(Exception):
    """Raised when key loading or validation fails."""


def _decode_b64_key(env_var_name: str, required: bool = True) -> bytes:
    """
    Decode a base64-encoded key from an environment variable.

    Args:
        env_var_name: Name of the environment variable.
        required:     If True, raise an error when the variable is missing.

    Returns:
        32-byte key as bytes.

    Raises:
        KeyManagerError: When the variable is missing, empty or not 32 bytes.
    """
    raw = os.environ.get(env_var_name, "").strip()
    if not raw:
        if required:
            raise KeyManagerError(
                f"Missing required environment variable: {env_var_name}\n"
                "Run  python scripts/generate_keys.py  to create your keys, "
                "then copy the output into your .env file."
            )
        return b""

    try:
        key_bytes = base64.b64decode(raw)
    except Exception as exc:
        raise KeyManagerError(
            f"{env_var_name} is not valid base64: {exc}"
        ) from exc

    if len(key_bytes) != 32:
        raise KeyManagerError(
            f"{env_var_name} must decode to exactly 32 bytes "
            f"(got {len(key_bytes)} bytes). Re-generate your keys."
        )
    return key_bytes


class KeyManager:
    """
    Loads and provides access to the three application-level cryptographic keys.

    Keys loaded:
      encryption_key  — AES-256-GCM encryption/decryption of sensor records.
      search_key      — HMAC-SHA-256 search token generation.
      integrity_key   — HMAC-SHA-256 integrity verification of stored objects.

    Key separation guarantees:
      Each key is used for exactly one cryptographic purpose.
      Using a different key for each domain prevents cross-context attacks.
    """

    # Singleton instance (populated once during app startup)
    _instance = None

    def __init__(self):
        self._encryption_key: bytes = b""
        self._search_key: bytes = b""
        self._integrity_key: bytes = b""
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "KeyManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_keys(self, testing: bool = False) -> None:
        """
        Load all keys from environment variables.

        Call this once during application startup (app.py).
        In testing mode the keys may be dummy values.
        """
        try:
            self._encryption_key = _decode_b64_key("ENCRYPTION_KEY_B64")
            self._search_key = _decode_b64_key("SEARCH_KEY_B64")
            self._integrity_key = _decode_b64_key("INTEGRITY_KEY_B64")
            self._loaded = True
            logger.info("Cryptographic keys loaded successfully.")
        except KeyManagerError:
            if testing:
                # During tests, fill with deterministic dummy bytes
                self._encryption_key = b"\x00" * 32
                self._search_key = b"\x01" * 32
                self._integrity_key = b"\x02" * 32
                self._loaded = True
                logger.warning("Using DUMMY TEST KEYS — do not use in production.")
            else:
                raise

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise KeyManagerError(
                "Keys have not been loaded. Call key_manager.load_keys() first."
            )

    @property
    def encryption_key(self) -> bytes:
        self._require_loaded()
        return self._encryption_key

    @property
    def search_key(self) -> bytes:
        self._require_loaded()
        return self._search_key

    @property
    def integrity_key(self) -> bytes:
        self._require_loaded()
        return self._integrity_key


# Module-level convenience accessor
key_manager = KeyManager.get_instance()


def generate_new_keys() -> dict:
    """
    Generate three new cryptographically secure 256-bit keys.

    Returns a dict with base64-encoded values ready to be placed in .env.

    This function is used only by scripts/generate_keys.py.
    It must NEVER be called automatically on application startup.
    """
    return {
        "ENCRYPTION_KEY_B64": base64.b64encode(secrets.token_bytes(32)).decode(),
        "SEARCH_KEY_B64": base64.b64encode(secrets.token_bytes(32)).decode(),
        "INTEGRITY_KEY_B64": base64.b64encode(secrets.token_bytes(32)).decode(),
        "FLASK_SECRET_KEY": secrets.token_hex(64),
    }
