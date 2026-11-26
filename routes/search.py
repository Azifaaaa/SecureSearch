"""
routes/search.py — Searchable encryption query endpoints

POST /api/search/exact    — Exact-match search using HMAC token index
POST /api/search/range    — Numeric range search using bucket tokens
POST /api/search/combined — Combined exact + range search
GET  /api/search/history  — Search history for the current user

All searches work in two phases:
  Phase 1 — Token index lookup (no decryption, no plaintext in DB)
  Phase 2 — Retrieve ciphertext, decrypt, exact numeric verification
"""
import base64
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, session

from backend.database import db
from backend.models import User, SensorRecord, SearchIndex, NumericBucketIndex, SearchHistory
from backend.crypto_engine import decrypt_from_b64, DecryptionError
from backend.searchable_index import (
    exact_search_token,
    temperature_range_tokens,
    humidity_range_tokens,
    FIELD_PREFIXES,
)
from backend.cloud_storage import storage_adapter
from config import get_config
from routes._uuid_helpers import get_current_user, get_sensor_record

logger = logging.getLogger(__name__)
search_bp = Blueprint("search", __name__)

cfg = get_config()
RESULTS_LIMIT = cfg.SEARCH_RESULTS_LIMIT


def _require_auth():
    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


def _record_ids_by_token(field: str, token: str) -> list:
    """Return record IDs matching a single exact-match token."""
    rows = SearchIndex.query.filter_by(field_type=field, token=token).all()
    return [row.record_id for row in rows]


def _record_ids_by_bucket_tokens(sensor_type: str, tokens: list) -> list:
    """Return record IDs matching any of the given bucket tokens."""
    if not tokens:
        return []
    rows = NumericBucketIndex.query.filter(
        NumericBucketIndex.sensor_type == sensor_type,
        NumericBucketIndex.bucket_token.in_(tokens),
    ).all()
    return list({row.record_id for row in rows})


def _fetch_and_decrypt(record_id: str) -> "dict | None":
    """Retrieve and decrypt a record. Returns None on failure."""
    db_record = db.session.get(SensorRecord, record_id)
    if not db_record:
        return None
    try:
        ciphertext = storage_adapter.download(db_record.object_path)
        return decrypt_from_b64(
            base64.b64encode(ciphertext).decode(),
            db_record.nonce_b64,
            record_id,
            db_record.encryption_version,
        )
    except (DecryptionError, Exception) as exc:
        logger.error("Decryption failed for record %s: %s", record_id, exc)
        return None


def _decrypted_to_result(record_id, decrypted: dict, db_record: SensorRecord) -> dict:
    """Format a decrypted record for API response."""
    return {
        "record_id":   str(record_id),   # uuid.UUID → str for JSON
        "device_id":   decrypted.get("device_id"),
        "device_name": decrypted.get("device_name"),
        "location":    decrypted.get("location"),
        "sensor_type": decrypted.get("sensor_type"),
        "temperature": decrypted.get("temperature"),
        "humidity":    decrypted.get("humidity"),
        "status":      decrypted.get("status"),
        "timestamp":   decrypted.get("timestamp"),
        "simulated":   decrypted.get("simulated", True),
        "created_at":  db_record.created_at.isoformat(),
        "integrity":   "verified",
    }


def _log_search(user_id: str, search_type: str, description: str,
                result_count: int, candidate_count: int):
    """Persist a search history entry."""
    history = SearchHistory(
        user_id=user_id,
        search_type=search_type,
        search_description=description[:300],
        result_count=result_count,
        candidate_count=candidate_count,
    )
    db.session.add(history)
    db.session.commit()


# ── Exact search ────────────────────────────────────────────────────────────────

@search_bp.route("/api/search/exact", methods=["POST"])
def exact_search():
    """
    Search for records where a categorical field equals a specific value.

    Request body:
        { "field": "location", "value": "Laboratory A" }

    Valid fields: device_id, device_name, location, sensor_type, status
    """
    user, err = _require_auth()
    if err:
        return err

    data  = request.get_json(silent=True) or {}
    field = (data.get("field") or "").strip().lower()
    value = (data.get("value") or "").strip()

    if not field or not value:
        return jsonify({"error": "field and value are required"}), 400

    exact_fields = {"device_id", "device_name", "location", "sensor_type", "status"}
    if field not in exact_fields:
        return jsonify({"error": f"field must be one of: {sorted(exact_fields)}"}), 400

    # Phase 1: generate query token and look up index
    query_token  = exact_search_token(field, value)
    candidate_ids = _record_ids_by_token(field, query_token)

    # Phase 2: decrypt candidates (exact-match by token already done in Phase 1)
    results = []
    for record_id in candidate_ids[:RESULTS_LIMIT]:
        decrypted = _fetch_and_decrypt(record_id)
        if decrypted is None:
            continue
        db_record = get_sensor_record(record_id)
        results.append(_decrypted_to_result(record_id, decrypted, db_record))

    description = f"exact:{field}={value}"
    _log_search(user.id, "exact", description, len(results), len(candidate_ids))

    return jsonify({
        "query":           {"field": field, "value": value},
        "candidate_count": len(candidate_ids),
        "result_count":    len(results),
        "results":         results,
        "workflow": [
            f"1. Generated HMAC token for {field}='{value}' using search key",
            f"2. Looked up token in index — found {len(candidate_ids)} candidate record(s)",
            f"3. Retrieved and decrypted {len(results)} record(s) from storage",
            "4. Returned decrypted records (token match = exact field match)",
        ],
    })


# ── Range search ────────────────────────────────────────────────────────────────

@search_bp.route("/api/search/range", methods=["POST"])
def range_search():
    """
    Numeric range search for temperature or humidity.

    Request body:
        {
          "sensor":  "temperature" | "humidity",
          "operator": "gt" | "lt" | "gte" | "lte" | "between",
          "value":    25.0,
          "value2":   35.0   (required for "between")
        }
    """
    user, err = _require_auth()
    if err:
        return err

    data     = request.get_json(silent=True) or {}
    sensor   = (data.get("sensor") or "").strip().lower()
    operator = (data.get("operator") or "").strip().lower()
    try:
        value  = float(data["value"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "numeric 'value' is required"}), 400

    value2 = None
    if operator == "between":
        try:
            value2 = float(data["value2"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "'value2' is required for 'between' operator"}), 400

    if sensor not in ("temperature", "humidity"):
        return jsonify({"error": "sensor must be 'temperature' or 'humidity'"}), 400

    valid_ops = {"gt", "lt", "gte", "lte", "between"}
    if operator not in valid_ops:
        return jsonify({"error": f"operator must be one of: {sorted(valid_ops)}"}), 400

    # Determine range bounds for bucket enumeration
    if operator == "gt":
        min_val, max_val = value, None
    elif operator == "gte":
        min_val, max_val = value, None
    elif operator == "lt":
        min_val, max_val = None, value
    elif operator == "lte":
        min_val, max_val = None, value
    else:  # between
        min_val, max_val = min(value, value2), max(value, value2)

    # Phase 1: enumerate bucket tokens and look up index
    if sensor == "temperature":
        bucket_tokens = temperature_range_tokens(min_val, max_val)
        bucket_type = "temp_bucket"
        field_name  = "temperature"
    else:
        bucket_tokens = humidity_range_tokens(min_val, max_val)
        bucket_type = "humid_bucket"
        field_name  = "humidity"

    candidate_ids = _record_ids_by_bucket_tokens(bucket_type, bucket_tokens)

    # Phase 2: decrypt candidates and apply EXACT numeric comparison
    results = []
    for record_id in candidate_ids[:RESULTS_LIMIT * 3]:   # allow extra for filtering
        decrypted = _fetch_and_decrypt(record_id)
        if decrypted is None:
            continue
        try:
            field_value = float(decrypted[field_name])
        except (KeyError, ValueError):
            continue

        # Exact comparison — MUST be verified after decryption
        match = False
        if operator == "gt"      and field_value >  value:
            match = True
        elif operator == "gte"   and field_value >= value:
            match = True
        elif operator == "lt"    and field_value <  value:
            match = True
        elif operator == "lte"   and field_value <= value:
            match = True
        elif operator == "between" and min_val <= field_value <= max_val:
            match = True

        if match:
            db_record = get_sensor_record(record_id)
            results.append(_decrypted_to_result(record_id, decrypted, db_record))
        if len(results) >= RESULTS_LIMIT:
            break

    description = f"range:{sensor} {operator} {value}" + (f" {value2}" if value2 else "")
    _log_search(user.id, "range", description, len(results), len(candidate_ids))

    return jsonify({
        "query": {
            "sensor":   sensor,
            "operator": operator,
            "value":    value,
            "value2":   value2,
        },
        "buckets_checked":  len(bucket_tokens),
        "candidate_count":  len(candidate_ids),
        "result_count":     len(results),
        "results":          results,
        "workflow": [
            f"1. Determined relevant {sensor} buckets for operator '{operator}' {value}",
            f"2. Generated HMAC tokens for {len(bucket_tokens)} bucket(s)",
            f"3. Index lookup found {len(candidate_ids)} candidate record(s)",
            f"4. Decrypted candidates and applied exact {sensor} comparison",
            f"5. {len(results)} record(s) satisfied the exact condition",
        ],
    })


# ── Combined search ─────────────────────────────────────────────────────────────

@search_bp.route("/api/search/combined", methods=["POST"])
def combined_search():
    """
    Combined exact-match AND numeric range filter.

    Request body:
        {
          "exact": { "field": "location", "value": "Laboratory A" },
          "range": {
            "sensor":   "temperature",
            "operator": "gt",
            "value":    30.0
          }
        }
    """
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    exact_params = data.get("exact")
    range_params = data.get("range")

    if not exact_params and not range_params:
        return jsonify({"error": "provide at least one of 'exact' or 'range' filters"}), 400

    candidate_ids = None

    # Phase 1a: exact token lookup
    if exact_params:
        field = (exact_params.get("field") or "").strip().lower()
        value = (exact_params.get("value") or "").strip()
        if not field or not value:
            return jsonify({"error": "exact.field and exact.value are required"}), 400
        exact_fields = {"device_id", "device_name", "location", "sensor_type", "status"}
        if field not in exact_fields:
            return jsonify({"error": f"exact.field must be one of: {sorted(exact_fields)}"}), 400
        query_token  = exact_search_token(field, value)
        exact_ids = set(_record_ids_by_token(field, query_token))
        candidate_ids = exact_ids if candidate_ids is None else candidate_ids & exact_ids

    # Phase 1b: bucket range lookup
    if range_params:
        sensor   = (range_params.get("sensor") or "").strip().lower()
        operator = (range_params.get("operator") or "").strip().lower()
        try:
            rvalue  = float(range_params["value"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "range.value must be a number"}), 400
        rvalue2 = None
        if operator == "between":
            try:
                rvalue2 = float(range_params["value2"])
            except (KeyError, ValueError, TypeError):
                return jsonify({"error": "range.value2 required for 'between'"}), 400

        if sensor not in ("temperature", "humidity"):
            return jsonify({"error": "range.sensor must be temperature or humidity"}), 400

        if operator in ("gt", "gte"):
            min_val, max_val = rvalue, None
        elif operator in ("lt", "lte"):
            min_val, max_val = None, rvalue
        else:
            min_val, max_val = min(rvalue, rvalue2), max(rvalue, rvalue2)

        if sensor == "temperature":
            tokens   = temperature_range_tokens(min_val, max_val)
            btype    = "temp_bucket"
        else:
            tokens   = humidity_range_tokens(min_val, max_val)
            btype    = "humid_bucket"

        bucket_ids = set(_record_ids_by_bucket_tokens(btype, tokens))
        candidate_ids = bucket_ids if candidate_ids is None else candidate_ids & bucket_ids
    else:
        rvalue = rvalue2 = None
        sensor = operator = ""

    candidate_ids = list(candidate_ids) if candidate_ids else []

    # Phase 2: decrypt and exact verify
    results = []
    for record_id in candidate_ids[:RESULTS_LIMIT * 3]:
        decrypted = _fetch_and_decrypt(record_id)
        if decrypted is None:
            continue

        # Apply range filter exactly if requested
        if range_params:
            try:
                fval = float(decrypted[sensor])
            except (KeyError, ValueError):
                continue
            match = False
            if operator == "gt"      and fval >  rvalue:    match = True
            elif operator == "gte"   and fval >= rvalue:    match = True
            elif operator == "lt"    and fval <  rvalue:    match = True
            elif operator == "lte"   and fval <= rvalue:    match = True
            elif operator == "between" and min_val <= fval <= max_val: match = True
            if not match:
                continue

        db_record = get_sensor_record(record_id)
        results.append(_decrypted_to_result(record_id, decrypted, db_record))
        if len(results) >= RESULTS_LIMIT:
            break

    description = f"combined: exact={exact_params} range={range_params}"
    _log_search(user.id, "combined", description[:300], len(results), len(candidate_ids))

    return jsonify({
        "candidate_count": len(candidate_ids),
        "result_count":    len(results),
        "results":         results,
    })


# ── Search history ───────────────────────────────────────────────────────────────

@search_bp.route("/api/search/history", methods=["GET"])
def search_history():
    user, err = _require_auth()
    if err:
        return err

    limit = min(int(request.args.get("limit", 50)), 200)
    rows  = (SearchHistory.query
             .filter_by(user_id=user.id)
             .order_by(SearchHistory.search_timestamp.desc())
             .limit(limit)
             .all())
    return jsonify({"history": [r.to_dict() for r in rows]})
