#!/usr/bin/env python3
"""Merge reviewed chemist labels from a pilot into the full tracking workbook."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analyses.clonality.labeling_batch import (
    merge_clonality_labeling_batch,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Merge ClonalityChemistLabel values by IdentityKey+Assay. "
            "Existing conflicting target labels are preserved by default."
        )
    )
    parser.add_argument("--batch-xlsx", type=Path, required=True)
    parser.add_argument("--target-xlsx", type=Path, required=True)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-json", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not args.batch_xlsx.is_file():
        raise FileNotFoundError(f"--batch-xlsx {args.batch_xlsx} not found")
    if not args.target_xlsx.is_file():
        raise FileNotFoundError(f"--target-xlsx {args.target_xlsx} not found")
    report = merge_clonality_labeling_batch(
        args.batch_xlsx,
        args.target_xlsx,
        allow_overwrite=args.allow_overwrite,
        dry_run=args.dry_run,
    )
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    print(
        "[labeling-merge] labeled={} written={} unchanged={} conflicts={} missing={}".format(
            report["batch_labeled_rows"],
            report["labels_written"],
            report["labels_unchanged"],
            report["conflict_count"],
            report["missing_target_count"],
        )
    )
    return 2 if report["conflict_count"] or report["missing_target_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
