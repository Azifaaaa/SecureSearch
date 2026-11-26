"""
backend/cloud_storage.py — Storage adapter for SecureSearch Cloud

Provides two storage adapters that share a common interface:
  • LocalStorageAdapter  — saves encrypted objects to local filesystem
  • SupabaseStorageAdapter — saves to Supabase private Storage bucket

The active adapter is selected at startup based on the STORAGE_MODE
environment variable.

Object path format:
  Encrypted objects are stored using the random record UUID as the filename
  (with a .enc extension). Device names, locations and other sensitive
  identifiers are NEVER used in the object path.
"""
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when a storage operation fails."""


# ── Local Storage Adapter ───────────────────────────────────────────────────────

class LocalStorageAdapter:
    """
    Stores encrypted objects as files on the local filesystem.

    Directory structure:
        storage/encrypted_objects/<record_id>.enc

    This adapter works without any network access or cloud credentials.
    It is the default adapter in development and testing.
    """

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageAdapter: using path %s", self.base_path)

    def upload(self, record_id: str, ciphertext: bytes) -> str:
        """
        Save encrypted bytes to a file.

        Args:
            record_id:  UUID used as the filename (never the sensor ID).
            ciphertext: Raw encrypted bytes.

        Returns:
            object_path: Relative path to the stored file.

        Raises:
            StorageError: On write failure.
        """
        try:
            filename = f"{record_id}.enc"
            filepath = self.base_path / filename
            filepath.write_bytes(ciphertext)
            object_path = str(filepath)
            logger.debug("LocalStorage: saved %s (%d bytes)", filename, len(ciphertext))
            return object_path
        except OSError as exc:
            raise StorageError(f"Local write failed for {record_id}: {exc}") from exc

    def download(self, object_path: str) -> bytes:
        """
        Read encrypted bytes from a file.

        Returns:
            Raw encrypted bytes.

        Raises:
            StorageError: When the file is not found or cannot be read.
        """
        try:
            path = Path(object_path)
            if not path.exists():
                raise StorageError(f"Object not found: {object_path}")
            data = path.read_bytes()
            logger.debug("LocalStorage: loaded %s (%d bytes)", object_path, len(data))
            return data
        except OSError as exc:
            raise StorageError(f"Local read failed for {object_path}: {exc}") from exc

    def delete(self, object_path: str) -> None:
        """Delete an encrypted object from local storage."""
        try:
            path = Path(object_path)
            if path.exists():
                path.unlink()
                logger.debug("LocalStorage: deleted %s", object_path)
        except OSError as exc:
            raise StorageError(f"Local delete failed: {exc}") from exc

    def test_connection(self) -> dict:
        """Check that the storage directory is writable."""
        try:
            test_file = self.base_path / ".connectivity_test"
            test_file.write_bytes(b"test")
            test_file.unlink()
            return {"status": "ok", "mode": "local", "path": str(self.base_path)}
        except OSError as exc:
            return {"status": "error", "mode": "local", "detail": str(exc)}

    @property
    def mode(self):
        return "local"


# ── Supabase Storage Adapter ────────────────────────────────────────────────────

class SupabaseStorageAdapter:
    """
    Stores encrypted objects in a private Supabase Storage bucket.

    Prerequisites:
      1. Create a Supabase project.
      2. Create a private Storage bucket named 'secure-sensor-data'.
      3. Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env.

    The service-role key is used server-side only. It is NEVER sent to
    the browser or included in API responses.
    """

    def __init__(self, supabase_url: str, service_key: str, bucket: str):
        if not supabase_url or not service_key:
            raise StorageError(
                "Supabase credentials are missing. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env file, "
                "or switch to STORAGE_MODE=local."
            )
        try:
            from supabase import create_client
            self._client = create_client(supabase_url, service_key)
            self._bucket = bucket
            self._url = supabase_url
            logger.info("SupabaseStorageAdapter: connected to %s bucket '%s'",
                        supabase_url, bucket)
        except Exception as exc:
            raise StorageError(f"Failed to initialise Supabase client: {exc}") from exc

    def upload(self, record_id: str, ciphertext: bytes) -> str:
        """Upload encrypted bytes to the private Supabase bucket."""
        try:
            object_key = f"records/{record_id}.enc"
            # Supabase storage upload: upsert=False to prevent overwriting
            self._client.storage.from_(self._bucket).upload(
                path=object_key,
                file=ciphertext,
                file_options={"content-type": "application/octet-stream", "upsert": "false"},
            )
            logger.debug("Supabase: uploaded %s (%d bytes)", object_key, len(ciphertext))
            return object_key
        except Exception as exc:
            raise StorageError(f"Supabase upload failed for {record_id}: {exc}") from exc

    def download(self, object_path: str) -> bytes:
        """Download encrypted bytes from the private Supabase bucket."""
        try:
            response = self._client.storage.from_(self._bucket).download(object_path)
            if isinstance(response, (bytes, bytearray)):
                return bytes(response)
            raise StorageError(f"Unexpected response type from Supabase: {type(response)}")
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"Supabase download failed for {object_path}: {exc}") from exc

    def delete(self, object_path: str) -> None:
        """Delete an encrypted object from Supabase storage."""
        try:
            self._client.storage.from_(self._bucket).remove([object_path])
            logger.debug("Supabase: deleted %s", object_path)
        except Exception as exc:
            raise StorageError(f"Supabase delete failed: {exc}") from exc

    def test_connection(self) -> dict:
        """Test connectivity and bucket accessibility."""
        try:
            # List up to 1 object to verify access
            self._client.storage.from_(self._bucket).list(limit=1)
            return {"status": "ok", "mode": "supabase", "bucket": self._bucket,
                    "url": self._url}
        except Exception as exc:
            return {"status": "error", "mode": "supabase", "detail": str(exc)}

    @property
    def mode(self):
        return "supabase"


# ── Factory function ─────────────────────────────────────────────────────────────

def create_storage_adapter(app_config) -> "LocalStorageAdapter | SupabaseStorageAdapter":
    """
    Create and return the appropriate storage adapter based on STORAGE_MODE.

    If STORAGE_MODE=cloud but credentials are missing, raise StorageError
    with a helpful message. NEVER silently fall back to local mode.

    app_config can be either a Flask app.config dict-like object or a
    plain config class — both are accessed via [] / getattr fallback.
    """
    def _get(key, default=""):
        # Flask app.config is a dict subclass; config classes use attributes
        if hasattr(app_config, "__getitem__"):
            return app_config.get(key, default)
        return getattr(app_config, key, default)

    mode = _get("STORAGE_MODE", "local")

    if mode == "cloud":
        return SupabaseStorageAdapter(
            supabase_url=_get("SUPABASE_URL"),
            service_key=_get("SUPABASE_SERVICE_KEY"),
            bucket=_get("SUPABASE_BUCKET", "secure-sensor-data"),
        )
    elif mode == "local":
        return LocalStorageAdapter(base_path=_get("LOCAL_STORAGE_PATH", "storage/encrypted_objects"))
    else:
        raise StorageError(
            f"Unknown STORAGE_MODE: '{mode}'. Must be 'local' or 'cloud'."
        )


# ── Module-level adapter instance (set during app.py startup) ────────────────────
storage_adapter: Optional[LocalStorageAdapter] = None


def init_storage(app_config) -> None:
    """Initialise the global storage adapter. Called once from app.py."""
    global storage_adapter
    storage_adapter = create_storage_adapter(app_config)
