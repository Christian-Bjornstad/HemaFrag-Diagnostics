from __future__ import annotations

import ast
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gs500rox_start_strategy_shadow_eval import GS500ROX_SIZES, linear_metrics  # noqa: E402

FIFTY_ROWS = ROOT / "local_triage" / "flt3_gs500rox_50_gapprior_candidate_html" / "candidate_rows.csv"
FIFTY_ANNOTATIONS = ROOT / "local_triage" / "flt3_gs500rox_50_gapprior_candidate_html" / "annotations_imported.csv"
THIRTY_FIVE_ROWS = ROOT / "local_triage" / "flt3_gs500rox_35_earlier_candidate_html" / "candidate_rows.csv"
THIRTY_FIVE_ANNOTATIONS = ROOT / "local_triage" / "flt3_gs500rox_35_earlier_candidate_html" / "annotations_imported.csv"
OUT_DIR = ROOT / "local_triage" / "flt3_gs500rox_annotated_start_remap_eval"


def _literal(value: object) -> Any:
    if isinstance(value, str):
        return ast.literal_eval(value)
    return value


def _candidate_scan(candidates: list[dict[str, Any]], label: str, prefix: str) -> int | None:
    if not isinstance(label, str) or not label.startswith(prefix):
        return None
    idx = ord(label[-1]) - ord("A")
    if 0 <= idx < len(candidates):
        return int(candidates[idx]["scan"])
    return None


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def _review_band(linear_max: float, linear_mean: float, linear_r2: float) -> bool:
    return _finite(linear_max) and _finite(linear_mean) and _finite(linear_r2) and linear_max <= 6.0 and linear_mean <= 3.0 and linear_r2 >= 0.9985


def _strong_band(linear_max: float, linear_mean: float, linear_r2: float) -> bool:
    return _finite(linear_max) and _finite(linear_mean) and _finite(linear_r2) and linear_max <= 3.0 and linear_mean <= 1.5 and linear_r2 >= 0.9994


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fifty_rows = pd.read_csv(FIFTY_ROWS)
    fifty_ann = pd.read_csv(FIFTY_ANNOTATIONS).fillna("")
    thirty_rows = pd.read_csv(THIRTY_FIVE_ROWS)
    thirty_ann = pd.read_csv(THIRTY_FIVE_ANNOTATIONS).fillna("")

    fifty = fifty_rows.merge(fifty_ann, on="ordinal", how="inner", suffixes=("", "_ann"))
    thirty = thirty_rows.merge(thirty_ann, on="ordinal", how="inner", suffixes=("", "_35ann"))
    thirty_by_ordinal = {int(row["ordinal"]): row for row in thirty.to_dict("records")}

    rows: list[dict[str, Any]] = []
    for row in fifty.sort_values("ordinal").to_dict("records"):
        ordinal = int(row["ordinal"])
        current = [int(value) for value in _literal(row["current_selected"])]
        current_linear_max, current_linear_mean, current_linear_r2 = linear_metrics(current)
        fifty_candidates = _literal(row["candidates"])
        label_50 = str(row.get("label") or "")
        annotated_50 = _candidate_scan(fifty_candidates, label_50, "50_")
        mode = "simple_shift_35_current50"
        label_35 = ""
        annotated_35 = current[1]
        note_35 = ""

        if ordinal in thirty_by_ordinal:
            trow = thirty_by_ordinal[ordinal]
            mode = "annotated_35_earlier"
            label_35 = str(trow.get("label_35ann") or "")
            note_35 = str(trow.get("note_35ann") or "")
            annotated_50 = int(trow["annotated_50"])
            thirty_candidates = _literal(trow["candidates_35"])
            annotated_35 = _candidate_scan(thirty_candidates, label_35, "35_")
            if annotated_35 is None:
                annotated_35 = current[0]
        elif label_50 == "none":
            mode = "unresolved_none"
            annotated_50 = current[1]

        if annotated_50 is None:
            annotated_50 = current[1]

        proposed = [int(annotated_35), int(annotated_50)] + current[2:]
        proposal_linear_max, proposal_linear_mean, proposal_linear_r2 = linear_metrics(proposed)
        gaps = list(np.diff(np.asarray(proposed[:5], dtype=float))) if len(proposed) >= 5 else []
        monotonic = all(right > left for left, right in zip(proposed, proposed[1:]))
        rows.append(
            {
                "ordinal": ordinal,
                "File": row["File"],
                "raw_path": row["raw_path"],
                "mode": mode,
                "label_50": label_50,
                "note_50": row.get("note", ""),
                "label_35": label_35,
                "note_35": note_35,
                "current_selected": json.dumps(current, separators=(",", ":")),
                "proposed_selected": json.dumps(proposed, separators=(",", ":")),
                "current_35": current[0],
                "current_50": current[1],
                "current_75": current[2],
                "annotated_35": int(annotated_35),
                "annotated_50": int(annotated_50),
                "gap_35_50": int(annotated_50) - int(annotated_35),
                "gap_50_75": current[2] - int(annotated_50),
                "gap_75_100": current[3] - current[2],
                "monotonic": monotonic,
                "current_linear_max": current_linear_max,
                "current_linear_mean": current_linear_mean,
                "current_linear_r2": current_linear_r2,
                "proposal_linear_max": proposal_linear_max,
                "proposal_linear_mean": proposal_linear_mean,
                "proposal_linear_r2": proposal_linear_r2,
                "delta_linear_max": proposal_linear_max - current_linear_max,
                "delta_linear_mean": proposal_linear_mean - current_linear_mean,
                "review_band": monotonic and _review_band(proposal_linear_max, proposal_linear_mean, proposal_linear_r2),
                "strong_band": monotonic and _strong_band(proposal_linear_max, proposal_linear_mean, proposal_linear_r2),
                "first_gaps": json.dumps([int(gap) for gap in gaps], separators=(",", ":")),
            }
        )

    out_csv = OUT_DIR / "annotated_remap_summary.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    by_mode = {}
    for mode, group in pd.DataFrame(rows).groupby("mode"):
        by_mode[mode] = {
            "rows": int(len(group)),
            "review_band": int(group["review_band"].sum()),
            "strong_band": int(group["strong_band"].sum()),
            "median_proposal_linear_max": float(group["proposal_linear_max"].median()),
            "median_proposal_linear_mean": float(group["proposal_linear_mean"].median()),
            "median_gap_35_50": float(group["gap_35_50"].median()),
            "median_gap_50_75": float(group["gap_50_75"].median()),
        }
    summary = {
        "rows": len(rows),
        "review_band": sum(1 for row in rows if row["review_band"]),
        "strong_band": sum(1 for row in rows if row["strong_band"]),
        "by_mode": by_mode,
        "summary_csv": str(out_csv),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
