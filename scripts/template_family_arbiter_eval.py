from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval  # noqa: E402
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402


DEFAULT_BROAD_DIR = ROOT / "artifacts" / "broad_live_ladder_learning_overnight_9000_2026-05-06"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "template_family_arbiter_eval_2026-05-06"
DEFAULT_MANIFEST = ROOT / "artifacts" / "ladder_learning_manifest" / "current_manifest.tsv"

LADDER_SIZES: dict[str, list[int]] = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


@dataclass(frozen=True)
class StatBand:
    median: float
    p10: float
    p90: float
    p05: float
    p95: float
    count: int


@dataclass
class BeamItem:
    indices: list[int]
    score: float
    template_penalty: float
    peak_penalty: float


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_float(value: object, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def parse_int(value: object) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def selected_scans(preview: dict[str, Any]) -> list[int]:
    refinement = preview.get("refinement") or {}
    values = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    return [parsed for value in values if (parsed := parse_int(value)) is not None]


def manual_adjustment_times(raw_path: Path) -> list[int]:
    path = raw_path.with_suffix(".ladder_adj.json")
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


def manual_distance(scans: list[int], manual: list[int]) -> tuple[float, float, int]:
    if not scans or len(scans) != len(manual):
        return float("nan"), float("nan"), 0
    deltas = [abs(int(left) - int(right)) for left, right in zip(scans, manual)]
    return float(max(deltas)), float(sum(deltas) / len(deltas)), int(sum(delta <= 2 for delta in deltas))


def linear_metrics(scans: list[int], sizes: list[int]) -> tuple[float, float, float]:
    if len(scans) != len(sizes) or len(scans) < 3:
        return float("nan"), float("nan"), float("nan")
    xs = np.asarray(sizes, dtype=float)
    ys = np.asarray(scans, dtype=float)
    slope, intercept = np.polyfit(xs, ys, deg=1)
    if not math.isfinite(float(slope)) or slope <= 0:
        return float("nan"), float("nan"), float("nan")
    predicted_bp = (ys - intercept) / slope
    abs_errors = np.abs(predicted_bp - xs)
    fitted = slope * xs + intercept
    ss_res = float(np.sum((ys - fitted) ** 2))
    ss_tot = float(np.sum((ys - float(np.mean(ys))) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(np.max(abs_errors)), float(np.mean(abs_errors)), float(r2)


def band_penalty(value: float, band: StatBand | None, slack: float, weight: float) -> float:
    if band is None or not math.isfinite(value):
        return 0.0
    lower = band.p10 - slack
    upper = band.p90 + slack
    if lower <= value <= upper:
        return 0.0
    delta = lower - value if value < lower else value - upper
    scale = max(slack, (band.p90 - band.p10) * 0.75, 8.0)
    return (delta / scale) * weight


def peak_quality_penalty(peak: dict[str, Any]) -> float:
    height = max(parse_float(peak.get("height"), 0.0), 1.0)
    prominence = max(parse_float(peak.get("prominence"), 0.0), 0.0)
    width = parse_float(peak.get("width"), 0.0)
    baseline = max(parse_float(peak.get("local_baseline"), 0.0), 0.0)
    score = max(parse_float(peak.get("score"), 0.0), 0.0)
    baseline_ratio = baseline / height
    purity = prominence / height
    penalty = 0.0
    penalty += max(0.0, baseline_ratio - 0.28) * 2.4
    penalty += max(0.0, 0.34 - purity) * 2.2
    penalty += max(0.0, 16.0 - prominence) / 20.0
    penalty += max(0.0, 14.0 - score) / 22.0
    if width < 0.5:
        penalty += 0.35
    if width > 95.0:
        penalty += min(1.4, (width - 95.0) / 80.0)
    return penalty


def family_peak_penalty(scans: list[int], peaks_by_index: dict[int, dict[str, Any]], ladder: str) -> float:
    selected = [peaks_by_index.get(scan) for scan in scans]
    selected = [peak for peak in selected if peak]
    if len(selected) < 4:
        return 9.0
    heights = np.asarray([max(parse_float(peak.get("height"), 0.0), 1.0) for peak in selected], dtype=float)
    prominences = np.asarray([max(parse_float(peak.get("prominence"), 0.0), 0.0) for peak in selected], dtype=float)
    height_ref = max(float(np.median(heights)), 1.0)
    prom_ref = max(float(np.median(prominences)), 1.0)
    penalty = 0.0
    for idx, peak in enumerate(selected):
        height = max(parse_float(peak.get("height"), 0.0), 1.0)
        prominence = max(parse_float(peak.get("prominence"), 0.0), 0.0)
        baseline = max(parse_float(peak.get("local_baseline"), 0.0), 0.0)
        purity = prominence / height
        height_ratio = height / height_ref
        prom_ratio = prominence / prom_ref
        baseline_ratio = baseline / height
        weak = max(0.0, 0.30 - min(height_ratio, prom_ratio)) / 0.30
        dirty = max(0.0, baseline_ratio - 0.26) / 0.34 + max(0.0, 0.40 - purity) / 0.40
        huge_early = 0.0
        if idx < 3:
            limit = 2.9 if ladder == "ROX400HD" else 4.3
            huge_early = max(0.0, height_ratio - limit) / limit
        tail_weak = 0.0
        if idx >= len(selected) - 3:
            tail_weak = max(0.0, 0.34 - min(height_ratio, prom_ratio)) / 0.34
        penalty += weak * 0.65 + dirty * 0.55 + huge_early * 0.90 + tail_weak * 0.45
    return penalty / len(selected)


def load_stat_bands(broad_dir: Path) -> tuple[dict[tuple[str, str, int], StatBand], dict[tuple[str, int], StatBand], dict[tuple[str, str, int], StatBand], dict[tuple[str, int], StatBand]]:
    source_bp: dict[tuple[str, str, int], StatBand] = {}
    global_bp: dict[tuple[str, int], StatBand] = {}
    source_gap: dict[tuple[str, str, int], StatBand] = {}
    global_gap: dict[tuple[str, int], StatBand] = {}

    bp_global_df = pd.read_csv(broad_dir / "template_bp_scan_stats.tsv", sep="\t")
    for row in bp_global_df.itertuples(index=False):
        global_bp[(str(row.ladder), int(row.bp))] = StatBand(
            median=float(row.median),
            p10=float(row.p10),
            p90=float(row.p90),
            p05=float(row.p05),
            p95=float(row.p95),
            count=int(row.count),
        )

    bp_source_df = pd.read_csv(broad_dir / "template_source_bp_scan_stats.tsv", sep="\t")
    for row in bp_source_df.itertuples(index=False):
        source_bp[(str(row.source_group), str(row.ladder), int(row.bp))] = StatBand(
            median=float(row.median),
            p10=float(row.p10),
            p90=float(row.p90),
            p05=float(row.p05),
            p95=float(row.p95),
            count=int(row.count),
        )

    gap_global_df = pd.read_csv(broad_dir / "template_gap_stats.tsv", sep="\t")
    for row in gap_global_df.itertuples(index=False):
        global_gap[(str(row.ladder), int(row.step_from))] = StatBand(
            median=float(row.median),
            p10=float(row.p10),
            p90=float(row.p90),
            p05=float(row.p05),
            p95=float(row.p95),
            count=int(row.count),
        )

    gap_detail = pd.read_csv(broad_dir / "template_gap_detail.tsv", sep="\t")
    for key, group in gap_detail.groupby(["source_group", "ladder", "step_from"], sort=True):
        arr = group["gap_scan"].to_numpy(dtype=float)
        source_group, ladder, step_from = str(key[0]), str(key[1]), int(key[2])
        source_gap[(source_group, ladder, step_from)] = StatBand(
            median=float(np.percentile(arr, 50)),
            p10=float(np.percentile(arr, 10)),
            p90=float(np.percentile(arr, 90)),
            p05=float(np.percentile(arr, 5)),
            p95=float(np.percentile(arr, 95)),
            count=int(arr.size),
        )
    return source_bp, global_bp, source_gap, global_gap


def analyze_path(raw_path: Path, timeout: int) -> dict[str, Any]:
    worker = _get_rust_worker()
    if worker is None:
        return {"ok": False, "error": "Rust worker unavailable"}
    response = worker.request(raw_path, "clonality", timeout)
    result = response.get("result") if isinstance(response, dict) else None
    error = ""
    if not isinstance(response, dict) or response.get("error") or response.get("ok") is False:
        error = str((response or {}).get("error") or "no response")
    if error and "timeout" in error.lower():
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is not None:
            response = worker.request(raw_path, "clonality", max(timeout * 2, 120))
            result = response.get("result") if isinstance(response, dict) else None
            error = "" if isinstance(result, dict) else str((response or {}).get("error") or "no response")
    if not isinstance(result, dict):
        return {"ok": False, "error": error or "missing result"}
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    return {
        "ok": True,
        "result": result,
        "ladder": str(result.get("ladder") or preview.get("ladder_kind") or ""),
        "selected": selected_scans(preview),
        "linear_max": parse_float(metrics.get("linear_trend_max_abs_error_bp")),
        "linear_mean": parse_float(metrics.get("linear_trend_mean_abs_error_bp")),
        "linear_r2": parse_float(metrics.get("linear_trend_r2")),
        "review": bool(review.get("suggested_review")),
        "primary_reason": str(review.get("primary_reason") or ""),
        "reason_codes": review.get("reason_codes") or [],
    }


def choose_cases(broad_dir: Path, max_controls_per_ladder: int) -> pd.DataFrame:
    live = pd.read_csv(broad_dir / "live_summary.tsv", sep="\t")
    for col in ["linear_max", "linear_mean", "linear_r2"]:
        live[col] = pd.to_numeric(live[col], errors="coerce")
    for col in ["review", "soft_fail", "severe_fail"]:
        live[col] = live[col].map(parse_bool)
    targets = live[live["soft_fail"] | live["severe_fail"] | live["review"]].copy()
    targets["eval_role"] = "target"

    controls: list[pd.DataFrame] = []
    trusted = live[(~live["soft_fail"]) & (~live["review"]) & (live["linear_max"] <= 5.0)].copy()
    for ladder, group in trusted.groupby("ladder", sort=True):
        ranked = group.sort_values(["source_group", "linear_max", "file"]).copy()
        if len(ranked) > max_controls_per_ladder:
            positions = np.linspace(0, len(ranked) - 1, max_controls_per_ladder).round().astype(int)
            ranked = ranked.iloc[positions]
        controls.append(ranked.assign(eval_role="control"))
    out = pd.concat([targets] + controls, ignore_index=True, sort=False)
    out = out[out["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    out = out.drop_duplicates(subset=["raw_path", "eval_role"], keep="first")
    return out


def load_manifest_annotations(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, sep="\t")
    keep = [
        col
        for col in [
            "file",
            "expected_use",
            "learning_category",
            "review_label",
            "tags",
            "review_note",
            "has_manual_adjustment",
        ]
        if col in df.columns
    ]
    if "file" not in keep:
        return {}
    rows = df[keep].drop_duplicates(subset=["file"], keep="first")
    return {str(row["file"]): row.to_dict() for _, row in rows.iterrows()}


def build_step_pools(
    peaks: list[dict[str, Any]],
    selected: list[int],
    source_group: str,
    ladder: str,
    source_bp: dict[tuple[str, str, int], StatBand],
    global_bp: dict[tuple[str, int], StatBand],
) -> list[list[int]]:
    sizes = LADDER_SIZES[ladder]
    by_index = {int(peak["index"]): peak for peak in peaks if parse_int(peak.get("index")) is not None}
    all_indices = sorted(by_index)
    pools: list[list[int]] = []
    for step_idx, bp in enumerate(sizes):
        step_band = source_bp.get((source_group, ladder, bp))
        global_band = global_bp.get((ladder, bp))
        windows: list[tuple[float, float]] = []
        for band, base_slack in [(step_band, 55.0), (global_band, 95.0)]:
            if band is None:
                continue
            span = max(band.p95 - band.p05, band.p90 - band.p10, 20.0)
            slack = max(base_slack, span * 0.55)
            if ladder == "LIZ500_250" and step_idx >= len(sizes) - 2:
                slack = max(slack, 150.0)
            if ladder == "ROX400HD" and step_idx < 3:
                slack = max(slack, 85.0)
            windows.append((band.p05 - slack, band.p95 + slack))
        if step_idx < len(selected):
            windows.append((selected[step_idx] - 65, selected[step_idx] + 65))

        candidates = []
        for index in all_indices:
            peak = by_index[index]
            if parse_float(peak.get("height"), 0.0) < 10.0 or parse_float(peak.get("prominence"), 0.0) < 8.0:
                continue
            if any(left <= index <= right for left, right in windows):
                candidates.append(index)
        if step_idx < len(selected) and selected[step_idx] in by_index and selected[step_idx] not in candidates:
            candidates.append(selected[step_idx])
        if not candidates and all_indices:
            target = (step_band or global_band)
            if target is not None:
                candidates = sorted(all_indices, key=lambda index: abs(index - target.median))[:6]

        def rank(index: int) -> tuple[float, float, int]:
            peak = by_index[index]
            step_pen = 0.0
            if step_band is not None:
                step_pen += abs(index - step_band.median) / max(step_band.p95 - step_band.p05, 40.0)
            elif global_band is not None:
                step_pen += abs(index - global_band.median) / max(global_band.p95 - global_band.p05, 80.0)
            return (step_pen + peak_quality_penalty(peak), -parse_float(peak.get("score"), 0.0), index)

        cap = 13 if ladder == "ROX400HD" else 15
        pools.append(sorted(sorted(set(candidates)), key=rank)[:cap])
    return pools


def run_template_beam(
    analysis: dict[str, Any],
    source_group: str,
    source_bp: dict[tuple[str, str, int], StatBand],
    global_bp: dict[tuple[str, int], StatBand],
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> dict[str, Any] | None:
    ladder = analysis["ladder"]
    if ladder not in LADDER_SIZES:
        return None
    result = analysis["result"]
    peaks = result.get("ladder_peak_preview") or []
    if not peaks:
        return None
    peaks_by_index = {int(peak["index"]): peak for peak in peaks if parse_int(peak.get("index")) is not None}
    sizes = LADDER_SIZES[ladder]
    selected = analysis["selected"]
    pools = build_step_pools(peaks, selected, source_group, ladder, source_bp, global_bp)
    if any(not pool for pool in pools):
        return None

    beam = [BeamItem(indices=[], score=0.0, template_penalty=0.0, peak_penalty=0.0)]
    beam_width = 90 if ladder == "ROX400HD" else 110
    min_sep = 6 if ladder == "ROX400HD" else 8
    for step_idx, pool in enumerate(pools):
        next_beam: list[BeamItem] = []
        bp = sizes[step_idx]
        step_band = source_bp.get((source_group, ladder, bp)) or global_bp.get((ladder, bp))
        for item in beam:
            last = item.indices[-1] if item.indices else None
            for index in pool:
                if last is not None and index <= last + min_sep:
                    continue
                if index in item.indices:
                    continue
                peak = peaks_by_index[index]
                step_penalty = band_penalty(index, step_band, 60.0, 0.35)
                gap_penalty = 0.0
                if last is not None:
                    gap = float(index - last)
                    gap_band = source_gap.get((source_group, ladder, step_idx)) or global_gap.get((ladder, step_idx))
                    gap_penalty = band_penalty(gap, gap_band, 16.0, 1.30)
                peak_penalty = peak_quality_penalty(peak) * 0.70
                next_beam.append(
                    BeamItem(
                        indices=item.indices + [index],
                        score=item.score + step_penalty + gap_penalty + peak_penalty,
                        template_penalty=item.template_penalty + step_penalty + gap_penalty,
                        peak_penalty=item.peak_penalty + peak_penalty,
                    )
                )
        next_beam.sort(key=lambda item: (item.score, item.template_penalty, item.peak_penalty, item.indices))
        beam = next_beam[:beam_width]
        if not beam:
            return None

    best: tuple[float, BeamItem, tuple[float, float, float], float] | None = None
    for item in beam:
        lmax, lmean, r2 = linear_metrics(item.indices, sizes)
        if not math.isfinite(lmax) or not math.isfinite(lmean) or not math.isfinite(r2):
            continue
        family_penalty = family_peak_penalty(item.indices, peaks_by_index, ladder)
        linear_penalty = max(0.0, lmax - 4.5) * 0.75 + max(0.0, lmean - 2.2) * 1.05 + max(0.0, 0.9992 - r2) * 900.0
        total = item.score + family_penalty * 2.10 + linear_penalty
        candidate = (total, item, (lmax, lmean, r2), family_penalty)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        return None
    total, item, metrics, family_pen = best
    return {
        "selected": item.indices,
        "linear_max": metrics[0],
        "linear_mean": metrics[1],
        "linear_r2": metrics[2],
        "total_score": total,
        "template_penalty": item.template_penalty,
        "peak_penalty": item.peak_penalty,
        "family_peak_penalty": family_pen,
    }


def summarize_decision(
    row: pd.Series,
    analysis: dict[str, Any],
    candidate: dict[str, Any] | None,
    manifest_annotations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected = analysis["selected"]
    ladder = analysis["ladder"]
    sizes = LADDER_SIZES.get(ladder, [])
    result = analysis.get("result") or {}
    peaks = result.get("ladder_peak_preview") or []
    peaks_by_index = {int(peak["index"]): peak for peak in peaks if parse_int(peak.get("index")) is not None}
    current_family_penalty = family_peak_penalty(selected, peaks_by_index, ladder) if sizes else float("nan")
    current_lmax = parse_float(analysis.get("linear_max"))
    current_lmean = parse_float(analysis.get("linear_mean"))
    current_r2 = parse_float(analysis.get("linear_r2"))
    file_name = Path(str(row.raw_path)).name
    annotation = manifest_annotations.get(file_name, {})
    raw_path = Path(str(row.raw_path))
    manual = manual_adjustment_times(raw_path)
    current_manual_max, current_manual_mean, current_manual_match2 = manual_distance(selected, manual)
    base = {
        "file": file_name,
        "raw_path": row.raw_path,
        "eval_role": row.eval_role,
        "source_group": row.source_group,
        "assay": row.assay,
        "ladder": ladder,
        "manifest_expected_use": annotation.get("expected_use", ""),
        "manifest_learning_category": annotation.get("learning_category", ""),
        "manifest_review_label": annotation.get("review_label", ""),
        "manifest_tags": annotation.get("tags", ""),
        "manifest_review_note": annotation.get("review_note", ""),
        "manifest_has_manual_adjustment": annotation.get("has_manual_adjustment", ""),
        "current_review": analysis.get("review", ""),
        "current_primary_reason": analysis.get("primary_reason", ""),
        "current_linear_max": current_lmax,
        "current_linear_mean": current_lmean,
        "current_linear_r2": current_r2,
        "current_family_peak_penalty": current_family_penalty,
        "manual_selected": json.dumps(manual, separators=(",", ":")) if manual else "",
        "current_manual_max_delta": current_manual_max,
        "current_manual_mean_delta": current_manual_mean,
        "current_manual_match2": current_manual_match2,
        "candidate_count": len(peaks),
        "current_selected": json.dumps(selected, separators=(",", ":")),
    }
    if candidate is None:
        base.update(
            {
                "arbiter_status": "no_candidate",
                "arbiter_selected": "",
                "arbiter_changed_steps": "",
                "arbiter_linear_max": "",
                "arbiter_linear_mean": "",
                "arbiter_linear_r2": "",
                "delta_linear_max": "",
                "delta_linear_mean": "",
                "delta_family_peak_penalty": "",
            }
        )
        return base
    cand_selected = candidate["selected"]
    changed_steps = [
        idx + 1
        for idx, (left, right) in enumerate(zip(selected, cand_selected))
        if abs(int(left) - int(right)) > 2
    ]
    delta_lmax = candidate["linear_max"] - current_lmax
    delta_lmean = candidate["linear_mean"] - current_lmean
    delta_family = candidate["family_peak_penalty"] - current_family_penalty
    arbiter_manual_max, arbiter_manual_mean, arbiter_manual_match2 = manual_distance(cand_selected, manual)
    manual_available = bool(manual)
    manual_closer = (
        not manual_available
        or arbiter_manual_mean + 0.01 < current_manual_mean
        or arbiter_manual_match2 > current_manual_match2
    )
    current_problem = bool(row.soft_fail) or bool(row.severe_fail) or bool(row.review)
    acceptable_qc = (
        candidate["linear_max"] <= 6.2
        and candidate["linear_mean"] <= 3.2
        and candidate["linear_r2"] >= 0.9989
    )
    materially_better = (
        (delta_lmax <= -0.70 and delta_lmean <= 0.35)
        or (delta_lmean <= -0.45 and delta_lmax <= 0.55)
        or (delta_family <= -0.18 and delta_lmax <= 0.45 and delta_lmean <= 0.30)
    )
    control_risk = (
        not current_problem
        and changed_steps
        and (delta_lmax > 0.35 or delta_lmean > 0.25 or delta_family > 0.18)
    )
    if not changed_steps:
        status = "same_as_current"
    elif control_risk:
        status = "control_regression_risk"
    elif current_problem and acceptable_qc and materially_better:
        status = "promising_repair"
    elif current_problem and acceptable_qc:
        status = "plausible_but_not_material"
    else:
        status = "not_safe"
    motor_candidate = (
        status == "promising_repair"
        and str(annotation.get("expected_use", "")) == "training_pair"
        and str(annotation.get("learning_category", "")) != "operator_or_bad_ladder"
        and manual_closer
    )
    base.update(
        {
            "arbiter_status": status,
            "motor_candidate": bool(motor_candidate),
            "arbiter_selected": json.dumps(cand_selected, separators=(",", ":")),
            "arbiter_changed_steps": json.dumps(changed_steps, separators=(",", ":")),
            "arbiter_linear_max": candidate["linear_max"],
            "arbiter_linear_mean": candidate["linear_mean"],
            "arbiter_linear_r2": candidate["linear_r2"],
            "arbiter_template_penalty": candidate["template_penalty"],
            "arbiter_peak_penalty": candidate["peak_penalty"],
            "arbiter_family_peak_penalty": candidate["family_peak_penalty"],
            "delta_linear_max": delta_lmax,
            "delta_linear_mean": delta_lmean,
            "delta_family_peak_penalty": delta_family,
            "arbiter_manual_max_delta": arbiter_manual_max,
            "arbiter_manual_mean_delta": arbiter_manual_mean,
            "arbiter_manual_match2": arbiter_manual_match2,
            "manual_closer": bool(manual_closer),
        }
    )
    return base


def render_comparison(
    out_dir: Path,
    analysis: dict[str, Any],
    row: pd.Series,
    decision: dict[str, Any],
) -> str:
    result = analysis["result"]
    ladder = analysis["ladder"]
    sizes = LADDER_SIZES.get(ladder, [])
    raw_path = Path(str(row.raw_path))
    channel = str(result.get("size_standard_channel_guess") or "")
    raw = live_eval.raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return ""
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)
    current = analysis["selected"]
    candidate = json.loads(decision.get("arbiter_selected") or "[]")
    peaks = result.get("ladder_peak_preview") or []
    candidate_indices = [int(peak["index"]) for peak in peaks if parse_int(peak.get("index")) is not None]
    x_min = 1250 if ladder == "ROX400HD" else 1300
    x_max = min(5000, trace.size - 1)
    visible = trace[x_min:x_max]
    y_max = 1000.0 if ladder == "ROX400HD" else 700.0
    if visible.size:
        y_max = max(220.0, min(y_max, float(np.nanpercentile(visible, 99.5) * 1.18)))

    fig, ax = plt.subplots(figsize=(14, 4.8), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.8, label=trace_label)
    visible_candidates = [idx for idx in candidate_indices if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(
        visible_candidates,
        [trace[idx] for idx in visible_candidates],
        color="#9ca3af",
        s=18,
        alpha=0.55,
        label="possible",
    )
    current_visible = [idx for idx in current if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(
        current_visible,
        [trace[idx] for idx in current_visible],
        color="#dc2626",
        s=48,
        marker="x",
        linewidth=1.6,
        label="current",
    )
    candidate_visible = [idx for idx in candidate if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(
        candidate_visible,
        [trace[idx] for idx in candidate_visible],
        color="#059669",
        s=44,
        marker="^",
        alpha=0.82,
        label="template arbiter",
    )
    for idx, scan in enumerate(candidate[: len(sizes)]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.annotate(
                str(sizes[idx]),
                (scan, trace[scan]),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color="#065f46",
            )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-20, y_max)
    ax.grid(True, alpha=0.18)
    ax.set_title(
        f"{raw_path.name} | {ladder} | {decision['arbiter_status']} | "
        f"current {float(decision['current_linear_max']):.2f}/{float(decision['current_linear_mean']):.2f} "
        f"-> arbiter {parse_float(decision['arbiter_linear_max'], float('nan')):.2f}/{parse_float(decision['arbiter_linear_mean'], float('nan')):.2f}"
    )
    ax.legend(loc="upper right", fontsize=8)
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    path = image_dir / f"{raw_path.stem}_template_arbiter.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def run(args: argparse.Namespace) -> None:
    broad_dir = args.broad_dir if args.broad_dir.is_absolute() else ROOT / args.broad_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    out_dir.mkdir(parents=True, exist_ok=True)
    source_bp, global_bp, source_gap, global_gap = load_stat_bands(broad_dir)
    manifest_annotations = load_manifest_annotations(manifest_path)
    cases = choose_cases(broad_dir, args.controls_per_ladder)
    cases.to_csv(out_dir / "selected_eval_cases.tsv", sep="\t", index=False)

    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(cases.itertuples(index=False), start=1):
        raw_path = Path(str(row.raw_path))
        analysis = analyze_path(raw_path, args.timeout)
        if not analysis.get("ok"):
            rows.append(
                {
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "eval_role": row.eval_role,
                    "source_group": row.source_group,
                    "assay": row.assay,
                    "ladder": getattr(row, "ladder", ""),
                    "arbiter_status": "rust_error",
                    "error": analysis.get("error", ""),
                }
            )
            continue
        candidate = run_template_beam(
            analysis,
            str(row.source_group),
            source_bp,
            global_bp,
            source_gap,
            global_gap,
        )
        decision = summarize_decision(row, analysis, candidate, manifest_annotations)
        if decision["arbiter_status"] in {"promising_repair", "control_regression_risk", "not_safe"}:
            decision["image"] = render_comparison(out_dir, analysis, row, decision)
        else:
            decision["image"] = ""
        rows.append(decision)
        print(f"{idx}/{len(cases)} {raw_path.name}: {decision['arbiter_status']}")

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "arbiter_eval.tsv", sep="\t", index=False)
    summary = {
        "cases": int(len(df)),
        "targets": int((df["eval_role"] == "target").sum()) if "eval_role" in df else 0,
        "controls": int((df["eval_role"] == "control").sum()) if "eval_role" in df else 0,
        "status_counts": df["arbiter_status"].value_counts(dropna=False).to_dict(),
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Template Family Arbiter Eval",
        "",
        f"- cases: {summary['cases']}",
        f"- targets: {summary['targets']}",
        f"- controls: {summary['controls']}",
        "",
        "## Status Counts",
    ]
    for key, count in summary["status_counts"].items():
        lines.append(f"- {key}: {count}")
    promising = df[df["arbiter_status"] == "promising_repair"].copy()
    motor_promising = df[df.get("motor_candidate", False).eq(True)].copy() if "motor_candidate" in df else pd.DataFrame()
    if not promising.empty:
        lines.extend(["", "## Promising Repairs"])
        for item in promising.sort_values(["ladder", "current_linear_max"], ascending=[True, False]).itertuples(index=False):
            lines.append(
                f"- {item.file}: {item.ladder} {float(item.current_linear_max):.2f}/{float(item.current_linear_mean):.2f} "
                f"-> {float(item.arbiter_linear_max):.2f}/{float(item.arbiter_linear_mean):.2f}; "
                f"steps {item.arbiter_changed_steps}; use {getattr(item, 'manifest_expected_use', '')}; "
                f"category {getattr(item, 'manifest_learning_category', '')}"
            )
    if not motor_promising.empty:
        lines.extend(["", "## Motor Candidate Subset"])
        for item in motor_promising.sort_values(["ladder", "current_linear_max"], ascending=[True, False]).itertuples(index=False):
            lines.append(
                f"- {item.file}: {item.ladder} {float(item.current_linear_max):.2f}/{float(item.current_linear_mean):.2f} "
                f"-> {float(item.arbiter_linear_max):.2f}/{float(item.arbiter_linear_mean):.2f}; "
                f"{getattr(item, 'manifest_learning_category', '')}"
            )
    risks = df[df["arbiter_status"] == "control_regression_risk"].copy()
    lines.extend(["", "## Interpretation"])
    if risks.empty:
        lines.append("- No sampled trusted-control regression risks were found.")
    else:
        lines.append(f"- {len(risks)} sampled trusted-control regression risks were found; do not promote directly.")
    lines.append("- This is a shadow diagnostic. It does not change Rust production behavior.")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broad-dir", type=Path, default=DEFAULT_BROAD_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--controls-per-ladder", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=90)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
