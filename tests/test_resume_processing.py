"""Tests for Resume Processing Service."""

from pathlib import Path
import pytest
from app.services.resume_processing import (
    CandidateProfile,
    build_candidate_profile,
    estimate_years_of_experience,
    extract_project_items,
    extract_raw_text,
    parse_resume_sections,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def test_estimate_experience_years():
    text1 = "I have 3.5 years of experience in data analysis and Python development."
    assert estimate_years_of_experience(text1) == 3.5

    text2 = "Software Engineer at TechCorp from 2020 to 2024 building web APIs."
    assert estimate_years_of_experience(text2) == 4.0

    text3 = ""
    assert estimate_years_of_experience(text3) == 0.0


def test_parse_sections():
    raw_resume = """
John Doe
Email: john@example.com

EDUCATION
Bachelor of Science in Computer Science, 2022

EXPERIENCE
Software Engineer at Acme Corp. Built backend microservices and REST APIs.

PROJECTS
• Predictive Analytics Engine: Machine learning model using Python.
• E-Commerce Web App: React and Flask system.

SKILLS
Python, SQL, Machine Learning, Docker
"""
    sections = parse_resume_sections(raw_resume)
    assert "Computer Science" in sections["education"]
    assert "Acme Corp" in sections["experience"]
    assert "Predictive Analytics" in sections["projects"]


def test_build_candidate_profile_from_sample():
    sample_file = BASE_DIR / "sample_data" / "sample_resume_data_analyst.txt"
    assert sample_file.exists()

    profile = build_candidate_profile(sample_file, candidate_name="Taylor Example")
    assert isinstance(profile, CandidateProfile)
    assert profile.candidate_name == "Taylor Example"
    assert len(profile.skills) > 0
    assert "Data Analytics" in profile.education or "Bachelor" in profile.education
    assert profile.experience_years >= 0.0

    # Summary text suitability for embeddings
    summary = profile.get_summary_text()
    assert "Skills:" in summary
    assert "Education:" in summary


def test_empty_and_corrupt_resume_handling():
    # Empty string
    empty_profile = build_candidate_profile("")
    assert empty_profile.skills == []
    assert empty_profile.education == ""
    assert empty_profile.experience_years == 0.0

    # None file
    none_profile = build_candidate_profile(None)
    assert none_profile.skills == []

    # Non-existent file
    nonexistent = build_candidate_profile("nonexistent_resume_file.pdf")
    assert nonexistent.skills == []
