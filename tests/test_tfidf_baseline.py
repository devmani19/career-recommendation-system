"""Tests for TF-IDF Cosine Similarity Baseline."""

import pytest
from app.services.esco_service import OccupationRecord
from app.services.tfidf_baseline import TFIDFBaseline, preprocess_text


def test_text_preprocessing():
    raw = "Senior Data Analyst, working with SQL & Python!"
    clean = preprocess_text(raw)
    assert clean == "senior data analyst working with sql python"


def test_fit_and_rank():
    occupations = {
        "Data Analyst": OccupationRecord(
            occupation_id="urn:esco:1",
            title="Data Analyst",
            description="Analyzes data, prepares dashboards, uses SQL and Excel.",
            essential_skills=["SQL", "Excel", "Data Visualization"],
        ),
        "Cybersecurity Specialist": OccupationRecord(
            occupation_id="urn:esco:2",
            title="Cybersecurity Specialist",
            description="Performs network defense, intrusion detection, penetration testing.",
            essential_skills=["Network Security", "Penetration Testing", "Firewalls"],
        ),
    }

    baseline = TFIDFBaseline()
    baseline.fit(occupations)

    candidate_text = "I am skilled in SQL databases, Excel spreadsheets, and data analytics dashboards."
    results = baseline.rank(candidate_text, limit=2)

    assert len(results) == 2
    assert results[0]["occupation_title"] == "Data Analyst"
    assert results[0]["rank"] == 1
    assert results[0]["ranking_method"] == "tfidf_cosine_baseline"
    assert results[0]["score"] > results[1]["score"]
