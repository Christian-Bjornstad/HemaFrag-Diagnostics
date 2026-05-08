from __future__ import annotations

import argparse
import ast
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker_pool, _invalidate_rust_worker_pool, _rust_timeout_seconds  # noqa: E402


DEFAULT_INPUT = (
    ROOT
    / "artifacts"
    / "broad_live_after_rox_postblob_balanced_1200_2026-05-06"
    / "live_summary.tsv"
)
DEFAULT_OUT_DIR = ROOT / "artifacts" / "rox_nonlinear_start_pair_shadow_eval_2026-05-06"

ROX_SIZES = np.array(
    [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
    dtype=float,
)


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_selected(value: object) -> list[int]:
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for item in parsed:
        try:
            out.append(int(round(float(item))))
        except (TypeError, ValueError):
            continue
    return out


def selected_scans(preview: dict[str, Any]) -> list[int]:
    refinement = preview.get("refinement") or {}
    scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    return [int(round(float(value))) for value in scans]


def unwrap_result(response: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    if not isinstance(response, dict):
        return {}, "empty response"
    if response.get("error"):
        return {}, str(response.get("error"))
    result = response.get("result")
    if isinstance(result, dict):
        return result, ""
    if isinstance(response.get("ladder_fit_preview"), dict):
        return response, ""
    return {}, "missing result"


def peak_map(peaks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for peak in peaks:
        try:
            out[int(round(float(peak.get("index"))))] = peak
        except (TypeError, ValueError):
            continue
    return out


def polynomial_metrics(scans: list[int], degree: int) -> tuple[float, float, float]:
    if len(scans) != len(ROX_SIZES) or len(scans) < degree + 2:
        return float("nan"), float("nan"), float("nan")
    x = np.asarray(scans, dtype=float)
    try:
        coef = np.polyfit(x, ROX_SIZES, degree)
    except np.linalg.LinAlgError:
        return float("nan"), float("nan"), float("nan")
    predicted = np.polyval(coef, x)
    residuals = ROX_SIZES - predicted
    ss_tot = float(np.sum((ROX_SIZES - float(np.mean(ROX_SIZES))) ** 2))
    ss_res = float(np.sum((ROX_SIZES - predicted) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(np.max(np.abs(residuals))), float(np.mean(np.abs(residuals))), r2


def finite(value: float) -> bool:
    return math.isfinite(value)


def pair_shape_score(first: dict[str, Any] | None, second: dict[str, Any] | None) -> float:
    if not first or not second:
        return float("inf")
    try:
        first_height = max(float(first.get("height")), 1.0)
        second_height = max(float(second.get("height")), 1.0)
        first_prom = max(float(first.get("prominence")), 0.0)
        second_prom = max(float(second.get("prominence")), 0.0)
        first_width = max(float(first.get("width")), 1.0)
        second_width = max(float(second.get("width")), 1.0)
    except (TypeError, ValueError):
        return float("inf")
    height_balance = abs(math.log(first_height / second_height))
    prom_balance = abs(math.log((first_prom + 1.0) / (second_prom + 1.0)))
    width_balance = abs(math.log(first_width / second_width))
    weak = max(0.0, 120.0 - min(first_height, second_height)) / 120.0
    return height_balance * 0.7 + prom_balance * 0.5 + width_balance * 0.35 + weak


def candidate_pairs(selected: list[int], peaks: dict[int, dict[str, Any]]) -> list[tuple[int, int]]:
    if len(selected) != len(ROX_SIZES):
        return []
    third = selected[2]
    left = max(1250, min(selected[:3]) - 320)
    right = third - 8
    indices = sorted(idx for idx in peaks if left <= idx <= right)
    pairs: list[tuple[int, int]] = []
    for pos, first in enumerate(indices):
        for second in indices[pos + 1 :]:
            gap12 = second - first
            gap23 = third - second
            if 35 <= gap12 <= 115 and 90 <= gap23 <= 280:
                pairs.append((first, second))
    return pairs


def nonlinear_candidate_status(current: dict[str, float], candidate: dict[str, float], selected: list[int], pair: tuple[int, int]) -> str:
    gap23_current = selected[2] - selected[1]
    gap23_candidate = selected[2] - pair[1]
    nonlinear_win = (
        candidate["d3_max"] + 1.20 < current["d3_max"]
        and candidate["d2_max"] + 1.50 < current["d2_max"]
        and candidate["d3_mean"] + 0.45 < current["d3_mean"]
    )
    excellent_nonlinear = (
        candidate["d3_max"] <= 0.80
        and candidate["d3_mean"] <= 0.30
        and candidate["d2_max"] <= 2.40
    )
    linear_guard = (
        candidate["d1_max"] <= 13.0
        and candidate["d1_mean"] <= 5.7
        and candidate["d1_r2"] >= 0.9963
        and candidate["d1_max"] <= current["d1_max"] + 4.20
    )
    gap_guard = 130 <= gap23_candidate <= 240 and gap23_candidate + 40 < gap23_current
    current_suspicious = current["d3_max"] > 2.5 or current["d2_max"] > 4.0 or gap23_current > 260
    if current_suspicious and gap_guard and nonlinear_win and excellent_nonlinear and linear_guard:
        return "nonlinear_repair_candidate"
    if current_suspicious and gap_guard and nonlinear_win and linear_guard:
        return "plausible_but_not_strong"
    return "not_safe"


def analyze_one(worker, row: pd.Series, timeout: int) -> dict[str, Any]:
    raw_path = Path(str(row["raw_path"]))
    response = worker.request(raw_path, "clonality", timeout)
    result, error = unwrap_result(response)
    base = {
        "file": raw_path.name,
        "raw_path": str(raw_path),
        "source_group": row.get("source_group", ""),
        "workbook_bucket": row.get("workbook_bucket", ""),
        "workbook_qc": row.get("workbook_qc", ""),
        "current_review": parse_bool(row.get("review", False)),
        "current_soft_fail": parse_bool(row.get("soft_fail", False)),
        "current_severe_fail": parse_bool(row.get("severe_fail", False)),
    }
    if error:
        return {**base, "ok": False, "error": error}
    preview = result.get("ladder_fit_preview") or {}
    selected = selected_scans(preview)
    peaks = peak_map(result.get("ladder_peak_preview") or [])
    if len(selected) != len(ROX_SIZES):
        return {**base, "ok": True, "status": "wrong_selected_count", "selected": json.dumps(selected)}
    current = {}
    for degree in (1, 2, 3):
        max_abs, mean_abs, r2 = polynomial_metrics(selected, degree)
        current[f"d{degree}_max"] = max_abs
        current[f"d{degree}_mean"] = mean_abs
        current[f"d{degree}_r2"] = r2

    best: dict[str, Any] | None = None
    for pair in candidate_pairs(selected, peaks):
        trial = [pair[0], pair[1], *selected[2:]]
        if not all(left < right for left, right in zip(trial, trial[1:])):
            continue
        candidate = {}
        for degree in (1, 2, 3):
            max_abs, mean_abs, r2 = polynomial_metrics(trial, degree)
            candidate[f"d{degree}_max"] = max_abs
            candidate[f"d{degree}_mean"] = mean_abs
            candidate[f"d{degree}_r2"] = r2
        if not all(finite(value) for value in candidate.values()):
            continue
        shape = pair_shape_score(peaks.get(pair[0]), peaks.get(pair[1]))
        status = nonlinear_candidate_status(current, candidate, selected, pair)
        record = {
            **base,
            "ok": True,
            "status": status,
            "candidate_first": pair[0],
            "candidate_second": pair[1],
            "current_first": selected[0],
            "current_second": selected[1],
            "current_third": selected[2],
            "candidate_gap12": pair[1] - pair[0],
            "candidate_gap23": selected[2] - pair[1],
            "current_gap12": selected[1] - selected[0],
            "current_gap23": selected[2] - selected[1],
            "pair_shape_score": shape,
            "selected": json.dumps(selected, separators=(",", ":")),
            "candidate_selected": json.dumps(trial, separators=(",", ":")),
            **{f"current_{key}": value for key, value in current.items()},
            **{f"candidate_{key}": value for key, value in candidate.items()},
            "delta_d1_max": candidate["d1_max"] - current["d1_max"],
            "delta_d2_max": candidate["d2_max"] - current["d2_max"],
            "delta_d3_max": candidate["d3_max"] - current["d3_max"],
        }
        key = (
            0 if status == "nonlinear_repair_candidate" else 1 if status == "plausible_but_not_strong" else 2,
            candidate["d3_max"],
            candidate["d2_max"],
            shape,
            candidate["d1_max"],
        )
        if best is None or key < best["_sort_key"]:
            record["_sort_key"] = key
            best = record
    if best is None:
        return {**base, "ok": True, "status": "no_pair_candidate", "selected": json.dumps(selected, separators=(",", ":"))}
    best.pop("_sort_key", None)
    return best


def load_rows(path: Path, limit: int) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    df = df[df["ladder"].astype(str).eq("ROX400HD")].copy()
    df = df[df["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    df = df.drop_duplicates(subset=["raw_path"], keep="first")
    if limit > 0:
        priority = (
            df["review"].map(parse_bool).astype(int) * 1000
            + df["soft_fail"].map(parse_bool).astype(int) * 100
            + pd.to_numeric(df["linear_max"], errors="coerce").fillna(0)
        )
        df = df.assign(_priority=priority).sort_values(["_priority", "file"], ascending=[False, True]).head(limit)
    return df.copy()


def run(args: argparse.Namespace) -> None:
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(input_path, args.limit)
    rows.to_csv(out_dir / "input_rows.tsv", sep="\t", index=False)

    worker_pool = _get_rust_worker_pool(max(1, args.workers))
    if not worker_pool:
        raise SystemExit("Could not start Rust worker pool")
    timeout = max(_rust_timeout_seconds("clonality"), args.timeout)
    row_list = [row for _, row in rows.iterrows()]
    shards = [[] for _ in worker_pool]
    for idx, row in enumerate(row_list):
        shards[idx % len(worker_pool)].append(row)

    def run_shard(worker_index: int, shard: list[pd.Series]) -> list[dict[str, Any]]:
        worker = worker_pool[worker_index]
        return [analyze_one(worker, row, timeout) for row in shard]

    output: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(worker_pool)) as executor:
        futures = [executor.submit(run_shard, idx, shard) for idx, shard in enumerate(shards) if shard]
        for done, future in enumerate(as_completed(futures), start=1):
            output.extend(future.result())
            print(f"completed shard {done}/{len(futures)} rows={len(output)}", flush=True)
            pd.DataFrame(output).drop(columns=["_sort_key"], errors="ignore").to_csv(
                out_dir / "shadow_results.partial.tsv", sep="\t", index=False
            )
    _invalidate_rust_worker_pool()

    result = pd.DataFrame(output).drop(columns=["_sort_key"], errors="ignore")
    result.to_csv(out_dir / "shadow_results.tsv", sep="\t", index=False)
    summary = {
        "input_rows": int(len(rows)),
        "output_rows": int(len(result)),
        "ok": int(result.get("ok", pd.Series(dtype=bool)).map(parse_bool).sum()) if not result.empty else 0,
        "status_counts": result.get("status", pd.Series(dtype=str)).value_counts(dropna=False).to_dict() if not result.empty else {},
        "candidate_rows": result[result.get("status", pd.Series(dtype=str)).eq("nonlinear_repair_candidate")][
            ["file", "candidate_first", "candidate_second", "current_first", "current_second", "current_d1_max", "candidate_d1_max", "current_d2_max", "candidate_d2_max", "current_d3_max", "candidate_d3_max"]
        ].to_dict(orient="records")
        if not result.empty
        else [],
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--limit", type=int, default=0)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
