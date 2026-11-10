"""Tests for Skill Normalization Module."""

import pytest
from app.services.skill_normalization import (
    clean_skill_string,
    normalize_skill_list,
    normalize_skill_name,
)


def test_alias_normalization():
    assert normalize_skill_name("ML") == "Machine Learning"
    assert normalize_skill_name("ml") == "Machine Learning"
    assert normalize_skill_name("JS") == "JavaScript"
    assert normalize_skill_name("py") == "Python"
    assert normalize_skill_name("k8s") == "Kubernetes"
    assert normalize_skill_name("nlp") == "Natural Language Processing"


def test_distinct_technologies_preserved():
    # Distinct databases must NOT be merged into a single generic database term
    pg = normalize_skill_name("PostgreSQL")
    my = normalize_skill_name("MySQL")
    sql = normalize_skill_name("SQL")
    assert pg == "PostgreSQL"
    assert my == "MySQL"
    assert sql == "SQL"
    assert pg != my
    assert pg != sql


def test_capitalization_and_whitespace():
    assert normalize_skill_name("  machine learning  ") == "Machine Learning"
    assert normalize_skill_name("PYTHON") == "Python"
    assert normalize_skill_name("docker") == "Docker"


def test_special_characters_preserved():
    assert normalize_skill_name("c++") == "C++"
    assert normalize_skill_name("c#") == "C#"
    assert normalize_skill_name(".net") == ".NET"
    assert normalize_skill_name("node.js") == "Node.js"


def test_deduplication_and_sorting():
    raw_list = ["Python", "python", "PYTHON", "ML", "Machine Learning", "SQL", "sql"]
    normalized = normalize_skill_list(raw_list)
    assert normalized == ["Machine Learning", "Python", "SQL"]


def test_empty_and_unknown_skills():
    assert normalize_skill_name("") == ""
    assert normalize_skill_name(None) == ""
    assert normalize_skill_name("   ") == ""
    assert normalize_skill_list([]) == []
    assert normalize_skill_list([None, "", "  "]) == []

    # Unknown term gets clean title capitalization
    assert normalize_skill_name("quantum entanglement computing") == "Quantum Entanglement Computing"
