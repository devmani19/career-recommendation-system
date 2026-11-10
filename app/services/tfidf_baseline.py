"""TF-IDF with Cosine Similarity Baseline Recommender.

Provides a classical Information Retrieval baseline using scikit-learn's TfidfVectorizer
and cosine similarity to compare against the proposed SBERT + XGBoost approach.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .esco_service import OccupationRecord

logger = logging.getLogger(__name__)


def preprocess_text(text: str) -> str:
    """Cleans and standardizes text for TF-IDF tokenization."""
    if not text:
        return ""
    # Lowercase, strip punctuation except alphanumeric and spaces
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return " ".join(cleaned.split())


class TFIDFBaseline:
    """
    TF-IDF and Cosine Similarity baseline model for career recommendation.
    Kept strictly independent of SBERT and XGBoost.
    """

    def __init__(self, ngram_range: Tuple[int, int] = (1, 2)):
        self.vectorizer = TfidfVectorizer(
            ngram_range=ngram_range,
            stop_words="english",
            sublinear_tf=True,
            norm="l2",
        )
        self._is_fitted: bool = False
        self._occupation_keys: List[str] = []
        self._occupation_matrix: Optional[np.ndarray] = None
        self._occupations_map: Dict[str, OccupationRecord] = {}

    def _build_occupation_document(self, occupation: OccupationRecord) -> str:
        """Constructs a combined document string from title, description, and skills."""
        title = occupation.title
        desc = occupation.description
        ess_skills = " ".join(occupation.essential_skills)
        opt_skills = " ".join(occupation.optional_skills)
        return preprocess_text(f"{title} {title} {desc} {ess_skills} {opt_skills}")

    def fit(self, occupations: Dict[str, OccupationRecord]) -> "TFIDFBaseline":
        """
        Fits the TF-IDF vectorizer on the corpus of occupation documents.
        """
        if not occupations:
            raise ValueError("Cannot fit TF-IDF baseline on an empty occupation dictionary.")

        self._occupations_map = dict(occupations)
        self._occupation_keys = list(occupations.keys())
        corpus = [self._build_occupation_document(occupations[k]) for k in self._occupation_keys]

        self._occupation_matrix = self.vectorizer.fit_transform(corpus)
        self._is_fitted = True
        return self

    def rank(
        self,
        candidate_text: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Transforms candidate text and ranks fitted occupations by cosine similarity.
        """
        if not self._is_fitted or self._occupation_matrix is None:
            raise RuntimeError("TFIDFBaseline must be fitted before ranking.")

        cleaned_cand = preprocess_text(candidate_text)
        if not cleaned_cand:
            return []

        cand_vector = self.vectorizer.transform([cleaned_cand])
        # Compute cosine similarity
        similarities = cosine_similarity(cand_vector, self._occupation_matrix)[0]

        # Sort indices descending
        ranked_indices = np.argsort(-similarities)

        results = []
        for rank_pos, idx in enumerate(ranked_indices[:limit], start=1):
            key = self._occupation_keys[idx]
            occ = self._occupations_map[key]
            sim_score = float(similarities[idx])
            results.append({
                "occupation_id": occ.occupation_id,
                "occupation_title": occ.title,
                "rank": rank_pos,
                "score": round(sim_score * 100.0, 2),
                "similarity": round(sim_score, 4),
                "ranking_method": "tfidf_cosine_baseline",
                "description": occ.description,
            })

        return results
