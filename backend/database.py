"""
backend/database.py — SQLAlchemy database initialisation

Provides the shared SQLAlchemy db instance and an init_db() helper.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    """Bind the SQLAlchemy instance to the Flask app and create all tables."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
