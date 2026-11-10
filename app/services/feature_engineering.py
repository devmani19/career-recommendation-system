"""Career Matching Feature Engineering Module.

Calculates the 5 standardized features for each candidate-occupation pair:
1. Semantic Similarity (via SBERT)
2. Skill Coverage (matched essential/required skills / total required skills)
3. Qualification Fit (candidate education vs occupation education requirements)
4. Experience Fit (candidate years vs occupation expectations)
5. Credential Confidence (certificate verification status: Valid, Unverifiable, Invalid, Revoked, or None)

All features are strictly normalized to the [0.0, 1.0] interval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from .esco_service import OccupationRecord
from .resume_processing import CandidateProfile
from .skill_normalization import normalize_skill_name


@dataclass
class MatchingFeatures:
    """Standardized numerical features for a candidate-occupation pair."""
    semantic_similarity: float = 0.0
    skill_coverage: float = 0.0
    qualification_fit: float = 0.5
    experience_fit: float = 0.5
    credential_confidence: float = 0.5

    # Metadata for interpretability and auditability
    matched_skills: List[str] = None  # type: ignore
    missing_skills: List[str] = None  # type: ignore
    optional_matched_skills: List[str] = None  # type: ignore
    credential_status: str = "none"  # "valid", "unverifiable", "invalid", "revoked", "none"

    def __post_init__(self):
        if self.matched_skills is None:
            self.matched_skills = []
        if self.missing_skills is None:
            self.missing_skills = []
        if self.optional_matched_skills is None:
            self.optional_matched_skills = []

    def to_vector(self) -> List[float]:
        """Returns feature vector in fixed ordering expected by ML models."""
        return [
            float(self.semantic_similarity),
            float(self.skill_coverage),
            float(self.qualification_fit),
            float(self.experience_fit),
            float(self.credential_confidence),
        ]

    def to_dict(self) -> Dict[str, float]:
        """Returns feature dictionary with percentage-friendly rounded values."""
        return {
            "semantic_similarity": round(self.semantic_similarity, 4),
            "skill_coverage": round(self.skill_coverage, 4),
            "qualification_fit": round(self.qualification_fit, 4),
            "experience_fit": round(self.experience_fit, 4),
            "credential_confidence": round(self.credential_confidence, 4),
        }


def compute_skill_coverage(
    candidate_skills: List[str],
    occupation: OccupationRecord,
) -> tuple[float, List[str], List[str], List[str]]:
    """
    Calculates skill coverage against ESCO essential and optional skills.
    Returns: (coverage_ratio, matched_essential, missing_essential, matched_optional)
    """
    cand_set = {normalize_skill_name(s).lower() for s in candidate_skills if s}
    essential_set = {normalize_skill_name(s).lower(): s for s in occupation.essential_skills}
    optional_set = {normalize_skill_name(s).lower(): s for s in occupation.optional_skills}

    if not essential_set:
        # If no essential skills specified, fallback to all skills
        essential_set = {normalize_skill_name(s).lower(): s for s in occupation.all_skills}

    if not essential_set:
        return 0.0, [], [], []

    matched_essential = [orig for k, orig in essential_set.items() if k in cand_set]
    missing_essential = [orig for k, orig in essential_set.items() if k not in cand_set]
    matched_optional = [orig for k, orig in optional_set.items() if k in cand_set]

    # Essential coverage ratio
    essential_ratio = len(matched_essential) / max(len(essential_set), 1)

    # Optional bonus (up to 0.1 additional coverage, capped at 1.0)
    optional_ratio = (len(matched_optional) / max(len(optional_set), 1)) if optional_set else 0.0
    coverage = min(1.0, essential_ratio * 0.9 + optional_ratio * 0.1)

    return float(round(coverage, 4)), matched_essential, missing_essential, matched_optional


def compute_qualification_fit(
    candidate_education: str,
    occupation: OccupationRecord,
) -> float:
    """
    Calculates qualification fit.
    Documented policy:
    - If candidate has relevant degree/field: 1.0 (B.Tech, B.S., M.S., Ph.D., CS, IT, etc.)
    - If candidate has non-tech degree or some education: 0.7
    - If occupation does not state specific degree requirement and candidate has no education: neutral 0.5
    - If explicit qualification required but missing: 0.2
    """
    if not candidate_education or not candidate_education.strip():
        # Neutral policy when education is not provided
        return 0.5

    edu_lower = candidate_education.lower()

    # Highly relevant STEM / IT qualifications
    relevant_keywords = [
        "computer science", "data science", "software", "information technology",
        "engineering", "b.tech", "m.tech", "bachelor", "master", "phd", "b.s.", "m.s.",
        "bsc", "msc", "analytics", "mathematics", "statistics",
    ]
    if any(kw in edu_lower for kw in relevant_keywords):
        return 1.0

    # General degree / diploma
    general_keywords = ["diploma", "associate", "degree", "graduate", "college", "university"]
    if any(kw in edu_lower for kw in general_keywords):
        return 0.75

    return 0.5


def compute_experience_fit(
    experience_years: float,
    occupation: OccupationRecord,
) -> float:
    """
    Calculates experience fit.
    Documented policy:
    - Scales candidate experience years against typical industry expectations.
    - 0-1 year: 0.4 - 0.6 (suitable for entry/junior roles)
    - 2-3 years: 0.7 - 0.9 (suitable for mid-level roles)
    - 4+ years: 1.0
    - Missing experience data: neutral 0.5 (does not penalize candidates who omit years)
    """
    if experience_years is None or experience_years < 0:
        return 0.5

    if experience_years == 0.0:
        # Check if role title suggests junior or entry level
        title_lower = occupation.title.lower()
        if any(term in title_lower for term in ["junior", "entry", "assistant", "technician", "support"]):
            return 0.7
        return 0.4

    if experience_years >= 4.0:
        return 1.0
    elif experience_years >= 2.0:
        return 0.8
    elif experience_years >= 1.0:
        return 0.65
    else:
        return 0.5


def compute_credential_confidence(
    verified_certificates: Optional[List[Dict[str, Any]]],
    occupation: OccupationRecord,
) -> tuple[float, str]:
    """
    Calculates credential confidence based on verified certificate records.
    Explicit distinct statuses:
    - "valid": 1.0 (verified authentic / integrity checked)
    - "unverifiable": 0.5 (submitted but could not be cryptographically or issuer-verified)
    - "invalid": 0.0 (tampered or failed verification)
    - "revoked": 0.0 (revoked credential)
    - "none": neutral 0.5 (absence of uploaded certificate NEVER unfairly penalizes)
    """
    if not verified_certificates:
        # Neutral policy: absence of uploaded certificate receives neutral confidence 0.5
        return 0.5, "none"

    has_valid = False
    has_unverifiable = False
    has_invalid = False
    has_revoked = False

    for cert in verified_certificates:
        status = str(cert.get("status", "")).lower()
        is_verified = cert.get("verified", False)

        if status == "revoked":
            has_revoked = True
        elif status == "invalid" or cert.get("valid") is False:
            has_invalid = True
        elif status == "valid" or is_verified is True:
            has_valid = True
        elif status == "unverifiable":
            has_unverifiable = True
        else:
            # Default for integrity-verified documents
            if is_verified:
                has_valid = True
            else:
                has_unverifiable = True

    if has_revoked:
        return 0.0, "revoked"
    if has_invalid:
        return 0.0, "invalid"
    if has_valid:
        return 1.0, "valid"
    if has_unverifiable:
        return 0.5, "unverifiable"

    return 0.5, "none"


def extract_pair_features(
    candidate: CandidateProfile,
    occupation: OccupationRecord,
    semantic_similarity: float,
    verified_certificates: Optional[List[Dict[str, Any]]] = None,
) -> MatchingFeatures:
    """
    Extracts all 5 standardized features for a candidate-occupation pair.
    """
    coverage, matched_ess, missing_ess, matched_opt = compute_skill_coverage(
        candidate.skills, occupation
    )
    qual_fit = compute_qualification_fit(candidate.education, occupation)
    exp_fit = compute_experience_fit(candidate.experience_years, occupation)
    cred_conf, cred_status = compute_credential_confidence(
        verified_certificates, occupation
    )

    return MatchingFeatures(
        semantic_similarity=float(max(0.0, min(1.0, semantic_similarity))),
        skill_coverage=float(max(0.0, min(1.0, coverage))),
        qualification_fit=float(max(0.0, min(1.0, qual_fit))),
        experience_fit=float(max(0.0, min(1.0, exp_fit))),
        credential_confidence=float(max(0.0, min(1.0, cred_conf))),
        matched_skills=matched_ess,
        missing_skills=missing_ess,
        optional_matched_skills=matched_opt,
        credential_status=cred_status,
    )
