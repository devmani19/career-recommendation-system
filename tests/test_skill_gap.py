"""Tests for Skill-Gap Analysis Module."""

import pytest
from app.services.esco_service import OccupationRecord
from app.services.skill_gap_service import SkillGapService


@pytest.fixture
def ml_occupation():
    return OccupationRecord(
        occupation_id="urn:esco:ml",
        title="Machine Learning Engineer",
        description="Builds ML pipelines.",
        essential_skills=["Python", "Machine Learning", "Mathematics", "TensorFlow"],
        optional_skills=["Docker", "Cloud Technologies"],
    )


def test_analyze_skill_gap_identification(ml_occupation):
    service = SkillGapService()
    candidate_skills = ["Python", "Machine Learning"]

    report = service.analyze_gap(candidate_skills, ml_occupation)

    assert report.occupation_title == "Machine Learning Engineer"
    assert set(report.matched_essential_skills) == {"Python", "Machine Learning"}
    assert set(report.missing_essential_skills) == {"Mathematics", "TensorFlow"}
    assert report.essential_coverage_rate == 0.5
    assert len(report.action_items) > 0


def test_suggest_certifications_for_missing_skills():
    service = SkillGapService()
    missing = ["Python", "TensorFlow", "Docker"]
    certs = service.suggest_certifications(missing, limit=3)

    assert len(certs) > 0
    assert any("Python" in c for c in certs)
    assert any("TensorFlow" in c for c in certs)


def test_full_match_gap_report(ml_occupation):
    service = SkillGapService()
    candidate_skills = ["Python", "Machine Learning", "Mathematics", "TensorFlow", "Docker", "Cloud Technologies"]

    report = service.analyze_gap(candidate_skills, ml_occupation)
    assert report.missing_essential_skills == []
    assert report.essential_coverage_rate == 1.0
