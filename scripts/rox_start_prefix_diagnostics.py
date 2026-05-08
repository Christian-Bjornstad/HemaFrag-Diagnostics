from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402


DEFAULT_LEARNING_CASES = (
    ROOT
    / "artifacts"
    / "overnight_manual_review_learning_2026-05-05"
    / "manual_review_learning_cases.tsv"
)
DEFAULT_OUT_DIR = ROOT / "artifacts" / "rox_start_prefix_diagnostics_2026-05-05"

ROX_SIZES = [
    50,
    60,
    90,
    100,
    120,
    150,
    160,
    180,
    190,
    200,
    220,
    240,
    260,
    280,
    290,
    300,
    320,
    340,
    360,
    380,
    400,
]
EXCLUDED_CATEGORIES = {"operator_or_bad_ladder"}


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_int(value: object) -> int | None:
    raw = text(value)
    if not raw:
        return None
    try:
        return int(round(float(raw)))
    except ValueError:
        return None


def parse_float(value: object) -> float:
    raw = text(value)
    if not raw:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def manual_adjustment_times(raw_path: Path) -> list[int]:
    path = raw_path.with_suffix(".ladder_adj.json")
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    mapping_times = payload.get("mapping_times") or {}
    rows: list[tuple[int, int]] = []
    for key, value in mapping_times.items():
        step = parse_int(key)
        scan = parse_int(value)
        if step is not None and scan is not None:
            rows.append((step, scan))
    return [scan for _step, scan in sorted(rows)]


def selected_scans(preview: dict[str, Any]) -> list[int]:
    refinement = preview.get("refinement") or {}
    scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    return [parsed for value in scans if (parsed := parse_int(value)) is not None]


def unwrap_response(response: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    if not isinstance(response, dict):
        return {}, "no response"
    if response.get("error"):
        return {}, text(response.get("error"))
    if response.get("ok") is False:
        return {}, text(response.get("error") or "rust response not ok")
    result = response.get("result")
    if isinstance(result, dict):
        return result, ""
    if isinstance(response.get("ladder_fit_preview"), dict):
        return response, ""
    return {}, "missing result"


def analyze_path(raw_path: Path, timeout: int) -> dict[str, Any]:
    worker = _get_rust_worker()
    if worker is None:
        return {"ok": False, "error": "Rust worker unavailable"}
    response = worker.request(raw_path, "clonality", timeout)
    result, error = unwrap_response(response)
    if error and ("timeout" in error.lower() or error == "no response"):
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is not None:
            response = worker.request(raw_path, "clonality", max(timeout * 2, 120))
            result, error = unwrap_response(response)
    if error:
        return {"ok": False, "error": error}
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    return {
        "ok": True,
        "result": result,
        "ladder": text(result.get("ladder") or preview.get("ladder_kind")),
        "selected": selected_scans(preview),
        "linear_max": metrics.get("linear_trend_max_abs_error_bp"),
        "linear_mean": metrics.get("linear_trend_mean_abs_error_bp"),
        "linear_r2": metrics.get("linear_trend_r2"),
        "review": bool(review.get("suggested_review")),
        "reason_codes": review.get("reason_codes") or [],
    }


def nearest(values: list[int], target: int) -> tuple[int | None, int | None]:
    if not values:
        return None, None
    item = min(values, key=lambda value: abs(value - target))
    return item, abs(item - target)


def linear_metrics(scans: list[int], sizes: list[int] = ROX_SIZES) -> tuple[float, float, float]:
    if len(scans) != len(sizes) or len(scans) < 3:
        return float("nan"), float("nan"), float("nan")
    n = float(len(scans))
    xs = [float(value) for value in sizes]
    ys = [float(value) for value in scans]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return float("nan"), float("nan"), float("nan")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    if slope <= 0 or not math.isfinite(slope):
        return float("nan"), float("nan"), float("nan")
    intercept = mean_y - slope * mean_x
    predicted_bp = [(scan - intercept) / slope for scan in ys]
    abs_errors = [abs(pred - bp) for pred, bp in zip(predicted_bp, xs)]
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return max(abs_errors), sum(abs_errors) / len(abs_errors), r2


def peak_by_index(peaks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for peak in peaks:
        idx = parse_int(peak.get("index"))
        if idx is not None:
            out[idx] = peak
    return out


def peak_feature(prefix: str, peak: dict[str, Any] | None, height_ref: float, prom_ref: float) -> dict[str, Any]:
    if not peak:
        return {
            f"{prefix}_height": "",
            f"{prefix}_prominence": "",
            f"{prefix}_width": "",
            f"{prefix}_baseline": "",
            f"{prefix}_baseline_ratio": "",
            f"{prefix}_purity": "",
            f"{prefix}_height_ratio": "",
            f"{prefix}_prom_ratio": "",
            f"{prefix}_score": "",
            f"{prefix}_feature_penalty": "",
        }
    height = max(parse_float(peak.get("height")), 1.0)
    prominence = max(parse_float(peak.get("prominence")), 0.0)
    baseline = parse_float(peak.get("local_baseline"))
    baseline_ratio = max(baseline, 0.0) / height
    purity = prominence / height
    height_ratio = height / max(height_ref, 1.0)
    prom_ratio = prominence / max(prom_ref, 1.0)
    weak = max(0.0, 0.40 - min(height_ratio, prom_ratio)) / 0.40
    huge = max(0.0, max(height_ratio, prom_ratio) - 7.0) / 7.0
    baseline_like = max(0.0, baseline_ratio - 0.12) / 0.18
    low_purity = max(0.0, 0.55 - min(purity, 2.0)) / 0.55
    penalty = weak * 1.2 + huge * 0.8 + baseline_like * 1.1 + low_purity * 0.8
    return {
        f"{prefix}_height": height,
        f"{prefix}_prominence": prominence,
        f"{prefix}_width": peak.get("width", ""),
        f"{prefix}_baseline": baseline,
        f"{prefix}_baseline_ratio": baseline_ratio,
        f"{prefix}_purity": purity,
        f"{prefix}_height_ratio": height_ratio,
        f"{prefix}_prom_ratio": prom_ratio,
        f"{prefix}_score": peak.get("score", ""),
        f"{prefix}_feature_penalty": penalty,
    }


def pair_label(pair: tuple[int, int], current: list[int], manual: list[int]) -> str:
    tags: list[str] = []
    if len(current) >= 2 and abs(pair[0] - current[0]) <= 2 and abs(pair[1] - current[1]) <= 2:
        tags.append("current")
    if len(manual) >= 2 and abs(pair[0] - manual[0]) <= 2 and abs(pair[1] - manual[1]) <= 2:
        tags.append("manual")
    return "+".join(tags) if tags else "candidate"


def pair_rows_for_case(
    file_name: str,
    selected: list[int],
    manual: list[int],
    peaks: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(selected) != len(ROX_SIZES) or len(selected) < 6:
        return []
    later = [peaks.get(scan) for scan in selected[2:7]]
    later = [peak for peak in later if peak]
    if not later:
        return []
    height_ref = sorted(max(parse_float(peak.get("height")), 1.0) for peak in later)[len(later) // 2]
    prom_ref = sorted(max(parse_float(peak.get("prominence")), 1.0) for peak in later)[len(later) // 2]
    candidate_indices = sorted(peaks)
    left_bound = max(1300, min(selected[:2] + manual[:2] or selected[:2]) - 260)
    right_bound = selected[2] - 8
    start_candidates = [idx for idx in candidate_indices if left_bound <= idx <= right_bound]
    rows: list[dict[str, Any]] = []
    current_max, current_mean, current_r2 = linear_metrics(selected)
    for i, first in enumerate(start_candidates):
        for second in start_candidates[i + 1 :]:
            first_gap = second - first
            second_gap = selected[2] - second
            if not (35 <= first_gap <= 115 and 90 <= second_gap <= 280):
                continue
            trial = [first, second] + selected[2:]
            linear_max, linear_mean, linear_r2 = linear_metrics(trial)
            f1 = peak_feature("first", peaks.get(first), height_ref, prom_ref)
            f2 = peak_feature("second", peaks.get(second), height_ref, prom_ref)
            feature_penalty = parse_float(f1.get("first_feature_penalty")) + parse_float(
                f2.get("second_feature_penalty")
            )
            rows.append(
                {
                    "file": file_name,
                    "pair_label": pair_label((first, second), selected, manual),
                    "first_scan": first,
                    "second_scan": second,
                    "third_scan": selected[2],
                    "first_gap": first_gap,
                    "second_gap_to_third": second_gap,
                    "linear_max": linear_max,
                    "linear_mean": linear_mean,
                    "linear_r2": linear_r2,
                    "delta_linear_max_vs_current": linear_max - current_max,
                    "delta_linear_mean_vs_current": linear_mean - current_mean,
                    "feature_penalty": feature_penalty,
                    **f1,
                    **f2,
                }
            )
    rows.sort(key=lambda row: (parse_float(row["linear_max"]), parse_float(row["linear_mean"]), parse_float(row["feature_penalty"])))
    for rank, row in enumerate(rows, start=1):
        row["rank_by_linear"] = rank
    rows.sort(key=lambda row: (parse_float(row["feature_penalty"]), parse_float(row["linear_max"]), parse_float(row["linear_mean"])))
    for rank, row in enumerate(rows, start=1):
        row["rank_by_feature"] = rank
    return rows


def load_cases(path: Path) -> list[dict[str, str]]:
    rows = read_tsv(path)
    out: list[dict[str, str]] = []
    for row in rows:
        if text(row.get("ladder")).upper() != "ROX":
            continue
        if text(row.get("label")) != "manual_adjusted":
            continue
        if text(row.get("learning_category")) in EXCLUDED_CATEGORIES:
            continue
        if parse_int(row.get("manual_count")) != len(ROX_SIZES):
            continue
        raw_path = Path(text(row.get("full_path")))
        if not raw_path.exists():
            continue
        out.append(row)
    out.sort(key=lambda row: (text(row.get("learning_category")), text(row.get("file"))))
    return out


def run(args: argparse.Namespace) -> None:
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = load_cases(args.learning_cases)
    case_rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(cases, start=1):
        raw_path = Path(text(row.get("full_path")))
        analysis = analyze_path(raw_path, args.timeout)
        if not analysis.get("ok"):
            case_rows.append(
                {
                    "index": idx,
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "ok": False,
                    "error": analysis.get("error", ""),
                    "learning_category": row.get("learning_category", ""),
                    "tags": row.get("tags", ""),
                    "note": row.get("note", ""),
                }
            )
            continue
        result = analysis["result"]
        preview_peaks = result.get("ladder_peak_preview") or []
        peaks = peak_by_index(preview_peaks)
        candidates = sorted(peaks)
        selected = [int(value) for value in analysis.get("selected") or []]
        manual = manual_adjustment_times(raw_path)
        pair_table = pair_rows_for_case(raw_path.name, selected, manual, peaks)
        pair_rows.extend(pair_table)

        manual_pair = next((item for item in pair_table if "manual" in str(item.get("pair_label"))), None)
        current_pair = next((item for item in pair_table if "current" in str(item.get("pair_label"))), None)
        best_linear_pair = min(pair_table, key=lambda item: parse_float(item.get("rank_by_linear")), default=None)
        best_feature_pair = min(pair_table, key=lambda item: parse_float(item.get("rank_by_feature")), default=None)
        manual_covered = 0
        auto_match = 0
        max_manual_nearest_delta = 0
        for step, target in enumerate(manual[: len(ROX_SIZES)], start=1):
            near, delta = nearest(candidates, int(target))
            delta_value = int(delta) if delta is not None else 999999
            max_manual_nearest_delta = max(max_manual_nearest_delta, delta_value)
            manual_covered += int(delta_value <= 5)
            auto_delta = (
                abs(selected[step - 1] - int(target)) if step - 1 < len(selected) else 999999
            )
            auto_match += int(auto_delta <= 2)
            peak = peaks.get(near or -1)
            step_rows.append(
                {
                    "file": raw_path.name,
                    "step": step,
                    "bp": ROX_SIZES[step - 1],
                    "manual_scan": int(target),
                    "auto_scan": selected[step - 1] if step - 1 < len(selected) else "",
                    "auto_delta": auto_delta,
                    "nearest_candidate": near if near is not None else "",
                    "nearest_candidate_delta": delta_value,
                    "manual_covered_5": delta_value <= 5,
                    **peak_feature("nearest", peak, 1.0, 1.0),
                }
            )

        if len(selected) >= 3 or len(manual) >= 3:
            window_min = max(1200, min((selected[:3] or [9999]) + (manual[:3] or [9999])) - 300)
            window_max = max((selected[:3] or [0]) + (manual[:3] or [0])) + 300
            for peak_idx in candidates:
                if not (window_min <= peak_idx <= window_max):
                    continue
                peak = peaks[peak_idx]
                nearest_manual, manual_delta = nearest(manual[:4], peak_idx) if manual else (None, None)
                nearest_auto, auto_delta = nearest(selected[:4], peak_idx) if selected else (None, None)
                candidate_rows.append(
                    {
                        "file": raw_path.name,
                        "scan": peak_idx,
                        "nearest_manual_start_scan": nearest_manual if nearest_manual is not None else "",
                        "nearest_manual_delta": manual_delta if manual_delta is not None else "",
                        "nearest_auto_start_scan": nearest_auto if nearest_auto is not None else "",
                        "nearest_auto_delta": auto_delta if auto_delta is not None else "",
                        "is_manual_start_5": bool(manual_delta is not None and manual_delta <= 5),
                        "is_auto_start_5": bool(auto_delta is not None and auto_delta <= 5),
                        **peak_feature("peak", peak, 1.0, 1.0),
                    }
                )

        case_rows.append(
            {
                "index": idx,
                "file": raw_path.name,
                "raw_path": str(raw_path),
                "ok": True,
                "learning_category": row.get("learning_category", ""),
                "tags": row.get("tags", ""),
                "note": row.get("note", ""),
                "candidate_count": len(candidates),
                "manual_coverage_5": manual_covered,
                "auto_match_2": auto_match,
                "max_manual_nearest_delta": max_manual_nearest_delta,
                "current_review": analysis.get("review"),
                "current_reason_codes": json.dumps(analysis.get("reason_codes") or [], separators=(",", ":")),
                "current_linear_max": analysis.get("linear_max"),
                "current_linear_mean": analysis.get("linear_mean"),
                "current_linear_r2": analysis.get("linear_r2"),
                "auto_first": selected[0] if selected else "",
                "auto_second": selected[1] if len(selected) > 1 else "",
                "auto_third": selected[2] if len(selected) > 2 else "",
                "manual_first": manual[0] if manual else "",
                "manual_second": manual[1] if len(manual) > 1 else "",
                "manual_third": manual[2] if len(manual) > 2 else "",
                "manual_pair_rank_by_linear": manual_pair.get("rank_by_linear") if manual_pair else "",
                "manual_pair_rank_by_feature": manual_pair.get("rank_by_feature") if manual_pair else "",
                "current_pair_rank_by_linear": current_pair.get("rank_by_linear") if current_pair else "",
                "current_pair_rank_by_feature": current_pair.get("rank_by_feature") if current_pair else "",
                "best_linear_pair": ""
                if not best_linear_pair
                else f"{best_linear_pair['first_scan']},{best_linear_pair['second_scan']}",
                "best_linear_pair_label": best_linear_pair.get("pair_label") if best_linear_pair else "",
                "best_linear_pair_qc": ""
                if not best_linear_pair
                else f"{float(best_linear_pair['linear_max']):.3f}/{float(best_linear_pair['linear_mean']):.3f}/{float(best_linear_pair['linear_r2']):.6f}",
                "best_feature_pair": ""
                if not best_feature_pair
                else f"{best_feature_pair['first_scan']},{best_feature_pair['second_scan']}",
                "best_feature_pair_label": best_feature_pair.get("pair_label") if best_feature_pair else "",
                "selected": json.dumps(selected, separators=(",", ":")),
                "manual": json.dumps(manual, separators=(",", ":")),
            }
        )
        print(f"{idx}/{len(cases)} {raw_path.name}: pairs={len(pair_table)}")

    write_tsv(out_dir / "case_summary.tsv", case_rows)
    write_tsv(out_dir / "prefix_steps.tsv", step_rows)
    write_tsv(out_dir / "candidate_start_window.tsv", candidate_rows)
    write_tsv(out_dir / "prefix_pair_candidates.tsv", pair_rows)

    ok_cases = [row for row in case_rows if row.get("ok") is True]
    category_counts = Counter(text(row.get("learning_category")) for row in ok_cases)
    lines = [
        "# ROX Start Prefix Diagnostics",
        "",
        f"- evaluated ROX manual cases: {len(ok_cases)}",
        f"- median manual candidate coverage <=5 scans: {median([parse_float(row.get('manual_coverage_5')) for row in ok_cases]):.1f}/21",
        f"- median auto/manual match <=2 scans: {median([parse_float(row.get('auto_match_2')) for row in ok_cases]):.1f}/21",
        "",
        "## Learning Categories",
    ]
    for key, count in sorted(category_counts.items()):
        lines.append(f"- {key or 'unknown'}: {count}")
    lines.extend(["", "## Cases Needing Prefix Attention"])
    for row in sorted(
        ok_cases,
        key=lambda item: (
            parse_float(item.get("auto_match_2")),
            parse_float(item.get("manual_coverage_5")),
            -parse_float(item.get("current_linear_max")),
        ),
    ):
        if parse_float(row.get("auto_match_2")) >= 19 and parse_float(row.get("current_linear_max")) < 8:
            continue
        lines.append(
            f"- {row['file']}: auto={row['auto_first']},{row['auto_second']},{row['auto_third']} "
            f"manual={row['manual_first']},{row['manual_second']},{row['manual_third']} "
            f"match2={row['auto_match_2']}/21 cand5={row['manual_coverage_5']}/21 "
            f"manual_pair_rank={row['manual_pair_rank_by_linear']}/{row['manual_pair_rank_by_feature']} "
            f"best_linear={row['best_linear_pair']}({row['best_linear_pair_label']}) "
            f"qc={float(row['current_linear_max']):.2f}/{float(row['current_linear_mean']):.2f}/{float(row['current_linear_r2']):.6f}"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "cases": len(case_rows),
        "ok_cases": len(ok_cases),
        "pair_candidates": len(pair_rows),
        "candidate_start_window_rows": len(candidate_rows),
        "category_counts": dict(category_counts),
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def median(values: list[float]) -> float:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return float("nan")
    middle = len(clean) // 2
    if len(clean) % 2:
        return clean[middle]
    return (clean[middle - 1] + clean[middle]) / 2.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learning-cases", type=Path, default=DEFAULT_LEARNING_CASES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=int, default=90)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
