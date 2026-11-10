"""Sentence-BERT (SBERT) Semantic Matching Service.

Provides dense semantic vector embeddings and cosine similarity matching between
candidate profiles and ESCO occupation profiles, with persistent caching and
graceful fallbacks if dependencies are absent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_PATH = BASE_DIR / "data" / "esco_occupation_embeddings.npz"
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class SBERTService:
    """
    Sentence-BERT semantic embedding and similarity service.
    Loads sentence-transformers model once, caches occupation embeddings to disk,
    and calculates semantic similarity against candidate profiles.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_path: Optional[str | Path] = None,
        device: Optional[str] = None,
    ):
        self.model_name = model_name or os.getenv("SBERT_MODEL_NAME", DEFAULT_MODEL_NAME)
        self.cache_path = Path(cache_path or os.getenv("SBERT_CACHE_PATH", DEFAULT_CACHE_PATH))
        self.device = device or os.getenv("SBERT_DEVICE", "cpu")

        self._model: Any = None
        self._is_available: bool = False
        self._load_error: Optional[str] = None
        self._occupation_embeddings: Dict[str, np.ndarray] = {}  # occupation_id -> vector
        self._dataset_hash: Optional[str] = None

    def initialize_model(self) -> bool:
        """
        Attempts to load the SentenceTransformer model.
        Returns True if successful, False otherwise.
        """
        if self._is_available and self._model is not None:
            return True

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._is_available = True
            self._load_error = None
            logger.info("Successfully loaded SBERT model: %s", self.model_name)
            return True
        except Exception as exc:
            self._is_available = False
            self._load_error = str(exc)
            logger.warning("Could not load SBERT model '%s': %s", self.model_name, exc)
            return False

    @property
    def is_available(self) -> bool:
        """Returns True if the SBERT model is successfully initialized."""
        if not self._is_available and self._load_error is None:
            self.initialize_model()
        return self._is_available

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def encode(self, texts: Union[str, List[str]]) -> np.ndarray:
        """
        Generates dense embeddings for one or more text strings.
        Returns float32 numpy array.
        """
        if isinstance(texts, str):
            single = True
            text_list = [texts]
        else:
            single = False
            text_list = texts

        if not text_list:
            return np.zeros((0, 384), dtype=np.float32)

        # Sanitize empty text
        sanitized = [t.strip() if (t and isinstance(t, str)) else "Empty" for t in text_list]

        if self.is_available and self._model is not None:
            embeddings = self._model.encode(
                sanitized,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return embeddings[0] if single else embeddings

        # Fallback pseudo-embedding if model unavailable (deterministic word-hash projection)
        logger.debug("Generating fallback representation (SBERT unavailable)")
        fallback_vecs = []
        for text in sanitized:
            vec = np.zeros(384, dtype=np.float32)
            words = text.lower().split()
            for i, w in enumerate(words):
                h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
                idx = h % 384
                vec[idx] += 1.0 / (1.0 + i * 0.1)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            fallback_vecs.append(vec)

        arr = np.array(fallback_vecs, dtype=np.float32)
        return arr[0] if single else arr

    @staticmethod
    def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Calculates cosine similarity between two 1D vectors."""
        if vec_a is None or vec_b is None:
            return 0.0
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        dot = np.dot(vec_a, vec_b)
        sim = float(dot / (norm_a * norm_b))
        return max(0.0, min(1.0, (sim + 1.0) / 2.0 if sim < 0 else sim))

    def compute_dataset_hash(self, occupations_dict: Dict[str, Any]) -> str:
        """Computes a SHA-256 hash of the occupation dataset text representation."""
        hasher = hashlib.sha256()
        hasher.update(self.model_name.encode("utf-8"))
        for occ_id in sorted(occupations_dict.keys()):
            record = occupations_dict[occ_id]
            desc = getattr(record, "description", "") or ""
            skills = ",".join(getattr(record, "essential_skills", []) or [])
            hasher.update(f"{occ_id}:{desc}:{skills}".encode("utf-8"))
        return hasher.hexdigest()

    def build_occupation_text(self, record: Any) -> str:
        """Combines title, description, and essential skills into a rich representation."""
        title = getattr(record, "title", "")
        desc = getattr(record, "description", "")
        skills = getattr(record, "essential_skills", []) or []
        skill_str = ", ".join(skills[:25])
        return f"{title}. {desc} Essential skills: {skill_str}."

    def ensure_occupation_embeddings(
        self,
        occupations: Dict[str, Any],
        force_refresh: bool = False,
    ) -> Dict[str, np.ndarray]:
        """
        Loads cached occupation embeddings or computes them and saves to disk.
        """
        if not occupations:
            return {}

        current_hash = self.compute_dataset_hash(occupations)

        # Check in-memory cache
        if (
            not force_refresh
            and self._dataset_hash == current_hash
            and len(self._occupation_embeddings) == len(occupations)
        ):
            return self._occupation_embeddings

        # Check on-disk cache
        if not force_refresh and self.cache_path.exists():
            try:
                data = np.load(self.cache_path, allow_pickle=True)
                cached_hash = str(data.get("dataset_hash", ""))
                if cached_hash == current_hash:
                    loaded_embeddings = {}
                    for key in data.files:
                        if key != "dataset_hash":
                            loaded_embeddings[key] = data[key]
                    if len(loaded_embeddings) == len(occupations):
                        self._occupation_embeddings = loaded_embeddings
                        self._dataset_hash = current_hash
                        return self._occupation_embeddings
            except Exception as exc:
                logger.warning("Could not read embedding cache file: %s", exc)

        # Generate fresh embeddings
        logger.info("Generating embeddings for %d occupations...", len(occupations))
        keys = list(occupations.keys())
        texts = [self.build_occupation_text(occupations[k]) for k in keys]
        vectors = self.encode(texts)

        embeddings_dict = {}
        for k, vec in zip(keys, vectors):
            embeddings_dict[k] = vec

        # Save to disk
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            save_payload = {k: v for k, v in embeddings_dict.items()}
            save_payload["dataset_hash"] = np.array(current_hash)
            np.savez_compressed(self.cache_path, **save_payload)
        except Exception as exc:
            logger.warning("Failed to save embedding cache to '%s': %s", self.cache_path, exc)

        self._occupation_embeddings = embeddings_dict
        self._dataset_hash = current_hash
        return embeddings_dict

    def calculate_similarities(
        self,
        candidate_summary: str,
        occupations: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        Calculates semantic similarity between candidate profile summary and all occupations.
        Returns dict: occupation_id -> similarity_score (in [0.0, 1.0]).
        """
        if not occupations:
            return {}

        occ_embeddings = self.ensure_occupation_embeddings(occupations)
        cand_vec = self.encode(candidate_summary)

        similarities: Dict[str, float] = {}
        for occ_id, occ_vec in occ_embeddings.items():
            sim = self.cosine_similarity(cand_vec, occ_vec)
            similarities[occ_id] = round(sim, 4)

        return similarities


# Global cached singleton instance
_GLOBAL_SBERT_SERVICE: Optional[SBERTService] = None


def get_sbert_service() -> SBERTService:
    global _GLOBAL_SBERT_SERVICE
    if _GLOBAL_SBERT_SERVICE is None:
        _GLOBAL_SBERT_SERVICE = SBERTService()
    return _GLOBAL_SBERT_SERVICE
