#!/usr/bin/env python3
"""Build a resumable local ML feature artifact from tracking rows and raw FSA."""
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
from core.analyses.clonality.ml_feature_dataset import (
    build_clonality_trace_feature_dataset,
    load_resumable_feature_artifact,
    write_clonality_trace_feature_artifact,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyze local .fsa files and export flat clonality ML trace features."
    )
    parser.add_argument("--xls", type=Path, required=True, help="Tracking workbook.")
    parser.add_argument("--fsa-root", type=Path, required=True, help="Local raw .fsa root.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local artifact directory (default: <workbook-dir>/clonality_ml_features).",
    )
    parser.add_argument(
        "--label-column",
        default=CHEMIST_LABEL_COLUMN,
        help=f"Chemist label column (default: {CHEMIST_LABEL_COLUMN}).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional smoke-run row limit.")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Atomically checkpoint after this many attempted rows (default: 25).",
    )
    parser.add_argument("--resume", action="store_true", help="Resume a compatible existing artifact.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Process resolvable rows even when the audit reports blocking errors.",
    )
    return parser.parse_args(argv)


def _pipeline_analyzer(path: Path):
    from core.analyses.clonality.pipeline import (
        _analyze_single_file_with_timeout,
        _clonality_file_timeout_seconds,
    )

    entry, reason = _analyze_single_file_with_timeout(
        path,
        _clonality_file_timeout_seconds(),
    )
    if reason:
        raise RuntimeError(reason)
    return entry


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not args.xls.is_file():
        raise FileNotFoundError(f"--xls {args.xls} not found")
    output_dir = args.output_dir or args.xls.parent / "clonality_ml_features"

    audit = audit_clonality_ml_data(
        args.xls,
        args.fsa_root,
        label_column=args.label_column,
    )
    write_clonality_ml_audit(audit, output_dir / "audit")
    blocking_codes = {
        issue["code"]
        for issue in audit.report["issues"]
        if issue.get("severity") == "error"
    }
    if blocking_codes and not args.allow_partial:
        print(
            "[features] audit failed; fix blocking issues or use --allow-partial: "
            + ", ".join(sorted(blocking_codes))
        )
        return 2

    existing = (
        load_resumable_feature_artifact(output_dir)
        if args.resume
        else None
    )

    def checkpoint(dataset):
        write_clonality_trace_feature_artifact(
            dataset,
            output_dir,
            workbook_path=args.xls,
            fsa_root=args.fsa_root,
            audit_report=audit.report,
        )

    def progress(done, total, status):
        print(f"[features] {done}/{total} {status}")

    dataset = build_clonality_trace_feature_dataset(
        audit.rows,
        analyze_file=_pipeline_analyzer,
        existing_features=existing,
        limit=args.limit,
        checkpoint_every=args.checkpoint_every,
        checkpoint_callback=checkpoint,
        progress_callback=progress,
    )
    paths = write_clonality_trace_feature_artifact(
        dataset,
        output_dir,
        workbook_path=args.xls,
        fsa_root=args.fsa_root,
        audit_report=audit.report,
    )
    print(
        "[features] rows={} errors={} processed={} resumed={}".format(
            len(dataset.features),
            len(dataset.errors),
            dataset.processed_count,
            dataset.skipped_existing_count,
        )
    )
    print(f"[features] features={paths['features']}")
    return 0 if dataset.errors.empty else 1


if __name__ == "__main__":
    sys.exit(main())
