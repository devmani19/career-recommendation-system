"""Benchmark Training Dataset Generator for XGBoost Career Model.

Generates structured candidate-occupation training examples across ESCO occupations.
Calculates authentic feature vectors using the real SBERT and feature engineering pipelines.
Assigns ground-truth relevance labels based on candidate background domain matching.
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.esco_service import get_esco_service
from app.services.feature_engineering import extract_pair_features
from app.services.resume_processing import CandidateProfile
from app.services.sbert_service import get_sbert_service

# Domain archetypes for candidate profiles
CANDIDATE_ARCHETYPES = [
    {
        "domain": "data_analytics",
        "target_roles": ["data analyst", "business analyst", "market research analyst"],
        "skills": ["SQL", "Excel", "Tableau", "Power BI", "Statistics", "Data Mining", "Data Visualization"],
        "education": "Bachelor of Science in Data Analytics",
        "experience_years": 2.0,
        "certifications": ["Microsoft Certified: Power BI Data Analyst (PL-300)"],
    },
    {
        "domain": "data_science",
        "target_roles": ["data scientist", "artificial intelligence engineer", "data analyst"],
        "skills": ["Python", "Machine Learning", "Statistics", "Pandas", "Scikit-Learn", "Data Science", "SQL"],
        "education": "Master of Science in Data Science",
        "experience_years": 3.0,
        "certifications": ["Machine Learning Specialization"],
    },
    {
        "domain": "data_engineering",
        "target_roles": ["data engineer", "database administrator", "cloud engineer"],
        "skills": ["Python", "SQL", "Data Engineering", "Data Warehousing", "ETL", "Hadoop", "Cloud Technologies"],
        "education": "Bachelor of Technology in Computer Science",
        "experience_years": 3.5,
        "certifications": ["IBM Data Engineering Professional Certificate"],
    },
    {
        "domain": "ai_ml",
        "target_roles": ["artificial intelligence engineer", "data scientist"],
        "skills": ["Python", "Deep Learning", "TensorFlow", "PyTorch", "Natural Language Processing", "Machine Learning"],
        "education": "Master of Technology in Artificial Intelligence",
        "experience_years": 2.5,
        "certifications": ["TensorFlow Developer Certificate"],
    },
    {
        "domain": "software_engineering",
        "target_roles": ["software developer", "web developer", "mobile application developer"],
        "skills": ["Java", "Python", "Git", "Data Structures", "Algorithms", "Software Testing", "APIs"],
        "education": "Bachelor of Engineering in Software Engineering",
        "experience_years": 4.0,
        "certifications": ["Oracle Java SE Certification"],
    },
    {
        "domain": "web_development",
        "target_roles": ["web developer", "software developer", "user interface designer"],
        "skills": ["JavaScript", "HTML", "CSS", "React", "Node.js", "Git", "APIs"],
        "education": "Bachelor of Science in Information Technology",
        "experience_years": 1.5,
        "certifications": ["Meta Front-End Developer Certificate"],
    },
    {
        "domain": "cloud_devops",
        "target_roles": ["cloud DevOps engineer", "cloud engineer", "database administrator"],
        "skills": ["Docker", "Kubernetes", "Linux", "CI/CD", "Amazon Web Services", "Cloud Technologies", "Git"],
        "education": "Bachelor of Science in Computer Science",
        "experience_years": 3.0,
        "certifications": ["AWS Certified Solutions Architect - Associate"],
    },
    {
        "domain": "networking",
        "target_roles": ["ICT network engineer", "cloud engineer"],
        "skills": ["Networking", "Linux", "Security", "Routing", "Switching", "TCP/IP"],
        "education": "Bachelor of Technology in Information Technology",
        "experience_years": 2.0,
        "certifications": ["Cisco CCNA"],
    },
    {
        "domain": "ui_ux",
        "target_roles": ["user interface designer", "web developer"],
        "skills": ["Figma", "User Interface Design", "Wireframing", "User Experience", "HTML", "CSS"],
        "education": "Bachelor of Design in Interaction Design",
        "experience_years": 2.0,
        "certifications": ["Google UX Design Certificate"],
    },
    {
        "domain": "finance_analytics",
        "target_roles": ["financial analyst", "business analyst"],
        "skills": ["Financial Analysis", "Excel", "Accounting", "Statistics", "Valuation", "Business Analytics"],
        "education": "Bachelor of Commerce in Finance",
        "experience_years": 3.0,
        "certifications": ["CFA Level 1"],
    },
    {
        "domain": "project_management",
        "target_roles": ["project manager", "product manager"],
        "skills": ["Project Management", "Agile", "Scrum", "Risk Management", "Stakeholder Management"],
        "education": "Master of Business Administration",
        "experience_years": 5.0,
        "certifications": ["PMI Certified Associate in Project Management (CAPM)"],
    },
    {
        "domain": "qa_testing",
        "target_roles": ["software tester", "software developer"],
        "skills": ["Software Testing", "Test Automation", "Selenium", "Java", "Python", "SQL", "Git"],
        "education": "Bachelor of Computer Applications",
        "experience_years": 1.5,
        "certifications": ["ISTQB Certified Tester Foundation Level (CTFL)"],
    },
]


def generate_benchmark_dataset(output_path: Path):
    esco_service = get_esco_service()
    occupations = esco_service.get_occupations()
    sbert_service = get_sbert_service()

    rows = []
    cand_counter = 1

    # Repeat archetypes with minor variations to generate 60+ diverse candidates
    for repeat in range(5):
        for arch in CANDIDATE_ARCHETYPES:
            cand_id = f"cand_{cand_counter}"
            cand_counter += 1

            # Variations in skill count and experience
            skills = list(arch["skills"])
            if repeat > 0 and len(skills) > 3:
                # Slight variation in skills
                np.random.seed(cand_counter)
                keep_count = max(3, len(skills) - (repeat % 3))
                skills = list(np.random.choice(skills, size=keep_count, replace=False))

            exp_years = max(0.5, arch["experience_years"] + (repeat - 2) * 0.5)

            candidate = CandidateProfile(
                candidate_name=f"Candidate {cand_counter}",
                skills=skills,
                education=arch["education"],
                experience_years=exp_years,
                certifications=arch.get("certifications", []),
            )

            # SBERT similarity for all occupations
            summary = candidate.get_summary_text()
            sims = sbert_service.calculate_similarities(summary, occupations)

            verified_certs = [{"filename": c, "verified": True, "status": "valid"} for c in candidate.certifications]

            for occ_title, occ in occupations.items():
                sem_sim = sims.get(occ_title, 0.0)
                features = extract_pair_features(
                    candidate=candidate,
                    occupation=occ,
                    semantic_similarity=sem_sim,
                    verified_certificates=verified_certs,
                )

                # Ground truth target: 1 if occupation is in archetype target_roles, else 0
                is_target = any(tr.lower() == occ_title.lower() for tr in arch["target_roles"])
                label = 1 if is_target else 0

                rows.append({
                    "candidate_id": cand_id,
                    "occupation_title": occ_title,
                    "label": label,
                    "semantic_similarity": round(features.semantic_similarity, 4),
                    "skill_coverage": round(features.skill_coverage, 4),
                    "qualification_fit": round(features.qualification_fit, 4),
                    "experience_fit": round(features.experience_fit, 4),
                    "credential_confidence": round(features.credential_confidence, 4),
                })

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Generated {len(df)} candidate-occupation pairs across {cand_counter-1} candidates.")
    print(f"Saved dataset to: {output_path}")
    print(f"Positive relevance pairs: {int(df['label'].sum())} / {len(df)}")
    return df


if __name__ == "__main__":
    out = BASE_DIR / "data" / "benchmark_training_data.csv"
    generate_benchmark_dataset(out)
