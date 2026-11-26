-- supabase/schema.sql
-- SecureSearch Cloud — Supabase PostgreSQL Schema
--
-- Run this script in the Supabase SQL Editor to create all tables.
-- Navigate to: Supabase Dashboard → SQL Editor → New Query → Paste → Run
--
-- After running, also create the private storage bucket:
--   Dashboard → Storage → New Bucket → Name: "secure-sensor-data" → Private (uncheck public)

-- ── Enable UUID extension ─────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username      VARCHAR(80)  NOT NULL UNIQUE,
    email         VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
CREATE INDEX IF NOT EXISTS ix_users_email    ON users(email);

-- ── Devices ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id   VARCHAR(50)  NOT NULL UNIQUE,
    device_name VARCHAR(100) NOT NULL,
    location    VARCHAR(100) NOT NULL,
    sensor_type VARCHAR(50)  NOT NULL DEFAULT 'temperature_humidity',
    status      VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_devices_device_id ON devices(device_id);

-- ── Sensor Records (encrypted metadata only) ──────────────────────────────────
-- Plaintext sensor values (temperature, humidity, location, etc.)
-- are NOT stored in this table.
CREATE TABLE IF NOT EXISTS sensor_records (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    object_path        VARCHAR(500) NOT NULL,
    nonce_b64          VARCHAR(32)  NOT NULL,
    encryption_version INTEGER      NOT NULL DEFAULT 1,
    integrity_sha256   VARCHAR(64)  NOT NULL,
    integrity_hmac     VARCHAR(64)  NOT NULL,
    storage_backend    VARCHAR(20)  NOT NULL DEFAULT 'supabase',
    device_id          VARCHAR(50)  NOT NULL,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_sensor_records_device_id  ON sensor_records(device_id);
CREATE INDEX IF NOT EXISTS ix_sensor_records_created_at ON sensor_records(created_at DESC);

-- ── Search Indexes (HMAC tokens for categorical fields) ───────────────────────
CREATE TABLE IF NOT EXISTS search_indexes (
    id            SERIAL PRIMARY KEY,
    record_id     UUID        NOT NULL REFERENCES sensor_records(id) ON DELETE CASCADE,
    field_type    VARCHAR(50) NOT NULL,
    token         VARCHAR(64) NOT NULL,
    index_version INTEGER     NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_search_field_token ON search_indexes(field_type, token);
CREATE INDEX IF NOT EXISTS ix_search_record_id   ON search_indexes(record_id);

-- ── Numeric Bucket Indexes ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS numeric_bucket_indexes (
    id            SERIAL PRIMARY KEY,
    record_id     UUID        NOT NULL REFERENCES sensor_records(id) ON DELETE CASCADE,
    sensor_type   VARCHAR(20) NOT NULL,
    bucket_token  VARCHAR(64) NOT NULL,
    index_version INTEGER     NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_bucket_type_token ON numeric_bucket_indexes(sensor_type, bucket_token);
CREATE INDEX IF NOT EXISTS ix_bucket_record_id  ON numeric_bucket_indexes(record_id);

-- ── Search History ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS search_history (
    id                   SERIAL PRIMARY KEY,
    user_id              UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    search_type          VARCHAR(50) NOT NULL,
    search_description   VARCHAR(300),
    result_count         INTEGER     NOT NULL DEFAULT 0,
    candidate_count      INTEGER     NOT NULL DEFAULT 0,
    search_timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_search_history_user_id   ON search_history(user_id);
CREATE INDEX IF NOT EXISTS ix_search_history_timestamp ON search_history(search_timestamp DESC);

-- ── Row Level Security (optional — adds extra protection) ─────────────────────
-- If you want to restrict data access per user, uncomment the following:
-- ALTER TABLE sensor_records ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Users can read own records" ON sensor_records
--     FOR SELECT USING (true);  -- adjust as needed
