"""
backend/simulator_service.py — Virtual IoT sensor simulator

This module simulates five virtual sensor devices without any physical hardware.
Readings are synthetic/generated values, NOT from a real sensor.

Devices:
  SENSOR_001 — Laboratory A
  SENSOR_002 — Server Room
  SENSOR_003 — Library
  SENSOR_004 — Classroom
  SENSOR_005 — Laboratory B

Each device has realistic baseline ranges and occasional anomalies.
"""
import random
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)

# ── Device profiles ──────────────────────────────────────────────────────────────

DEVICE_PROFILES = [
    {
        "device_id":   "SENSOR_001",
        "device_name": "Laboratory A Sensor",
        "location":    "Laboratory A",
        "sensor_type": "temperature_humidity",
        "temp_mean":   22.0,   # °C
        "temp_std":    2.5,
        "humid_mean":  55.0,   # %
        "humid_std":   8.0,
    },
    {
        "device_id":   "SENSOR_002",
        "device_name": "Server Room Sensor",
        "location":    "Server Room",
        "sensor_type": "temperature_humidity",
        "temp_mean":   28.0,
        "temp_std":    3.0,
        "humid_mean":  40.0,
        "humid_std":   5.0,
    },
    {
        "device_id":   "SENSOR_003",
        "device_name": "Library Sensor",
        "location":    "Library",
        "sensor_type": "temperature_humidity",
        "temp_mean":   21.0,
        "temp_std":    1.5,
        "humid_mean":  50.0,
        "humid_std":   6.0,
    },
    {
        "device_id":   "SENSOR_004",
        "device_name": "Classroom Sensor",
        "location":    "Classroom",
        "sensor_type": "temperature_humidity",
        "temp_mean":   24.0,
        "temp_std":    3.5,
        "humid_mean":  60.0,
        "humid_std":   10.0,
    },
    {
        "device_id":   "SENSOR_005",
        "device_name": "Laboratory B Sensor",
        "location":    "Laboratory B",
        "sensor_type": "temperature_humidity",
        "temp_mean":   23.0,
        "temp_std":    2.0,
        "humid_mean":  52.0,
        "humid_std":   7.0,
    },
]

DEVICE_ID_TO_PROFILE = {p["device_id"]: p for p in DEVICE_PROFILES}

# ── Status thresholds ────────────────────────────────────────────────────────────
# Temperature: >35°C = WARNING, >40°C = CRITICAL
# Humidity:    >80%  = WARNING, >90%  = CRITICAL

def _determine_status(temperature: float, humidity: float) -> str:
    if temperature > 40.0 or humidity > 90.0:
        return "CRITICAL"
    if temperature > 35.0 or humidity > 80.0:
        return "WARNING"
    return "NORMAL"


def generate_reading(device_id: Optional[str] = None, seed: Optional[int] = None) -> dict:
    """
    Generate a single synthetic sensor reading.

    Args:
        device_id: Which device to simulate (random if None).
        seed:      Optional random seed for reproducibility.

    Returns:
        A dict representing one sensor reading (all fields plaintext at this stage).
        The caller is responsible for encrypting this reading before storage.

    NOTE: All returned values are SYNTHETIC/SIMULATED. They do not come
          from any physical device.
    """
    rng = random.Random(seed) if seed is not None else random

    if device_id and device_id in DEVICE_ID_TO_PROFILE:
        profile = DEVICE_ID_TO_PROFILE[device_id]
    else:
        profile = rng.choice(DEVICE_PROFILES)

    # Inject anomalies ~5% of the time for realism
    anomaly = rng.random() < 0.05
    temp_offset = rng.gauss(0, 8) if anomaly else 0
    humid_offset = rng.gauss(0, 15) if anomaly else 0

    temperature = round(
        rng.gauss(profile["temp_mean"], profile["temp_std"]) + temp_offset, 2
    )
    humidity = round(
        rng.gauss(profile["humid_mean"], profile["humid_std"]) + humid_offset, 2
    )

    # Clamp to realistic physical limits
    temperature = max(-10.0, min(60.0, temperature))
    humidity = max(0.0, min(100.0, humidity))

    status = _determine_status(temperature, humidity)

    reading = {
        "device_id":    profile["device_id"],
        "device_name":  profile["device_name"],
        "location":     profile["location"],
        "sensor_type":  profile["sensor_type"],
        "temperature":  temperature,
        "humidity":     humidity,
        "status":       status,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "simulated":    True,   # Always mark readings as simulated
    }
    return reading


# ── Background Simulator Thread ──────────────────────────────────────────────────

class SimulatorService:
    """
    Background thread that periodically generates readings and delivers
    them to a callback function (usually a Flask route that encrypts
    and stores the reading).

    Thread safety:
      _running and _status are protected by _lock.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self._interval = 5          # seconds between readings
        self._device_id: Optional[str] = None
        self._callback: Optional[Callable] = None
        self._readings_generated = 0
        self._last_reading: Optional[dict] = None

    def start(self, interval: int = 5,
              device_id: Optional[str] = None,
              callback: Optional[Callable] = None) -> dict:
        """Start the background simulator thread."""
        with self._lock:
            if self._running:
                return {"status": "already_running", "interval": self._interval}
            self._interval = max(1, int(interval))
            self._device_id = device_id
            self._callback = callback
            self._running = True

        self._thread = threading.Thread(target=self._run, daemon=True, name="SimulatorThread")
        self._thread.start()
        logger.info("Simulator started (interval=%ds, device=%s)", self._interval, self._device_id)
        return {"status": "started", "interval": self._interval, "device_id": self._device_id}

    def stop(self) -> dict:
        """Signal the simulator thread to stop."""
        with self._lock:
            if not self._running:
                return {"status": "already_stopped"}
            self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 2)
        logger.info("Simulator stopped after %d readings.", self._readings_generated)
        return {"status": "stopped", "readings_generated": self._readings_generated}

    def status(self) -> dict:
        with self._lock:
            return {
                "running":            self._running,
                "interval":           self._interval,
                "device_id":          self._device_id,
                "readings_generated": self._readings_generated,
                "last_reading":       self._last_reading,
            }

    def _run(self):
        """Main loop of the simulator background thread."""
        while True:
            with self._lock:
                if not self._running:
                    break
                interval = self._interval
                device_id = self._device_id
                callback = self._callback

            reading = generate_reading(device_id=device_id)

            with self._lock:
                self._readings_generated += 1
                self._last_reading = reading

            if callback:
                try:
                    callback(reading)
                except Exception as exc:
                    logger.error("Simulator callback error: %s", exc)

            time.sleep(interval)


# Module-level singleton
simulator_service = SimulatorService()
