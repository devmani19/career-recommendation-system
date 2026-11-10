import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from .db import init_db


def create_app():
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
