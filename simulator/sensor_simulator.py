"""
simulator/sensor_simulator.py — Standalone sensor simulator script

This script runs outside the Flask application and sends simulated
sensor readings to the Flask backend API at regular intervals.

Usage:
    python simulator/sensor_simulator.py --url http://localhost:5000 \
        --username admin --password adminpass123 \
        --interval 5 --device SENSOR_001

All generated readings are SYNTHETIC/SIMULATED. No physical sensor is used.
"""
import sys
import os
import argparse
import time
import logging

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from backend.simulator_service import generate_reading, DEVICE_PROFILES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sensor_simulator")


def login(base_url: str, username: str, password: str) -> requests.Session:
    """Log in to the Flask application and return an authenticated session."""
    session = requests.Session()
    resp = session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Logged in as '%s'.", username)
    return session


def ingest_reading(session: requests.Session, base_url: str, reading: dict) -> str:
    """Send a reading to the backend ingest endpoint."""
    resp = session.post(
        f"{base_url}/api/records/ingest",
        json=reading,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("record_id", "?")


def run_simulator(args):
    """Main loop: generate and send readings until interrupted."""
    logger.info("=" * 60)
    logger.info("SecureSearch Cloud — Sensor Simulator")
    logger.info("NOTICE: All readings are SYNTHETIC/SIMULATED.")
    logger.info("        No physical IoT hardware is used.")
    logger.info("=" * 60)
    logger.info("Target URL : %s", args.url)
    logger.info("Device     : %s", args.device or "random")
    logger.info("Interval   : %ds", args.interval)
    logger.info("=" * 60)

    http_session = login(args.url, args.username, args.password)

    readings_sent = 0
    try:
        while True:
            reading = generate_reading(device_id=args.device or None)
            try:
                record_id = ingest_reading(http_session, args.url, reading)
                readings_sent += 1
                logger.info(
                    "[%d] %s | %s | %.1f°C | %.1f%% | %s → record %s",
                    readings_sent,
                    reading["device_id"],
                    reading["location"],
                    reading["temperature"],
                    reading["humidity"],
                    reading["status"],
                    record_id,
                )
            except requests.HTTPError as exc:
                logger.error("Ingest failed: %s", exc)
                # Re-login if session expired
                if exc.response is not None and exc.response.status_code == 401:
                    logger.info("Session expired — re-logging in.")
                    http_session = login(args.url, args.username, args.password)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("Simulator stopped. Total readings sent: %d", readings_sent)


def main():
    parser = argparse.ArgumentParser(
        description="SecureSearch Cloud — Virtual IoT Sensor Simulator"
    )
    parser.add_argument("--url", default="http://localhost:5000",
                        help="Base URL of the Flask backend")
    parser.add_argument("--username", default="admin",
                        help="Username to authenticate with")
    parser.add_argument("--password", default="adminpass123",
                        help="Password for the account")
    parser.add_argument("--interval", type=int, default=5,
                        help="Seconds between readings (default: 5)")
    parser.add_argument("--device", default=None,
                        choices=[p["device_id"] for p in DEVICE_PROFILES] + [None],
                        help="Specific device to simulate (default: random)")
    parser.add_argument("--count", type=int, default=0,
                        help="Number of readings to send (0 = run forever)")
    args = parser.parse_args()

    run_simulator(args)


if __name__ == "__main__":
    main()
