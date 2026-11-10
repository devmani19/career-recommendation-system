"""Career Recommendation Service.

Coordinates candidate profile processing, ESCO dataset retrieval, SBERT semantic
similarity, multi-feature generation, XGBoost relevance prediction (when trained)
or weighted fallback scoring, and skill-gap analysis.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .esco_service import ESCOService, OccupationRecord, get_esco_service
from .feature_engineering import (
    MatchingFeatures,
    extract_pair_features,
)
from .resume_processing import CandidateProfile
from .sbert_service import SBERTService, get_sbert_service
from .skill_gap_service import SkillGapService, get_skill_gap_service
from .skill_normalization import normalize_skill_list
from .xgboost_service import XGBoostService, get_xgboost_service

logger = logging.getLogger(__name__)


# Default initial heuristic weights for fallback ranking (must sum to 1.0)
DEFAULT_FALLBACK_WEIGHTS: Dict[str, float] = {
    "semantic_similarity": 0.40,
    "skill_coverage": 0.30,
    "qualification_fit": 0.15,
    "experience_fit": 0.10,
    "credential_confidence": 0.05,
}


@dataclass
class CareerRecommendation:
    """Standardized output structure for a single career recommendation."""
    occupation_id: str
    occupation_title: str
    rank: int
    score: float  # Percentage score [0.0, 100.0]
    raw_score: float  # Underlying model probability or weighted sum [0.0, 1.0]
    ranking_method: str  # "xgboost" or "weighted_fallback"
    matched_skills: List[str]
    missing_skills: List[str]
    score_components: Dict[str, float]
    explanation: str
    description: str
    suggested_certifications: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "occupation_id": self.occupation_id,
            "occupation_title": self.occupation_title,
            "rank": self.rank,
            "score": round(self.score, 1),
            "raw_score": round(self.raw_score, 4),
            "ranking_method": self.ranking_method,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "score_components": self.score_components,
            "explanation": self.explanation,
            "description": self.description,
            "suggested_certifications": self.suggested_certifications,
        }


def build_explanation(
    features: MatchingFeatures,
    ranking_method: str,
    occupation_title: str,
) -> str:
    """
    Constructs a factual, transparent explanation based on actual computed features.
    Never invents nonexistent reasons or fabricated claims.
    """
    sem_pct = round(features.semantic_similarity * 100, 1)
    cov_pct = round(features.skill_coverage * 100, 1)
    matched_count = len(features.matched_skills)
    missing_count = len(features.missing_skills)

    parts = []
    if ranking_method == "xgboost":
        parts.append("Ranked by trained XGBoost classifier.")
    else:
        parts.append("Ranked using multi-criteria weighted scoring.")

    if matched_count > 0:
        top_matched = ", ".join(features.matched_skills[:3])
        parts.append(f"Matches {matched_count} essential skills (e.g. {top_matched}) with {cov_pct}% skill coverage.")
    else:
        parts.append(f"No direct essential skill matches identified (skill coverage {cov_pct}%).")

    parts.append(f"Semantic profile alignment is {sem_pct}%.")

    if missing_count > 0:
        parts.append(f"Requires development in {missing_count} essential skills.")
    else:
        parts.append("Candidate matches all listed essential skills for this profile.")

    return " ".join(parts)


class CareerRecommendationService:
    """
    Reusable career recommendation engine orchestrating ESCO, SBERT, and XGBoost/fallback.
    """

    def __init__(
        self,
        esco_service: Optional[ESCOService] = None,
        sbert_service: Optional[SBERTService] = None,
        xgboost_service: Optional[XGBoostService] = None,
        skill_gap_service: Optional[SkillGapService] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.esco_service = esco_service or get_esco_service()
        self.sbert_service = sbert_service or get_sbert_service()
        self.xgboost_service = xgboost_service or get_xgboost_service()
        self.skill_gap_service = skill_gap_service or get_skill_gap_service()

        self.weights = weights or dict(DEFAULT_FALLBACK_WEIGHTS)
        # Normalize weights to ensure sum is 1.0
        total_w = sum(self.weights.values())
        if total_w > 0:
            self.weights = {k: v / total_w for k, v in self.weights.items()}

    def recommend(
        self,
        candidate_profile: CandidateProfile,
        limit: int = 5,
        verified_certificates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generates ranked career recommendations for the provided candidate profile.
        Returns a dictionary with 'ranking_method', 'recommendations', and metadata.
        """
        # 1. Normalize candidate skills
        candidate_profile.skills = normalize_skill_list(candidate_profile.skills)

        # 2. Retrieve ESCO occupations
        occupations = self.esco_service.get_occupations()
        if not occupations:
            raise RuntimeError("ESCO occupations dataset is empty or not loaded.")

        # 3. Compute SBERT semantic similarities
        summary_text = candidate_profile.get_summary_text()
        semantic_sims = self.sbert_service.calculate_similarities(summary_text, occupations)

        # 4. Check whether XGBoost is available
        use_xgboost = self.xgboost_service.is_available
        ranking_method = "xgboost" if use_xgboost else "weighted_fallback"

        # 5. Calculate features and scores for all candidate-occupation pairs
        scored_pairs: List[Tuple[float, OccupationRecord, MatchingFeatures, List[str]]] = []

        for title, occupation in occupations.items():
            sem_sim = semantic_sims.get(title, 0.0)
            features = extract_pair_features(
                candidate=candidate_profile,
                occupation=occupation,
                semantic_similarity=sem_sim,
                verified_certificates=verified_certificates,
            )

            # Skill gap analysis for certifications and detailed missing skills
            gap_report = self.skill_gap_service.analyze_gap(
                candidate_skills=candidate_profile.skills,
                occupation=occupation,
            )

            if use_xgboost:
                # Use supervised predicted probability
                score = self.xgboost_service.predict_relevance(features.to_vector())
            else:
                # Use documented transparent weighted fallback formula
                score = (
                    self.weights.get("semantic_similarity", 0.40) * features.semantic_similarity
                    + self.weights.get("skill_coverage", 0.30) * features.skill_coverage
                    + self.weights.get("qualification_fit", 0.15) * features.qualification_fit
                    + self.weights.get("experience_fit", 0.10) * features.experience_fit
                    + self.weights.get("credential_confidence", 0.05) * features.credential_confidence
                )

            scored_pairs.append((score, occupation, features, gap_report.suggested_certifications))

        # 6. Sort descending by score
        scored_pairs.sort(key=lambda x: x[0], reverse=True)

        # 7. Compile ranked results
        recommendations: List[CareerRecommendation] = []
        for rank_idx, (score, occupation, features, certs) in enumerate(scored_pairs[:limit], start=1):
            explanation = build_explanation(features, ranking_method, occupation.title)

            recommendations.append(
                CareerRecommendation(
                    occupation_id=occupation.occupation_id,
                    occupation_title=occupation.title,
                    rank=rank_idx,
                    score=float(score * 100.0),
                    raw_score=float(score),
                    ranking_method=ranking_method,
                    matched_skills=features.matched_skills,
                    missing_skills=features.missing_skills,
                    score_components=features.to_dict(),
                    explanation=explanation,
                    description=occupation.description,
                    suggested_certifications=certs,
                )
            )

        return {
            "success": True,
            "candidate_name": candidate_profile.candidate_name,
            "ranking_method": ranking_method,
            "recommendations": [rec.to_dict() for rec in recommendations],
            "weights_used": self.weights if not use_xgboost else None,
            "total_evaluated_occupations": len(occupations),
        }


# Global singleton instance
_GLOBAL_RECOMMENDER: Optional[CareerRecommendationService] = None


def get_career_recommendation_service() -> CareerRecommendationService:
    global _GLOBAL_RECOMMENDER
    if _GLOBAL_RECOMMENDER is None:
        _GLOBAL_RECOMMENDER = CareerRecommendationService()
    return _GLOBAL_RECOMMENDER
