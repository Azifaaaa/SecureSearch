"""
tests/server_smoke_test.py — Runs the Flask app in a background thread
and exercises all major HTTP endpoints without needing a separate server process.

Usage: python tests/server_smoke_test.py
"""
import sys, os, threading, time, base64, tempfile

os.environ["ENCRYPTION_KEY_B64"] = base64.b64encode(b"\xAA" * 32).decode()
os.environ["SEARCH_KEY_B64"]     = base64.b64encode(b"\xBB" * 32).decode()
os.environ["INTEGRITY_KEY_B64"]  = base64.b64encode(b"\xCC" * 32).decode()
os.environ["FLASK_ENV"]          = "testing"
os.environ["STORAGE_MODE"]       = "local"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a temp file-based SQLite so it's accessible from multiple threads
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)

from config import TestingConfig

class SmokeTestConfig(TestingConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_db_path}"
    LOCAL_STORAGE_PATH       = "storage/smoke_test_objects"

from app import create_app
from backend.database import db as _db
import requests

PORT = 15432   # use an unusual port to avoid conflicts

def start_server(app):
    # Run Flask's werkzeug server in a daemon thread
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)   # suppress werkzeug chatter
    app.run(host="127.0.0.1", port=PORT, use_reloader=False, threaded=True)

app = create_app(config_override=SmokeTestConfig)
# Create all tables in the file-based DB before starting the threaded server
with app.app_context():
    _db.create_all()

t = threading.Thread(target=start_server, args=(app,), daemon=True)
t.start()
time.sleep(1.5)   # wait for the server to bind

BASE = f"http://127.0.0.1:{PORT}"
s = requests.Session()
passed = 0
failed = 0

def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label} -- {detail}")

# Register + login
r = s.post(BASE + "/api/auth/register",
           json={"username":"smoketest","email":"smoke@test.com","password":"Password1!"})
check("Register", r.status_code == 201, r.text)

r = s.post(BASE + "/api/auth/login",
           json={"username":"smoketest","password":"Password1!"})
check("Login", r.status_code == 200 and r.json().get("user",{}).get("username")=="smoketest", r.text)

# Cloud status
r = s.get(BASE + "/api/cloud/status")
check("Cloud status = local", r.status_code == 200 and r.json()["mode"] == "local", r.text)

# Ingest
reading = dict(device_id="SENSOR_001",device_name="Laboratory A Sensor",
               location="Laboratory A",sensor_type="temperature_humidity",
               temperature=38.5,humidity=42.0,status="WARNING",
               timestamp="2024-06-01T10:00:00+00:00",simulated=True)
r = s.post(BASE + "/api/records/ingest", json=reading)
check("Ingest", r.status_code == 201, r.text)
rid = r.json().get("record_id","")

# Decrypt
r = s.get(BASE + f"/api/records/{rid}")
check("Decrypt record", r.status_code==200 and r.json()["record"]["temperature"]==38.5, r.text)

# Verify integrity
r = s.get(BASE + f"/api/records/{rid}/verify")
check("Integrity", r.status_code==200 and r.json()["integrity"]["overall"]==True, r.text)

# Exact search
r = s.post(BASE + "/api/search/exact",
           json={"field":"location","value":"Laboratory A"})
check("Exact search", r.status_code==200 and r.json()["result_count"]>=1, r.text)

# Range search
r = s.post(BASE + "/api/search/range",
           json={"sensor":"temperature","operator":"gt","value":30.0})
d = r.json()
wrong = [rec for rec in d.get("results",[]) if rec["temperature"]<=30.0]
check("Range search boundary", r.status_code==200 and not wrong,
      f"boundary violations: {[x['temperature'] for x in wrong]}")

# Combined search
r = s.post(BASE + "/api/search/combined", json={
    "exact":{"field":"location","value":"Laboratory A"},
    "range":{"sensor":"temperature","operator":"gt","value":30.0}
})
check("Combined search", r.status_code==200, r.text)

# Dashboard metrics
r = s.get(BASE + "/api/dashboard/metrics")
check("Metrics", r.status_code==200 and r.json()["total_records"]>=1, r.text)

# Unauthenticated
fresh = requests.Session()
r = fresh.get(BASE + "/api/records")
check("Unauth rejected", r.status_code==401, r.text)

# Simulator generate
r = s.post(BASE + "/api/simulator/generate",
           json={"device_id":"SENSOR_002","ingest":True})
check("Simulator generate", r.status_code==200 and r.json()["reading"]["simulated"]==True, r.text)

# HTML pages
for path in ["/login", "/register", "/dashboard", "/search", "/cryptography", "/leakage", "/about"]:
    r = s.get(BASE + path)
    check(f"HTML {path}", r.status_code == 200, f"got {r.status_code}")

print()
print("=" * 55)
print(f"  PASSED: {passed}   FAILED: {failed}")
print("=" * 55)

# Cleanup temp db
try:
    os.unlink(_db_path)
except Exception:
    pass

sys.exit(0 if failed == 0 else 1)
