"""
scripts/initialize_database.py — Initialize the SQLite database and seed default data

Run once after setting up your .env file:
    python scripts/initialize_database.py

Creates all tables and optionally seeds:
  - A default admin user
  - Device records for all 5 simulated sensors
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Set testing=False so real keys are required
os.environ.setdefault("FLASK_ENV", "development")

from app import create_app
from backend.database import db
from backend.models import User, Device
from backend.simulator_service import DEVICE_PROFILES
from werkzeug.security import generate_password_hash
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("initialize_database")


def main():
    app = create_app()
    with app.app_context():
        # Create all tables
        db.create_all()
        logger.info("Database tables created.")

        # Seed device records if not present
        for profile in DEVICE_PROFILES:
            existing = Device.query.filter_by(device_id=profile["device_id"]).first()
            if not existing:
                device = Device(
                    device_id=profile["device_id"],
                    device_name=profile["device_name"],
                    location=profile["location"],
                    sensor_type=profile["sensor_type"],
                    status="ACTIVE",
                )
                db.session.add(device)
                logger.info("Seeded device: %s", profile["device_id"])

        # Create default admin user if no users exist
        if User.query.count() == 0:
            admin = User(
                username="admin",
                email="admin@securesearch.local",
                password_hash=generate_password_hash("adminpass123"),
                role="admin",
            )
            db.session.add(admin)
            logger.info("Created default admin user (username=admin, password=adminpass123)")
            logger.info("IMPORTANT: Change the default password before using in production!")

        db.session.commit()
        logger.info("Database initialisation complete.")


if __name__ == "__main__":
    main()
