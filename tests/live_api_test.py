"""
tests/live_api_test.py — Live HTTP smoke test against a running server.

Run with:  python tests/live_api_test.py
Requires the Flask server to be running at http://127.0.0.1:5000
"""
import sys
import requests

BASE = "http://127.0.0.1:5000"

import os
# Allow overriding the base URL via environment
BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:5000")

def run():
    s = requests.Session()
    failures = []
    passed   = 0

    def ok(label):
        nonlocal passed
        passed += 1
        print(f"  PASS  {label}")

    def fail(label, detail=""):
        failures.append(f"{label}: {detail}")
        print(f"  FAIL  {label}: {detail}")

    # ── Auth ────────────────────────────────────────────────────────────────
    r = s.get(BASE + "/", allow_redirects=False)
    if r.status_code == 302:
        ok("GET / redirects to /login")
    else:
        fail("GET / redirect", r.status_code)

    r = s.post(BASE + "/api/auth/login",
               json={"username": "admin", "password": "adminpass123"})
    if r.status_code == 200 and r.json().get("user", {}).get("username") == "admin":
        ok("POST /api/auth/login — admin login")
    else:
        fail("Login", r.text)
        print("ABORT: cannot continue without auth")
        sys.exit(1)

    r = s.get(BASE + "/api/auth/me")
    if r.status_code == 200 and r.json()["user"]["username"] == "admin":
        ok("GET /api/auth/me")
    else:
        fail("GET /api/auth/me", r.text)

    # ── Cloud status ─────────────────────────────────────────────────────────
    r = s.get(BASE + "/api/cloud/status")
    if r.status_code == 200 and r.json()["mode"] == "local":
        ok("GET /api/cloud/status — local mode confirmed")
    else:
        fail("Cloud status", r.text)

    # ── Ingest test records ──────────────────────────────────────────────────
    test_records = [
        {"device_id": "SENSOR_001", "device_name": "Laboratory A Sensor",
         "location": "Laboratory A", "sensor_type": "temperature_humidity",
         "temperature": 28.5, "humidity": 55.0, "status": "NORMAL",
         "timestamp": "2024-06-01T10:00:00+00:00", "simulated": True},
        {"device_id": "SENSOR_002", "device_name": "Server Room Sensor",
         "location": "Server Room", "sensor_type": "temperature_humidity",
         "temperature": 38.2, "humidity": 42.0, "status": "WARNING",
         "timestamp": "2024-06-01T10:01:00+00:00", "simulated": True},
        {"device_id": "SENSOR_001", "device_name": "Laboratory A Sensor",
         "location": "Laboratory A", "sensor_type": "temperature_humidity",
         "temperature": 22.1, "humidity": 60.0, "status": "NORMAL",
         "timestamp": "2024-06-01T10:02:00+00:00", "simulated": True},
        {"device_id": "SENSOR_003", "device_name": "Library Sensor",
         "location": "Library", "sensor_type": "temperature_humidity",
         "temperature": 41.5, "humidity": 85.0, "status": "CRITICAL",
         "timestamp": "2024-06-01T10:03:00+00:00", "simulated": True},
        # Exactly 30.0 — must NOT appear in temperature > 30 results
        {"device_id": "SENSOR_004", "device_name": "Classroom Sensor",
         "location": "Classroom", "sensor_type": "temperature_humidity",
         "temperature": 30.0, "humidity": 65.0, "status": "NORMAL",
         "timestamp": "2024-06-01T10:04:00+00:00", "simulated": True},
    ]

    ingested_ids = []
    all_ok = True
    for rec in test_records:
        r = s.post(BASE + "/api/records/ingest", json=rec)
        if r.status_code == 201:
            ingested_ids.append(r.json()["record_id"])
        else:
            all_ok = False
            fail("Ingest record", r.text)
    if all_ok:
        ok(f"POST /api/records/ingest — {len(test_records)} records")

    # ── Records list ─────────────────────────────────────────────────────────
    r = s.get(BASE + "/api/records?per_page=5")
    if r.status_code == 200 and r.json()["total"] > 0:
        ok(f"GET /api/records — total={r.json()['total']}")
    else:
        fail("GET /api/records", r.text)

    # ── Decrypt single record ─────────────────────────────────────────────────
    if ingested_ids:
        rid = ingested_ids[0]
        r = s.get(BASE + f"/api/records/{rid}")
        d = r.json()
        if r.status_code == 200 and d["record"]["device_id"] == "SENSOR_001":
            ok(f"GET /api/records/<id> — decrypted correctly")
        else:
            fail("GET /api/records/<id>", r.text)

    # ── Exact search ─────────────────────────────────────────────────────────
    r = s.post(BASE + "/api/search/exact",
               json={"field": "location", "value": "Laboratory A"})
    d = r.json()
    if r.status_code == 200 and d["result_count"] > 0:
        all_lab = all(rec["location"] == "Laboratory A" for rec in d["results"])
        if all_lab:
            ok(f"Exact search location=Laboratory A — {d['result_count']} results, all correct")
        else:
            fail("Exact search wrong result", str(d["results"]))
    else:
        fail("Exact search location", r.text)

    r = s.post(BASE + "/api/search/exact",
               json={"field": "status", "value": "WARNING"})
    d = r.json()
    if r.status_code == 200:
        wrong = [rec for rec in d["results"] if rec["status"] != "WARNING"]
        if not wrong:
            ok(f"Exact search status=WARNING — {d['result_count']} results, all correct")
        else:
            fail("Exact search status=WARNING had wrong results", str(wrong))
    else:
        fail("Exact search status", r.text)

    r = s.post(BASE + "/api/search/exact",
               json={"field": "location", "value": "NonExistentXYZ99999"})
    if r.status_code == 200 and r.json()["result_count"] == 0:
        ok("Exact search — no results for unknown value")
    else:
        fail("Exact search no-results", r.text)

    # ── Range search ─────────────────────────────────────────────────────────
    r = s.post(BASE + "/api/search/range",
               json={"sensor": "temperature", "operator": "gt", "value": 30.0})
    d = r.json()
    if r.status_code == 200:
        wrong = [rec for rec in d["results"] if rec["temperature"] <= 30.0]
        if not wrong:
            ok(f"Range temp > 30 -- {d['result_count']} results, boundary correct (none <=30)")
        else:
            fail("Range boundary gt 30 FAILED", f"These should not appear: {[r['temperature'] for r in wrong]}")
    else:
        fail("Range search temp > 30", r.text)

    r = s.post(BASE + "/api/search/range",
               json={"sensor": "temperature", "operator": "lt", "value": 25.0})
    d = r.json()
    if r.status_code == 200:
        wrong = [rec for rec in d["results"] if rec["temperature"] >= 25.0]
        if not wrong:
            ok(f"Range temp < 25 — {d['result_count']} results, boundary correct")
        else:
            fail("Range boundary lt 25 FAILED", str([r["temperature"] for r in wrong]))
    else:
        fail("Range search temp < 25", r.text)

    r = s.post(BASE + "/api/search/range",
               json={"sensor": "temperature", "operator": "between",
                     "value": 25.0, "value2": 35.0})
    d = r.json()
    if r.status_code == 200:
        wrong = [rec for rec in d["results"] if not (25.0 <= rec["temperature"] <= 35.0)]
        if not wrong:
            ok(f"Range temp between 25–35 — {d['result_count']} results, all in range")
        else:
            fail("Range between 25-35 FAILED", str([r["temperature"] for r in wrong]))
    else:
        fail("Range search between", r.text)

    r = s.post(BASE + "/api/search/range",
               json={"sensor": "humidity", "operator": "gt", "value": 70.0})
    d = r.json()
    if r.status_code == 200:
        wrong = [rec for rec in d["results"] if rec["humidity"] <= 70.0]
        if not wrong:
            ok(f"Range humidity > 70 — {d['result_count']} results, boundary correct")
        else:
            fail("Range humidity boundary FAILED", str([r["humidity"] for r in wrong]))
    else:
        fail("Range search humidity", r.text)

    # ── Combined search ───────────────────────────────────────────────────────
    r = s.post(BASE + "/api/search/combined", json={
        "exact": {"field": "location", "value": "Laboratory A"},
        "range": {"sensor": "temperature", "operator": "gt", "value": 25.0},
    })
    d = r.json()
    if r.status_code == 200:
        wrong = [rec for rec in d["results"]
                 if rec["location"] != "Laboratory A" or rec["temperature"] <= 25.0]
        if not wrong:
            ok(f"Combined search Lab A + temp>25 — {d['result_count']} results, all correct")
        else:
            fail("Combined search wrong results", str(wrong))
    else:
        fail("Combined search", r.text)

    # ── Search history ────────────────────────────────────────────────────────
    r = s.get(BASE + "/api/search/history")
    if r.status_code == 200 and len(r.json()["history"]) > 0:
        ok(f"GET /api/search/history — {len(r.json()['history'])} entries recorded")
    else:
        fail("Search history", r.text)

    # ── Integrity verification ────────────────────────────────────────────────
    if ingested_ids:
        all_ok = True
        for rid in ingested_ids[:3]:
            r = s.get(BASE + f"/api/records/{rid}/verify")
            if r.status_code == 200 and r.json()["integrity"]["overall"]:
                pass
            else:
                all_ok = False
                fail(f"Integrity check {rid[:8]}", r.text)
        if all_ok:
            ok("Integrity verification — HMAC + SHA-256 both pass for all checked records")

    # ── Dashboard metrics ─────────────────────────────────────────────────────
    r = s.get(BASE + "/api/dashboard/metrics")
    if r.status_code == 200 and r.json()["total_records"] > 0:
        ok(f"GET /api/dashboard/metrics — total_records={r.json()['total_records']}")
    else:
        fail("Dashboard metrics", r.text)

    # ── Simulator single generate ─────────────────────────────────────────────
    r = s.post(BASE + "/api/simulator/generate",
               json={"device_id": "SENSOR_002", "ingest": True})
    if r.status_code == 200 and r.json()["reading"]["device_id"] == "SENSOR_002":
        ok("POST /api/simulator/generate — reading generated and ingested")
    else:
        fail("Simulator generate", r.text)

    # ── Input validation ──────────────────────────────────────────────────────
    r = s.post(BASE + "/api/search/exact",
               json={"field": "plaintext_temperature", "value": "30"})
    if r.status_code == 400:
        ok("Input validation — invalid field rejected with 400")
    else:
        fail("Input validation bad field", f"Expected 400, got {r.status_code}")

    r = s.post(BASE + "/api/search/range",
               json={"sensor": "temperature", "operator": "equals", "value": 30.0})
    if r.status_code == 400:
        ok("Input validation — invalid operator rejected with 400")
    else:
        fail("Input validation bad operator", f"Expected 400, got {r.status_code}")

    # ── Unauthenticated access ────────────────────────────────────────────────
    fresh = requests.Session()   # no login
    r = fresh.get(BASE + "/api/records")
    if r.status_code == 401:
        ok("Unauthenticated access to /api/records returns 401")
    else:
        fail("Unauthenticated access", f"Expected 401, got {r.status_code}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  PASSED: {passed}")
    print(f"  FAILED: {len(failures)}")
    if failures:
        print("  Failures:")
        for f in failures:
            print(f"    - {f}")
    print("=" * 60)
    return len(failures) == 0


if __name__ == "__main__":
    import sys
    success = run()
    sys.exit(0 if success else 1)
