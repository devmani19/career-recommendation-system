"""Comparative Evaluation Script: TF-IDF Baseline vs. Proposed SBERT/ESCO Recommender.

Compares recommendations produced by the baseline (TF-IDF + Cosine Similarity)
against the proposed multi-feature SBERT/ESCO recommendation approach on candidate profiles.
Never fabricates performance claims or fictitious metrics without genuine evaluation labels.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.career_recommendation_service import CareerRecommendationService
from app.services.esco_service import get_esco_service
from app.services.resume_processing import CandidateProfile, build_candidate_profile
from app.services.tfidf_baseline import TFIDFBaseline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_recommenders")


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate TF-IDF baseline vs proposed career recommender.")
    parser.add_argument("--eval-data", type=str, default=None, help="Path to held-out evaluation dataset JSON.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of recommendations to compare.")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 75)
    print("CAREER RECOMMENDATION EVALUATION: TF-IDF BASELINE VS PROPOSED SBERT/ESCO")
    print("=" * 75)

    esco_service = get_esco_service()
    occupations = esco_service.get_occupations()

    # 1. Fit TF-IDF baseline
    print(f"\n[1] Fitting TF-IDF Baseline on {len(occupations)} ESCO occupation documents...")
    baseline = TFIDFBaseline()
    baseline.fit(occupations)

    # 2. Initialize proposed recommender
    print("[2] Initializing Proposed Career Recommendation Service (SBERT + ESCO)...")
    proposed = CareerRecommendationService(esco_service=esco_service)

    # 3. Test profiles to evaluate
    sample_resumes = [
        BASE_DIR / "sample_data" / "sample_resume_data_analyst.txt",
        BASE_DIR / "sample_data" / "sample_resume_data_engineer_90plus.txt",
    ]

    existing_samples = [f for f in sample_resumes if f.exists()]
    if not existing_samples:
        print("[!] No sample resumes found in sample_data/.")
        sys.exit(0)

    print(f"\n[3] Running comparative evaluation across {len(existing_samples)} candidate profiles...\n")

    for sample_path in existing_samples:
        print("-" * 75)
        print(f"Candidate Document: {sample_path.name}")
        profile = build_candidate_profile(sample_path)
        print(f"Extracted Skills  : {', '.join(profile.skills[:8])} ({len(profile.skills)} total)")
        print(f"Education         : {profile.education or 'Not specified'}")
        print(f"Experience Years  : {profile.experience_years}")

        # Baseline ranking
        candidate_text = profile.get_summary_text()
        baseline_results = baseline.rank(candidate_text, limit=args.top_k)

        # Proposed ranking
        proposed_results = proposed.recommend(profile, limit=args.top_k)["recommendations"]

        print("\nTOP RECOMMENDATIONS COMPARISON:")
        print(f"{'Rank':<5} | {'TF-IDF Baseline':<32} {'Score':<8} | {'Proposed Recommender':<32} {'Score':<8}")
        print("-" * 88)

        for i in range(max(len(baseline_results), len(proposed_results))):
            base_title = baseline_results[i]["occupation_title"] if i < len(baseline_results) else "-"
            base_score = f"{baseline_results[i]['score']:.1f}%" if i < len(baseline_results) else "-"

            prop_title = proposed_results[i]["occupation_title"] if i < len(proposed_results) else "-"
            prop_score = f"{proposed_results[i]['score']:.1f}%" if i < len(proposed_results) else "-"

            print(f"{i+1:<5} | {base_title[:32]:<32} {base_score:<8} | {prop_title[:32]:<32} {prop_score:<8}")

        # Measure top-K overlap
        base_set = {r["occupation_title"].lower() for r in baseline_results}
        prop_set = {r["occupation_title"].lower() for r in proposed_results}
        overlap = len(base_set & prop_set)
        jaccard = overlap / len(base_set | prop_set) if (base_set | prop_set) else 0.0

        print(f"\nTop-{args.top_k} Overlap Agreement: {overlap}/{args.top_k} roles (Jaccard similarity: {jaccard:.2f})")
        print("Proposed Top Role Explanation:")
        if proposed_results:
            print(f"  -> {proposed_results[0]['explanation']}")

    print("\n" + "=" * 75)
    print("EVALUATION SUMMARY & METHODOLOGICAL NOTE:")
    print("1. TF-IDF uses unigram/bigram token overlap and cosine similarity.")
    print("2. The Proposed Recommender integrates semantic representation (SBERT),")
    print("   structured skill coverage against ESCO knowledge base, qualification fit,")
    print("   and experience fit.")
    print("3. Supervised accuracy/NDCG comparisons require ground-truth labelled hiring")
    print("   or student outcome data; neither method is artificially promoted as superior")
    print("   without held-out empirical ground truth.")
    print("=" * 75)


if __name__ == "__main__":
    main()
