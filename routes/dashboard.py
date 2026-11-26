"""
routes/dashboard.py — Dashboard metrics and trend data

GET /api/dashboard/metrics — Counts and aggregates from the database
GET /api/dashboard/trends  — Time-series data for charts
"""
import logging
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, session

from sqlalchemy import func

from backend.database import db
from backend.models import User, SensorRecord, SearchHistory
from backend.cloud_storage import storage_adapter
from backend.simulator_service import simulator_service

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint("dashboard", __name__)


def _require_auth():
    uid = session.get("user_id")
    if not uid:
        return None, (jsonify({"error": "authentication required"}), 401)
    user = db.session.get(User, uid)
    if not user:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


@dashboard_bp.route("/api/dashboard/metrics", methods=["GET"])
def metrics():
    user, err = _require_auth()
    if err:
        return err

    total_records = SensorRecord.query.count()
    total_searches = SearchHistory.query.count()
    total_users = User.query.count()

    # Records uploaded to cloud vs local
    cloud_records = SensorRecord.query.filter_by(storage_backend="supabase").count()
    local_records = SensorRecord.query.filter_by(storage_backend="local").count()

    # Records created in last 24h
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    # SQLite stores without timezone; compare naively
    recent_records = SensorRecord.query.filter(
        SensorRecord.created_at >= since.replace(tzinfo=None)
    ).count()

    sim_status = simulator_service.status()

    return jsonify({
        "total_records":     total_records,
        "total_searches":    total_searches,
        "total_users":       total_users,
        "cloud_records":     cloud_records,
        "local_records":     local_records,
        "recent_records_24h": recent_records,
        "storage_mode":      storage_adapter.mode,
        "simulator_running": sim_status["running"],
        "simulator_readings": sim_status["readings_generated"],
    })


@dashboard_bp.route("/api/dashboard/trends", methods=["GET"])
def trends():
    """
    Return the last N records with decrypted temperature/humidity for charting.
    Decrypts up to 50 records — keep this limit small.
    """
    user, err = _require_auth()
    if err:
        return err

    import base64
    from backend.crypto_engine import decrypt_from_b64
    from backend.cloud_storage import storage_adapter as sa

    limit  = min(int(session.get("trend_limit", 50)), 50)
    recent = SensorRecord.query.order_by(SensorRecord.created_at.desc()).limit(limit).all()

    chart_data = []
    for rec in reversed(recent):   # oldest first for time-series charts
        try:
            ciphertext = sa.download(rec.object_path)
            decrypted  = decrypt_from_b64(
                base64.b64encode(ciphertext).decode(),
                rec.nonce_b64,
                rec.id,
                rec.encryption_version,
            )
            chart_data.append({
                "timestamp":   decrypted.get("timestamp", rec.created_at.isoformat()),
                "temperature": decrypted.get("temperature"),
                "humidity":    decrypted.get("humidity"),
                "device_id":   decrypted.get("device_id"),
                "status":      decrypted.get("status"),
            })
        except Exception:
            pass   # skip records that fail decryption (e.g., test records)

    # Status distribution
    status_counts = {"NORMAL": 0, "WARNING": 0, "CRITICAL": 0}
    for d in chart_data:
        s = d.get("status", "NORMAL")
        if s in status_counts:
            status_counts[s] += 1

    # Device distribution
    device_counts = {}
    for d in chart_data:
        did = d.get("device_id", "unknown")
        device_counts[did] = device_counts.get(did, 0) + 1

    return jsonify({
        "chart_data":    chart_data,
        "status_counts": status_counts,
        "device_counts": device_counts,
    })
