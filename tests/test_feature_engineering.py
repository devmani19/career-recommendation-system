"""Tests for Feature Engineering and Policy Rules."""

import pytest
from app.services.esco_service import OccupationRecord
from app.services.feature_engineering import (
    compute_credential_confidence,
    compute_experience_fit,
    compute_qualification_fit,
    compute_skill_coverage,
    extract_pair_features,
)
from app.services.resume_processing import CandidateProfile


@pytest.fixture
def sample_occupation():
    return OccupationRecord(
        occupation_id="urn:esco:test:1",
        title="Data Analyst",
        description="Analyzes data and builds reports.",
        essential_skills=["Python", "SQL", "Statistics", "Data Mining"],
        optional_skills=["Cloud Technologies", "Tableau"],
        all_skills=["Python", "SQL", "Statistics", "Data Mining", "Cloud Technologies", "Tableau"],
    )


def test_skill_coverage_calculation(sample_occupation):
    # Candidate with 3 of 4 essential skills
    cand_skills = ["Python", "SQL", "Statistics"]
    cov, matched, missing, opt_matched = compute_skill_coverage(cand_skills, sample_occupation)

    # Essential: 3/4 = 0.75 -> essential component 0.75 * 0.9 = 0.675
    assert cov > 0.6
    assert set(matched) == {"Python", "SQL", "Statistics"}
    assert missing == ["Data Mining"]
    assert opt_matched == []


def test_missing_qualification_fit_neutral_policy(sample_occupation):
    # Empty education gets documented neutral policy 0.5
    fit_empty = compute_qualification_fit("", sample_occupation)
    assert fit_empty == 0.5

    # Relevant degree gets 1.0
    fit_stem = compute_qualification_fit("B.Tech in Computer Science", sample_occupation)
    assert fit_stem == 1.0


def test_missing_experience_fit_neutral_policy(sample_occupation):
    # Candidate with 0 experience
    fit_zero = compute_experience_fit(0.0, sample_occupation)
    assert fit_zero >= 0.4

    # Candidate with 4 years
    fit_exp = compute_experience_fit(4.0, sample_occupation)
    assert fit_exp == 1.0


def test_credential_confidence_and_neutral_absence_policy(sample_occupation):
    # Absence of uploaded certificate MUST NEVER penalize (neutral 0.5)
    conf_none, status_none = compute_credential_confidence(None, sample_occupation)
    assert conf_none == 0.5
    assert status_none == "none"

    conf_empty, status_empty = compute_credential_confidence([], sample_occupation)
    assert conf_empty == 0.5
    assert status_empty == "none"

    # Valid verified certificate
    certs_valid = [{"filename": "cert.pdf", "verified": True, "status": "valid"}]
    conf_valid, status_valid = compute_credential_confidence(certs_valid, sample_occupation)
    assert conf_valid == 1.0
    assert status_valid == "valid"

    # Invalid certificate
    certs_invalid = [{"filename": "bad.pdf", "verified": False, "status": "invalid"}]
    conf_inv, status_inv = compute_credential_confidence(certs_invalid, sample_occupation)
    assert conf_inv == 0.0
    assert status_inv == "invalid"

    # Revoked certificate
    certs_revoked = [{"filename": "revoked.pdf", "status": "revoked"}]
    conf_rev, status_rev = compute_credential_confidence(certs_revoked, sample_occupation)
    assert conf_rev == 0.0
    assert status_rev == "revoked"


def test_feature_scaling():
    candidate = CandidateProfile(
        candidate_name="Alice",
        skills=["Python", "SQL"],
        education="Bachelor of Science",
        experience_years=2.0,
    )
    occ = OccupationRecord(
        occupation_id="urn:esco:test:2",
        title="Data Engineer",
        description="ETL pipelines",
        essential_skills=["Python", "SQL", "Spark"],
    )

    features = extract_pair_features(candidate, occ, semantic_similarity=0.82)
    vec = features.to_vector()
    assert len(vec) == 5
    for val in vec:
        assert 0.0 <= val <= 1.0
