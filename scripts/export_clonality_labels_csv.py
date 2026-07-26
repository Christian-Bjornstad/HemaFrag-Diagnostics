#!/usr/bin/env python3
"""scripts/export_clonality_labels_csv.py

Walk a clonality tracking Excel workbook, run the rule interpreter over each
entry, and emit a flat comparison CSV. This is not a chemist-label export and
must not be used as supervised ML ground truth.

CLI:
  python scripts/export_clonality_labels_csv.py \\
      --xls /path/to/Clonality_Tracking.xlsx \\
      --out  /path/to/rule_suggestions.csv \\
      [--entry-metadata /path/to/identity_key_lookup.json]

Reasonable defaults: --out writes to ./rule_suggestions.csv next to --xls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from core.analyses.clonality.feature_artifacts import (
    build_clonality_feature_tables,
)
from core.analyses.clonality.interpretation import (
    features_from_entry,
    interpret_entry,
)


def _load_entry_metadata(entry_metadata_path):
    if not entry_metadata_path:
        return None
    with open(entry_metadata_path, encoding="utf-8") as f:
        em = json.load(f)
    if isinstance(em, dict):
        return em
    if isinstance(em, list):
        return em
    raise TypeError(
        "entry_metadata JSON must be a dict or list, got %s" % type(em).__name__
    )


def _resolve_columns(xlsx_path, entry_metadata=None):
    """Read the tracking xlsx, return (entries_df, raw_path_lookup)."""
    tables = build_clonality_feature_tables(xlsx_path, entry_metadata=entry_metadata)
    df = tables["combined"]
    if "identity_key" not in df.columns:
        df = df.rename(columns={"IdentityKey": "identity_key"})
    return df


def _labels_csv_for(df):
    """Apply features_from_entry + interpret_entry per row, return rows."""
    out = []
    for _, row in df.iterrows():
        entry = row.to_dict()
        # Reduce to minimal keys interpret_entry needs
        minimal = {
            "assay": entry.get("assay") or entry.get("Assay"),
            "ladder": entry.get("ladder"),
            "ladder_qc_status": entry.get("ladder_qc") or entry.get("ladder_qc_status"),
            "ladder_review_required": entry.get("ladder_review_required", False),
            "ladder_r2": entry.get("ladder_r2"),
            "ladder_linear_r2": entry.get("ladder_linear_r2"),
            "ladder_linear_mean_residual_bp": entry.get("ladder_linear_mean_residual_bp"),
            "ladder_linear_max_residual_bp": entry.get("ladder_linear_max_residual_bp"),
            "control": entry.get("control") or "",
            "sample_kind": entry.get("sample_kind") or "",
            "sl_metrics": entry.get("sl_metrics") or {},
            # Pass everything else through (interpret_entry tolerates extras).
        }
        minimal.update(entry)
        try:
            features = features_from_entry(minimal)
            result = interpret_entry({**minimal, "features": features})
        except Exception:
            continue
        out.append(
            {
                "identity_key": str(entry.get("identity_key") or ""),
                "assay": str(minimal["assay"] or ""),
                "ClonalityRuleSuggestion": result.get("ClonalitySuggestion", ""),
                "ClonalityRuleConfidence": result.get("ClonalityConfidence", 0.0),
                "ClonalityRuleReviewNeeded": result.get("ClonalityReviewNeeded", False),
                "ClonalityRuleEvidence": result.get("ClonalityEvidence", ""),
                "control_flag": str(entry.get("control") or ""),
                "ladder_qc": str(entry.get("ladder_qc") or ""),
            }
        )
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Walk a clonality tracking xlsx and emit rule suggestions for comparison."
    )
    p.add_argument(
        "--xls",
        type=Path,
        required=True,
        help="Path to Clonality_Tracking.xlsx",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output comparison CSV path. Default: ./rule_suggestions.csv next to --xls.",
    )
    p.add_argument(
        "--entry-metadata",
        type=Path,
        default=None,
        help="Optional JSON sidecar for build_clonality_feature_tables.identity_key population.",
    )
    args = p.parse_args(argv)
    if not args.xls.exists():
        raise FileNotFoundError("--xls %s not found" % args.xls)
    out = args.out if args.out else args.xls.parent / "rule_suggestions.csv"
    entry_metadata = _load_entry_metadata(args.entry_metadata) if args.entry_metadata else None
    df = _resolve_columns(args.xls, entry_metadata=entry_metadata)
    rows = _labels_csv_for(df)
    if not rows:
        raise SystemExit("No rows produced: did you pick the right workbook?")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print("[labels] wrote %d rows to %s" % (len(rows), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
