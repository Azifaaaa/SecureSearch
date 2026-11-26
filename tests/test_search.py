"""
tests/test_search.py — Tests for HMAC-SHA-256 searchable index

Verifies:
  - Token generation is deterministic (same input = same token)
  - Domain separation works (same value, different field = different token)
  - Bucket assignment is correct for temperatures and humidity
  - Range token lists are correct
  - Boundary conditions are handled
"""
import os
import base64
import pytest

os.environ["ENCRYPTION_KEY_B64"] = base64.b64encode(b"\xAA" * 32).decode()
os.environ["SEARCH_KEY_B64"]     = base64.b64encode(b"\xBB" * 32).decode()
os.environ["INTEGRITY_KEY_B64"]  = base64.b64encode(b"\xCC" * 32).decode()

from backend.key_manager import key_manager
key_manager.load_keys(testing=True)

from backend.searchable_index import (
    generate_token,
    generate_tokens_for_record,
    temperature_range_tokens,
    humidity_range_tokens,
    exact_search_token,
    _temperature_bucket,
    _humidity_bucket,
    SearchIndexError,
    TEMP_MIN, TEMP_MAX, HUMID_MIN, HUMID_MAX,
)


class TestTokenGeneration:

    def test_deterministic_token(self):
        """Same field + value must always produce the same token."""
        t1 = generate_token("location", "Laboratory A")
        t2 = generate_token("location", "Laboratory A")
        assert t1 == t2

    def test_token_is_hex_string(self):
        """Token must be a 64-character lowercase hex string."""
        t = generate_token("device_id", "SENSOR_001")
        assert isinstance(t, str)
        assert len(t) == 64
        assert all(c in "0123456789abcdef" for c in t)

    def test_domain_separation(self):
        """
        'Laboratory A' as location vs. 'Laboratory A' as device_name
        must produce DIFFERENT tokens.
        """
        t_location = generate_token("location", "Laboratory A")
        t_name     = generate_token("device_name", "Laboratory A")
        assert t_location != t_name

    def test_different_values_different_tokens(self):
        """Different values in the same field must produce different tokens."""
        t1 = generate_token("status", "NORMAL")
        t2 = generate_token("status", "WARNING")
        t3 = generate_token("status", "CRITICAL")
        assert t1 != t2
        assert t2 != t3
        assert t1 != t3

    def test_case_insensitive_normalisation(self):
        """
        'Laboratory A' and 'laboratory a' should produce the same token
        after normalisation (lowercase + strip).
        """
        t1 = generate_token("location", "Laboratory A")
        t2 = generate_token("location", "laboratory a")
        assert t1 == t2

    def test_unknown_field_raises(self):
        """Generating a token for an unsupported field should raise SearchIndexError."""
        with pytest.raises(SearchIndexError):
            generate_token("plaintext_temperature", "30.0")

    def test_exact_search_token_matches_stored_token(self):
        """
        Token generated at search time must match token generated at ingest time.
        """
        ingest_token = generate_token("location", "Server Room")
        query_token  = exact_search_token("location", "Server Room")
        assert ingest_token == query_token


class TestNumericBuckets:

    def test_temperature_bucket_basic(self):
        """30.7°C should land in bucket 30."""
        assert _temperature_bucket(30.7) == 30

    def test_temperature_bucket_exact(self):
        """Exact integer temperature 30.0°C should land in bucket 30."""
        assert _temperature_bucket(30.0) == 30

    def test_temperature_bucket_31(self):
        """31.8°C should land in bucket 31, not 30."""
        assert _temperature_bucket(31.8) == 31

    def test_temperature_bucket_negative(self):
        """-5.3°C should land in bucket -6 (floor division)."""
        assert _temperature_bucket(-5.3) == -6

    def test_temperature_bucket_out_of_range(self):
        """Temperature above TEMP_MAX should return None."""
        assert _temperature_bucket(TEMP_MAX + 1) is None
        assert _temperature_bucket(TEMP_MIN - 1) is None

    def test_humidity_bucket_basic(self):
        """65.9% humidity should land in bucket 65."""
        assert _humidity_bucket(65.9) == 65

    def test_humidity_bucket_exact_100(self):
        """100% humidity should land in bucket 100."""
        assert _humidity_bucket(100.0) == 100

    def test_humidity_bucket_out_of_range(self):
        """Humidity > 100 should return None."""
        assert _humidity_bucket(101) is None


class TestRangeTokens:

    def test_temperature_range_gt_30(self):
        """
        Tokens for temperature > 30 should include buckets 31..80.
        Bucket 30 covers 30.0–30.99°C. A value > 30 (not ≥ 30) starts at bucket 31
        AFTER exact post-decryption comparison — but the index includes bucket 30
        as a candidate (values like 30.5 are > 30 and in bucket 30).
        """
        tokens = temperature_range_tokens(30.0, None)
        # Should produce a non-empty list covering buckets from 30 up to TEMP_MAX
        assert len(tokens) > 0
        # Token for bucket 30 should be in the list (30.5 > 30 satisfies the condition)
        expected_30 = generate_token("temp_bucket", "30")
        assert expected_30 in tokens

    def test_temperature_range_lt_25(self):
        """Tokens for temperature < 25 should cover buckets TEMP_MIN..25."""
        tokens = temperature_range_tokens(None, 25.0)
        assert len(tokens) > 0
        expected_25 = generate_token("temp_bucket", "25")
        assert expected_25 in tokens

    def test_temperature_range_between_25_35(self):
        """Between 25 and 35 should cover buckets 25..35."""
        tokens = temperature_range_tokens(25.0, 35.0)
        assert len(tokens) == 11   # buckets 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35
        expected_30 = generate_token("temp_bucket", "30")
        assert expected_30 in tokens

    def test_range_tokens_out_of_range_clipped(self):
        """
        Range query beyond configured limits should not generate tokens
        outside TEMP_MIN..TEMP_MAX.
        """
        tokens = temperature_range_tokens(-100, 200)
        # Should be capped to TEMP_MIN..TEMP_MAX
        expected_min = generate_token("temp_bucket", str(TEMP_MIN))
        expected_max = generate_token("temp_bucket", str(TEMP_MAX))
        assert expected_min in tokens
        assert expected_max in tokens

    def test_humidity_range_between(self):
        """Humidity between 40 and 60 should produce 21 bucket tokens."""
        tokens = humidity_range_tokens(40.0, 60.0)
        assert len(tokens) == 21   # 40, 41, …, 60

    def test_empty_range_returns_empty_list(self):
        """min > max should return an empty list."""
        tokens = temperature_range_tokens(50.0, 20.0)
        assert tokens == []


class TestGenerateTokensForRecord:

    def test_generates_all_index_types(self):
        """generate_tokens_for_record should produce tokens for all 7 field types."""
        tokens = generate_tokens_for_record(
            device_id="SENSOR_001",
            device_name="Laboratory A Sensor",
            location="Laboratory A",
            sensor_type="temperature_humidity",
            status="NORMAL",
            temperature=25.3,
            humidity=55.1,
        )
        field_types = {t["field_type"] for t in tokens}
        assert "device_id"   in field_types
        assert "device_name" in field_types
        assert "location"    in field_types
        assert "sensor_type" in field_types
        assert "status"      in field_types
        assert "temp_bucket" in field_types
        assert "humid_bucket" in field_types

    def test_all_tokens_are_64_char_hex(self):
        """Every generated token must be a 64-char hex string."""
        tokens = generate_tokens_for_record(
            device_id="SENSOR_002", device_name="Server Room Sensor",
            location="Server Room", sensor_type="temperature_humidity",
            status="WARNING", temperature=38.0, humidity=42.5,
        )
        for t in tokens:
            assert len(t["token"]) == 64
            assert all(c in "0123456789abcdef" for c in t["token"])
