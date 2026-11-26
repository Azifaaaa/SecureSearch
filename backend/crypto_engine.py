"""
backend/crypto_engine.py — AES-256-GCM encryption engine for SecureSearch Cloud

This module implements the actual cryptographic operations:
  • AES-256-GCM encryption and decryption of complete sensor records.
  • Fresh nonce generation for every encryption operation.
  • Associated Authenticated Data (AAD) binding metadata to ciphertext.
  • Authentication tag verification on decryption.

Why AES-256-GCM?
  AES-GCM provides both CONFIDENTIALITY and AUTHENTICITY in a single
  operation. The 128-bit authentication tag ensures that any modification
  to the ciphertext or its associated data is detected before decryption.

Nonce usage policy:
  A cryptographically secure random 96-bit nonce is generated for every
  single encryption call. With a 96-bit nonce space, random collision
  probability is negligible for practical dataset sizes (< 2^32 records).
  Nonces are stored in the database alongside the encrypted record so
  that decryption is always possible.

Key isolation:
  This module only uses the ENCRYPTION_KEY. The SEARCH_KEY and
  INTEGRITY_KEY are never passed to or used by this module.
"""
import os
import json
import base64
import logging
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from backend.key_manager import key_manager

logger = logging.getLogger(__name__)

# Nonce length for AES-256-GCM: 96 bits = 12 bytes (recommended by NIST)
NONCE_LENGTH_BYTES = 12


class EncryptionError(Exception):
    """Raised when encryption fails."""


class DecryptionError(Exception):
    """Raised when decryption or authentication verification fails."""


def encrypt_record(record_dict: dict, record_id: str, version: int = 1) -> Tuple[bytes, bytes]:
    """
    Encrypt a complete sensor record using AES-256-GCM.

    The entire record dictionary is serialised to JSON and then encrypted.
    The record_id is included as Associated Authenticated Data (AAD) so
    that the ciphertext is cryptographically bound to this specific record.
    Swapping ciphertext between records will cause authentication failure.

    Args:
        record_dict: Sensor reading as a plain Python dictionary.
        record_id:   Unique record identifier (used as AAD).
        version:     Encryption version integer for future key rotation.

    Returns:
        (ciphertext_with_tag, nonce)
        The cryptography library appends the 16-byte GCM tag to the
        end of the ciphertext automatically.

    Raises:
        EncryptionError: On any failure.
    """
    try:
        # Serialise record to canonical JSON bytes
        plaintext = json.dumps(record_dict, default=str, sort_keys=True).encode("utf-8")

        # Build AAD: bind record_id and encryption version to this ciphertext.
        # If either value is changed in the database, decryption will fail.
        aad = _build_aad(record_id, version)

        # Generate a fresh cryptographically secure 96-bit nonce
        nonce = os.urandom(NONCE_LENGTH_BYTES)

        # AES-256-GCM: the library appends the 16-byte authentication tag
        aesgcm = AESGCM(key_manager.encryption_key)
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, aad)

        return ciphertext_with_tag, nonce

    except Exception as exc:
        raise EncryptionError(f"Encryption failed: {exc}") from exc


def decrypt_record(ciphertext_with_tag: bytes, nonce: bytes, record_id: str, version: int = 1) -> dict:
    """
    Decrypt and authenticate a sensor record using AES-256-GCM.

    Args:
        ciphertext_with_tag: Encrypted bytes including the 16-byte GCM tag.
        nonce:               96-bit nonce used during encryption (12 bytes).
        record_id:           Record identifier used as AAD during encryption.
        version:             Encryption version integer.

    Returns:
        Decrypted record as a Python dictionary.

    Raises:
        DecryptionError: When the authentication tag is invalid (tampered
                         ciphertext, wrong key, wrong AAD) or on any other
                         decryption failure.
    """
    try:
        aad = _build_aad(record_id, version)

        aesgcm = AESGCM(key_manager.encryption_key)
        # InvalidTag is raised automatically if authentication fails
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, aad)

        record = json.loads(plaintext.decode("utf-8"))
        return record

    except InvalidTag:
        raise DecryptionError(
            "Authentication tag verification failed. "
            "The ciphertext may have been tampered with, or the wrong key/nonce was used."
        )
    except Exception as exc:
        raise DecryptionError(f"Decryption failed: {exc}") from exc


def encrypt_to_b64(record_dict: dict, record_id: str, version: int = 1) -> Tuple[str, str]:
    """
    Convenience wrapper: encrypt and return base64-encoded strings suitable
    for JSON storage in the database.

    Returns:
        (ciphertext_b64, nonce_b64)
    """
    ciphertext, nonce = encrypt_record(record_dict, record_id, version)
    return (
        base64.b64encode(ciphertext).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )


def decrypt_from_b64(ciphertext_b64: str, nonce_b64: str, record_id: str, version: int = 1) -> dict:
    """
    Convenience wrapper: accept base64-encoded inputs from the database and
    return the decrypted record dictionary.
    """
    ciphertext = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    return decrypt_record(ciphertext, nonce, record_id, version)


def _build_aad(record_id: str, version: int) -> bytes:
    """
    Build the Associated Authenticated Data (AAD) string.

    The AAD cryptographically binds the ciphertext to this specific
    record_id and encryption version. It is not encrypted but IS
    authenticated: any modification to these fields will cause
    authentication failure during decryption.
    """
    aad_string = f"securesearch:v{version}:record:{record_id}"
    return aad_string.encode("utf-8")
