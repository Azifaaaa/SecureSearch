"""
tests/test_integration.py — End-to-end integration tests using Flask test client

These tests exercise the complete application stack including:
  - Authentication
  - Record ingestion with real AES-256-GCM encryption
  - HMAC token index creation
  - Exact search
  - Range search with boundary verification
  - Combined search
  - Integrity verification
  - Input validation
  - Unauthenticated access rejection

No live HTTP server is required — uses Flask's built-in test client.
"""
import os
import base64
import pytest
import sys

os.environ["ENCRYPTION_KEY_B64"] = base64.b64encode(b"\xAA" * 32).decode()
os.environ["SEARCH_KEY_B64"]     = base64.b64encode(b"\xBB" * 32).decode()
os.environ["INTEGRITY_KEY_B64"]  = base64.b64encode(b"\xCC" * 32).decode()
os.environ["FLASK_ENV"]          = "testing"
os.environ["STORAGE_MODE"]       = "local"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TestingConfig
from app import create_app
from backend.database import db as _db

# ── Fixtures ──────────────────────────────────────────────────────────────────

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
def authed(client):
    """Return client logged in as 'integ_user'."""
    client.post("/api/auth/register", json={
        "username": "integ_user",
        "email":    "integ@example.com",
        "password": "Password123!",
    })
    client.post("/api/auth/login", json={
        "username": "integ_user",
        "password": "Password123!",
    })
    return client


# ── Helper reading payloads ───────────────────────────────────────────────────

def make_reading(device_id="SENSOR_001", location="Laboratory A",
                 temperature=25.0, humidity=55.0, status="NORMAL"):
    devices = {
        "SENSOR_001": "Laboratory A Sensor",
        "SENSOR_002": "Server Room Sensor",
        "SENSOR_003": "Library Sensor",
        "SENSOR_004": "Classroom Sensor",
        "SENSOR_005": "Laboratory B Sensor",
    }
    return {
        "device_id":   device_id,
        "device_name": devices.get(device_id, "Unknown Sensor"),
        "location":    location,
        "sensor_type": "temperature_humidity",
        "temperature": temperature,
        "humidity":    humidity,
        "status":      status,
        "timestamp":   "2024-06-01T10:00:00+00:00",
        "simulated":   True,
    }


def ingest(client, **kwargs):
    r = client.post("/api/records/ingest", json=make_reading(**kwargs))
    assert r.status_code == 201, f"Ingest failed: {r.get_json()}"
    return r.get_json()["record_id"]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLiveIntegration:

    @pytest.fixture(autouse=True)
    def setup(self, authed, app):
        """Ensure we have a known dataset for each test class."""
        self.c = authed
        self.app = app

        # Re-login in case session expired between tests
        self.c.post("/api/auth/login", json={
            "username": "integ_user", "password": "Password123!"
        })

        # Ingest a fixed set of records for deterministic search tests
        self.ids = {}
        with app.app_context():
            self.ids["lab_a_normal"]  = ingest(self.c, device_id="SENSOR_001",
                location="Laboratory A", temperature=25.0, humidity=55.0, status="NORMAL")
            self.ids["server_warning"] = ingest(self.c, device_id="SENSOR_002",
                location="Server Room", temperature=38.5, humidity=42.0, status="WARNING")
            self.ids["lab_a_critical"] = ingest(self.c, device_id="SENSOR_001",
                location="Laboratory A", temperature=42.0, humidity=85.0, status="CRITICAL")
            self.ids["classroom_normal"] = ingest(self.c, device_id="SENSOR_004",
                location="Classroom", temperature=22.5, humidity=62.0, status="NORMAL")
            # Exactly 30.0°C — must NOT appear in temp > 30 results
            self.ids["exactly_30"] = ingest(self.c, device_id="SENSOR_003",
                location="Library", temperature=30.0, humidity=50.0, status="NORMAL")

    # ── Auth & Access ─────────────────────────────────────────────────────────

    def test_unauthenticated_records_rejected(self, client):
        """Fresh client (no login) must get 401 on protected routes."""
        fresh = client.application.test_client()
        assert fresh.get("/api/records").status_code == 401
        assert fresh.post("/api/search/exact",
                          json={"field": "location", "value": "x"}).status_code == 401

    def test_logout_and_reauth(self):
        self.c.post("/api/auth/logout")
        r = self.c.get("/api/records")
        assert r.status_code == 401
        # Re-login for subsequent tests
        self.c.post("/api/auth/login", json={
            "username": "integ_user", "password": "Password123!"
        })

    # ── Record operations ──────────────────────────────────────────────────────

    def test_records_list_non_empty(self):
        r = self.c.get("/api/records?per_page=5")
        assert r.status_code == 200
        d = r.get_json()
        assert d["total"] > 0

    def test_decrypt_specific_record(self):
        rid = self.ids["server_warning"]
        r = self.c.get(f"/api/records/{rid}")
        assert r.status_code == 200
        d = r.get_json()
        # Exact field values should survive encrypt-then-decrypt
        assert d["record"]["device_id"]   == "SENSOR_002"
        assert d["record"]["location"]    == "Server Room"
        assert d["record"]["temperature"] == 38.5
        assert d["record"]["humidity"]    == 42.0
        assert d["record"]["status"]      == "WARNING"

    def test_integrity_passes_for_all_ingested(self):
        for label, rid in self.ids.items():
            r = self.c.get(f"/api/records/{rid}/verify")
            assert r.status_code == 200, f"Verify endpoint failed for {label}"
            i = r.get_json()["integrity"]
            assert i["overall"]      is True, f"Integrity FAIL for {label}: {i['detail']}"
            assert i["sha256_match"] is True, f"SHA-256 mismatch for {label}"
            assert i["hmac_match"]   is True, f"HMAC mismatch for {label}"

    # ── Exact search ──────────────────────────────────────────────────────────

    def test_exact_search_location_laboratory_a(self):
        r = self.c.post("/api/search/exact",
                        json={"field": "location", "value": "Laboratory A"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["result_count"] >= 2
        for rec in d["results"]:
            assert rec["location"] == "Laboratory A", \
                f"Wrong location in result: {rec['location']}"

    def test_exact_search_status_warning(self):
        r = self.c.post("/api/search/exact",
                        json={"field": "status", "value": "WARNING"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["result_count"] >= 1
        for rec in d["results"]:
            assert rec["status"] == "WARNING", \
                f"Non-WARNING record returned: {rec['status']}"

    def test_exact_search_device_id(self):
        r = self.c.post("/api/search/exact",
                        json={"field": "device_id", "value": "SENSOR_001"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["result_count"] >= 1
        for rec in d["results"]:
            assert rec["device_id"] == "SENSOR_001"

    def test_exact_search_no_results(self):
        r = self.c.post("/api/search/exact",
                        json={"field": "location", "value": "NonexistentPlace_XYZ"})
        assert r.status_code == 200
        assert r.get_json()["result_count"] == 0

    def test_exact_search_does_not_decrypt_entire_db(self):
        """
        Candidate count must be <= result count * some factor.
        The key invariant: we do NOT decrypt all records for an exact search.
        The token lookup narrows candidates before decryption.
        """
        r = self.c.post("/api/search/exact",
                        json={"field": "status", "value": "CRITICAL"})
        d = r.get_json()
        # candidate_count comes from the token index — should equal result_count for exact match
        assert d["candidate_count"] == d["result_count"], \
            "Exact match should have candidate_count == result_count (token is exact)"

    # ── Range search ──────────────────────────────────────────────────────────

    def test_range_temperature_gt_30_exact_boundary(self):
        """
        CRITICAL BOUNDARY TEST: temperature > 30 must NOT return the record
        with temperature == 30.0, even though it falls in the same bucket.
        """
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "gt", "value": 30.0})
        assert r.status_code == 200
        d = r.get_json()
        for rec in d["results"]:
            assert rec["temperature"] > 30.0, \
                f"BOUNDARY VIOLATION: temperature={rec['temperature']} should be > 30, not =="

    def test_range_temperature_gte_30_includes_boundary(self):
        """temperature >= 30 SHOULD return the record with temperature == 30.0."""
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "gte", "value": 30.0})
        assert r.status_code == 200
        d = r.get_json()
        temps = [rec["temperature"] for rec in d["results"]]
        assert 30.0 in temps, \
            f"GTE boundary: 30.0 should be included, got temps={temps}"

    def test_range_temperature_lt_25(self):
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "lt", "value": 25.0})
        assert r.status_code == 200
        d = r.get_json()
        for rec in d["results"]:
            assert rec["temperature"] < 25.0, \
                f"lt boundary: {rec['temperature']} should be < 25"

    def test_range_temperature_lte_25(self):
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "lte", "value": 25.0})
        assert r.status_code == 200
        d = r.get_json()
        for rec in d["results"]:
            assert rec["temperature"] <= 25.0, \
                f"lte boundary: {rec['temperature']} should be <= 25"

    def test_range_temperature_between(self):
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "between",
                              "value": 20.0, "value2": 32.0})
        assert r.status_code == 200
        d = r.get_json()
        assert d["result_count"] >= 1
        for rec in d["results"]:
            assert 20.0 <= rec["temperature"] <= 32.0, \
                f"between: {rec['temperature']} outside [20, 32]"

    def test_range_humidity_gt(self):
        r = self.c.post("/api/search/range",
                        json={"sensor": "humidity", "operator": "gt", "value": 70.0})
        assert r.status_code == 200
        d = r.get_json()
        for rec in d["results"]:
            assert rec["humidity"] > 70.0

    def test_range_no_results(self):
        """Query for unrealistic temperature should return 0 results."""
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "gt", "value": 59.9})
        assert r.status_code == 200
        # We ingested max 42°C so this should be empty
        assert r.get_json()["result_count"] == 0

    def test_range_candidate_filtering(self):
        """
        Bucket candidates >= result count.
        Bucket 30 token is retrieved for temp > 30 query, but after exact
        comparison, the record with temp=30.0 is filtered out.
        """
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "gt", "value": 30.0})
        d = r.get_json()
        # Candidate count must be >= result count (some candidates filtered out)
        assert d["candidate_count"] >= d["result_count"]

    # ── Combined search ───────────────────────────────────────────────────────

    def test_combined_exact_and_range(self):
        r = self.c.post("/api/search/combined", json={
            "exact": {"field": "location", "value": "Laboratory A"},
            "range": {"sensor": "temperature", "operator": "gt", "value": 30.0},
        })
        assert r.status_code == 200
        d = r.get_json()
        assert d["result_count"] >= 1
        for rec in d["results"]:
            assert rec["location"] == "Laboratory A"
            assert rec["temperature"] > 30.0

    def test_combined_no_overlap_gives_no_results(self):
        """Server Room AND temperature < 10 — should return 0 results."""
        r = self.c.post("/api/search/combined", json={
            "exact": {"field": "location", "value": "Server Room"},
            "range": {"sensor": "temperature", "operator": "lt", "value": 10.0},
        })
        assert r.status_code == 200
        assert r.get_json()["result_count"] == 0

    def test_combined_exact_only(self):
        """Combined with only exact filter should work."""
        r = self.c.post("/api/search/combined", json={
            "exact": {"field": "status", "value": "CRITICAL"},
        })
        assert r.status_code == 200
        d = r.get_json()
        for rec in d["results"]:
            assert rec["status"] == "CRITICAL"

    # ── Search history ────────────────────────────────────────────────────────

    def test_search_history_recorded(self):
        # Run a search first
        self.c.post("/api/search/exact", json={"field": "status", "value": "NORMAL"})
        r = self.c.get("/api/search/history")
        assert r.status_code == 200
        h = r.get_json()["history"]
        assert len(h) > 0
        # Most recent entry should be an exact search
        assert h[0]["search_type"] == "exact"

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def test_dashboard_metrics(self):
        r = self.c.get("/api/dashboard/metrics")
        assert r.status_code == 200
        d = r.get_json()
        assert d["total_records"] > 0
        assert d["storage_mode"] == "local"
        assert d["total_searches"] > 0

    def test_cloud_status_local_mode(self):
        r = self.c.get("/api/cloud/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["mode"] == "local"
        assert d["status"] == "ok"

    # ── Input validation ──────────────────────────────────────────────────────

    def test_invalid_exact_field_rejected(self):
        r = self.c.post("/api/search/exact",
                        json={"field": "plaintext_temperature", "value": "30"})
        assert r.status_code == 400

    def test_invalid_range_operator_rejected(self):
        r = self.c.post("/api/search/range",
                        json={"sensor": "temperature", "operator": "equals", "value": 30.0})
        assert r.status_code == 400

    def test_ingest_missing_field_rejected(self):
        incomplete = make_reading()
        del incomplete["temperature"]
        r = self.c.post("/api/records/ingest", json=incomplete)
        assert r.status_code == 400

    def test_ingest_temperature_out_of_range_rejected(self):
        bad = make_reading(temperature=200.0)
        r = self.c.post("/api/records/ingest", json=bad)
        assert r.status_code == 400

    # ── Simulator ─────────────────────────────────────────────────────────────

    def test_simulator_generate_and_ingest(self):
        r = self.c.post("/api/simulator/generate",
                        json={"device_id": "SENSOR_002", "ingest": True})
        assert r.status_code == 200
        d = r.get_json()
        assert d["reading"]["device_id"] == "SENSOR_002"
        assert d["reading"]["simulated"] is True
        assert d["reading"].get("ingested") is True

    def test_simulator_devices_endpoint(self):
        r = self.c.get("/api/simulator/devices")
        assert r.status_code == 200
        devices = r.get_json()["devices"]
        device_ids = {d["device_id"] for d in devices}
        assert "SENSOR_001" in device_ids
        assert "SENSOR_005" in device_ids
        assert len(devices) == 5
