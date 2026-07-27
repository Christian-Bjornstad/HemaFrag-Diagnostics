#!/usr/bin/env python3
"""Create a diverse local chemist-labeling workbook from real FSA features."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analyses.clonality.labeling_batch import (
    build_clonality_labeling_batch,
    write_clonality_labeling_batch,
)
from core.analyses.clonality.ml_data_contract import load_tracking_run_table


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Select a deterministic assay-balanced, feature-diverse chemist "
            "labeling batch. Rule suggestions are sampling strata, not labels."
        )
    )
    parser.add_argument("--xls", type=Path, required=True, help="Full tracking workbook.")
    parser.add_argument(
        "--features-csv",
        type=Path,
        required=True,
        help="Local v3 trace feature artifact.",
    )
    parser.add_argument("--output-xlsx", type=Path, required=True)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--per-assay", type=int, default=24)
    parser.add_argument("--max-rows", type=int, default=300)
    parser.add_argument("--review-fraction", type=float, default=0.65)
    parser.add_argument("--random-state", type=int, default=20260726)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not args.xls.is_file():
        raise FileNotFoundError(f"--xls {args.xls} not found")
    if not args.features_csv.is_file():
        raise FileNotFoundError(f"--features-csv {args.features_csv} not found")
    batch_id = args.batch_id or datetime.now(timezone.utc).strftime(
        "chemist-pilot-%Y%m%d"
    )
    tracking = load_tracking_run_table(args.xls).frame
    features = pd.read_csv(args.features_csv)
    batch = build_clonality_labeling_batch(
        tracking,
        features,
        batch_id=batch_id,
        per_assay=args.per_assay,
        max_rows=args.max_rows,
        review_fraction=args.review_fraction,
        random_state=args.random_state,
    )
    paths = write_clonality_labeling_batch(
        batch,
        args.output_xlsx,
        source_workbook=args.xls,
        source_features=args.features_csv,
        overwrite=args.overwrite,
    )
    print(
        "[labeling-batch] rows={} assays={} dits={} runs={} rule_review={}".format(
            batch.manifest["selected_rows"],
            batch.manifest["selected_assays"],
            batch.manifest["selected_dits"],
            batch.manifest["selected_source_runs"],
            batch.manifest["selected_rule_review_rows"],
        )
    )
    print(f"[labeling-batch] workbook={paths['workbook']}")
    print(f"[labeling-batch] manifest={paths['manifest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
