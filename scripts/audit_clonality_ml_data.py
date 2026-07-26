#!/usr/bin/env python3
"""Audit a clonality tracking workbook before real-data ML training."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analyses.clonality.ml_data_audit import (
    audit_clonality_ml_data,
    write_clonality_ml_audit,
)
from core.analyses.clonality.ml_data_contract import CHEMIST_LABEL_COLUMN


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate labels, DIT groups, feature quality, and local FSA paths."
    )
    parser.add_argument("--xls", type=Path, required=True, help="Tracking workbook.")
    parser.add_argument("--fsa-root", type=Path, required=True, help="Local root containing raw .fsa files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local audit output directory (default: <workbook-dir>/clonality_ml_audit).",
    )
    parser.add_argument(
        "--label-column",
        default=CHEMIST_LABEL_COLUMN,
        help=f"Chemist label column (default: {CHEMIST_LABEL_COLUMN}).",
    )
    parser.add_argument("--include-controls", action="store_true", help="Include control injections.")
    parser.add_argument(
        "--no-recursive-fallback",
        action="store_true",
        help="Do not search the FSA root recursively when direct paths fail.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 when blocking data errors are found.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not args.xls.is_file():
        raise FileNotFoundError(f"--xls {args.xls} not found")

    output_dir = args.output_dir or args.xls.parent / "clonality_ml_audit"
    audit = audit_clonality_ml_data(
        args.xls,
        args.fsa_root,
        label_column=args.label_column,
        include_controls=args.include_controls,
        recursive_fallback=not args.no_recursive_fallback,
    )
    paths = write_clonality_ml_audit(audit, output_dir)

    report = audit.report
    print(
        "[audit] status={status} rows={rows} labelled={labelled} "
        "resolved_fsa={resolved} missing_fsa={missing}".format(
            status=report["status"],
            rows=report["row_count"],
            labelled=report["labeled_row_count"],
            resolved=report["resolved_fsa_count"],
            missing=report["missing_fsa_count"],
        )
    )
    for issue in report["issues"]:
        print("[audit] {severity}: {code}: {message}".format(**issue))
    print(f"[audit] report={paths['report']}")
    return 2 if args.strict and audit.has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
