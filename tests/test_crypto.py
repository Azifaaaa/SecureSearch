"""
tests/test_crypto.py — Tests for AES-256-GCM encryption engine

Verifies:
  - Encrypt / decrypt round-trip produces original plaintext
  - Different nonces are generated for each encryption call
  - Repeated encryption of the same plaintext produces different ciphertexts
  - Modified ciphertext is rejected with DecryptionError
  - Invalid authentication tag is rejected
  - Wrong AAD (record_id mismatch) is rejected
  - Base64 convenience wrappers work correctly
"""
import os
import base64
import pytest

# Set dummy keys before importing crypto modules
os.environ["ENCRYPTION_KEY_B64"] = base64.b64encode(b"\xAA" * 32).decode()
os.environ["SEARCH_KEY_B64"]     = base64.b64encode(b"\xBB" * 32).decode()
os.environ["INTEGRITY_KEY_B64"]  = base64.b64encode(b"\xCC" * 32).decode()

from backend.key_manager import key_manager, KeyManagerError
key_manager.load_keys(testing=True)

from backend.crypto_engine import (
    encrypt_record, decrypt_record, encrypt_to_b64, decrypt_from_b64,
    EncryptionError, DecryptionError, NONCE_LENGTH_BYTES,
)


SAMPLE_RECORD = {
    "device_id":   "SENSOR_001",
    "device_name": "Laboratory A Sensor",
    "location":    "Laboratory A",
    "sensor_type": "temperature_humidity",
    "temperature": 25.3,
    "humidity":    55.1,
    "status":      "NORMAL",
    "timestamp":   "2024-01-01T12:00:00+00:00",
    "simulated":   True,
}

SAMPLE_ID = "test-record-id-001"


class TestAESGCMBasic:

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt then decrypt should return original record."""
        ciphertext, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        decrypted = decrypt_record(ciphertext, nonce, SAMPLE_ID)
        assert decrypted["device_id"] == SAMPLE_RECORD["device_id"]
        assert decrypted["temperature"] == SAMPLE_RECORD["temperature"]
        assert decrypted["location"] == SAMPLE_RECORD["location"]

    def test_nonce_length(self):
        """Nonce must be exactly 12 bytes (96 bits) for AES-GCM."""
        _, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        assert len(nonce) == NONCE_LENGTH_BYTES
        assert len(nonce) == 12

    def test_fresh_nonce_each_call(self):
        """Each encryption call must produce a different nonce."""
        _, nonce1 = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        _, nonce2 = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        assert nonce1 != nonce2  # Probabilistic — will fail with overwhelming probability if nonces are reused

    def test_different_ciphertext_same_plaintext(self):
        """Same plaintext encrypted twice must produce different ciphertexts."""
        ct1, _ = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        ct2, _ = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        assert ct1 != ct2

    def test_ciphertext_longer_than_plaintext(self):
        """Ciphertext should include the 16-byte GCM authentication tag."""
        import json
        plaintext_len = len(json.dumps(SAMPLE_RECORD, default=str, sort_keys=True).encode())
        ct, _ = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        # AES-GCM ciphertext = plaintext_len + 16 (auth tag)
        assert len(ct) == plaintext_len + 16


class TestAESGCMTamperDetection:

    def test_modified_ciphertext_rejected(self):
        """Bit-flip in ciphertext must cause DecryptionError."""
        ct, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        # Flip the first byte of the ciphertext (before the auth tag)
        tampered = bytearray(ct)
        tampered[0] ^= 0xFF
        with pytest.raises(DecryptionError):
            decrypt_record(bytes(tampered), nonce, SAMPLE_ID)

    def test_modified_auth_tag_rejected(self):
        """Bit-flip in the GCM authentication tag must cause DecryptionError."""
        ct, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        # Flip the last byte (the authentication tag is at the end)
        tampered = bytearray(ct)
        tampered[-1] ^= 0xFF
        with pytest.raises(DecryptionError):
            decrypt_record(bytes(tampered), nonce, SAMPLE_ID)

    def test_wrong_record_id_rejected(self):
        """Using a different record_id (AAD) must fail authentication."""
        ct, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        with pytest.raises(DecryptionError):
            decrypt_record(ct, nonce, "wrong-record-id")

    def test_wrong_nonce_rejected(self):
        """Using a different nonce must fail authentication."""
        ct, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        wrong_nonce = os.urandom(12)
        with pytest.raises(DecryptionError):
            decrypt_record(ct, wrong_nonce, SAMPLE_ID)

    def test_truncated_ciphertext_rejected(self):
        """Truncated ciphertext must fail."""
        ct, nonce = encrypt_record(SAMPLE_RECORD, SAMPLE_ID)
        with pytest.raises((DecryptionError, Exception)):
            decrypt_record(ct[:8], nonce, SAMPLE_ID)


class TestBase64Wrappers:

    def test_b64_roundtrip(self):
        """Base64 wrapper round-trip must recover original record."""
        ct_b64, nonce_b64 = encrypt_to_b64(SAMPLE_RECORD, SAMPLE_ID)
        decrypted = decrypt_from_b64(ct_b64, nonce_b64, SAMPLE_ID)
        assert decrypted["device_id"] == SAMPLE_RECORD["device_id"]
        assert decrypted["humidity"]  == SAMPLE_RECORD["humidity"]

    def test_b64_values_are_strings(self):
        """encrypt_to_b64 must return str, not bytes."""
        ct_b64, nonce_b64 = encrypt_to_b64(SAMPLE_RECORD, SAMPLE_ID)
        assert isinstance(ct_b64, str)
        assert isinstance(nonce_b64, str)
