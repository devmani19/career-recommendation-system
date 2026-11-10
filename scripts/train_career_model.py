"""Training Script for XGBoost Supervised Career Relevance Model.

Usage:
    python scripts/train_career_model.py --data-path path/to/labelled_dataset.csv

Expects genuine labelled candidate-occupation data with schema:
- candidate_id: Identifier to group multiple pairs from the same candidate and prevent data leakage
- label / is_relevant: Binary relevance target (1 = suitable recommendation, 0 = unsuitable)
- Features: semantic_similarity, skill_coverage, qualification_fit, experience_fit, credential_confidence

Never invents fake relevance labels to claim artificial accuracy.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.xgboost_service import FEATURE_NAMES, XGBoostService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_career_model")


def parse_args():
    parser = argparse.ArgumentParser(description="Train XGBoost career relevance classifier.")
    parser.add_argument(
        "--data-path",
        type=str,
        default=None,
        help="Path to CSV or JSON file containing genuine labelled candidate-occupation examples.",
    )
    parser.add_argument(
        "--output-model",
        type=str,
        default=str(BASE_DIR / "data" / "models" / "xgboost_career_ranker.json"),
        help="Destination path for trained model JSON artifact.",
    )
    parser.add_argument(
        "--output-metadata",
        type=str,
        default=str(BASE_DIR / "data" / "models" / "xgboost_metadata.json"),
        help="Destination path for training metadata JSON.",
    )
    parser.add_argument("--n-estimators", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--val-size", type=float, default=0.2)
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 70)
    print("CAREER RECOMMENDATION SYSTEM - XGBOOST TRAINING PIPELINE")
    print("=" * 70)

    if not args.data_path or not Path(args.data_path).exists():
        print("\n[!] No valid labelled training dataset provided.")
        print(f"    Specified path: '{args.data_path}'")
        print("\nDATASET REQUIREMENTS TO TRAIN XGBOOST:")
        print("To activate the trained XGBoost ranker, provide genuine labelled data with:")
        print("1. 'candidate_id'  : Group identifier (string/integer) to prevent data leakage")
        print("2. 'label'         : Ground-truth relevance flag (1 = relevant, 0 = not relevant)")
        print("3. Feature columns (all scaled to [0.0, 1.0]):")
        for feat in FEATURE_NAMES:
            print(f"   - {feat}")
        print("\nWhen no genuine labelled data is present, the application transparently")
        print("uses the multi-criteria weighted-scoring fallback engine without claiming")
        print("unsupported accuracy figures.")
        print("=" * 70)
        sys.exit(0)

    data_file = Path(args.data_path)
    logger.info("Loading labelled data from %s...", data_file)
    if data_file.suffix.lower() == ".csv":
        df = pd.read_csv(data_file)
    elif data_file.suffix.lower() in {".json", ".jsonl"}:
        df = pd.read_json(data_file)
    else:
        logger.error("Unsupported file extension: %s. Use CSV or JSON.", data_file.suffix)
        sys.exit(1)

    # Validate target label
    label_col = "label" if "label" in df.columns else ("is_relevant" if "is_relevant" in df.columns else None)
    if not label_col:
        logger.error("Dataset missing target column: expected 'label' or 'is_relevant'.")
        sys.exit(1)

    # Validate candidate_id
    candidate_ids = df["candidate_id"].tolist() if "candidate_id" in df.columns else None
    if candidate_ids is None:
        logger.warning("No 'candidate_id' column found; stratified split will be used instead of grouped split.")

    # Validate features
    missing_feats = [f for f in FEATURE_NAMES if f not in df.columns]
    if missing_feats:
        logger.error("Dataset missing required feature columns: %s", missing_feats)
        sys.exit(1)

    X = df[FEATURE_NAMES].to_numpy(dtype=np.float32)
    y = df[label_col].to_numpy(dtype=np.int32)

    logger.info("Dataset shape: %d rows, %d features", X.shape[0], X.shape[1])
    logger.info("Class distribution: 0s=%d, 1s=%d", int(np.sum(y == 0)), int(np.sum(y == 1)))

    service = XGBoostService(model_path=args.output_model, metadata_path=args.output_metadata)
    try:
        metadata = service.train(
            X=X,
            y=y,
            candidate_ids=candidate_ids,
            val_size=args.val_size,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
        )
        print("\n[SUCCESS] XGBoost model trained successfully!")
        print(f"Model saved to: {args.output_model}")
        print(f"Metadata saved to: {args.output_metadata}")
        print("\nValidation Metrics:")
        for k, v in metadata.get("validation_metrics", {}).items():
            print(f"  {k:15s}: {v}")
    except Exception as exc:
        logger.exception("Model training failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
