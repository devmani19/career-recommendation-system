"""Skill-Gap Analysis Module.

Compares candidate skills against ESCO occupation essential and optional skills,
identifies exact matches, highlights critical missing skills, and suggests
targeted industry certifications and actionable skill development steps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .esco_service import OccupationRecord
from .skill_normalization import normalize_skill_name, normalize_skill_list

logger = logging.getLogger(__name__)


# Curated mapping of canonical skills to recognized industry certifications
SKILL_CERTIFICATION_MAP: Dict[str, str] = {
    "python": "Python for Everybody / PCAP Certified Associate Python Programmer",
    "sql": "SQL Fundamentals / Oracle Database Certified Associate",
    "excel": "Microsoft Office Specialist: Excel Expert",
    "microsoft excel": "Microsoft Office Specialist: Excel Expert",
    "power bi": "Microsoft Certified: Power BI Data Analyst (PL-300)",
    "tableau": "Tableau Desktop Specialist",
    "statistics": "Statistics for Data Analysis Specialization",
    "machine learning": "Machine Learning Specialization (Coursera / Stanford)",
    "deep learning": "Deep Learning Specialization (DeepLearning.AI)",
    "tensorflow": "TensorFlow Developer Certificate",
    "pytorch": "Deep Learning with PyTorch Certification",
    "natural language processing": "Natural Language Processing Specialization",
    "cloud technologies": "AWS Certified Cloud Practitioner / Azure Fundamentals",
    "amazon web services": "AWS Certified Solutions Architect - Associate",
    "microsoft azure": "Microsoft Certified: Azure Fundamentals (AZ-900)",
    "google cloud platform": "Google Cloud Associate Cloud Engineer",
    "docker": "Docker Certified Associate (DCA)",
    "kubernetes": "Certified Kubernetes Administrator (CKA)",
    "linux": "Linux Professional Institute LPIC-1",
    "ci/cd": "GitLab Certified CI/CD Specialist / GitHub Actions",
    "git": "GitHub Foundations Certification",
    "cybersecurity": "CompTIA Security+ / CEH",
    "data engineering": "IBM Data Engineering Professional Certificate",
    "data science": "IBM Data Science Professional Certificate",
    "data mining": "Data Mining Foundations Certificate",
    "data warehousing": "Data Warehousing Specialization",
    "business intelligence": "Google Business Intelligence Certificate",
    "business analysis": "IIBA Entry Certificate in Business Analysis (ECBA)",
    "project management": "PMI Certified Associate in Project Management (CAPM)",
    "agile": "ICAgile Certified Professional (ICP)",
    "software testing": "ISTQB Certified Tester Foundation Level (CTFL)",
}


@dataclass
class SkillGapReport:
    """Detailed skill gap analysis report for a candidate-occupation pair."""
    occupation_id: str
    occupation_title: str
    matched_essential_skills: List[str] = field(default_factory=list)
    missing_essential_skills: List[str] = field(default_factory=list)
    matched_optional_skills: List[str] = field(default_factory=list)
    missing_optional_skills: List[str] = field(default_factory=list)
    essential_coverage_rate: float = 0.0
    suggested_certifications: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "occupation_id": self.occupation_id,
            "occupation_title": self.occupation_title,
            "matched_essential_skills": self.matched_essential_skills,
            "missing_essential_skills": self.missing_essential_skills,
            "matched_optional_skills": self.matched_optional_skills,
            "missing_optional_skills": self.missing_optional_skills,
            "essential_coverage_rate": round(self.essential_coverage_rate, 4),
            "suggested_certifications": self.suggested_certifications,
            "action_items": self.action_items,
        }


class SkillGapService:
    """
    Independent service that computes skill gaps between candidate profiles and ESCO occupations.
    """

    @staticmethod
    def suggest_certifications(missing_skills: List[str], limit: int = 3) -> List[str]:
        """Maps missing skills to suggested credentials without inventing certifications."""
        suggested: List[str] = []
        seen: Set[str] = set()

        for skill in missing_skills:
            norm_key = normalize_skill_name(skill).lower()
            # Direct match
            cert = SKILL_CERTIFICATION_MAP.get(norm_key)
            if not cert:
                # Substring match
                for map_key, cert_name in SKILL_CERTIFICATION_MAP.items():
                    if map_key in norm_key or norm_key in map_key:
                        cert = cert_name
                        break

            if cert and cert not in seen:
                seen.add(cert)
                suggested.append(cert)
                if len(suggested) >= limit:
                    break

        return suggested

    def analyze_gap(
        self,
        candidate_skills: List[str],
        occupation: OccupationRecord,
    ) -> SkillGapReport:
        """
        Calculates exact matches and missing skills for an occupation.
        """
        cand_normalized = {normalize_skill_name(s).lower() for s in candidate_skills if s}

        # Index essential skills
        ess_map = {normalize_skill_name(s).lower(): s for s in occupation.essential_skills}
        opt_map = {normalize_skill_name(s).lower(): s for s in occupation.optional_skills}

        if not ess_map and occupation.all_skills:
            ess_map = {normalize_skill_name(s).lower(): s for s in occupation.all_skills}

        matched_ess = [orig for k, orig in ess_map.items() if k in cand_normalized]
        missing_ess = [orig for k, orig in ess_map.items() if k not in cand_normalized]

        matched_opt = [orig for k, orig in opt_map.items() if k in cand_normalized]
        missing_opt = [orig for k, orig in opt_map.items() if k not in cand_normalized]

        total_ess = len(ess_map)
        coverage_rate = (len(matched_ess) / total_ess) if total_ess > 0 else 0.0

        # Suggested certifications for top missing essential skills
        suggested_certs = self.suggest_certifications(missing_ess, limit=3)

        # Action items
        action_items = []
        if missing_ess:
            top_missing = missing_ess[:4]
            action_items.append(f"Focus on learning high-priority essential skills: {', '.join(top_missing)}.")
        if suggested_certs:
            action_items.append(f"Consider targeted training or certification in: {suggested_certs[0]}.")
        if not missing_ess and missing_opt:
            action_items.append(f"Strengthen your competitiveness with optional skills: {', '.join(missing_opt[:3])}.")
        if not missing_ess and not missing_opt:
            action_items.append("Your skills match all standard requirements for this ESCO profile.")

        return SkillGapReport(
            occupation_id=occupation.occupation_id,
            occupation_title=occupation.title,
            matched_essential_skills=matched_ess,
            missing_essential_skills=missing_ess,
            matched_optional_skills=matched_opt,
            missing_optional_skills=missing_opt,
            essential_coverage_rate=float(coverage_rate),
            suggested_certifications=suggested_certs,
            action_items=action_items,
        )


# Global singleton instance
_GLOBAL_SKILL_GAP_SERVICE: Optional[SkillGapService] = None


def get_skill_gap_service() -> SkillGapService:
    global _GLOBAL_SKILL_GAP_SERVICE
    if _GLOBAL_SKILL_GAP_SERVICE is None:
        _GLOBAL_SKILL_GAP_SERVICE = SkillGapService()
    return _GLOBAL_SKILL_GAP_SERVICE
