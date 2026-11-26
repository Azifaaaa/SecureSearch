"""
routes/_uuid_helpers.py — Shared UUID utilities for route handlers

Centralises the two recurring patterns that need UUID conversion:
  1. Fetching the current user from the session (session stores str; DB needs uuid.UUID).
  2. Fetching any model by its UUID primary key from a URL path param (str → uuid.UUID).
"""
import uuid as _uuid_mod
import logging

from flask import session

from backend.database import db
from backend.models import User, SensorRecord

logger = logging.getLogger(__name__)


def _str_to_uuid(value: str) -> "_uuid_mod.UUID | None":
    """
    Safely convert a string to uuid.UUID.
    Returns None if the string is not a valid UUID.
    """
    if not value:
        return None
    try:
        return _uuid_mod.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def get_current_user() -> "User | None":
    """
    Return the User object for the currently authenticated session, or None.

    The session stores the UUID as a plain string (JSON-serialisable).
    db.session.get() needs a uuid.UUID when the column uses UUIDType on PostgreSQL.
    """
    uid_str = session.get("user_id")
    uid = _str_to_uuid(uid_str)
    if uid is None:
        return None
    return db.session.get(User, uid)


def get_sensor_record(record_id_str: str) -> "SensorRecord | None":
    """
    Fetch a SensorRecord by its UUID primary key given as a URL path string.
    Returns None if the ID is not a valid UUID or the record does not exist.
    """
    uid = _str_to_uuid(record_id_str)
    if uid is None:
        return None
    return db.session.get(SensorRecord, uid)
