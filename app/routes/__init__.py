"""Routes package exposing main Blueprint and api_v1 Blueprint.
"""

from .main_routes import main
from .recommendation_routes import api_v1
from .assessment_routes import assessment_bp
from .auth_routes import auth_bp

__all__ = ["main", "api_v1", "assessment_bp", "auth_bp"]

