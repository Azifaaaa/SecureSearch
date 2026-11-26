"""
app.py — SecureSearch Cloud Flask Application Entry Point

Startup sequence:
  1. Load configuration from environment variables.
  2. Load cryptographic keys (fails fast if keys are missing).
  3. Initialise the database and create tables.
  4. Initialise the storage adapter (local or Supabase).
  5. Register all API blueprints.
  6. Register the main HTML template routes.
"""
import os
import logging

from flask import Flask, render_template, session, redirect, url_for, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import get_config
from backend.key_manager import key_manager
from backend.database import init_db
from backend.cloud_storage import init_storage

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(config_override=None) -> Flask:
    """
    Application factory.

    Args:
        config_override: Optional config class to override the env-based selection.
                         Used in tests.

    Returns:
        Configured Flask application.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── Load configuration ───────────────────────────────────────────────────
    cfg = config_override if config_override else get_config()
    app.config.from_object(cfg)

    # ── Load cryptographic keys ──────────────────────────────────────────────
    # In testing mode, dummy keys are used so tests don't need real .env values.
    testing = app.config.get("TESTING", False)
    key_manager.load_keys(testing=testing)

    # ── Initialise database ──────────────────────────────────────────────────
    init_db(app)

    # ── Initialise storage adapter ───────────────────────────────────────────
    with app.app_context():
        init_storage(app.config)

    # ── Rate limiting ────────────────────────────────────────────────────────
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per minute"],
        storage_uri="memory://",
    )

    # ── Security headers ─────────────────────────────────────────────────────
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # NOTE: CSP is kept permissive for development. Tighten for production.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:;"
        )
        return response

    # ── Register API blueprints ──────────────────────────────────────────────
    from routes.auth      import auth_bp
    from routes.records   import records_bp
    from routes.search    import search_bp
    from routes.simulator import simulator_bp
    from routes.dashboard import dashboard_bp
    from routes.cloud     import cloud_bp

    for bp in [auth_bp, records_bp, search_bp, simulator_bp, dashboard_bp, cloud_bp]:
        app.register_blueprint(bp)

    # Rate-limit authentication endpoints more strictly
    limiter.limit("20 per minute")(auth_bp)

    # ── Template (HTML page) routes ──────────────────────────────────────────
    @app.route("/")
    def index():
        if session.get("user_id"):
            return redirect(url_for("dashboard_page"))
        return redirect(url_for("login_page"))

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/register")
    def register_page():
        return render_template("register.html")

    @app.route("/dashboard")
    def dashboard_page():
        return render_template("dashboard.html")

    @app.route("/monitoring")
    def monitoring_page():
        return render_template("monitoring.html")

    @app.route("/dataset")
    def dataset_page():
        return render_template("dataset.html")

    @app.route("/records")
    def records_page():
        return render_template("encrypted_records.html")

    @app.route("/search")
    def search_page():
        return render_template("search.html")

    @app.route("/integrity")
    def integrity_page():
        return render_template("integrity.html")

    @app.route("/cryptography")
    def cryptography_page():
        return render_template("cryptography.html")

    @app.route("/cloud-status")
    def cloud_status_page():
        return render_template("cloud_status.html")

    @app.route("/leakage")
    def leakage_page():
        return render_template("leakage.html")

    @app.route("/settings")
    def settings_page():
        return render_template("settings.html")

    @app.route("/history")
    def history_page():
        return render_template("history.html")

    @app.route("/about")
    def about_page():
        return render_template("about.html")

    # ── Error handlers ───────────────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "bad request", "detail": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "authentication required"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({"error": "too many requests — slow down"}), 429

    @app.errorhandler(500)
    def server_error(e):
        logger.error("Internal error: %s", e)
        return jsonify({"error": "internal server error"}), 500

    logger.info(
        "SecureSearch Cloud started — mode=%s storage=%s",
        "testing" if testing else os.environ.get("FLASK_ENV", "development"),
        app.config.get("STORAGE_MODE", "local"),
    )

    return app


# ── Run directly ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    application = create_app()
    application.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_ENV", "development") == "development",
    )
