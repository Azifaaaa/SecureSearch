# SecureSearch Cloud

**Privacy-Preserving Searchable Encryption for Simulated IoT Sensor Data in Cloud Storage**

> M.Sc. Cybersecurity Academic Project  
> All sensor readings in this system are **synthetic/simulated**. No physical IoT hardware is used.

---

## Table of Contents

1. [Abstract](#1-abstract)
2. [Introduction](#2-introduction)
3. [Problem Statement](#3-problem-statement)
4. [Project Objectives](#4-project-objectives)
5. [System Architecture](#5-system-architecture)
6. [Technologies Used](#6-technologies-used)
7. [Cryptographic Algorithms](#7-cryptographic-algorithms)
8. [Searchable Encryption Design](#8-searchable-encryption-design)
9. [Numeric Bucket Indexing](#9-numeric-bucket-indexing)
10. [Cloud Storage Architecture](#10-cloud-storage-architecture)
11. [Dataset Description](#11-dataset-description)
12. [Database Structure](#12-database-structure)
13. [Threat Model and Leakage Analysis](#13-threat-model-and-leakage-analysis)
14. [Installation — Windows PowerShell](#14-installation--windows-powershell)
15. [Installation — Linux / macOS](#15-installation--linuxmacos)
16. [Running the Application](#16-running-the-application)
17. [Generating the Dataset](#17-generating-the-dataset)
18. [Starting the Simulator](#18-starting-the-simulator)
19. [Supabase Cloud Setup](#19-supabase-cloud-setup)
20. [Running Automated Tests](#20-running-automated-tests)
21. [Testing Search Operations](#21-testing-search-operations)
22. [Verifying Encryption and Integrity](#22-verifying-encryption-and-integrity)
23. [Troubleshooting](#23-troubleshooting)
24. [Limitations](#24-limitations)
25. [Future Enhancements](#25-future-enhancements)
26. [Conclusion](#26-conclusion)
27. [Short Explanation for Your Professor](#27-short-explanation-for-your-professor)

---

## 1. Abstract

SecureSearch Cloud demonstrates a **Privacy-Preserving Searchable Encryption (PPSE)** system for IoT sensor data stored in cloud environments. Every sensor reading is encrypted with **AES-256-GCM** before it is stored, so the cloud provider never sees plaintext sensor values. Authorized users can search the encrypted dataset using **HMAC-SHA-256 search tokens** without decrypting the entire database. Numeric range queries (e.g., "temperature > 30°C") use a **bucket-indexing scheme** followed by exact post-decryption verification, ensuring correctness without false positives.

---

## 2. Introduction

Modern IoT deployments push sensor readings to cloud storage where they may be processed by third-party services. This creates a privacy challenge: how can a user search their encrypted data without giving the cloud provider the ability to read it?

This project implements a practical answer using Searchable Symmetric Encryption (SSE) techniques, applied to a simulated building-environment monitoring system with five virtual sensor devices.

---

## 3. Problem Statement

Traditional cloud storage either:
- Stores data in **plaintext** (privacy risk), or
- Encrypts data in a way that **prevents any searching** (usability cost).

SecureSearch Cloud solves this by implementing a keyed token index: each encrypted record is indexed by HMAC-SHA-256 tokens of its searchable fields. The cloud database stores only tokens — not the original field values. Only someone with the secret search key can generate matching query tokens.

---

## 4. Project Objectives

1. Simulate IoT sensor data from five virtual devices without physical hardware.
2. Encrypt every sensor record with AES-256-GCM before storage.
3. Enable exact-match search using HMAC-SHA-256 token indexes.
4. Enable numeric range search using bucket indexing + post-decryption verification.
5. Integrate with Supabase cloud storage and PostgreSQL (optional cloud mode).
6. Provide a complete web dashboard with real data from the application.
7. Demonstrate integrity verification for stored encrypted objects.
8. Provide honest leakage analysis documenting what information is revealed.

---

## 5. System Architecture

```
Browser (HTML/CSS/JS)
        │
        ▼
Flask Backend (Python)
  ├── Authentication (Werkzeug password hashing)
  ├── Crypto Engine (AES-256-GCM via pyca/cryptography)
  ├── Searchable Index (HMAC-SHA-256)
  ├── Integrity Module (SHA-256 + HMAC)
  ├── Storage Adapter ─────┬── Local (filesystem .enc files)
  │                        └── Cloud (Supabase private bucket)
  └── Database ────────────┬── Local (SQLite via SQLAlchemy)
                           └── Cloud (Supabase PostgreSQL)
```

**Data flow — record ingestion:**
```
Simulator generates reading
    → Flask validates
    → AES-256-GCM encrypts full record
    → HMAC tokens generated for each indexed field
    → Ciphertext uploaded to storage (local or Supabase)
    → Record metadata + tokens stored in database
```

**Data flow — search:**
```
User submits search query
    → Flask generates HMAC query token (never the query value)
    → Token matched against index table (Phase 1)
    → Matching ciphertexts retrieved from storage
    → Records decrypted and authenticated (Phase 2)
    → For range queries: exact numeric comparison applied
    → Matching records returned to user
```

---

## 6. Technologies Used

| Component | Technology |
|-----------|-----------|
| Backend   | Python 3, Flask 3.0 |
| Database  | SQLAlchemy, SQLite (local), PostgreSQL (cloud) |
| Encryption | Python `cryptography` library (pyca) — AES-256-GCM |
| Search    | Python `hmac`, `hashlib` — HMAC-SHA-256 |
| Cloud     | Supabase Storage + Supabase PostgreSQL |
| Frontend  | HTML5, CSS3, Vanilla JavaScript, Chart.js |
| Auth      | Flask sessions, Werkzeug password hashing |
| Testing   | pytest, pytest-flask |

---

## 7. Cryptographic Algorithms

### AES-256-GCM

**AES (Advanced Encryption Standard)** in **GCM (Galois/Counter Mode)** provides:
- **Confidentiality**: 256-bit key space, computationally infeasible to brute-force.
- **Authenticity**: 128-bit authentication tag detects any modification to the ciphertext.
- **Associated Data**: The record's UUID and encryption version are bound to the ciphertext via AAD. Swapping ciphertexts between records causes authentication failure.

Parameters used:
- Key: 256 bits (32 bytes), from `ENCRYPTION_KEY_B64`
- Nonce: 96 bits (12 bytes), cryptographically random, generated fresh for every encryption
- Tag: 128 bits (16 bytes), appended to ciphertext by the library

### HMAC-SHA-256

**HMAC (Hash-based Message Authentication Code)** with SHA-256 provides deterministic, keyed tokens:

```
token = HMAC(SEARCH_KEY, "field_prefix:normalized_value")
```

Properties:
- Deterministic: same input + same key = same token (enabling search)
- One-way: cannot reverse a token to its value without the key
- Domain-separated: different field prefixes prevent cross-field token collisions

---

## 8. Searchable Encryption Design

### Exact-match search

At **ingestion** time, for each indexed field:
```python
token = HMAC(search_key, "location:laboratory_a")
# store (record_id, "location", token) in search_index table
```

At **query** time:
```python
query_token = HMAC(search_key, "location:laboratory_a")
# SELECT record_id FROM search_indexes WHERE field_type='location' AND token=query_token
# retrieve ciphertexts, decrypt, return
```

The database index **never contains plaintext field values**.

### Indexed fields

| Field | Domain prefix | Type |
|-------|--------------|------|
| device_id | `device_id:` | Exact |
| device_name | `device_name:` | Exact |
| location | `location:` | Exact |
| sensor_type | `sensor_type:` | Exact |
| status | `status:` | Exact |
| temperature | `temp_bucket:` | Numeric bucket |
| humidity | `humid_bucket:` | Numeric bucket |

---

## 9. Numeric Bucket Indexing

HMAC tokens are equality checks — they cannot directly express "greater than" relationships. The solution is **bucket indexing**:

1. The numeric range is divided into fixed-width buckets (1°C for temperature, 1% for humidity).
2. Each record's numeric value is mapped to its bucket (e.g., 30.7°C → bucket 30).
3. A token is generated for the bucket: `HMAC(key, "temp_bucket:30")`

**Range query execution (temperature > 30°C):**
1. Enumerate all buckets in the range: 30, 31, 32, … 80
2. Generate HMAC tokens for each bucket
3. Query index for all candidate record IDs (Phase 1 — no decryption)
4. For each candidate: retrieve ciphertext, decrypt, apply exact comparison `temperature > 30.0`
5. Only return records where the decrypted temperature is truly > 30.0

**Boundary correctness**: A record with temperature = 30.0 is in bucket 30 and is retrieved as a candidate, but the exact post-decryption check `30.0 > 30.0 == False` correctly excludes it.

---

## 10. Cloud Storage Architecture

### Local mode (default)
- Encrypted objects stored as `.enc` files in `storage/encrypted_objects/`
- Metadata and tokens in SQLite database (`securesearch_local.db`)
- No cloud credentials required

### Cloud mode (Supabase)
- Encrypted objects in a **private** Supabase Storage bucket (`secure-sensor-data`)
- Object paths use the random UUID, not device names or sensor values
- Metadata and tokens in Supabase PostgreSQL
- Service-role key kept server-side, **never sent to the browser**

**Object path format:** `records/<uuid>.enc` — no plaintext data in the path.

---

## 11. Dataset Description

**File:** `data/sensor_dataset.csv`

| Property | Value |
|----------|-------|
| Records | 5,000 |
| Devices | 5 virtual sensors |
| Time window | 30 days |
| Temperature range | 4.9°C – 48.0°C |
| Humidity range | 11.0% – 98.6% |
| Status distribution | NORMAL: 98.9%, WARNING: 1.0%, CRITICAL: 0.1% |
| Anomaly injection | ~5% of readings |
| Reproducible | Yes (seed=42) |

All records are marked `simulated=True`. Generated by `scripts/generate_dataset.py`.

---

## 12. Database Structure

### `users`
Stores registered users with hashed passwords. Roles: `user`, `admin`.

### `sensor_records`
Encrypted record metadata only. **No plaintext sensor values.**
Key fields: `id` (UUID), `object_path`, `nonce_b64`, `encryption_version`, `integrity_sha256`, `integrity_hmac`, `storage_backend`, `device_id`.

### `search_indexes`
HMAC token index for categorical fields.
Key fields: `record_id`, `field_type`, `token` (64-char hex).

### `numeric_bucket_indexes`
HMAC token index for temperature and humidity buckets.
Key fields: `record_id`, `sensor_type` (`temp_bucket`/`humid_bucket`), `bucket_token`.

### `devices`
Virtual sensor device registry (non-sensitive metadata).

### `search_history`
Audit log of searches. Stores search type, result count, timestamp. **No raw query values.**

---

## 13. Threat Model and Leakage Analysis

### What is protected

An attacker with only the **encrypted storage objects** (but not the keys):
- Cannot read sensor values, device IDs, locations, or timestamps (all encrypted)
- Cannot forge valid authentication tags without the encryption key

### What is revealed (leakage)

| Leakage | Severity | Detail |
|---------|----------|--------|
| Object sizes | Low | Approximate record content length |
| Record count | Low | Total number of records |
| Equality patterns | Medium | Records with same field value share the same HMAC token |
| Search patterns | Medium | Same search repeated produces same query token |
| Access patterns | Medium | Which records are retrieved after a query |
| Bucket ranges | Medium | Bucket token reveals value is in a 1-unit range |
| Creation timestamps | Low | Stored in DB (not encrypted) |

### Level 3 threat (compromised server)

If the Flask server or `.env` file is compromised, the attacker can decrypt all records and reverse the token index. This is a known limitation of SSE — the server is a trusted party.

### Integrity verification

Three mechanisms:
1. **AES-GCM tag** — 128-bit tag, automatically checked on every decryption
2. **SHA-256 digest** — detects accidental corruption, not targeted attacks
3. **HMAC-SHA-256 reference** — keyed MAC, cannot be forged without `INTEGRITY_KEY`

---

## 14. Installation — Windows PowerShell

```powershell
# 1. Clone/download the project
cd C:\path\to\SecureSearch-Cloud

# 2. Create a Python virtual environment
python -m venv venv

# 3. Activate the virtual environment
.\venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install flask flask-sqlalchemy flask-login flask-limiter werkzeug sqlalchemy cryptography python-dotenv requests pytest pytest-flask

# 5. Generate cryptographic keys (run ONCE only)
python scripts/generate_keys.py

# 6. Copy the output into a .env file
#    Copy-Item .env.example .env
#    Then edit .env with the generated key values

# 7. Initialize the database (creates tables and default admin user)
python scripts/initialize_database.py

# 8. Generate the 5,000-record dataset
python scripts/generate_dataset.py
```

---

## 15. Installation — Linux/macOS

```bash
# 1. Navigate to project directory
cd /path/to/SecureSearch-Cloud

# 2. Create virtual environment
python3 -m venv venv

# 3. Activate
source venv/bin/activate

# 4. Install dependencies
pip install flask flask-sqlalchemy flask-login flask-limiter werkzeug sqlalchemy cryptography python-dotenv requests pytest pytest-flask

# 5. Generate keys
python scripts/generate_keys.py

# 6. Create .env from example and fill in key values
cp .env.example .env
# Edit .env with your generated keys

# 7. Initialize database
python scripts/initialize_database.py

# 8. Generate dataset
python scripts/generate_dataset.py
```

---

## 16. Running the Application

### Windows PowerShell

```powershell
# Activate venv if not already active
.\venv\Scripts\Activate.ps1

# Start the Flask development server
python app.py
```

The server starts at: **http://127.0.0.1:5000**

Default login: **admin** / **adminpass123**

> To run without the debug reloader (more stable in some environments):
> ```powershell
> $env:FLASK_ENV="development"; python -m flask run --host=127.0.0.1 --port=5000 --no-reload
> ```

### Linux/macOS

```bash
source venv/bin/activate
python app.py
```

---

## 17. Generating the Dataset

```powershell
# Generate 5,000 records (default, seed=42)
python scripts/generate_dataset.py

# Generate 10,000 records with a specific seed
python scripts/generate_dataset.py --records 10000 --seed 123
```

Output files:
- `data/sensor_dataset.csv` — full dataset
- `data/sample_records.json` — first 50 records as JSON
- `static/data/sensor_dataset.csv` — copy for browser import (created automatically)

---

## 18. Starting the Simulator

### Via the web dashboard

1. Navigate to **Sensor Monitor** in the sidebar
2. Select a device (or leave "Random device")
3. Set the interval (seconds between readings)
4. Click **Start Simulator**

### Via standalone script

```powershell
# Generate a reading every 5 seconds, send to running server
python simulator/sensor_simulator.py --url http://localhost:5000 --username admin --password adminpass123 --interval 5

# Generate readings from a specific device
python simulator/sensor_simulator.py --url http://localhost:5000 --username admin --password adminpass123 --device SENSOR_002
```

---

## 19. Supabase Cloud Setup

> Skip this section if you are using local mode (`STORAGE_MODE=local`).

### Step 1: Create a Supabase project

1. Go to [supabase.com](https://supabase.com) → New Project
2. Note your **Project URL** and **service-role key** (Settings → API)

### Step 2: Create the database schema

1. Supabase Dashboard → SQL Editor → New Query
2. Paste the contents of `supabase/schema.sql`
3. Click **Run**

### Step 3: Create the private storage bucket

1. Supabase Dashboard → Storage → New Bucket
2. Name: `secure-sensor-data`
3. **Uncheck** "Make bucket public" (must be private)
4. Click **Create**

### Step 4: Configure environment variables

Add to your `.env` file:

```
STORAGE_MODE=cloud
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_here
SUPABASE_DB_URL=postgresql://postgres:YOUR_DB_PASSWORD@db.YOUR_PROJECT_ID.supabase.co:5432/postgres
DATABASE_URL=postgresql://postgres:YOUR_DB_PASSWORD@db.YOUR_PROJECT_ID.supabase.co:5432/postgres
```

### Step 5: Verify connection

```powershell
python scripts/initialize_database.py   # creates tables in Supabase PostgreSQL
```

Then start the app and navigate to **Cloud Status** in the dashboard.

---

## 20. Running Automated Tests

```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# Run all tests
python -m pytest tests/ -v

# Run specific test files
python -m pytest tests/test_crypto.py -v         # AES-256-GCM tests
python -m pytest tests/test_search.py -v         # HMAC token tests
python -m pytest tests/test_simulator.py -v      # Simulator tests
python -m pytest tests/test_cloud_storage.py -v  # Storage adapter tests
python -m pytest tests/test_api.py -v            # API endpoint tests
python -m pytest tests/test_integration.py -v    # End-to-end integration tests

# Run with coverage (if coverage is installed)
python -m pytest tests/ --tb=short
```

**Expected result:** 110 tests passing.

---

## 21. Testing Search Operations

### Exact search (via API)

```powershell
# Using PowerShell's Invoke-RestMethod:

# Step 1: Login
$session = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
Invoke-RestMethod -Uri "http://localhost:5000/api/auth/login" -Method Post `
  -ContentType "application/json" -Body '{"username":"admin","password":"adminpass123"}' `
  -SessionVariable session

# Step 2: Exact search
Invoke-RestMethod -Uri "http://localhost:5000/api/search/exact" -Method Post `
  -ContentType "application/json" `
  -Body '{"field":"location","value":"Laboratory A"}' -WebSession $session

# Step 3: Range search
Invoke-RestMethod -Uri "http://localhost:5000/api/search/range" -Method Post `
  -ContentType "application/json" `
  -Body '{"sensor":"temperature","operator":"gt","value":30.0}' -WebSession $session
```

Or use the web dashboard at http://localhost:5000/search.

---

## 22. Verifying Encryption and Integrity

### Via web dashboard

1. Go to **Encrypted Records** → click **Verify** on any record
2. Go to **Integrity Check** → click **Run Integrity Check on All Records**

### Via API

```powershell
# Get a record ID
$records = Invoke-RestMethod -Uri "http://localhost:5000/api/records?per_page=1" -WebSession $session
$id = $records.records[0].id

# Verify integrity
Invoke-RestMethod -Uri "http://localhost:5000/api/records/$id/verify" -WebSession $session
```

Expected response:
```json
{
  "integrity": {
    "sha256_match": true,
    "hmac_match": true,
    "overall": true,
    "detail": "Integrity verified: SHA-256 digest and HMAC reference both match."
  }
}
```

---

## 23. Troubleshooting

### "Missing required environment variable: ENCRYPTION_KEY_B64"

You haven't set up your `.env` file. Run:
```powershell
python scripts/generate_keys.py
```
Then copy the output into `.env`.

### "No module named 'cryptography'"

The virtual environment is not activated, or dependencies weren't installed:
```powershell
.\venv\Scripts\Activate.ps1
pip install cryptography flask flask-sqlalchemy flask-limiter werkzeug python-dotenv pytest pytest-flask
```

### Flask starts but exits immediately

Run `python app.py` in the foreground to see the full traceback. Common causes:
- Missing `.env` file
- Missing keys in `.env`
- Port 5000 already in use (use `--port=5001`)

### Database not initialized

```powershell
python scripts/initialize_database.py
```

### "StorageError: Supabase credentials are missing"

Either set `STORAGE_MODE=local` in `.env`, or provide the Supabase credentials (see Section 19).

### Tests fail with key errors

The test suite uses dummy keys automatically. If you've overridden the environment with invalid base64, reset them:
```powershell
Remove-Item Env:ENCRYPTION_KEY_B64 -ErrorAction SilentlyContinue
python -m pytest tests/ -v
```

---

## 24. Limitations

1. **Equality-pattern leakage**: Records with the same field value share the same HMAC token. An observer of the database can count token frequencies.
2. **Bucket-range leakage**: Temperature bucket tokens reveal approximate 1°C ranges.
3. **Search-pattern leakage**: Repeated searches for the same value produce the same query token.
4. **Trusted server**: The Flask backend handles plaintext during ingestion and authorized decryption. A compromised server exposes all data.
5. **No ORAM**: Oblivious RAM would hide access patterns but has high performance cost and is beyond the scope of this project.
6. **HTTP only**: The development server uses HTTP. Production deployment requires HTTPS.
7. **Single-key scheme**: Key rotation requires re-encrypting and re-indexing all records.

---

## 25. Future Enhancements

- **Oblivious RAM (ORAM)** to hide access patterns
- **Range-queryable encryption** (e.g., Order-Preserving Encryption) with better privacy
- **Key rotation** without full re-encryption using envelope encryption
- **Multi-user access control** per record or device
- **Hardware Security Module (HSM)** integration for key storage
- **TLS/HTTPS** enforcement in production
- **Attribute-Based Encryption (ABE)** for fine-grained access control
- **Homomorphic encryption** for computation on encrypted data

---

## 26. Conclusion

SecureSearch Cloud demonstrates a practical implementation of Searchable Symmetric Encryption applied to IoT sensor data. The system achieves the core academic contribution: encrypted sensor records stored in cloud storage, with HMAC-SHA-256 token indexes enabling search without plaintext exposure, and two-phase range queries providing correct numeric filtering through bucket indexing plus post-decryption verification.

The honest leakage analysis and documented threat model make this suitable as an academic demonstration of controlled-leakage searchable encryption.

---

## 27. Short Explanation for Your Professor

**What does this project do?**

It solves the problem of searching encrypted data stored in the cloud. When sensor readings are uploaded, they are fully encrypted (AES-256-GCM) before leaving the application. The cloud storage provider never sees any plaintext.

To enable searching without decrypting everything, we pre-compute HMAC-SHA-256 "tokens" (keyed fingerprints) for each searchable field value and store these tokens in the database alongside the encrypted record. When a user searches for "Laboratory A", the backend computes the same HMAC token and matches it against the token index — no plaintext is involved.

For numeric range queries (temperature > 30°C), we map each value to a 1-degree bucket and generate a token for the bucket. At query time, all relevant bucket tokens are checked, candidate records are retrieved and decrypted, then an exact numeric comparison is applied to ensure correctness — no false positives.

The system honestly documents its leakage: token frequency patterns and bucket-range information are observable by someone who has the database. This is consistent with the academic SSE literature and is clearly distinguished from the stronger guarantees of ORAM-based schemes.
