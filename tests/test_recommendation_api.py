"""Tests for Recommendation REST API Endpoints."""

import json
import pytest
from app import create_app
from app.db import create_user, init_db


@pytest.fixture
def app_client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "testuser"
        yield client


def test_api_status_endpoint(app_client):
    res = app_client.get("/api/v1/recommendations/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "esco_loaded" in data
    assert "sbert_available" in data
    assert "xgboost_trained" in data


def test_api_unauthorized_access(app_client):
    # Request without session or auth header must return 401
    payload = {
        "candidate_name": "Test User",
        "profile": {"skills": ["Python", "SQL"]},
    }
    res = app_client.post("/api/v1/recommendations", json=payload)
    assert res.status_code == 401
    data = res.get_json()
    assert data["success"] is False
    assert "Authentication required" in data["error"]


def test_api_validation_errors(authenticated_client):
    # Not JSON
    res_raw = authenticated_client.post("/api/v1/recommendations", data="plain text")
    assert res_raw.status_code == 400

    # Negative experience years
    bad_exp_payload = {
        "profile": {
            "skills": ["Python"],
            "experience_years": -5,
        }
    }
    res_exp = authenticated_client.post("/api/v1/recommendations", json=bad_exp_payload)
    assert res_exp.status_code == 400
    assert "cannot be negative" in res_exp.get_json()["error"]

    # Invalid skills type
    bad_skills_payload = {
        "profile": {
            "skills": 12345,
        }
    }
    res_skills = authenticated_client.post("/api/v1/recommendations", json=bad_skills_payload)
    assert res_skills.status_code == 400


def test_api_successful_recommendation(authenticated_client):
    payload = {
        "candidate_name": "Taylor Example",
        "profile": {
            "skills": ["Python", "SQL", "Statistics", "Machine Learning"],
            "education": "B.Tech Computer Science",
            "experience_years": 1.5,
            "projects": ["Predictive Analytics System"],
            "certifications": [],
        },
        "limit": 3,
    }

    res = authenticated_client.post("/api/v1/recommendations", json=payload)
    assert res.status_code == 200
    data = res.get_json()

    assert data["success"] is True
    assert "ranking_method" in data
    assert data["ranking_method"] in ["xgboost", "weighted_fallback"]
    assert len(data["recommendations"]) > 0

    top_rec = data["recommendations"][0]
    # Verify required schema from specification
    assert "occupation_id" in top_rec
    assert "occupation_title" in top_rec
    assert "rank" in top_rec
    assert "score" in top_rec
    assert "matched_skills" in top_rec
    assert "missing_skills" in top_rec
    assert "score_components" in top_rec
    assert "explanation" in top_rec
    assert top_rec["rank"] == 1


def test_candidate_data_isolation(authenticated_client, app_client):
    # Try querying a recommendation referencing non-existent or other user's record
    payload = {"recommendation_id": 999999}
    res = authenticated_client.post("/api/v1/recommendations", json=payload)
    assert res.status_code == 404
