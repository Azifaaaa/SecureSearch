"""
tests/test_cloud_storage.py — Tests for local and cloud storage adapters

Verifies:
  - LocalStorageAdapter upload/download/delete works
  - LocalStorageAdapter test_connection reports ok
  - SupabaseStorageAdapter rejects missing credentials gracefully
  - Upload/download round-trip preserves bytes exactly
"""
import os
import base64
import tempfile
import pytest
from pathlib import Path

os.environ["ENCRYPTION_KEY_B64"] = base64.b64encode(b"\xAA" * 32).decode()
os.environ["SEARCH_KEY_B64"]     = base64.b64encode(b"\xBB" * 32).decode()
os.environ["INTEGRITY_KEY_B64"]  = base64.b64encode(b"\xCC" * 32).decode()

from backend.cloud_storage import LocalStorageAdapter, StorageError


@pytest.fixture
def local_adapter(tmp_path):
    """Create a LocalStorageAdapter backed by a temporary directory."""
    return LocalStorageAdapter(base_path=str(tmp_path))


class TestLocalStorageAdapter:

    def test_upload_creates_file(self, local_adapter, tmp_path):
        """Uploading bytes should create an .enc file."""
        data = b"encrypted_test_bytes_1234"
        path = local_adapter.upload("test-record-001", data)
        assert Path(path).exists()
        assert path.endswith(".enc")

    def test_download_roundtrip(self, local_adapter):
        """Uploaded bytes must be recovered exactly after download."""
        data = os.urandom(128)
        path = local_adapter.upload("test-record-002", data)
        recovered = local_adapter.download(path)
        assert recovered == data

    def test_delete_removes_file(self, local_adapter):
        """Deleting an uploaded object should remove the file."""
        data = b"delete_me"
        path = local_adapter.upload("test-record-003", data)
        local_adapter.delete(path)
        assert not Path(path).exists()

    def test_download_missing_file_raises(self, local_adapter, tmp_path):
        """Downloading a non-existent file should raise StorageError."""
        with pytest.raises(StorageError):
            local_adapter.download(str(tmp_path / "nonexistent.enc"))

    def test_test_connection_ok(self, local_adapter):
        """test_connection should return status=ok when directory is writable."""
        result = local_adapter.test_connection()
        assert result["status"] == "ok"
        assert result["mode"] == "local"

    def test_mode_property(self, local_adapter):
        """mode property must return 'local'."""
        assert local_adapter.mode == "local"

    def test_different_records_separate_files(self, local_adapter, tmp_path):
        """Two different record IDs should produce separate files."""
        data1 = b"record_one_ciphertext"
        data2 = b"record_two_ciphertext"
        path1 = local_adapter.upload("record-aaa", data1)
        path2 = local_adapter.upload("record-bbb", data2)
        assert path1 != path2
        assert local_adapter.download(path1) == data1
        assert local_adapter.download(path2) == data2


class TestSupabaseAdapterMissingCredentials:

    def test_missing_url_raises(self):
        """SupabaseStorageAdapter should raise StorageError when URL is missing."""
        from backend.cloud_storage import SupabaseStorageAdapter
        with pytest.raises(StorageError):
            SupabaseStorageAdapter(supabase_url="", service_key="", bucket="test")

    def test_missing_key_raises(self):
        """SupabaseStorageAdapter should raise StorageError when key is missing."""
        from backend.cloud_storage import SupabaseStorageAdapter
        with pytest.raises(StorageError):
            SupabaseStorageAdapter(supabase_url="https://example.supabase.co",
                                   service_key="", bucket="test")
