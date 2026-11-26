"""
routes/simulator.py — Simulator control endpoints

POST /api/simulator/start    — Start the background simulator
POST /api/simulator/stop     — Stop the background simulator
GET  /api/simulator/status   — Get simulator status and last reading
POST /api/simulator/generate — Generate a single reading and optionally ingest it
"""
import logging
from flask import Blueprint, request, jsonify, session, current_app

from backend.database import db
from backend.models import User
from backend.simulator_service import simulator_service, generate_reading, DEVICE_PROFILES
from routes._uuid_helpers import get_current_user

logger = logging.getLogger(__name__)
simulator_bp = Blueprint("simulator", __name__)


def _require_auth():
    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "authentication required"}), 401)
    return user, None


def _ingest_reading(reading: dict):
    """
    Helper: ingest a generated reading via the records ingest route.
    Called as the simulator callback.
    """
    with current_app.app_context():
        try:
            from routes.records import _do_ingest
            _do_ingest(reading)
        except Exception as exc:
            logger.error("Background simulator ingest failed: %s", exc)


@simulator_bp.route("/api/simulator/start", methods=["POST"])
def start_simulator():
    user, err = _require_auth()
    if err:
        return err

    data      = request.get_json(silent=True) or {}
    interval  = int(data.get("interval", 5))
    device_id = data.get("device_id")  # None means random device each time

    # Pass the Flask app to the callback so it can run in app context
    app = current_app._get_current_object()

    def callback(reading):
        with app.app_context():
            try:
                # Import here to avoid circular import at module level
                from routes.records import _do_ingest
                _do_ingest(reading)
            except Exception as exc:
                logger.error("Simulator ingest error: %s", exc)

    result = simulator_service.start(interval=interval, device_id=device_id, callback=callback)
    return jsonify(result)


@simulator_bp.route("/api/simulator/stop", methods=["POST"])
def stop_simulator():
    user, err = _require_auth()
    if err:
        return err
    result = simulator_service.stop()
    return jsonify(result)


@simulator_bp.route("/api/simulator/status", methods=["GET"])
def simulator_status():
    user, err = _require_auth()
    if err:
        return err
    return jsonify(simulator_service.status())


@simulator_bp.route("/api/simulator/generate", methods=["POST"])
def generate_single():
    """Generate one reading and immediately ingest + encrypt it."""
    user, err = _require_auth()
    if err:
        return err

    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    ingest    = data.get("ingest", True)

    reading = generate_reading(device_id=device_id)

    if ingest:
        try:
            from routes.records import _do_ingest
            record_id = _do_ingest(reading)
            reading["record_id"] = record_id
            reading["ingested"]  = True
        except Exception as exc:
            reading["ingested"] = False
            reading["ingest_error"] = str(exc)

    return jsonify({"reading": reading})


@simulator_bp.route("/api/simulator/devices", methods=["GET"])
def list_devices():
    """Return the list of simulated device profiles (non-sensitive metadata)."""
    return jsonify({
        "devices": [
            {
                "device_id":   p["device_id"],
                "device_name": p["device_name"],
                "location":    p["location"],
                "sensor_type": p["sensor_type"],
            }
            for p in DEVICE_PROFILES
        ]
    })
