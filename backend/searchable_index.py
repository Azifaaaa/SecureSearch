"""
backend/searchable_index.py — HMAC-SHA-256 searchable encryption index

This module implements searchable encryption using keyed HMAC tokens.

Design:
  For each indexed field, a deterministic HMAC-SHA-256 token is computed:
      token = HMAC(search_key, "field_name:normalized_value")

  The token is stored in the database index table alongside the record ID.
  To search for a value, the backend computes the same token and performs
  an exact-match lookup in the index table — no plaintext sensor data is
  ever stored in the index or searched.

Security properties:
  • An attacker who obtains only the database cannot reverse a token to
    its plaintext value (HMAC is a one-way keyed function).
  • Domain separation ("field_name:" prefix) prevents the same plaintext
    value from producing the same token in different fields.
  • The search_key is never sent to the browser and never stored in the DB.

Leakage (honest disclosure):
  • Equality-pattern leakage: repeated values produce repeated tokens.
    An observer of the index can count how many records share each token.
  • Search-pattern leakage: a passive observer can see which tokens are
    queried and when.
  These are known limitations of this construction (see leakage.html).

Numeric bucket indexing:
  Numeric fields (temperature, humidity) cannot be directly searched with
  HMAC equality tokens. Instead, the value is mapped to a fixed-width bucket
  and a token is generated for the bucket label.

  Example: temperature 30.7°C → bucket "30" → token HMAC(key, "temp_bucket:30")

  Range queries enumerate all relevant buckets, retrieve candidate record IDs,
  then decrypt each candidate and perform the exact numeric comparison.
  This two-phase approach ensures correctness: only records truly satisfying
  the range condition are returned.
"""
import hmac
import hashlib
import logging
from typing import List, Optional

from backend.key_manager import key_manager

logger = logging.getLogger(__name__)

# ── Domain-separation prefixes for each indexed field ──────────────────────────
# These must NEVER be changed after data has been stored.
FIELD_PREFIXES = {
    "device_id":    "device_id",
    "device_name":  "device_name",
    "location":     "location",
    "sensor_type":  "sensor_type",
    "status":       "status",
    "temp_bucket":  "temp_bucket",
    "humid_bucket": "humid_bucket",
}

# ── Bucket configuration ────────────────────────────────────────────────────────
TEMP_MIN = -20
TEMP_MAX = 80
TEMP_STEP = 1

HUMID_MIN = 0
HUMID_MAX = 100
HUMID_STEP = 1


class SearchIndexError(Exception):
    """Raised on invalid search parameters."""


# ── Token generation ────────────────────────────────────────────────────────────

def generate_token(field: str, value: str) -> str:
    """
    Generate a deterministic HMAC-SHA-256 search token for a field/value pair.

    The token is a 64-character lowercase hex string.

    Args:
        field: One of the keys in FIELD_PREFIXES.
        value: The plaintext field value (will be normalised).

    Returns:
        Hex string token (64 characters).

    Raises:
        SearchIndexError: If field is not a recognised index field.
    """
    if field not in FIELD_PREFIXES:
        raise SearchIndexError(
            f"Unknown index field: '{field}'. "
            f"Valid fields: {list(FIELD_PREFIXES.keys())}"
        )

    # Normalise: strip whitespace, lower-case, replace internal spaces with _
    normalised = _normalise(value)

    # Build the message with domain separation prefix
    prefix = FIELD_PREFIXES[field]
    message = f"{prefix}:{normalised}".encode("utf-8")

    # Compute HMAC-SHA-256 using the dedicated search key
    token = hmac.new(key_manager.search_key, message, hashlib.sha256).hexdigest()
    return token


def generate_tokens_for_record(device_id: str, device_name: str, location: str,
                                sensor_type: str, status: str,
                                temperature: float, humidity: float) -> List[dict]:
    """
    Generate all searchable tokens for a sensor record.

    Returns a list of dicts, each suitable for inserting into the
    SearchIndex table:
        {"field_type": str, "token": str}

    Temperature and humidity produce one exact token each plus one
    bucket token for numeric range searching.
    """
    tokens = []

    # Exact-match tokens for categorical fields
    for field, value in [
        ("device_id",   device_id),
        ("device_name", device_name),
        ("location",    location),
        ("sensor_type", sensor_type),
        ("status",      status),
    ]:
        tokens.append({
            "field_type": field,
            "token":      generate_token(field, value),
        })

    # Numeric bucket tokens for temperature
    temp_bucket = _temperature_bucket(temperature)
    if temp_bucket is not None:
        tokens.append({
            "field_type": "temp_bucket",
            "token":      generate_token("temp_bucket", str(temp_bucket)),
        })

    # Numeric bucket tokens for humidity
    humid_bucket = _humidity_bucket(humidity)
    if humid_bucket is not None:
        tokens.append({
            "field_type": "humid_bucket",
            "token":      generate_token("humid_bucket", str(humid_bucket)),
        })

    return tokens


# ── Bucket helpers ──────────────────────────────────────────────────────────────

def _temperature_bucket(temperature: float) -> Optional[int]:
    """
    Map a temperature value to its integer bucket lower bound.

    Returns None if the value is outside the supported range.
    Example: 30.7°C → 30, -5.1°C → -6 (floor to nearest integer step)
    """
    if temperature < TEMP_MIN or temperature > TEMP_MAX:
        logger.warning("Temperature %.1f°C is outside bucket range [%d, %d].",
                       temperature, TEMP_MIN, TEMP_MAX)
        return None
    return int(temperature // TEMP_STEP) * TEMP_STEP


def _humidity_bucket(humidity: float) -> Optional[int]:
    """Map a humidity value to its integer bucket lower bound."""
    if humidity < HUMID_MIN or humidity > HUMID_MAX:
        logger.warning("Humidity %.1f%% is outside bucket range [%d, %d].",
                       humidity, HUMID_MIN, HUMID_MAX)
        return None
    return int(humidity // HUMID_STEP) * HUMID_STEP


def _normalise(value: str) -> str:
    """Normalise a string value before token generation."""
    return value.strip().lower().replace(" ", "_")


# ── Range query helpers ─────────────────────────────────────────────────────────

def temperature_range_tokens(min_temp: Optional[float], max_temp: Optional[float]) -> List[str]:
    """
    Return a list of HMAC tokens covering all temperature buckets in [min_temp, max_temp].

    Buckets that fall entirely outside the query range are excluded.
    The caller must still perform an exact numeric comparison after decryption.

    Args:
        min_temp: Lower bound (inclusive), or None for unbounded lower end.
        max_temp: Upper bound (inclusive), or None for unbounded upper end.

    Returns:
        List of token hex strings.
    """
    lo = TEMP_MIN if min_temp is None else max(TEMP_MIN, int(min_temp // TEMP_STEP) * TEMP_STEP)
    hi = TEMP_MAX if max_temp is None else min(TEMP_MAX, int(max_temp // TEMP_STEP) * TEMP_STEP)

    if lo > hi:
        return []

    tokens = []
    bucket = lo
    while bucket <= hi:
        tokens.append(generate_token("temp_bucket", str(bucket)))
        bucket += TEMP_STEP
    return tokens


def humidity_range_tokens(min_humid: Optional[float], max_humid: Optional[float]) -> List[str]:
    """Return tokens covering humidity buckets in [min_humid, max_humid]."""
    lo = HUMID_MIN if min_humid is None else max(HUMID_MIN, int(min_humid // HUMID_STEP) * HUMID_STEP)
    hi = HUMID_MAX if max_humid is None else min(HUMID_MAX, int(max_humid // HUMID_STEP) * HUMID_STEP)

    if lo > hi:
        return []

    tokens = []
    bucket = lo
    while bucket <= hi:
        tokens.append(generate_token("humid_bucket", str(bucket)))
        bucket += HUMID_STEP
    return tokens


def exact_search_token(field: str, value: str) -> str:
    """Generate the token for an exact-match search query (called at query time)."""
    return generate_token(field, value)
