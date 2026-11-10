"""Tests for ESCO Dataset Service."""

import json
from pathlib import Path
import pytest
from app.services.esco_service import ESCOService, OccupationRecord


def test_load_real_esco_dataset():
    service = ESCOService()
    service.load_dataset()
    assert service.is_loaded

    occupations = service.get_occupations()
    assert len(occupations) > 0

    # Check that real ESCO fields exist
    record = next(iter(occupations.values()))
    assert isinstance(record, OccupationRecord)
    assert record.occupation_id.startswith("http") or record.occupation_id.startswith("urn")
    assert len(record.title) > 0
    assert len(record.description) > 0
    assert isinstance(record.essential_skills, list)
    assert len(record.essential_skills) > 0


def test_get_occupation_queries():
    service = ESCOService()
    service.load_dataset()

    data_analyst = service.get_occupation_by_title("data analyst")
    assert data_analyst is not None
    assert "data analyst" in data_analyst.title.lower()

    # Query by ESCO URI
    by_uri = service.get_occupation_by_id(data_analyst.occupation_id)
    assert by_uri is not None
    assert by_uri.title == data_analyst.title


def test_missing_esco_file_handling(tmp_path):
    missing_path = tmp_path / "nonexistent_esco.json"
    service = ESCOService(dataset_path=missing_path)

    with pytest.raises(FileNotFoundError) as exc_info:
        service.load_dataset()
    assert "ESCO dataset file not found" in str(exc_info.value)


def test_malformed_esco_data_handling(tmp_path):
    corrupt_file = tmp_path / "corrupt_esco.json"
    corrupt_file.write_text("{ this is not valid json :", encoding="utf-8")

    service = ESCOService(dataset_path=corrupt_file)
    with pytest.raises(ValueError) as exc_info:
        service.load_dataset()
    assert "not valid JSON" in str(exc_info.value)


def test_empty_esco_data_handling(tmp_path):
    empty_file = tmp_path / "empty_esco.json"
    empty_file.write_text("{}", encoding="utf-8")

    service = ESCOService(dataset_path=empty_file)
    with pytest.raises(ValueError) as exc_info:
        service.load_dataset()
    assert "empty or invalid" in str(exc_info.value)
