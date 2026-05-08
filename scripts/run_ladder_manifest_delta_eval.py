from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402


DEFAULT_MANIFEST = ROOT / "artifacts" / "ladder_learning_manifest" / "current_manifest.tsv"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "ladder_manifest_delta_eval"
LADDER_COUNTS = {"LIZ500_250": 16, "ROX400HD": 21}


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_float(value: object) -> float:
    raw = text(value)
    if not raw:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def parse_int(value: object) -> int | None:
    raw = text(value)
    if not raw:
        return None
    try:
        return int(round(float(raw)))
    except ValueError:
        return None


def parse_selected(value: object) -> list[int]:
    raw = text(value)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw.strip("[]").split(",")
    out: list[int] = []
    if isinstance(payload, list):
        for item in payload:
            parsed = parse_int(item)
            if parsed is not None:
                out.append(parsed)
    return out


def manual_adjustment_times(path: Path) -> list[int]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    mapping = payload.get("mapping_times") or {}
    rows: list[tuple[int, int]] = []
    for key, value in mapping.items():
        step = parse_int(key)
        scan = parse_int(value)
        if step is not None and scan is not None:
            rows.append((step, scan))
    return [scan for _step, scan in sorted(rows)]


def selected_scans(preview: dict[str, Any]) -> list[int]:
    refinement = preview.get("refinement") or {}
    scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    out: list[int] = []
    for value in scans:
        parsed = parse_int(value)
        if parsed is not None:
            out.append(parsed)
    return out


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


def complete_qc_ok(
    ladder: str,
    selected_count: int,
    expected_count: int,
    linear_max: float,
    linear_mean: float,
    linear_r2: float,
    quadratic_max: float,
    quadratic_mean: float,
    quadratic_r2: float,
) -> bool:
    if selected_count != expected_count or expected_count != LADDER_COUNTS.get(ladder, 0):
        return False
    if ladder == "ROX400HD":
        return bool(
            linear_max <= 13.0
            and linear_mean <= 5.7
            and linear_r2 >= 0.9963
            and quadratic_max <= 2.5
            and quadratic_mean <= 1.1
            and quadratic_r2 >= 0.99985
        )
    if ladder == "LIZ500_250":
        return bool(
            linear_max <= 7.2
            and linear_mean <= 3.6
            and linear_r2 >= 0.9993
            and quadratic_max <= 6.0
            and quadratic_mean <= 2.3
            and quadratic_r2 >= 0.9997
        )
    return False


def analyze_path(path: Path, timeout: int) -> dict[str, Any]:
    worker = _get_rust_worker()
    if worker is None:
        return {"ok": False, "error": "Rust worker unavailable"}

    response = worker.request(path, "clonality", timeout)
    result, error = unwrap_response(response)
    if error and ("timeout" in error.lower() or error == "no response"):
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is not None:
            response = worker.request(path, "clonality", max(timeout * 2, 120))
            result, error = unwrap_response(response)
    if error:
        return {"ok": False, "error": error}

    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    peaks = result.get("ladder_peak_preview") or []
    selected = selected_scans(preview)
    expected_count = len(preview.get("expected_sizes") or []) or len(selected)
    ladder = text(result.get("ladder") or preview.get("ladder_kind") or "")
    linear_max = parse_float(metrics.get("linear_trend_max_abs_error_bp"))
    linear_mean = parse_float(metrics.get("linear_trend_mean_abs_error_bp"))
    linear_r2 = parse_float(metrics.get("linear_trend_r2"))
    quadratic_max = parse_float(metrics.get("quadratic_trend_max_abs_error_bp"))
    quadratic_mean = parse_float(metrics.get("quadratic_trend_mean_abs_error_bp"))
    quadratic_r2 = parse_float(metrics.get("quadratic_trend_r2"))
    return {
        "ok": True,
        "ladder": ladder,
        "review": bool(review.get("suggested_review")),
        "primary_reason": review.get("primary_reason") or "",
        "reason_codes": json.dumps(review.get("reason_codes") or [], separators=(",", ":")),
        "candidate_count": len(peaks) if isinstance(peaks, list) else "",
        "selected_count": len(selected),
        "expected_count": expected_count,
        "complete_qc_ok": complete_qc_ok(
            ladder,
            len(selected),
            expected_count,
            linear_max,
            linear_mean,
            linear_r2,
            quadratic_max,
            quadratic_mean,
            quadratic_r2,
        ),
        "linear_max": linear_max,
        "linear_mean": linear_mean,
        "linear_r2": linear_r2,
        "quadratic_max": quadratic_max,
        "quadratic_mean": quadratic_mean,
        "quadratic_r2": quadratic_r2,
        "selected": selected,
    }


def compare_series(current: list[int], reference: list[int]) -> dict[str, Any]:
    if not current or not reference:
        return {
            "ref_count": len(reference),
            "match_2": "",
            "match_5": "",
            "changed_steps": "",
            "max_abs_delta": "",
            "mean_abs_delta": "",
        }
    deltas = [abs(current[idx] - reference[idx]) for idx in range(min(len(current), len(reference)))]
    changed = sum(1 for delta in deltas if delta > 2) + abs(len(current) - len(reference))
    return {
        "ref_count": len(reference),
        "match_2": sum(1 for delta in deltas if delta <= 2),
        "match_5": sum(1 for delta in deltas if delta <= 5),
        "changed_steps": changed,
        "max_abs_delta": max(deltas) if deltas else "",
        "mean_abs_delta": sum(deltas) / len(deltas) if deltas else "",
    }


def valid_scan_reference(reference: list[int]) -> bool:
    if not reference:
        return False
    # Review bundles may contain internal best-combination indices. Real ladder
    # scan positions for these runs are never in the first few hundred points.
    return max(reference) >= 1000 and min(reference) >= 900


def load_manifest(path: Path, include_uses: set[str], limit: int | None) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter="\t")]
    rows = [row for row in rows if text(row.get("expected_use")) in include_uses]
    rows = [row for row in rows if text(row.get("full_path")) and Path(text(row.get("full_path"))).exists()]
    rows.sort(key=lambda row: (text(row.get("expected_use")), text(row.get("ladder")), text(row.get("file"))))
    if limit is not None and limit > 0:
        return rows[:limit]
    return rows


def run_eval(rows: list[dict[str, str]], timeout: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        raw_path = Path(text(row.get("full_path")))
        analysis = analyze_path(raw_path, timeout)
        manifest_selected = parse_selected(row.get("selected_peaks"))
        adjustment_path = Path(text(row.get("manual_adjustment_path"))) if text(row.get("manual_adjustment_path")) else raw_path.with_suffix(".ladder_adj.json")
        manual_selected = manual_adjustment_times(adjustment_path)
        selected = analysis.get("selected") if analysis.get("ok") else []
        reference = manual_selected or (manifest_selected if valid_scan_reference(manifest_selected) else [])
        comparison = compare_series([int(v) for v in selected], reference)
        previous_max = parse_float(row.get("linear_max"))
        current_max = parse_float(analysis.get("linear_max")) if analysis.get("ok") else float("nan")
        previous_mean = parse_float(row.get("linear_mean"))
        current_mean = parse_float(analysis.get("linear_mean")) if analysis.get("ok") else float("nan")
        result = {
            "index": idx,
            "file": row.get("file", ""),
            "full_path": str(raw_path),
            "assay": row.get("assay", ""),
            "ladder": analysis.get("ladder") or row.get("ladder", ""),
            "expected_use": row.get("expected_use", ""),
            "learning_category": row.get("learning_category", ""),
            "review_label": row.get("review_label", ""),
            "ok": bool(analysis.get("ok")),
            "error": analysis.get("error", ""),
            "current_review": analysis.get("review", ""),
            "current_primary_reason": analysis.get("primary_reason", ""),
            "current_reason_codes": analysis.get("reason_codes", ""),
            "candidate_count": analysis.get("candidate_count", ""),
            "selected_count": analysis.get("selected_count", ""),
            "expected_count": analysis.get("expected_count", ""),
            "current_complete_qc_ok": analysis.get("complete_qc_ok", ""),
            "current_linear_max": analysis.get("linear_max", ""),
            "current_linear_mean": analysis.get("linear_mean", ""),
            "current_linear_r2": analysis.get("linear_r2", ""),
            "current_quadratic_max": analysis.get("quadratic_max", ""),
            "current_quadratic_mean": analysis.get("quadratic_mean", ""),
            "current_quadratic_r2": analysis.get("quadratic_r2", ""),
            "manifest_linear_max": row.get("linear_max", ""),
            "manifest_linear_mean": row.get("linear_mean", ""),
            "manifest_linear_r2": row.get("linear_r2", ""),
            "delta_linear_max": "" if math.isnan(current_max) or math.isnan(previous_max) else current_max - previous_max,
            "delta_linear_mean": "" if math.isnan(current_mean) or math.isnan(previous_mean) else current_mean - previous_mean,
            "reference_source": "manual_adjustment"
            if manual_selected
            else ("manifest_selected" if reference else ("invalid_manifest_selected" if manifest_selected else "")),
            "reference_count": comparison["ref_count"],
            "reference_match_2": comparison["match_2"],
            "reference_match_5": comparison["match_5"],
            "reference_changed_steps": comparison["changed_steps"],
            "reference_max_abs_delta": comparison["max_abs_delta"],
            "reference_mean_abs_delta": comparison["mean_abs_delta"],
            "current_selected": json.dumps(selected, separators=(",", ":")),
            "reference_selected": json.dumps(reference, separators=(",", ":")),
        }
        out.append(result)
    return out


def write_outputs(results: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir = out_dir if out_dir.is_absolute() else ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(results[0].keys()) if results else []
    if fieldnames:
        with (out_dir / "case_results.tsv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)

    by_use = defaultdict(Counter)
    by_ladder = defaultdict(Counter)
    for row in results:
        use = text(row.get("expected_use")) or "unknown"
        ladder = text(row.get("ladder")) or "unknown"
        by_use[use]["rows"] += 1
        by_ladder[ladder]["rows"] += 1
        if row.get("ok"):
            by_use[use]["ok"] += 1
            by_ladder[ladder]["ok"] += 1
        else:
            by_use[use]["error"] += 1
            by_ladder[ladder]["error"] += 1
        if str(row.get("current_review")).lower() == "true":
            by_use[use]["review"] += 1
            by_ladder[ladder]["review"] += 1
        linear_max = parse_float(row.get("current_linear_max"))
        linear_mean = parse_float(row.get("current_linear_mean"))
        linear_r2 = parse_float(row.get("current_linear_r2"))
        if not math.isnan(linear_max) and linear_max > 6.0:
            by_use[use]["linear_max_gt6"] += 1
            by_ladder[ladder]["linear_max_gt6"] += 1
        if not math.isnan(linear_mean) and linear_mean > 3.0:
            by_use[use]["linear_mean_gt3"] += 1
            by_ladder[ladder]["linear_mean_gt3"] += 1
        if not math.isnan(linear_r2) and linear_r2 < 0.999:
            by_use[use]["linear_r2_lt999"] += 1
            by_ladder[ladder]["linear_r2_lt999"] += 1

    regressions = [
        row
        for row in results
        if row.get("ok")
        and (
            parse_float(row.get("current_linear_max")) > 6.0
            or str(row.get("current_review")).lower() == "true"
            or (parse_int(row.get("reference_changed_steps")) or 0) > 0
        )
    ]
    regressions.sort(
        key=lambda row: (
            str(row.get("expected_use")),
            -parse_float(row.get("current_linear_max")) if not math.isnan(parse_float(row.get("current_linear_max"))) else 0,
            str(row.get("file")),
        )
    )
    if regressions:
        with (out_dir / "watchlist.tsv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(regressions)

    summary = {
        "rows": len(results),
        "ok": sum(1 for row in results if row.get("ok")),
        "errors": sum(1 for row in results if not row.get("ok")),
        "review": sum(1 for row in results if str(row.get("current_review")).lower() == "true"),
        "by_expected_use": {key: dict(value) for key, value in sorted(by_use.items())},
        "by_ladder": {key: dict(value) for key, value in sorted(by_ladder.items())},
        "watchlist_rows": len(regressions),
        "case_results": str((out_dir / "case_results.tsv").relative_to(ROOT)),
        "watchlist": str((out_dir / "watchlist.tsv").relative_to(ROOT)) if regressions else "",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run current Rust ladder engine against the ladder learning manifest.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--include-uses", default="training_pair,non_regression_control")
    parser.add_argument("--limit", type=int, default=0, help="0 means all filtered rows.")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    include_uses = {item.strip() for item in args.include_uses.split(",") if item.strip()}
    rows = load_manifest(args.manifest, include_uses, args.limit or None)
    if not rows:
        raise SystemExit("No manifest rows matched the selected filters.")
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    write_outputs(run_eval(rows, args.timeout), out_dir)


if __name__ == "__main__":
    main()
