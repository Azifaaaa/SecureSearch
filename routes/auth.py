"""
routes/auth.py — Authentication endpoints

POST /api/auth/register   — Create a new user account
POST /api/auth/login      — Authenticate and start a session
POST /api/auth/logout     — End the current session
GET  /api/auth/me         — Return current user info
"""
import logging
import uuid as _uuid_mod

from flask import Blueprint, request, jsonify, session

from werkzeug.security import generate_password_hash, check_password_hash

from backend.database import db
from backend.models import User

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


def _current_user() -> "User | None":
    uid_str = session.get("user_id")
    if not uid_str:
        return None
    try:
        # db.session.get() needs a uuid.UUID when the column is UUIDType/PostgreSQL
        uid = _uuid_mod.UUID(str(uid_str))
    except (ValueError, AttributeError):
        return None
    return db.session.get(User, uid)


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required"}), 400
    if len(username) < 3 or len(username) > 80:
        return jsonify({"error": "username must be 3–80 characters"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400
    if "@" not in email:
        return jsonify({"error": "invalid email address"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "username already taken"}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        role="user",
    )
    db.session.add(user)
    db.session.commit()
    logger.info("New user registered: %s", username)

    session["user_id"] = str(user.id)   # store as str; uuid.UUID is not JSON-serialisable
    return jsonify({"message": "registered", "user": user.to_dict()}), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "invalid username or password"}), 401

    session["user_id"] = str(user.id)   # store as str; uuid.UUID is not JSON-serialisable
    logger.info("User logged in: %s", username)
    return jsonify({"message": "logged in", "user": user.to_dict()})


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "logged out"})


@auth_bp.route("/api/auth/me", methods=["GET"])
def me():
    user = _current_user()
    if not user:
        return jsonify({"error": "not authenticated"}), 401
    return jsonify({"user": user.to_dict()})
