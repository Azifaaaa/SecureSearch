"""
backend/models.py — SQLAlchemy database models for SecureSearch Cloud

UUID strategy (cross-database compatible):
  PostgreSQL / Supabase: columns are native UUID type.
  SQLite (local dev):    columns stored as VARCHAR(36) string.

  We use a TypeDecorator (UUIDType) that transparently handles both.
  Python-side values are always uuid.UUID objects so SQLAlchemy sends
  the right type to each backend.  to_dict() converts to str for JSON.

IMPORTANT DESIGN RULE:
  Plaintext sensor readings (temperature, humidity, location, device name,
  status) are NEVER stored in these tables. They are stored encrypted in
  the cloud/local object store. Only encrypted metadata, search tokens,
  and record identifiers are stored here.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, CHAR

from backend.database import db


# ── Cross-database UUID type ────────────────────────────────────────────────────
#
# On PostgreSQL (Supabase): stored as native UUID — matches the schema exactly.
# On SQLite  (local mode):  stored as CHAR(36) string representation.
#
# Python application code always works with uuid.UUID objects.
# JSON serialisation uses str(value) in every to_dict() method.

class UUIDType(TypeDecorator):
    """
    Platform-independent UUID type.

    Uses PostgreSQL's native UUID type when connected to PostgreSQL,
    and CHAR(36) when connected to SQLite or any other database.

    Always returns Python uuid.UUID objects from the database.
    Always sends uuid.UUID objects to the database (or their string
    representation for SQLite, which stores them as text).
    """
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # Use the native PostgreSQL UUID type (no casting needed)
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            # SQLite and others: store as a 36-character string
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        """Convert to the right format before writing to the DB."""
        if value is None:
            return value
        if dialect.name == "postgresql":
            # psycopg3 / asyncpg want a uuid.UUID object for the native UUID type
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(str(value))
        else:
            # SQLite: store as lowercase hyphenated string
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        """Convert DB value back to uuid.UUID when reading."""
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


def _new_uuid() -> uuid.UUID:
    """Generate a new random UUID as a uuid.UUID object (not a string)."""
    return uuid.uuid4()


def _uuid_str(value) -> str:
    """Safe helper: convert a uuid.UUID or string UUID to str for JSON."""
    if value is None:
        return None
    return str(value)


# ── Users ───────────────────────────────────────────────────────────────────────

class User(db.Model):
    """Application user with hashed password and role."""
    __tablename__ = "users"

    id         = db.Column(UUIDType, primary_key=True, default=_new_uuid)
    username   = db.Column(db.String(80),  unique=True, nullable=False, index=True)
    email      = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role       = db.Column(db.String(20),  default="user", nullable=False)
    created_at = db.Column(db.DateTime,    default=datetime.utcnow, nullable=False)

    # Relationships
    search_history = db.relationship(
        "SearchHistory", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id":         _uuid_str(self.id),
            "username":   self.username,
            "email":      self.email,
            "role":       self.role,
            "created_at": self.created_at.isoformat(),
        }

    # Flask-Login interface
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        # Flask-Login requires a string; convert uuid.UUID → str
        return str(self.id)


# ── Devices ─────────────────────────────────────────────────────────────────────

class Device(db.Model):
    """
    Virtual simulated sensor device registration.

    Stores only the device metadata (non-sensitive). The actual
    readings are encrypted in SensorRecord objects.
    """
    __tablename__ = "devices"

    id          = db.Column(UUIDType,     primary_key=True, default=_new_uuid)
    device_id   = db.Column(db.String(50),  unique=True, nullable=False, index=True)
    device_name = db.Column(db.String(100), nullable=False)
    location    = db.Column(db.String(100), nullable=False)
    sensor_type = db.Column(db.String(50),  default="temperature_humidity", nullable=False)
    status      = db.Column(db.String(20),  default="ACTIVE", nullable=False)
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id":          _uuid_str(self.id),
            "device_id":   self.device_id,
            "device_name": self.device_name,
            "location":    self.location,
            "sensor_type": self.sensor_type,
            "status":      self.status,
            "created_at":  self.created_at.isoformat(),
        }


# ── Sensor Records (encrypted metadata only) ────────────────────────────────────

class SensorRecord(db.Model):
    """
    Encrypted sensor record metadata.

    The actual sensor reading is stored as an encrypted object in cloud
    storage (or local filesystem). This table stores only the metadata
    needed to retrieve and decrypt it.

    Fields intentionally NOT stored here:
      - temperature (stored encrypted in object)
      - humidity    (stored encrypted in object)
      - location    (stored encrypted in object)
      - device_name (stored encrypted in object)
      - status      (stored encrypted in object)
    """
    __tablename__ = "sensor_records"

    id                 = db.Column(UUIDType,      primary_key=True, default=_new_uuid)
    object_path        = db.Column(db.String(500), nullable=False)
    nonce_b64          = db.Column(db.String(32),  nullable=False)
    encryption_version = db.Column(db.Integer,     default=1,       nullable=False)
    integrity_sha256   = db.Column(db.String(64),  nullable=False)
    integrity_hmac     = db.Column(db.String(64),  nullable=False)
    storage_backend    = db.Column(db.String(20),  default="local",  nullable=False)
    device_id          = db.Column(db.String(50),  nullable=False,   index=True)
    created_at         = db.Column(db.DateTime,    default=datetime.utcnow,
                                   nullable=False, index=True)

    # Relationships
    search_indexes = db.relationship(
        "SearchIndex", backref="record", lazy=True, cascade="all, delete-orphan"
    )
    bucket_indexes = db.relationship(
        "NumericBucketIndex", backref="record", lazy=True, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id":                 _uuid_str(self.id),
            "object_path":        self.object_path,
            "encryption_version": self.encryption_version,
            "storage_backend":    self.storage_backend,
            "device_id":          self.device_id,
            "integrity_sha256":   self.integrity_sha256,
            "created_at":         self.created_at.isoformat(),
        }


# ── Search Indexes (HMAC tokens for categorical fields) ─────────────────────────

class SearchIndex(db.Model):
    """
    HMAC-SHA-256 token index for categorical (exact-match) searchable fields.

    record_id references sensor_records.id — must use the same UUIDType
    so that PostgreSQL FK joins work without a type cast.
    """
    __tablename__ = "search_indexes"

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    record_id     = db.Column(
        UUIDType,
        db.ForeignKey("sensor_records.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    field_type    = db.Column(db.String(50), nullable=False)
    token         = db.Column(db.String(64), nullable=False)
    index_version = db.Column(db.Integer,   default=1, nullable=False)

    __table_args__ = (
        db.Index("ix_search_field_token", "field_type", "token"),
    )

    def to_dict(self):
        return {
            "id":            self.id,
            "record_id":     _uuid_str(self.record_id),
            "field_type":    self.field_type,
            "token":         self.token,
            "index_version": self.index_version,
        }


# ── Numeric Bucket Indexes ───────────────────────────────────────────────────────

class NumericBucketIndex(db.Model):
    """
    HMAC token index for numeric bucket range searches.

    record_id references sensor_records.id — UUIDType for FK compatibility.
    """
    __tablename__ = "numeric_bucket_indexes"

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    record_id     = db.Column(
        UUIDType,
        db.ForeignKey("sensor_records.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sensor_type   = db.Column(db.String(20), nullable=False)
    bucket_token  = db.Column(db.String(64), nullable=False)
    index_version = db.Column(db.Integer,   default=1, nullable=False)

    __table_args__ = (
        db.Index("ix_bucket_type_token", "sensor_type", "bucket_token"),
    )

    def to_dict(self):
        return {
            "id":            self.id,
            "record_id":     _uuid_str(self.record_id),
            "sensor_type":   self.sensor_type,
            "bucket_token":  self.bucket_token,
            "index_version": self.index_version,
        }


# ── Search History ───────────────────────────────────────────────────────────────

class SearchHistory(db.Model):
    """
    Log of search operations performed by authenticated users.

    user_id references users.id — UUIDType for FK compatibility.
    Raw search query values and secrets are NOT stored here.
    """
    __tablename__ = "search_history"

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id          = db.Column(
        UUIDType,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    search_type         = db.Column(db.String(50),  nullable=False)
    search_description  = db.Column(db.String(300), nullable=True)
    result_count        = db.Column(db.Integer,     default=0, nullable=False)
    candidate_count     = db.Column(db.Integer,     default=0, nullable=False)
    search_timestamp    = db.Column(db.DateTime,    default=datetime.utcnow,
                                    nullable=False, index=True)

    def to_dict(self):
        return {
            "id":                 self.id,
            "user_id":            _uuid_str(self.user_id),
            "search_type":        self.search_type,
            "search_description": self.search_description,
            "result_count":       self.result_count,
            "candidate_count":    self.candidate_count,
            "search_timestamp":   self.search_timestamp.isoformat(),
        }
