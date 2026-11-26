"""
scripts/generate_dataset.py — Generate a synthetic IoT sensor dataset

Creates:
  data/sensor_dataset.csv    — 5000+ synthetic sensor readings (CSV)
  data/sample_records.json   — 50 sample records (JSON)

Usage:
    python scripts/generate_dataset.py
    python scripts/generate_dataset.py --records 10000 --seed 42

All records are marked as simulated=True. No physical sensor is used.
"""
import sys
import os
import argparse
import csv
import json
import random
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.simulator_service import DEVICE_PROFILES, _determine_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("generate_dataset")

DATA_DIR = Path("data")
CSV_PATH  = DATA_DIR / "sensor_dataset.csv"
JSON_PATH = DATA_DIR / "sample_records.json"

CSV_FIELDS = [
    "record_index", "device_id", "device_name", "location",
    "sensor_type", "temperature", "humidity", "status", "timestamp", "simulated"
]


def generate_records(n: int, seed: int) -> list:
    """
    Generate n synthetic sensor records with realistic patterns.

    Features:
      - Gaussian noise around device-specific baselines
      - Gradual temperature drift over the time window (simulates day/night)
      - 5% anomaly injection for realism
      - Reproducible with a fixed seed
    """
    rng = random.Random(seed)
    records = []

    # Distribute records over the past 30 days
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=30)
    total_seconds = (end_time - start_time).total_seconds()

    for i in range(n):
        profile = rng.choice(DEVICE_PROFILES)

        # Random timestamp within the window
        offset  = rng.uniform(0, total_seconds)
        ts      = start_time + timedelta(seconds=offset)

        # Day/night temperature cycle (±2°C over 24h)
        hour_of_day = ts.hour + ts.minute / 60
        day_cycle   = 2.0 * (hour_of_day - 14) / 12   # peak at 14:00

        anomaly = rng.random() < 0.05
        temp_offset  = rng.gauss(0, 7) if anomaly else rng.gauss(0, 1) * 0.3
        humid_offset = rng.gauss(0, 12) if anomaly else rng.gauss(0, 1) * 0.3

        temperature = round(
            rng.gauss(profile["temp_mean"] + day_cycle, profile["temp_std"]) + temp_offset, 2
        )
        humidity = round(
            rng.gauss(profile["humid_mean"], profile["humid_std"]) + humid_offset, 2
        )
        temperature = max(-10.0, min(60.0, temperature))
        humidity    = max(0.0, min(100.0, humidity))

        status = _determine_status(temperature, humidity)

        records.append({
            "record_index": i + 1,
            "device_id":    profile["device_id"],
            "device_name":  profile["device_name"],
            "location":     profile["location"],
            "sensor_type":  profile["sensor_type"],
            "temperature":  temperature,
            "humidity":     humidity,
            "status":       status,
            "timestamp":    ts.isoformat(),
            "simulated":    True,
        })

    # Sort by timestamp (chronological)
    records.sort(key=lambda r: r["timestamp"])
    return records


def save_csv(records: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    logger.info("CSV saved: %s (%d records)", path, len(records))


def save_json(records: list, path: Path, sample_size: int = 50) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = records[:sample_size]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2, default=str)
    logger.info("JSON sample saved: %s (%d records)", path, len(sample))


def print_summary(records: list) -> None:
    from collections import Counter
    statuses = Counter(r["status"] for r in records)
    devices  = Counter(r["device_id"] for r in records)
    temps    = [r["temperature"] for r in records]
    humids   = [r["humidity"] for r in records]

    logger.info("=" * 50)
    logger.info("Dataset Summary")
    logger.info("  Total records : %d", len(records))
    logger.info("  Status counts : %s", dict(statuses))
    logger.info("  Device counts : %s", dict(devices))
    logger.info("  Temp range    : %.1f°C — %.1f°C (mean %.1f°C)",
                min(temps), max(temps), sum(temps) / len(temps))
    logger.info("  Humidity range: %.1f%% — %.1f%% (mean %.1f%%)",
                min(humids), max(humids), sum(humids) / len(humids))
    logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic IoT sensor dataset")
    parser.add_argument("--records", type=int, default=5000,
                        help="Number of records to generate (default: 5000)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility (default: 42)")
    args = parser.parse_args()

    logger.info("Generating %d synthetic sensor records (seed=%d)...", args.records, args.seed)
    records = generate_records(args.records, args.seed)

    save_csv(records, CSV_PATH)
    save_json(records, JSON_PATH)
    print_summary(records)

    logger.info("Done. Files written to %s/", DATA_DIR)


if __name__ == "__main__":
    main()
