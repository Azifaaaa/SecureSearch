"""
backend/integrity.py — Integrity verification for encrypted sensor records

Three levels of integrity protection are used in SecureSearch Cloud:

1. AES-GCM Authentication Tag (per-record, automatic)
   Every encrypted record includes a 128-bit GCM authentication tag.
   Any modification to the ciphertext — even a single bit — causes
   decryption to fail with an InvalidTag error.
   This is the strongest and most granular protection.

2. SHA-256 Content Digest (per-object, stored in DB)
   A SHA-256 hash of the raw ciphertext bytes is stored in the database
   when the object is uploaded. Before decryption the current hash of
   the retrieved object is compared to the stored reference.
   LIMITATION: A plain SHA-256 hash does NOT protect against an attacker
   who can modify both the stored object AND the hash reference in the
   database. It detects accidental corruption, not a targeted attack.

3. HMAC-SHA-256 Integrity Reference (per-object, keyed)
   An HMAC over the ciphertext using the INTEGRITY_KEY is stored in the DB.
   This is keyed, so an attacker who cannot access the integrity key cannot
   forge a valid HMAC even if they modify the object and the stored hash.
   This provides stronger tamper-evidence than plain SHA-256.
   It does NOT replace encryption — it supplements it.

Summary:
   • For confidentiality:  AES-256-GCM encryption.
   • For tamper detection: GCM authentication tag (automatic) + HMAC reference.
   • For accidental corruption detection: SHA-256 digest comparison.
"""
import hmac
import hashlib
import base64
import logging

from backend.key_manager import key_manager

logger = logging.getLogger(__name__)


def compute_sha256(data: bytes) -> str:
    """
    Compute a hex-encoded SHA-256 digest of raw bytes.

    Used to detect accidental storage corruption.
    """
    return hashlib.sha256(data).hexdigest()


def compute_hmac_reference(record_id: str, ciphertext: bytes) -> str:
    """
    Compute a keyed HMAC-SHA-256 integrity reference for a ciphertext object.

    The HMAC covers both the record_id and the ciphertext, binding the
    integrity reference to this specific record. Swapping ciphertexts
    between records will fail verification.

    Args:
        record_id:  Unique identifier for this record.
        ciphertext: Raw encrypted bytes (including GCM tag).

    Returns:
        Hex-encoded HMAC-SHA-256 (64 hex chars).
    """
    # Build a message that includes the record_id as context
    message = f"integrity:{record_id}:".encode("utf-8") + ciphertext
    return hmac.new(key_manager.integrity_key, message, hashlib.sha256).hexdigest()


def verify_integrity(record_id: str, ciphertext: bytes,
                     stored_sha256: str, stored_hmac: str) -> dict:
    """
    Verify the integrity of a retrieved encrypted object.

    Performs both SHA-256 comparison and HMAC verification.

    Returns:
        {
            "sha256_match": bool,
            "hmac_match":   bool,
            "overall":      bool,
            "detail":       str    (human-readable explanation)
        }
    """
    result = {
        "sha256_match": False,
        "hmac_match":   False,
        "overall":      False,
        "detail":       "",
    }

    # ── SHA-256 check ──────────────────────────────────────────────────────
    current_sha256 = compute_sha256(ciphertext)
    result["sha256_match"] = hmac.compare_digest(current_sha256, stored_sha256)

    # ── HMAC check ─────────────────────────────────────────────────────────
    expected_hmac = compute_hmac_reference(record_id, ciphertext)
    result["hmac_match"] = hmac.compare_digest(expected_hmac, stored_hmac)

    # ── Overall result ─────────────────────────────────────────────────────
    result["overall"] = result["sha256_match"] and result["hmac_match"]

    if result["overall"]:
        result["detail"] = (
            "Integrity verified: SHA-256 digest and HMAC reference both match. "
            "No tampering detected."
        )
    elif not result["sha256_match"] and not result["hmac_match"]:
        result["detail"] = (
            "INTEGRITY FAILURE: Both SHA-256 and HMAC checks failed. "
            "The stored object has likely been modified."
        )
    elif not result["sha256_match"]:
        result["detail"] = (
            "INTEGRITY WARNING: SHA-256 mismatch but HMAC matches. "
            "Possible partial corruption."
        )
    else:
        result["detail"] = (
            "INTEGRITY FAILURE: SHA-256 matches but HMAC verification failed. "
            "Possible key mismatch or database tampering."
        )

    return result


def compute_integrity_references(record_id: str, ciphertext: bytes) -> dict:
    """
    Compute both the SHA-256 and HMAC integrity references for storage.

    Returns:
        {
            "sha256":      hex string,
            "hmac_ref":    hex string,
        }
    """
    return {
        "sha256":   compute_sha256(ciphertext),
        "hmac_ref": compute_hmac_reference(record_id, ciphertext),
    }
