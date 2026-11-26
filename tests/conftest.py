"""
tests/conftest.py — pytest configuration

Sets up a temporary storage directory for tests and
ensures the backend/__init__.py and routes/__init__.py exist.
"""
import os
import base64

# Provide dummy keys before any test module imports crypto code
os.environ.setdefault("ENCRYPTION_KEY_B64", base64.b64encode(b"\xAA" * 32).decode())
os.environ.setdefault("SEARCH_KEY_B64",     base64.b64encode(b"\xBB" * 32).decode())
os.environ.setdefault("INTEGRITY_KEY_B64",  base64.b64encode(b"\xCC" * 32).decode())
os.environ.setdefault("FLASK_ENV",          "testing")
os.environ.setdefault("STORAGE_MODE",       "local")
os.environ.setdefault("LOCAL_STORAGE_PATH", "storage/test_encrypted_objects")
