"""Tests for SBERT Service and Embedding Generation."""

from unittest.mock import MagicMock
import numpy as np
import pytest
from app.services.sbert_service import SBERTService


def test_cosine_similarity_calculation():
    # Identical vectors
    v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    sim = SBERTService.cosine_similarity(v1, v2)
    assert pytest.approx(sim, 0.001) == 1.0

    # Orthogonal vectors
    v3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    sim_ortho = SBERTService.cosine_similarity(v1, v3)
    assert pytest.approx(sim_ortho, 0.001) == 0.0

    # Zero vectors
    v_zero = np.zeros(3, dtype=np.float32)
    assert SBERTService.cosine_similarity(v1, v_zero) == 0.0


def test_embedding_generation_and_fallback():
    service = SBERTService()
    # Generate embeddings for candidate and occupation descriptions
    texts = [
        "Data analyst with Python and SQL experience.",
        "Designs machine learning systems using PyTorch and scikit-learn.",
    ]
    embeddings = service.encode(texts)
    assert isinstance(embeddings, np.ndarray)
    assert len(embeddings) == 2
    assert embeddings.shape[1] == 384

    # Single text encode
    single = service.encode("Machine learning engineer")
    assert single.shape == (384,)


def test_embedding_caching(tmp_path):
    cache_file = tmp_path / "test_cache.npz"
    service = SBERTService(cache_path=cache_file)

    mock_occupations = {
        "Data Analyst": MagicMock(
            title="Data Analyst",
            description="Analyzes data and builds reports.",
            essential_skills=["SQL", "Python"],
        ),
        "Software Engineer": MagicMock(
            title="Software Engineer",
            description="Builds software applications.",
            essential_skills=["Java", "Git"],
        ),
    }

    # First run computes and creates cache
    emb_dict1 = service.ensure_occupation_embeddings(mock_occupations)
    assert len(emb_dict1) == 2
    assert cache_file.exists()

    # Second run loads from cache
    emb_dict2 = service.ensure_occupation_embeddings(mock_occupations)
    assert len(emb_dict2) == 2
    np.testing.assert_array_almost_equal(emb_dict1["Data Analyst"], emb_dict2["Data Analyst"])
