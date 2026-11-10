"""Tests for XGBoost Service."""

import numpy as np
import pytest
from app.services.xgboost_service import XGBoostService


def test_unavailable_behavior_when_not_trained(tmp_path):
    nonexistent = tmp_path / "nonexistent_model.json"
    service = XGBoostService(model_path=nonexistent)

    # Must honestly report that model is not available
    assert not service.is_available

    # Must raise RuntimeError if predict is attempted on untrained model
    with pytest.raises(RuntimeError) as exc_info:
        service.predict_relevance([0.5, 0.5, 0.5, 0.5, 0.5])
    assert "not trained or loaded" in str(exc_info.value)


def test_train_pipeline_and_grouped_splitting(tmp_path):
    model_path = tmp_path / "test_xgb_model.json"
    metadata_path = tmp_path / "test_xgb_meta.json"
    service = XGBoostService(model_path=model_path, metadata_path=metadata_path)

    # Synthesize labelled dataset with candidate groupings to test group split
    # 20 samples from 4 distinct candidates
    np.random.seed(42)
    X = np.random.uniform(0.0, 1.0, size=(20, 5)).astype(np.float32)
    # Target label: 1 if high coverage, else 0
    y = ((X[:, 0] + X[:, 1]) > 1.0).astype(np.int32)
    candidate_ids = ["cand_1"] * 5 + ["cand_2"] * 5 + ["cand_3"] * 5 + ["cand_4"] * 5

    metadata = service.train(
        X=X,
        y=y,
        candidate_ids=candidate_ids,
        val_size=0.25,
        n_estimators=10,
        max_depth=2,
    )

    # Check model was saved and loaded
    assert service.is_available
    assert model_path.exists()
    assert metadata_path.exists()

    # Predict probability
    prob = service.predict_relevance([0.8, 0.9, 0.7, 0.6, 0.5])
    assert 0.0 <= prob <= 1.0


def test_reload_trained_model(tmp_path):
    model_path = tmp_path / "test_xgb_model.json"
    metadata_path = tmp_path / "test_xgb_meta.json"

    # Train model
    s1 = XGBoostService(model_path=model_path, metadata_path=metadata_path)
    X = np.array([
        [0.9, 0.8, 0.7, 0.6, 0.5],
        [0.8, 0.7, 0.6, 0.5, 0.4],
        [0.1, 0.2, 0.1, 0.2, 0.1],
        [0.2, 0.1, 0.3, 0.1, 0.2],
    ], dtype=np.float32)
    y = np.array([1, 1, 0, 0], dtype=np.int32)
    s1.train(X, y, val_size=0.5, n_estimators=5, max_depth=2)

    # Load in new service instance
    s2 = XGBoostService(model_path=model_path, metadata_path=metadata_path)
    assert s2.is_available
    p = s2.predict_relevance([0.9, 0.8, 0.7, 0.6, 0.5])
    assert 0.0 <= p <= 1.0
