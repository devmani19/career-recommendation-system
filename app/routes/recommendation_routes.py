"""Recommendation REST API Routes Blueprint.

Exposes POST /api/v1/recommendations and GET /api/v1/recommendations/status.
Provides strict authentication, input validation, candidate data isolation,
and standardized JSON responses based on real ESCO data and ML models.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, session

from ..db import get_db_connection, save_recommendation
from ..services.career_recommendation_service import get_career_recommendation_service
from ..services.esco_service import get_esco_service
from ..services.resume_processing import CandidateProfile
from ..services.sbert_service import get_sbert_service
from ..services.skill_normalization import normalize_skill_list
from ..services.xgboost_service import get_xgboost_service

logger = logging.getLogger(__name__)

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def get_current_user_id() -> Optional[int]:
    """Retrieves user_id from active session or authorization header."""
    user_id = session.get("user_id")
    if user_id:
        return int(user_id)

    # Header-based fallback for API testing (e.g. Postman / pytest)
    auth_header = request.headers.get("X-User-Id")
    if auth_header and auth_header.isdigit():
        return int(auth_header)

    return None


@api_v1.route("/recommendations/status", methods=["GET"])
def get_recommendation_status():
    """
    Returns public health/status of the recommendation engine components:
    - ESCO knowledge base loading state
    - SBERT embedding service availability
    - XGBoost trained model status
    """
    esco_srv = get_esco_service()
    sbert_srv = get_sbert_service()
    xgb_srv = get_xgboost_service()

    return jsonify({
        "success": True,
        "esco_loaded": esco_srv.is_loaded,
        "esco_occupations_count": len(esco_srv.get_occupations()) if esco_srv.is_loaded else 0,
        "sbert_model_name": sbert_srv.model_name,
        "sbert_available": sbert_srv.is_available,
        "xgboost_trained": xgb_srv.is_available,
        "xgboost_metadata": xgb_srv.metadata if xgb_srv.is_available else None,
        "fallback_active": not xgb_srv.is_available,
    }), 200


@api_v1.route("/recommendations", methods=["POST"])
def create_career_recommendations():
    """
    POST /api/v1/recommendations

    Accepts structured candidate profile data:
    {
        "candidate_name": "Taylor Example",
        "profile": {
            "skills": ["Python", "SQL", "Machine Learning"],
            "education": "B.Tech Computer Science",
            "experience_years": 1.5,
            "projects": ["Predictive Model"],
            "certifications": []
        },
        "limit": 5
    }

    Or flat profile structure, or reference to user's saved recommendation_id.
    """
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({
            "success": False,
            "error": "Authentication required. Please log in or provide a valid X-User-Id header.",
        }), 401

    if not request.is_json and not request.form:
        return jsonify({
            "success": False,
            "error": "Request body must be JSON formatted.",
        }), 400

    payload = request.get_json(silent=True) or {}

    # Support reference to user's prior recommendation while ensuring isolation
    ref_id = payload.get("recommendation_id")
    if ref_id is not None:
        conn = get_db_connection()
        record = conn.execute(
            "SELECT * FROM recommendations WHERE id = ? AND user_id = ?",
            (ref_id, user_id),
        ).fetchone()
        conn.close()

        if not record:
            return jsonify({
                "success": False,
                "error": "Recommendation reference not found or access denied.",
            }), 404

        try:
            stored_data = json.loads(record["result_json"])
            return jsonify({
                "success": True,
                "candidate_name": record["candidate_name"],
                "ranking_method": "stored_history",
                "recommendations": stored_data,
            }), 200
        except Exception as exc:
            return jsonify({
                "success": False,
                "error": f"Failed to parse stored recommendation: {exc}",
            }), 500

    # Extract profile attributes
    profile_data = payload.get("profile", payload)
    if not isinstance(profile_data, dict):
        return jsonify({
            "success": False,
            "error": "Field 'profile' must be a valid JSON object.",
        }), 400

    raw_skills = profile_data.get("skills", [])
    if isinstance(raw_skills, str):
        skills = [s.strip() for s in raw_skills.split(",") if s.strip()]
    elif isinstance(raw_skills, list):
        skills = [str(s).strip() for s in raw_skills if str(s).strip()]
    else:
        return jsonify({
            "success": False,
            "error": "Field 'skills' must be a list of strings or comma-separated string.",
        }), 400

    education = str(profile_data.get("education", "") or "").strip()
    raw_exp = profile_data.get("experience_years", 0.0)
    try:
        experience_years = float(raw_exp) if raw_exp is not None else 0.0
        if experience_years < 0:
            return jsonify({
                "success": False,
                "error": "Field 'experience_years' cannot be negative.",
            }), 400
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "error": "Field 'experience_years' must be a valid number.",
        }), 400

    projects = profile_data.get("projects", [])
    if isinstance(projects, str):
        projects = [projects]
    elif not isinstance(projects, list):
        projects = []

    certifications = profile_data.get("certifications", [])
    if isinstance(certifications, str):
        certifications = [certifications]
    elif not isinstance(certifications, list):
        certifications = []

    candidate_name = str(payload.get("candidate_name") or profile_data.get("candidate_name") or "Candidate").strip()
    limit = int(payload.get("limit", 5))
    limit = max(1, min(limit, 20))

    candidate_profile = CandidateProfile(
        candidate_name=candidate_name,
        skills=skills,
        education=education,
        experience_years=experience_years,
        projects=projects,
        certifications=certifications,
    )

    verified_certificates = payload.get("verified_certificates")

    try:
        recommender = get_career_recommendation_service()
        result = recommender.recommend(
            candidate_profile=candidate_profile,
            limit=limit,
            verified_certificates=verified_certificates,
        )

        # Persist recommendation in DB for this authenticated user
        save_recommendation(
            user_id=user_id,
            candidate_name=candidate_name,
            certificate_name=", ".join(certifications) if certifications else "Candidate Profile",
            score=json.dumps({rec["occupation_title"]: rec["score"] for rec in result["recommendations"]}),
            result_json=json.dumps(result["recommendations"]),
            ranking_method=result.get("ranking_method", "weighted_fallback"),
            model_version="1.0.0",
        )

        return jsonify(result), 200

    except Exception as exc:
        logger.exception("Error executing career recommendation: %s", exc)
        return jsonify({
            "success": False,
            "error": f"Failed to compute recommendations: {str(exc)}",
        }), 500
