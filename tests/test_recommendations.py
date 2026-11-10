"""Tests for End-to-End Career Recommendation Pipeline."""

import pytest
from app.services.career_recommendation_service import CareerRecommendationService
from app.services.esco_service import ESCOService, OccupationRecord
from app.services.resume_processing import CandidateProfile


from app.services.xgboost_service import XGBoostService


@pytest.fixture
def dummy_recommender(tmp_path):
    # Setup mock ESCO occupations
    mock_esco = ESCOService()
    mock_esco._occupations = {
        "data analyst": OccupationRecord(
            occupation_id="urn:esco:occ:da",
            title="Data Analyst",
            description="Analyzes data and reports.",
            essential_skills=["Python", "SQL", "Statistics", "Data Visualization"],
            optional_skills=["Excel", "Tableau"],
        ),
        "software developer": OccupationRecord(
            occupation_id="urn:esco:occ:dev",
            title="Software Developer",
            description="Develops software applications.",
            essential_skills=["Java", "Git", "Algorithms", "Data Structures"],
            optional_skills=["SQL", "Docker"],
        ),
    }
    mock_esco._uri_index = {
        rec.occupation_id: rec for rec in mock_esco._occupations.values()
    }
    mock_esco._is_loaded = True

    # Pass explicitly untrained service to test fallback logic
    untrained_xgb = XGBoostService(model_path=tmp_path / "untrained_model.json")
    return CareerRecommendationService(esco_service=mock_esco, xgboost_service=untrained_xgb)


def test_weighted_fallback_recommendations(dummy_recommender):
    candidate = CandidateProfile(
        candidate_name="Alex Smith",
        skills=["Python", "SQL", "Statistics"],
        education="B.S. Computer Science",
        experience_years=2.0,
    )

    result = dummy_recommender.recommend(candidate, limit=2)
    assert result["success"] is True
    assert result["ranking_method"] == "weighted_fallback"
    assert len(result["recommendations"]) == 2

    top = result["recommendations"][0]
    assert top["occupation_title"] == "Data Analyst"
    assert top["rank"] == 1
    assert top["score"] > 0
    assert "Python" in top["matched_skills"]
    assert "Data Visualization" in top["missing_skills"]
    assert "explanation" in top
    assert len(top["explanation"]) > 0
    assert "score_components" in top
    assert "semantic_similarity" in top["score_components"]


def test_ranking_sort_order(dummy_recommender):
    candidate = CandidateProfile(
        candidate_name="Sam",
        skills=["Java", "Git", "Algorithms"],
        education="B.Tech Computer Science",
        experience_years=3.0,
    )

    result = dummy_recommender.recommend(candidate, limit=2)
    top = result["recommendations"][0]
    assert top["occupation_title"] == "Software Developer"
    assert result["recommendations"][0]["score"] >= result["recommendations"][1]["score"]
