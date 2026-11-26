"""
tests/test_api.py — Flask API integration tests

Verifies:
  - Registration and login work
  - Invalid login is rejected
  - Protected routes require authentication
  - Record ingest, retrieval and integrity verification work
  - Exact search, range search and combined search return correct results
  - Search history is recorded
  - Input validation rejects bad data
"""
import os
import base64
import json
import pytest
import sys

# Set dummy keys before importing app
os.environ["ENCRYPTION_KEY_B64"] = base64.b64encode(b"\xAA" * 32).decode()
os.environ["SEARCH_KEY_B64"]     = base64.b64encode(b"\xBB" * 32).decode()
os.environ["INTEGRITY_KEY_B64"]  = base64.b64encode(b"\xCC" * 32).decode()
os.environ["FLASK_ENV"]          = "testing"
os.environ["STORAGE_MODE"]       = "local"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TestingConfig
from app import create_app
from backend.database import db as _db


@pytest.fixture(scope="module")
def app():
    application = create_app(config_override=TestingConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(scope="module")
def auth_client(client):
    """Return a client that is already logged in as a test user."""
    client.post("/api/auth/register", json={
        "username": "testuser",
        "email":    "test@example.com",
        "password": "password123",
    })
    client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "password123",
    })
    return client


# ── Authentication ────────────────────────────────────────────────────────────

class TestAuth:

    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "username": "newuser",
            "email":    "new@example.com",
            "password": "securepassword",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["user"]["username"] == "newuser"

    def test_register_duplicate_username(self, client):
        client.post("/api/auth/register", json={
            "username": "dupuser", "email": "dup@example.com", "password": "password123"
        })
        resp = client.post("/api/auth/register", json={
            "username": "dupuser", "email": "dup2@example.com", "password": "password123"
        })
        assert resp.status_code == 409

    def test_login_success(self, client):
        client.post("/api/auth/register", json={
            "username": "logintest", "email": "login@example.com", "password": "password123"
        })
        resp = client.post("/api/auth/login", json={
            "username": "logintest", "password": "password123"
        })
        assert resp.status_code == 200
        assert resp.get_json()["user"]["username"] == "logintest"

    def test_invalid_login_rejected(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "logintest", "password": "wrongpassword"
        })
        assert resp.status_code == 401

    def test_protected_route_without_auth(self, client):
        """Accessing a protected route without login should return 401."""
        # Use a fresh client without auth
        fresh_client = client.application.test_client()
        resp = fresh_client.get("/api/records")
        assert resp.status_code == 401

    def test_logout(self, auth_client):
        resp = auth_client.post("/api/auth/logout")
        assert resp.status_code == 200
        # Re-login for subsequent tests
        auth_client.post("/api/auth/login", json={
            "username": "testuser", "password": "password123"
        })


# ── Records ───────────────────────────────────────────────────────────────────

SAMPLE_READING = {
    "device_id":   "SENSOR_001",
    "device_name": "Laboratory A Sensor",
    "location":    "Laboratory A",
    "sensor_type": "temperature_humidity",
    "temperature": 25.5,
    "humidity":    55.0,
    "status":      "NORMAL",
    "timestamp":   "2024-06-01T12:00:00+00:00",
    "simulated":   True,
}


class TestRecords:

    @pytest.fixture(autouse=True)
    def ensure_logged_in(self, auth_client):
        self.client = auth_client
        auth_client.post("/api/auth/login", json={
            "username": "testuser", "password": "password123"
        })

    def test_ingest_success(self):
        resp = self.client.post("/api/records/ingest", json=SAMPLE_READING)
        assert resp.status_code == 201
        data = resp.get_json()
        assert "record_id" in data

    def test_ingest_missing_field(self):
        incomplete = {k: v for k, v in SAMPLE_READING.items() if k != "temperature"}
        resp = self.client.post("/api/records/ingest", json=incomplete)
        assert resp.status_code == 400

    def test_ingest_invalid_temperature(self):
        bad = dict(SAMPLE_READING)
        bad["temperature"] = 200.0   # out of valid range
        resp = self.client.post("/api/records/ingest", json=bad)
        assert resp.status_code == 400

    def test_list_records(self):
        resp = self.client.get("/api/records")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "records" in data
        assert "total" in data
        assert len(data["records"]) > 0

    def test_get_specific_record(self):
        # Ingest first
        ingest_resp = self.client.post("/api/records/ingest", json=SAMPLE_READING)
        record_id   = ingest_resp.get_json()["record_id"]

        # Retrieve and check decrypted data
        resp = self.client.get(f"/api/records/{record_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["record"]["device_id"]   == "SENSOR_001"
        assert data["record"]["temperature"] == 25.5

    def test_verify_integrity(self):
        ingest_resp = self.client.post("/api/records/ingest", json=SAMPLE_READING)
        record_id   = ingest_resp.get_json()["record_id"]

        resp = self.client.get(f"/api/records/{record_id}/verify")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["integrity"]["overall"] is True
        assert data["integrity"]["sha256_match"] is True
        assert data["integrity"]["hmac_match"] is True


# ── Search ────────────────────────────────────────────────────────────────────

class TestSearch:

    @pytest.fixture(autouse=True)
    def ingest_test_records(self, auth_client):
        """Ingest a known set of records for search tests."""
        self.client = auth_client
        auth_client.post("/api/auth/login", json={
            "username": "testuser", "password": "password123"
        })

        self.records = []
        test_readings = [
            dict(SAMPLE_READING, location="Laboratory A", temperature=25.0, status="NORMAL"),
            dict(SAMPLE_READING, location="Server Room",  temperature=38.0, status="WARNING",
                 device_id="SENSOR_002", device_name="Server Room Sensor"),
            dict(SAMPLE_READING, location="Laboratory A", temperature=42.0, status="CRITICAL"),
        ]
        for reading in test_readings:
            resp = auth_client.post("/api/records/ingest", json=reading)
            if resp.status_code == 201:
                self.records.append(resp.get_json()["record_id"])

    def test_exact_search_location(self):
        """Search for location = Laboratory A should return matching records."""
        resp = self.client.post("/api/search/exact", json={
            "field": "location", "value": "Laboratory A"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["result_count"] > 0
        for r in data["results"]:
            assert r["location"] == "Laboratory A"

    def test_exact_search_status(self):
        """Search for status = WARNING should return only WARNING records."""
        resp = self.client.post("/api/search/exact", json={
            "field": "status", "value": "WARNING"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        for r in data["results"]:
            assert r["status"] == "WARNING"

    def test_exact_search_no_results(self):
        """Search for a non-existent value should return 0 results."""
        resp = self.client.post("/api/search/exact", json={
            "field": "location", "value": "NonexistentLocation12345"
        })
        assert resp.status_code == 200
        assert resp.get_json()["result_count"] == 0

    def test_range_search_temperature_gt(self):
        """Temperature > 30 should return only records with temp > 30."""
        resp = self.client.post("/api/search/range", json={
            "sensor": "temperature", "operator": "gt", "value": 30.0
        })
        assert resp.status_code == 200
        data = resp.get_json()
        for r in data["results"]:
            assert r["temperature"] > 30.0  # Exact post-decryption check

    def test_range_search_boundary_gt_30(self):
        """Temperature > 30 must NOT return a record with temperature == 30.0."""
        # Ingest a record with exactly 30.0°C
        exact30 = dict(SAMPLE_READING, temperature=30.0, location="TestBoundary",
                       device_id="SENSOR_003", device_name="Library Sensor")
        self.client.post("/api/records/ingest", json=exact30)

        resp = self.client.post("/api/search/range", json={
            "sensor": "temperature", "operator": "gt", "value": 30.0
        })
        data = resp.get_json()
        for r in data["results"]:
            assert r["temperature"] > 30.0, f"Expected > 30 but got {r['temperature']}"

    def test_range_search_temperature_between(self):
        """Temperature between 20 and 30 should return records in that range."""
        resp = self.client.post("/api/search/range", json={
            "sensor": "temperature", "operator": "between", "value": 20.0, "value2": 30.0
        })
        assert resp.status_code == 200
        data = resp.get_json()
        for r in data["results"]:
            assert 20.0 <= r["temperature"] <= 30.0

    def test_combined_search(self):
        """Combined exact + range search should return only records matching both."""
        resp = self.client.post("/api/search/combined", json={
            "exact": {"field": "location", "value": "Laboratory A"},
            "range": {"sensor": "temperature", "operator": "gt", "value": 30.0},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        for r in data["results"]:
            assert r["location"] == "Laboratory A"
            assert r["temperature"] > 30.0

    def test_search_history_recorded(self):
        """After searching, history endpoint should contain the entry."""
        self.client.post("/api/search/exact", json={
            "field": "status", "value": "NORMAL"
        })
        resp = self.client.get("/api/search/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["history"]) > 0

    def test_invalid_field_rejected(self):
        """Searching with an unsupported field should return 400."""
        resp = self.client.post("/api/search/exact", json={
            "field": "plaintext_temperature", "value": "30"
        })
        assert resp.status_code == 400

    def test_invalid_range_operator_rejected(self):
        """Searching with an unsupported operator should return 400."""
        resp = self.client.post("/api/search/range", json={
            "sensor": "temperature", "operator": "equals", "value": 30.0
        })
        assert resp.status_code == 400
