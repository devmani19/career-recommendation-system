"""XGBoost Supervised Career Relevance Service.

Implements the XGBClassifier training and inference pipeline for ranking
candidate-occupation recommendations. Gracefully detects whether a valid trained
model exists, provides strict candidate-grouped splitting to prevent data leakage,
and never fabricates experimental findings or claims an untrained model is working.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_MODEL_DIR = BASE_DIR / "data" / "models"
DEFAULT_MODEL_PATH = DEFAULT_MODEL_DIR / "xgboost_career_ranker.json"
DEFAULT_METADATA_PATH = DEFAULT_MODEL_DIR / "xgboost_metadata.json"

FEATURE_NAMES: List[str] = [
    "semantic_similarity",
    "skill_coverage",
    "qualification_fit",
    "experience_fit",
    "credential_confidence",
]


class XGBoostService:
    """
    XGBoost ranking and inference service.
    Loads trained model if present, predicts relevance probabilities,
    or transparently signals that no trained model is available.
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        metadata_path: Optional[str | Path] = None,
    ):
        env_path = os.getenv("XGBOOST_MODEL_PATH")
        self.model_path = Path(model_path or env_path or DEFAULT_MODEL_PATH)
        self.metadata_path = Path(metadata_path or DEFAULT_METADATA_PATH)

        self._model: Any = None
        self._is_loaded: bool = False
        self._metadata: Dict[str, Any] = {}
        self._try_load()

    def _try_load(self) -> bool:
        """Attempts to load a previously trained XGBoost model from disk."""
        if not self.model_path.exists():
            self._is_loaded = False
            return False

        try:
            import xgboost as xgb

            classifier = xgb.XGBClassifier()
            classifier.load_model(str(self.model_path))
            self._model = classifier
            self._is_loaded = True

            if self.metadata_path.exists():
                with open(self.metadata_path, "r", encoding="utf-8") as mf:
                    self._metadata = json.load(mf)
            logger.info("Loaded trained XGBoost model from %s", self.model_path)
            return True
        except Exception as exc:
            logger.warning("Could not load XGBoost model from %s: %s", self.model_path, exc)
            self._is_loaded = False
            return False

    @property
    def is_available(self) -> bool:
        """Returns True only when a verified trained model is loaded in memory."""
        return self._is_loaded and self._model is not None

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    def predict_relevance(self, feature_vector: Union[List[float], np.ndarray]) -> float:
        """
        Predicts relevance probability for a single feature vector.
        Requires is_available to be True.
        """
        if not self.is_available:
            raise RuntimeError(
                "XGBoost model is not trained or loaded. "
                "Use the weighted fallback scorer or train the model using scripts/train_career_model.py."
            )

        features = np.asarray(feature_vector, dtype=np.float32).reshape(1, -1)
        # Predict probability for class 1 (relevant)
        proba = self._model.predict_proba(features)[0, 1]
        return float(np.clip(proba, 0.0, 1.0))

    def predict_batch(self, feature_matrix: Union[List[List[float]], np.ndarray]) -> np.ndarray:
        """
        Predicts relevance probabilities for a batch of feature vectors.
        """
        if not self.is_available:
            raise RuntimeError("XGBoost model is not trained or loaded.")

        features = np.asarray(feature_matrix, dtype=np.float32)
        if features.ndim == 1:
            features = features.reshape(1, -1)
        probas = self._model.predict_proba(features)[:, 1]
        return np.clip(probas, 0.0, 1.0)

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        candidate_ids: Optional[List[str | int]] = None,
        val_size: float = 0.2,
        random_state: int = 42,
        n_estimators: int = 100,
        max_depth: int = 4,
        learning_rate: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Trains the XGBoost classifier on genuine labelled candidate-occupation examples.
        Uses GroupShuffleSplit when candidate_ids are provided to prevent data leakage.
        """
        import xgboost as xgb
        from sklearn.metrics import accuracy_score, f1_score, log_loss, roc_auc_score

        X_arr = np.asarray(X, dtype=np.float32)
        y_arr = np.asarray(y, dtype=np.int32)

        if len(X_arr) == 0 or len(y_arr) == 0:
            raise ValueError("Training dataset cannot be empty.")
        if len(np.unique(y_arr)) < 2:
            raise ValueError("Training dataset must contain at least 2 distinct classes (0 and 1).")

        # Group-aware splitting to avoid leakage
        if candidate_ids and len(candidate_ids) == len(X_arr):
            from sklearn.model_selection import GroupShuffleSplit

            gss = GroupShuffleSplit(n_splits=1, test_size=val_size, random_state=random_state)
            train_idx, val_idx = next(gss.split(X_arr, y_arr, groups=candidate_ids))
        else:
            from sklearn.model_selection import train_test_split

            _, class_counts = np.unique(y_arr, return_counts=True)
            can_stratify = bool(np.min(class_counts) >= 2) if len(class_counts) >= 2 else False

            train_idx, val_idx = train_test_split(
                np.arange(len(X_arr)),
                test_size=val_size,
                random_state=random_state,
                stratify=y_arr if can_stratify else None,
            )

        X_train, y_train = X_arr[train_idx], y_arr[train_idx]
        X_val, y_val = X_arr[val_idx], y_arr[val_idx]

        clf = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            eval_metric="logloss",
            random_state=random_state,
        )

        clf.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        val_preds = clf.predict(X_val)
        val_proba = clf.predict_proba(X_val)[:, 1]

        acc = float(accuracy_score(y_val, val_preds))
        f1 = float(f1_score(y_val, val_preds, zero_division=0))
        auc = float(roc_auc_score(y_val, val_proba)) if len(np.unique(y_val)) > 1 else 0.5
        loss = float(log_loss(y_val, val_proba))

        # Save model
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        clf.save_model(str(self.model_path))

        metadata = {
            "version": "1.0.0",
            "model_type": "XGBClassifier",
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "n_samples": int(len(X_arr)),
            "n_train": int(len(X_train)),
            "n_val": int(len(X_val)),
            "feature_names": FEATURE_NAMES,
            "hyperparameters": {
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "learning_rate": learning_rate,
                "random_state": random_state,
            },
            "validation_metrics": {
                "accuracy": round(acc, 4),
                "f1_score": round(f1, 4),
                "roc_auc": round(auc, 4),
                "log_loss": round(loss, 4),
            },
        }

        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        self._model = clf
        self._is_loaded = True
        self._metadata = metadata

        return metadata


# Global cached singleton instance
_GLOBAL_XGBOOST_SERVICE: Optional[XGBoostService] = None


def get_xgboost_service() -> XGBoostService:
    global _GLOBAL_XGBOOST_SERVICE
    if _GLOBAL_XGBOOST_SERVICE is None:
        _GLOBAL_XGBOOST_SERVICE = XGBoostService()
    return _GLOBAL_XGBOOST_SERVICE
