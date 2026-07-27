#!/usr/bin/env python3
"""Report whether real chemist labels support grouped per-assay training."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analyses.clonality.ml_data_contract import load_tracking_run_table
from core.analyses.clonality.ml_readiness import (
    assess_clonality_label_readiness,
    write_clonality_label_readiness,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Assess per-assay chemist-label, DIT, source-run, calibration, "
            "and promotion-preflight support before fitting classifiers."
        )
    )
    parser.add_argument("--xls", type=Path, required=True)
    parser.add_argument("--features-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-samples", type=int, default=200)
    parser.add_argument("--validation-folds", type=int, default=5)
    parser.add_argument("--source-run-validation-folds", type=int, default=3)
    parser.add_argument("--min-dit-groups", type=int, default=50)
    parser.add_argument("--min-class-dit-groups", type=int, default=10)
    parser.add_argument("--min-core-class-dit-groups", type=int, default=20)
    parser.add_argument("--min-class-source-run-groups", type=int, default=3)
    parser.add_argument("--min-class-evaluation-folds", type=int, default=2)
    parser.add_argument("--min-class-training-rows-per-fold", type=int, default=6)
    parser.add_argument("--max-class-dit-row-fraction", type=float, default=0.10)
    parser.add_argument(
        "--require-candidate",
        action="store_true",
        help="Return exit code 2 when no assay is candidate-ready.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not args.xls.is_file():
        raise FileNotFoundError(f"--xls {args.xls} not found")
    if not args.features_csv.is_file():
        raise FileNotFoundError(f"--features-csv {args.features_csv} not found")
    tracking = load_tracking_run_table(args.xls).frame
    features = pd.read_csv(args.features_csv)
    readiness = assess_clonality_label_readiness(
        tracking,
        features,
        min_samples=args.min_samples,
        validation_folds=args.validation_folds,
        source_run_validation_folds=args.source_run_validation_folds,
        min_dit_groups=args.min_dit_groups,
        min_class_dit_groups=args.min_class_dit_groups,
        min_core_class_dit_groups=args.min_core_class_dit_groups,
        min_class_source_run_groups=args.min_class_source_run_groups,
        min_class_evaluation_folds=args.min_class_evaluation_folds,
        min_class_training_rows_per_fold=args.min_class_training_rows_per_fold,
        max_class_dit_row_fraction=args.max_class_dit_row_fraction,
    )
    paths = write_clonality_label_readiness(
        readiness,
        args.output_dir,
        source_workbook=args.xls,
        source_features=args.features_csv,
    )
    report = readiness.report
    print(
        "[readiness] status={} labeled={}/{} candidate_assays={} "
        "promotion_preflight_assays={}".format(
            report["status"],
            report["labeled_rows"],
            report["available_rows"],
            report["candidate_ready_assay_count"],
            report["promotion_preflight_ready_assay_count"],
        )
    )
    print(f"[readiness] report={paths['report']}")
    if args.require_candidate and not report["candidate_ready_assay_count"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
