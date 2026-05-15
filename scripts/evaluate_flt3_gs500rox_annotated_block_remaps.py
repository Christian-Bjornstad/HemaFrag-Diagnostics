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

START_SUMMARY = ROOT / "local_triage" / "flt3_gs500rox_annotated_start_remap_eval" / "annotated_remap_summary.csv"
FIFTY_ROWS = ROOT / "local_triage" / "flt3_gs500rox_50_gapprior_candidate_html" / "candidate_rows.csv"
OUT_DIR = ROOT / "local_triage" / "flt3_gs500rox_annotated_block_remap_eval"


def _literal(value: object) -> Any:
    if isinstance(value, str):
        return ast.literal_eval(value)
    return value


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def _review_band(linear_max: float, linear_mean: float, linear_r2: float) -> bool:
    return _finite(linear_max) and _finite(linear_mean) and _finite(linear_r2) and linear_max <= 6.0 and linear_mean <= 3.0 and linear_r2 >= 0.9985


def _candidate_pool(current: list[int], first: int, second: int, raw_candidates: list[dict[str, Any]]) -> list[list[int]]:
    # For 75/100/139, use current anchors plus visible local peaks from the earlier
    # 50-candidate panel. This keeps the shadow pass constrained to peaks the user saw.
    candidate_scans = sorted({int(c["scan"]) for c in raw_candidates} | set(current[:6]) | {first, second})
    return [
        [first],
        [second],
        [scan for scan in candidate_scans if second + 45 <= scan <= current[2] + 35],
        [scan for scan in candidate_scans if current[2] - 15 <= scan <= current[3] + 45],
        [scan for scan in candidate_scans if current[3] - 20 <= scan <= current[4] + 50],
    ]


def _score_partial(selected: list[int], current: list[int]) -> tuple[float, float, float, float]:
    linear_max, linear_mean, linear_r2 = linear_metrics(selected)
    if not _finite(linear_max) or not _finite(linear_mean) or not _finite(linear_r2):
        return float("inf"), linear_max, linear_mean, linear_r2
    changed = sum(1 for left, right in zip(selected, current) if left != right)
    score = linear_max * 7.0 + linear_mean * 2.5 + max(0.0, 0.9992 - linear_r2) * 900.0 + changed * 0.05
    return score, linear_max, linear_mean, linear_r2


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = pd.read_csv(START_SUMMARY)
    fifty_rows = pd.read_csv(FIFTY_ROWS)
    candidates_by_ordinal = {
        int(row["ordinal"]): _literal(row["candidates"])
        for row in fifty_rows.to_dict("records")
    }
    rows: list[dict[str, Any]] = []
    for row in start.sort_values("ordinal").to_dict("records"):
        current = _literal(row["current_selected"])
        annotated_pair = _literal(row["proposed_selected"])
        pair_selected = [int(annotated_pair[0]), int(annotated_pair[1])] + [int(x) for x in current[2:]]
        best_selected = pair_selected
        best_strategy = "annotated_35_50_keep_75_plus"
        best_score, best_max, best_mean, best_r2 = _score_partial(best_selected, current)

        raw_candidates = candidates_by_ordinal.get(int(row["ordinal"]), [])
        pools = _candidate_pool(current, pair_selected[0], pair_selected[1], raw_candidates)
        trials: list[tuple[float, list[int], str, float, float, float]] = []
        for third in pools[2]:
            for fourth in pools[3]:
                for fifth in pools[4]:
                    prefix = [pair_selected[0], pair_selected[1], int(third), int(fourth), int(fifth)]
                    if not all(right > left for left, right in zip(prefix, prefix[1:])):
                        continue
                    selected = prefix + [int(x) for x in current[5:]]
                    score, linear_max, linear_mean, linear_r2 = _score_partial(selected, current)
                    trials.append((score, selected, "annotated_35_50_refit_75_100_139", linear_max, linear_mean, linear_r2))
        if trials:
            trials.sort(key=lambda item: item[0])
            top = trials[0]
            if top[0] + 0.001 < best_score:
                best_score, best_selected, best_strategy, best_max, best_mean, best_r2 = top

        rows.append(
            {
                **row,
                "block_strategy": best_strategy,
                "block_selected": json.dumps([int(x) for x in best_selected], separators=(",", ":")),
                "block_linear_max": best_max,
                "block_linear_mean": best_mean,
                "block_linear_r2": best_r2,
                "block_review_band": _review_band(best_max, best_mean, best_r2),
                "block_changed_steps": json.dumps(
                    [GS500ROX_SIZES[idx] for idx, (left, right) in enumerate(zip(current, best_selected)) if int(left) != int(right)],
                    separators=(",", ":"),
                ),
                "block_delta_vs_pair_max": best_max - float(row["proposal_linear_max"]),
                "block_delta_vs_pair_mean": best_mean - float(row["proposal_linear_mean"]),
            }
        )

    out_csv = OUT_DIR / "annotated_block_remap_summary.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    frame = pd.DataFrame(rows)
    summary = {
        "rows": len(rows),
        "pair_review_band": int(frame["review_band"].sum()),
        "block_review_band": int(frame["block_review_band"].sum()),
        "block_refit_rows": int((frame["block_strategy"] == "annotated_35_50_refit_75_100_139").sum()),
        "summary_csv": str(out_csv),
        "by_mode": {
            mode: {
                "rows": int(len(group)),
                "pair_review_band": int(group["review_band"].sum()),
                "block_review_band": int(group["block_review_band"].sum()),
                "block_refit_rows": int((group["block_strategy"] == "annotated_35_50_refit_75_100_139").sum()),
                "median_block_linear_max": float(group["block_linear_max"].median()),
                "median_block_linear_mean": float(group["block_linear_mean"].median()),
            }
            for mode, group in frame.groupby("mode")
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
