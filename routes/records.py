"""
routes/records.py — Sensor record ingestion and retrieval

POST /api/records/ingest      — Encrypt and store a sensor reading
GET  /api/records             — List record metadata (paginated)
GET  /api/records/<id>        — Fetch and decrypt a single record
GET  /api/records/<id>/verify — Verify integrity of a stored record
"""
import base64
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, session

from backend.database import db
from backend.models import User, SensorRecord, SearchIndex, NumericBucketIndex
from backend.crypto_engine import encrypt_to_b64, decrypt_from_b64, DecryptionError
from backend.searchable_index import generate_tokens_for_record
from backend.integrity import compute_integrity_references, verify_integrity
from backend.cloud_storage import storage_adapter
from routes._uuid_helpers import get_current_user, get_sensor_record

logger = logging.getLogger(__name__)
records_bp = Blueprint("records", __name__)


def _require_auth():
    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


@records_bp.route("/api/records/ingest", methods=["POST"])
def ingest():
    """
    Accept a sensor reading, encrypt it and store it.

    Expected JSON body: same fields as generate_reading() output.
    """
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    # Validate required fields
    required = ["device_id", "device_name", "location", "sensor_type",
                "temperature", "humidity", "status", "timestamp"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400

    try:
        temperature = float(data["temperature"])
        humidity    = float(data["humidity"])
    except (ValueError, TypeError):
        return jsonify({"error": "temperature and humidity must be numbers"}), 400

    if not (-50 <= temperature <= 100):
        return jsonify({"error": "temperature out of valid range"}), 400
    if not (0 <= humidity <= 100):
        return jsonify({"error": "humidity out of valid range"}), 400

    # Build the record dict to encrypt (plain sensor data)
    record_dict = {
        "device_id":   data["device_id"],
        "device_name": data["device_name"],
        "location":    data["location"],
        "sensor_type": data["sensor_type"],
        "temperature": temperature,
        "humidity":    humidity,
        "status":      data["status"],
        "timestamp":   data["timestamp"],
        "simulated":   data.get("simulated", True),
    }

    # Create a DB record first to get the UUID
    db_record = SensorRecord(
        object_path="",        # will be filled after upload
        nonce_b64="",          # will be filled after encryption
        encryption_version=1,
        integrity_sha256="",
        integrity_hmac="",
        storage_backend=storage_adapter.mode,
        device_id=data["device_id"],
    )
    db.session.add(db_record)
    db.session.flush()  # get the generated UUID without committing yet
    record_id = db_record.id

    try:
        # ── 1. Encrypt the record ──────────────────────────────────────────────
        ciphertext_b64, nonce_b64 = encrypt_to_b64(record_dict, record_id, version=1)
        ciphertext_bytes = base64.b64decode(ciphertext_b64)

        # ── 2. Compute integrity references ───────────────────────────────────
        integrity = compute_integrity_references(record_id, ciphertext_bytes)

        # ── 3. Upload ciphertext to storage ───────────────────────────────────
        object_path = storage_adapter.upload(record_id, ciphertext_bytes)

        # ── 4. Update the DB record with encryption metadata ──────────────────
        db_record.object_path      = object_path
        db_record.nonce_b64        = nonce_b64
        db_record.integrity_sha256 = integrity["sha256"]
        db_record.integrity_hmac   = integrity["hmac_ref"]

        # ── 5. Generate and store searchable HMAC tokens ──────────────────────
        tokens = generate_tokens_for_record(
            device_id=data["device_id"],
            device_name=data["device_name"],
            location=data["location"],
            sensor_type=data["sensor_type"],
            status=data["status"],
            temperature=temperature,
            humidity=humidity,
        )

        for token_entry in tokens:
            field = token_entry["field_type"]
            if field in ("temp_bucket", "humid_bucket"):
                bucket_index = NumericBucketIndex(
                    record_id=record_id,
                    sensor_type=field,
                    bucket_token=token_entry["token"],
                    index_version=1,
                )
                db.session.add(bucket_index)
            else:
                search_index = SearchIndex(
                    record_id=record_id,
                    field_type=field,
                    token=token_entry["token"],
                    index_version=1,
                )
                db.session.add(search_index)

        db.session.commit()
        logger.info("Ingested record %s for device %s", record_id, data["device_id"])

        return jsonify({
            "message":   "record ingested and encrypted",
            "record_id": record_id,
            "storage":   storage_adapter.mode,
        }), 201

    except Exception as exc:
        db.session.rollback()
        logger.error("Ingest failed: %s", exc)
        return jsonify({"error": f"ingest failed: {exc}"}), 500


@records_bp.route("/api/records", methods=["GET"])
def list_records():
    user, err = _require_auth()
    if err:
        return err

    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    page     = max(1, page)
    per_page = max(1, min(100, per_page))

    paginated = SensorRecord.query.order_by(
        SensorRecord.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "records":    [r.to_dict() for r in paginated.items],
        "total":      paginated.total,
        "page":       paginated.page,
        "pages":      paginated.pages,
        "per_page":   per_page,
    })


@records_bp.route("/api/records/<record_id>", methods=["GET"])
def get_record(record_id):
    user, err = _require_auth()
    if err:
        return err

    db_record = get_sensor_record(record_id)
    if not db_record:
        return jsonify({"error": "record not found"}), 404

    try:
        ciphertext = storage_adapter.download(db_record.object_path)
        plaintext  = decrypt_from_b64(
            base64.b64encode(ciphertext).decode(),
            db_record.nonce_b64,
            record_id,
            db_record.encryption_version,
        )
        return jsonify({
            "id":                 db_record.id,
            "created_at":        db_record.created_at.isoformat(),
            "encryption_version": db_record.encryption_version,
            "storage_backend":   db_record.storage_backend,
            "record":            plaintext,
        })
    except DecryptionError as exc:
        return jsonify({"error": f"decryption failed: {exc}"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@records_bp.route("/api/records/<record_id>/verify", methods=["GET"])
def verify_record(record_id):
    user, err = _require_auth()
    if err:
        return err

    db_record = get_sensor_record(record_id)
    if not db_record:
        return jsonify({"error": "record not found"}), 404

    try:
        ciphertext = storage_adapter.download(db_record.object_path)
        result = verify_integrity(
            record_id=record_id,
            ciphertext=ciphertext,
            stored_sha256=db_record.integrity_sha256,
            stored_hmac=db_record.integrity_hmac,
        )
        return jsonify({
            "record_id": record_id,
            "integrity": result,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _do_ingest(reading: dict) -> str:
    """
    Internal helper used by the simulator callback and test code.
    Encrypts and stores a reading without going through HTTP.

    Returns the new record_id on success, raises on failure.
    """
    record_dict = {
        "device_id":   reading["device_id"],
        "device_name": reading["device_name"],
        "location":    reading["location"],
        "sensor_type": reading["sensor_type"],
        "temperature": float(reading["temperature"]),
        "humidity":    float(reading["humidity"]),
        "status":      reading["status"],
        "timestamp":   reading["timestamp"],
        "simulated":   reading.get("simulated", True),
    }

    db_record = SensorRecord(
        object_path="",
        nonce_b64="",
        encryption_version=1,
        integrity_sha256="",
        integrity_hmac="",
        storage_backend=storage_adapter.mode,
        device_id=reading["device_id"],
    )
    db.session.add(db_record)
    db.session.flush()
    record_id = db_record.id

    ciphertext_b64, nonce_b64 = encrypt_to_b64(record_dict, record_id, version=1)
    ciphertext_bytes = base64.b64decode(ciphertext_b64)
    integrity = compute_integrity_references(record_id, ciphertext_bytes)
    object_path = storage_adapter.upload(record_id, ciphertext_bytes)

    db_record.object_path      = object_path
    db_record.nonce_b64        = nonce_b64
    db_record.integrity_sha256 = integrity["sha256"]
    db_record.integrity_hmac   = integrity["hmac_ref"]

    tokens = generate_tokens_for_record(
        device_id=reading["device_id"],
        device_name=reading["device_name"],
        location=reading["location"],
        sensor_type=reading["sensor_type"],
        status=reading["status"],
        temperature=float(reading["temperature"]),
        humidity=float(reading["humidity"]),
    )
    for token_entry in tokens:
        field = token_entry["field_type"]
        if field in ("temp_bucket", "humid_bucket"):
            db.session.add(NumericBucketIndex(
                record_id=record_id,
                sensor_type=field,
                bucket_token=token_entry["token"],
                index_version=1,
            ))
        else:
            db.session.add(SearchIndex(
                record_id=record_id,
                field_type=field,
                token=token_entry["token"],
                index_version=1,
            ))

    db.session.commit()
    return record_id
