import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from .db import init_db


def create_app():
    if os.environ.get("K_SERVICE"):
        required_settings = ["SECRET_KEY", "AUTH_SECRET_PEPPER", "DATABASE_TYPE"]
        if os.environ.get("DATABASE_TYPE", "").lower() in {"postgres", "postgresql"}:
            required_settings.append("DATABASE_URL")
        elif os.environ.get("DATABASE_TYPE", "").lower() == "mysql":
            required_settings.extend(("MYSQL_DB", "MYSQL_USER", "MYSQL_PASSWORD"))
        if os.environ.get("EMAIL_PROVIDER", "smtp").lower() in {"resend", "brevo"}:
            required_settings.extend(("EMAIL_API_KEY", "EMAIL_FROM"))
        else:
            required_settings.extend(("SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"))
        missing_settings = [name for name in required_settings if not os.environ.get(name)]
        if missing_settings:
            raise RuntimeError(
                "Missing required Cloud Run configuration: " + ", ".join(missing_settings)
            )

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(32)
    app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "..", "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.config["DATABASE"] = os.path.join(os.path.dirname(__file__), "..", "data", "career_app.db")
    app.config["MAX_FORM_MEMORY_SIZE"] = 20 * 1024 * 1024

    from datetime import timedelta
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    init_db()

    from .routes import assessment_bp, main
    from .routes.auth_routes import auth_bp
    from .routes.recommendation_routes import api_v1

    app.register_blueprint(main)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_v1)
    app.register_blueprint(assessment_bp)
    return app
