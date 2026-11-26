"""
routes/cloud.py — Cloud storage status and connectivity endpoints

GET  /api/cloud/status          — Show current storage mode and status
POST /api/cloud/test-connection — Test connectivity to storage backend
"""
import logging
from flask import Blueprint, jsonify, session

from backend.database import db
from backend.models import User
from backend.cloud_storage import storage_adapter
from routes._uuid_helpers import get_current_user

logger = logging.getLogger(__name__)
cloud_bp = Blueprint("cloud", __name__)


def _require_auth():
    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


@cloud_bp.route("/api/cloud/status", methods=["GET"])
def cloud_status():
    user, err = _require_auth()
    if err:
        return err

    mode = storage_adapter.mode
    result = storage_adapter.test_connection()

    return jsonify({
        "mode":   mode,
        "status": result.get("status", "unknown"),
        "detail": result,
        "note":   (
            "Running in LOCAL mode. Encrypted objects are stored on the filesystem."
            if mode == "local" else
            "Running in CLOUD mode. Encrypted objects are stored in Supabase Storage."
        ),
    })


@cloud_bp.route("/api/cloud/test-connection", methods=["POST"])
def test_connection():
    user, err = _require_auth()
    if err:
        return err

    result = storage_adapter.test_connection()
    return jsonify(result), (200 if result.get("status") == "ok" else 503)
