from __future__ import annotations

import argparse
import ast
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
from core.utils import is_water_file  # noqa: E402
from scripts.template_family_arbiter_eval import (  # noqa: E402
    LADDER_SIZES,
    StatBand,
    band_penalty,
    family_peak_penalty,
    linear_metrics,
    load_stat_bands,
    parse_bool,
    parse_float,
    parse_int,
    peak_quality_penalty,
    selected_scans,
)
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402


DEFAULT_INPUT = (
    ROOT
    / "artifacts"
    / "broad_live_smoke_liz_tail_neighbor_final_2000_2026-05-07"
    / "live_summary.tsv"
)
DEFAULT_TEMPLATE_DIR = ROOT / "artifacts" / "broad_live_smoke_liz_tail_neighbor_final_2000_2026-05-07"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "liz_family_block_shadow_eval_2026-05-07"
LIZ = "LIZ500_250"
LIZ_SIZES = LADDER_SIZES[LIZ]
WATCH_FILES = {
    "PK2_TCRg_B_180226_H03_H920GFSX.fsa",
    "26OUM04224_KDE_200326_A05_H9H1DHZK.fsa",
    "26OUM00877_TCRg_A_22012026_H01_H9C0U3SF.fsa",
    "25OUM07652_Kde_150525_C12_H9C0ZJ8K.fsa",
}


@dataclass
class ShadowCandidate:
    kind: str
    selected: list[int]
    score: float
    template_penalty: float
    peak_penalty: float
    note: str


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
        "channel": str(result.get("size_standard_channel_guess") or ""),
        "selected": selected_scans(preview),
        "linear_max": parse_float(metrics.get("linear_trend_max_abs_error_bp")),
        "linear_mean": parse_float(metrics.get("linear_trend_mean_abs_error_bp")),
        "linear_r2": parse_float(metrics.get("linear_trend_r2")),
        "review": bool(review.get("suggested_review")),
        "primary_reason": str(review.get("primary_reason") or ""),
        "reason_codes": review.get("reason_codes") or [],
    }


def peak_map(peaks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for peak in peaks:
        index = parse_int(peak.get("index"))
        if index is not None:
            out[index] = peak
    return out


def quality(index: int, peaks: dict[int, dict[str, Any]]) -> float:
    peak = peaks.get(index)
    if not peak:
        return 2.5
    return peak_quality_penalty(peak)


def peak_height(index: int, peaks: dict[int, dict[str, Any]]) -> float:
    return max(parse_float((peaks.get(index) or {}).get("height"), 0.0), 0.0)


def peak_prominence(index: int, peaks: dict[int, dict[str, Any]]) -> float:
    return max(parse_float((peaks.get(index) or {}).get("prominence"), 0.0), 0.0)


def candidate_indices(peaks: dict[int, dict[str, Any]], left: int, right: int, min_height: float = 8.0) -> list[int]:
    out = []
    for index, peak in peaks.items():
        if left <= index <= right and peak_height(index, peaks) >= min_height and peak_prominence(index, peaks) >= 5.0:
            out.append(index)
    return sorted(out)


def changed_steps(current: list[int], candidate: list[int]) -> list[int]:
    return [
        idx + 1
        for idx, (left, right) in enumerate(zip(current, candidate))
        if abs(int(left) - int(right)) > 2
    ]


def changed_bps(current: list[int], candidate: list[int]) -> list[int]:
    return [
        LIZ_SIZES[idx]
        for idx, (left, right) in enumerate(zip(current, candidate))
        if idx < len(LIZ_SIZES) and abs(int(left) - int(right)) > 2
    ]


def finite_metrics(scans: list[int]) -> tuple[float, float, float]:
    if len(scans) != len(LIZ_SIZES):
        return float("nan"), float("nan"), float("nan")
    return linear_metrics(scans, LIZ_SIZES)


def gap_band(
    source_group: str,
    step_idx: int,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> StatBand | None:
    return source_gap.get((source_group, LIZ, step_idx)) or global_gap.get((LIZ, step_idx))


def block_template_penalty(
    selected: list[int],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
    changed: set[int],
) -> float:
    penalty = 0.0
    for step_idx in range(len(selected) - 1):
        if step_idx not in changed and step_idx + 1 not in changed:
            continue
        band = gap_band(source_group, step_idx, source_gap, global_gap)
        penalty += band_penalty(float(selected[step_idx + 1] - selected[step_idx]), band, 14.0, 1.0)
    return penalty


def candidate_score(
    kind: str,
    current: list[int],
    candidate: list[int],
    peaks: dict[int, dict[str, Any]],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> ShadowCandidate | None:
    if len(candidate) != len(LIZ_SIZES):
        return None
    if not all(left < right for left, right in zip(candidate, candidate[1:])):
        return None
    lmax, lmean, r2 = finite_metrics(candidate)
    if not all(math.isfinite(value) for value in [lmax, lmean, r2]):
        return None
    changed_idx = {idx for idx, (left, right) in enumerate(zip(current, candidate)) if abs(left - right) > 2}
    if not changed_idx:
        return None
    template_penalty = block_template_penalty(candidate, source_group, source_gap, global_gap, changed_idx)
    peak_penalty = family_peak_penalty(candidate, peaks, LIZ)
    local_quality = sum(quality(candidate[idx], peaks) for idx in changed_idx) / max(len(changed_idx), 1)
    linear_penalty = max(0.0, lmax - 8.5) * 0.9 + max(0.0, lmean - 3.8) * 1.2 + max(0.0, 0.9990 - r2) * 900.0
    current_lmax, current_lmean, _current_r2 = finite_metrics(current)
    tradeoff_penalty = max(0.0, lmax - current_lmax - 1.2) * 0.45 + max(0.0, lmean - current_lmean - 0.55) * 0.65
    score = template_penalty * 1.3 + peak_penalty * 2.0 + local_quality * 0.9 + linear_penalty + tradeoff_penalty
    note = f"changed_bp={changed_bps(current, candidate)}"
    return ShadowCandidate(kind, candidate, score, template_penalty, peak_penalty, note)


def best_by_score(candidates: list[ShadowCandidate]) -> ShadowCandidate | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.score, item.template_penalty, item.peak_penalty, item.selected))[0]


def triplet_candidates(
    current: list[int],
    peaks: dict[int, dict[str, Any]],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> list[ShadowCandidate]:
    if len(current) != len(LIZ_SIZES):
        return []
    left = max(1200, current[4] - 220)
    right = min(5000, current[6] + 280)
    pool = candidate_indices(peaks, left, right, min_height=8.0)
    out: list[ShadowCandidate] = []
    for pos, a in enumerate(pool):
        for pos_b, b in enumerate(pool[pos + 1 :], start=pos + 1):
            gap_ab = b - a
            if not 28 <= gap_ab <= 105:
                continue
            for c in pool[pos_b + 1 :]:
                gap_bc = c - b
                if not 28 <= gap_bc <= 105:
                    continue
                trial = current.copy()
                trial[4:7] = [a, b, c]
                candidate = candidate_score("triplet_139_150_160", current, trial, peaks, source_group, source_gap, global_gap)
                if candidate:
                    balance = abs(math.log((peak_height(a, peaks) + 1.0) / (peak_height(b, peaks) + 1.0)))
                    balance += abs(math.log((peak_height(b, peaks) + 1.0) / (peak_height(c, peaks) + 1.0)))
                    candidate.score += balance * 0.45
                    out.append(candidate)
    return sorted(out, key=lambda item: item.score)[:12]


def tail_pair_candidates(
    current: list[int],
    peaks: dict[int, dict[str, Any]],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> list[ShadowCandidate]:
    if len(current) != len(LIZ_SIZES):
        return []
    left = max(current[13] + 10, current[14] - 240)
    right = min(5000, current[15] + 260)
    pool = candidate_indices(peaks, left, right, min_height=6.0)
    out: list[ShadowCandidate] = []
    for pos, a in enumerate(pool):
        for b in pool[pos + 1 :]:
            gap = b - a
            if not 28 <= gap <= 92:
                continue
            trial = current.copy()
            trial[14:16] = [a, b]
            candidate = candidate_score("tail_490_500", current, trial, peaks, source_group, source_gap, global_gap)
            if candidate:
                candidate.score += abs(gap - 47.0) / 55.0
                out.append(candidate)
    return sorted(out, key=lambda item: item.score)[:12]


def apex_block_candidate(
    current: list[int],
    peaks: dict[int, dict[str, Any]],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> ShadowCandidate | None:
    if len(current) != len(LIZ_SIZES):
        return None
    trial = current.copy()
    changed = False
    for step_idx in [9, 10, 12, 13]:
        left_bound = trial[step_idx - 1] + 8
        right_bound = trial[step_idx + 1] - 8 if step_idx + 1 < len(trial) else trial[step_idx] + 90
        pool = [
            index
            for index in candidate_indices(peaks, max(left_bound, current[step_idx] - 95), min(right_bound, current[step_idx] + 95), min_height=6.0)
            if abs(index - current[step_idx]) <= 95
        ]
        if not pool:
            continue
        current_height = peak_height(current[step_idx], peaks)
        best = max(pool, key=lambda index: (peak_height(index, peaks), peak_prominence(index, peaks), -abs(index - current[step_idx])))
        if best != current[step_idx] and peak_height(best, peaks) >= max(current_height * 1.6, current_height + 18.0, 18.0):
            trial[step_idx] = best
            changed = True
    if not changed:
        return None
    return candidate_score("late_apex_block_300_340_400_450", current, trial, peaks, source_group, source_gap, global_gap)


def predicted_start_pools(
    anchor_selected: list[int],
    current: list[int],
    peaks: dict[int, dict[str, Any]],
) -> list[list[int]]:
    anchor_steps = list(range(4, len(LIZ_SIZES)))
    xs = np.asarray([LIZ_SIZES[idx] for idx in anchor_steps], dtype=float)
    ys = np.asarray([anchor_selected[idx] for idx in anchor_steps], dtype=float)
    try:
        slope, intercept = np.polyfit(xs, ys, deg=1)
    except np.linalg.LinAlgError:
        return []
    pools: list[list[int]] = []
    for step_idx in range(4):
        predicted = int(round(float(slope * LIZ_SIZES[step_idx] + intercept)))
        left = max(1200, min(predicted - 130, current[step_idx] - 140))
        right = min(anchor_selected[4] - 8, max(predicted + 130, current[step_idx] + 140))
        pool = candidate_indices(peaks, left, right, min_height=6.0)
        if current[step_idx] in peaks and current[step_idx] not in pool:
            pool.append(current[step_idx])
        ranked = sorted(
            set(pool),
            key=lambda index: (
                abs(index - predicted) / 85.0 + quality(index, peaks) * 0.75,
                -peak_height(index, peaks),
                index,
            ),
        )[:10]
        pools.append(ranked)
    return pools


def reverse_start_candidates(
    current: list[int],
    anchor_selected: list[int],
    kind: str,
    peaks: dict[int, dict[str, Any]],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> list[ShadowCandidate]:
    pools = predicted_start_pools(anchor_selected, current, peaks)
    if len(pools) != 4 or any(not pool for pool in pools):
        return []
    beam: list[tuple[list[int], float]] = [([], 0.0)]
    for step_idx, pool in enumerate(pools):
        next_beam: list[tuple[list[int], float]] = []
        for prefix, prefix_score in beam:
            last = prefix[-1] if prefix else None
            for index in pool:
                if last is not None and index <= last + 8:
                    continue
                trial_prefix = prefix + [index]
                penalty = prefix_score + quality(index, peaks)
                if len(trial_prefix) >= 2:
                    gap_idx = len(trial_prefix) - 2
                    band = gap_band(source_group, gap_idx, source_gap, global_gap)
                    penalty += band_penalty(float(trial_prefix[-1] - trial_prefix[-2]), band, 14.0, 0.9)
                next_beam.append((trial_prefix, penalty))
        beam = sorted(next_beam, key=lambda item: (item[1], item[0]))[:50]
    out: list[ShadowCandidate] = []
    for prefix, prefix_score in beam:
        trial = anchor_selected.copy()
        trial[:4] = prefix
        candidate = candidate_score(kind, current, trial, peaks, source_group, source_gap, global_gap)
        if candidate:
            candidate.score += prefix_score * 0.4
            out.append(candidate)
    return sorted(out, key=lambda item: item.score)[:12]


def all_shadow_candidates(
    current: list[int],
    peaks: dict[int, dict[str, Any]],
    source_group: str,
    source_gap: dict[tuple[str, str, int], StatBand],
    global_gap: dict[tuple[str, int], StatBand],
) -> list[ShadowCandidate]:
    candidates: list[ShadowCandidate] = []
    triplets = triplet_candidates(current, peaks, source_group, source_gap, global_gap)
    tails = tail_pair_candidates(current, peaks, source_group, source_gap, global_gap)
    candidates.extend(triplets[:3])
    candidates.extend(tails[:3])
    apex = apex_block_candidate(current, peaks, source_group, source_gap, global_gap)
    if apex:
        candidates.append(apex)
    candidates.extend(reverse_start_candidates(current, current, "reverse_start_from_tail", peaks, source_group, source_gap, global_gap)[:3])
    for triplet in triplets[:4]:
        candidates.extend(
            reverse_start_candidates(current, triplet.selected, "reverse_start_plus_triplet", peaks, source_group, source_gap, global_gap)[:2]
        )
    for tail in tails[:3]:
        candidates.extend(reverse_start_candidates(current, tail.selected, "reverse_start_plus_tail", peaks, source_group, source_gap, global_gap)[:2])
    return candidates


def shadow_status(current_metrics: tuple[float, float, float], cand_metrics: tuple[float, float, float], current_family: float, cand_family: float) -> str:
    current_max, current_mean, current_r2 = current_metrics
    cand_max, cand_mean, cand_r2 = cand_metrics
    if not all(math.isfinite(value) for value in [cand_max, cand_mean, cand_r2]):
        return "invalid"
    within_no_review = cand_max <= 10.0 and cand_mean <= 4.5 and cand_r2 >= 0.9985
    residual_win = cand_max + 0.75 < current_max or cand_mean + 0.40 < current_mean
    family_win = cand_family + 0.12 < current_family
    small_tradeoff = cand_max <= current_max + 2.5 and cand_mean <= current_mean + 1.1 and cand_r2 >= current_r2 - 0.00045
    if within_no_review and residual_win and small_tradeoff:
        return "residual_repair_candidate"
    if within_no_review and family_win and small_tradeoff:
        return "visual_family_tradeoff"
    if within_no_review:
        return "plausible_shadow"
    return "not_safe"


def changed_peak_ratios(current: list[int], candidate: list[int], peaks: dict[int, dict[str, Any]]) -> tuple[float, float, float, float]:
    selected_heights = [peak_height(scan, peaks) for scan in current if peak_height(scan, peaks) > 0]
    selected_proms = [peak_prominence(scan, peaks) for scan in current if peak_prominence(scan, peaks) > 0]
    height_ref = max(float(np.median(selected_heights)), 1.0) if selected_heights else 1.0
    prom_ref = max(float(np.median(selected_proms)), 1.0) if selected_proms else 1.0
    ratios_h: list[float] = []
    ratios_p: list[float] = []
    for left, right in zip(current, candidate):
        if abs(left - right) <= 2:
            continue
        ratios_h.append(peak_height(right, peaks) / height_ref)
        ratios_p.append(peak_prominence(right, peaks) / prom_ref)
    if not ratios_h:
        return float("nan"), float("nan"), float("nan"), float("nan")
    return float(min(ratios_h)), float(min(ratios_p)), float(max(ratios_h)), float(max(ratios_p))


def changed_ratio_spread(
    min_height_ratio: float,
    min_prom_ratio: float,
    max_height_ratio: float,
    max_prom_ratio: float,
) -> tuple[float, float]:
    if not all(math.isfinite(value) for value in [min_height_ratio, min_prom_ratio, max_height_ratio, max_prom_ratio]):
        return float("nan"), float("nan")
    return max_height_ratio / max(min_height_ratio, 1e-6), max_prom_ratio / max(min_prom_ratio, 1e-6)


def changed_apex_support(
    current: list[int],
    candidate: list[int],
    peaks: dict[int, dict[str, Any]],
    radius: int = 24,
) -> tuple[int, float, int, str]:
    ranks: list[int] = []
    stronger_ratios: list[float] = []
    stronger_counts = 0
    missing_features = 0
    for left, right in zip(current, candidate):
        if abs(left - right) <= 2:
            continue
        candidate_height = peak_height(right, peaks)
        candidate_prom = peak_prominence(right, peaks)
        if candidate_height <= 0.0 or candidate_prom <= 0.0:
            missing_features += 1
            continue
        local = [
            index
            for index in peaks
            if abs(index - right) <= radius and peak_height(index, peaks) > 0.0 and peak_prominence(index, peaks) > 0.0
        ]
        if not local:
            missing_features += 1
            continue
        ranked = sorted(local, key=lambda index: (peak_height(index, peaks), peak_prominence(index, peaks)), reverse=True)
        rank = ranked.index(right) + 1 if right in ranked else len(ranked) + 1
        ranks.append(rank)
        best_height = peak_height(ranked[0], peaks)
        stronger_ratio = best_height / max(candidate_height, 1.0)
        stronger_ratios.append(stronger_ratio)
        if rank > 1 and stronger_ratio >= 1.35:
            stronger_counts += 1
    if missing_features:
        return max(ranks or [99]), max(stronger_ratios or [float("inf")]), stronger_counts, "missing_peak_feature"
    if not ranks:
        return 0, float("nan"), 0, "unchanged"
    max_rank = max(ranks)
    max_stronger_ratio = max(stronger_ratios)
    if stronger_counts and max_stronger_ratio >= 1.8:
        return max_rank, max_stronger_ratio, stronger_counts, "shoulder_or_foot_risk"
    if stronger_counts:
        return max_rank, max_stronger_ratio, stronger_counts, "nearby_apex_tradeoff"
    return max_rank, max_stronger_ratio, stronger_counts, "apex_supported"


def candidate_block_group(kind: str, changed_bp_values: list[int]) -> str:
    changed = set(changed_bp_values)
    early = bool(changed & {35, 50, 75, 100})
    triplet = bool(changed & {139, 150, 160})
    late_apex = bool(changed & {300, 340, 400, 450})
    tail = bool(changed & {490, 500})
    if kind.startswith("reverse_start") and triplet:
        return "reverse_start_plus_triplet"
    if kind.startswith("reverse_start") and tail:
        return "reverse_start_plus_tail"
    if kind.startswith("reverse_start") or early:
        return "reverse_start"
    if triplet:
        return "triplet_139_150_160"
    if late_apex:
        return "late_apex_300_340_400_450"
    if tail:
        return "tail_490_500"
    return "other"


def residual_delta_class(current_metrics: tuple[float, float, float], cand_metrics: tuple[float, float, float]) -> str:
    current_max, current_mean, current_r2 = current_metrics
    cand_max, cand_mean, cand_r2 = cand_metrics
    if not all(math.isfinite(value) for value in [current_max, current_mean, current_r2, cand_max, cand_mean, cand_r2]):
        return "invalid"
    max_gain = current_max - cand_max
    mean_gain = current_mean - cand_mean
    r2_drop = current_r2 - cand_r2
    if max_gain >= 2.0 and mean_gain >= 0.4 and r2_drop <= 0.00035:
        return "strong_residual_win"
    if max_gain >= 1.0 and mean_gain >= -0.1 and r2_drop <= 0.00045:
        return "max_win_small_mean_tradeoff"
    if mean_gain >= 0.8 and max_gain >= -1.5 and r2_drop <= 0.00045:
        return "mean_win_max_tradeoff"
    if cand_max <= current_max + 1.0 and cand_mean <= current_mean + 0.5 and r2_drop <= 0.00035:
        return "qc_neutral_visual_candidate"
    return "weak_or_regressive"


def visual_review_candidate(
    status: str,
    current_metrics: tuple[float, float, float],
    residual_class: str,
    block_group: str,
    min_height_ratio: float,
    min_prom_ratio: float,
    max_height_ratio: float,
    max_prom_ratio: float,
    height_spread: float,
    prom_spread: float,
    apex_class: str,
) -> bool:
    current_max, current_mean, _current_r2 = current_metrics
    problem_or_watch = current_max > 5.0 or current_mean > 2.2 or status in {"residual_repair_candidate", "visual_family_tradeoff"}
    plausible_signal = (
        math.isfinite(min_height_ratio)
        and math.isfinite(min_prom_ratio)
        and math.isfinite(max_height_ratio)
        and math.isfinite(max_prom_ratio)
        and min_height_ratio >= 0.16
        and min_prom_ratio >= 0.12
        and max_height_ratio <= 6.0
        and max_prom_ratio <= 6.0
    )
    not_one_extreme_family = (
        math.isfinite(height_spread)
        and math.isfinite(prom_spread)
        and height_spread <= 18.0
        and prom_spread <= 18.0
    )
    useful_block = block_group in {
        "reverse_start",
        "reverse_start_plus_triplet",
        "reverse_start_plus_tail",
        "triplet_139_150_160",
        "late_apex_300_340_400_450",
        "tail_490_500",
    }
    useful_residual = residual_class in {
        "strong_residual_win",
        "max_win_small_mean_tradeoff",
        "mean_win_max_tradeoff",
        "qc_neutral_visual_candidate",
    }
    reviewable_apex = apex_class in {"apex_supported", "nearby_apex_tradeoff", "shoulder_or_foot_risk"}
    return bool(problem_or_watch and plausible_signal and not_one_extreme_family and useful_block and useful_residual and reviewable_apex)


def production_gate_candidate(
    eval_role: str,
    status: str,
    residual_class: str,
    current_metrics: tuple[float, float, float],
    min_height_ratio: float,
    min_prom_ratio: float,
    max_height_ratio: float,
    max_prom_ratio: float,
    apex_class: str,
) -> bool:
    current_max, current_mean, _current_r2 = current_metrics
    # Keep this narrower than the broad eval target selector; complete good fits
    # can still have small residual wins that are not worth production movement.
    current_problem = current_max > 5.7 or current_mean > 2.8
    strong_status = status == "residual_repair_candidate"
    strong_residual = residual_class in {"strong_residual_win", "max_win_small_mean_tradeoff"}
    peak_guard = (
        math.isfinite(min_height_ratio)
        and math.isfinite(min_prom_ratio)
        and math.isfinite(max_height_ratio)
        and math.isfinite(max_prom_ratio)
        and min_height_ratio >= 0.22
        and min_prom_ratio >= 0.18
        and max_height_ratio <= 4.5
        and max_prom_ratio <= 4.5
    )
    apex_guard = apex_class in {"apex_supported", "nearby_apex_tradeoff"}
    return bool(current_problem and strong_status and strong_residual and peak_guard and apex_guard)


def choose_rows(input_path: Path, max_controls: int, include_watch: bool) -> pd.DataFrame:
    df = pd.read_csv(input_path, sep="\t")
    df = df[df["ladder"].astype(str).eq(LIZ)].copy()
    df = df[~df["file"].astype(str).map(is_water_file)].copy()
    df = df[df["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    for col in ["linear_max", "linear_mean", "linear_r2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["review", "soft_fail", "severe_fail"]:
        df[col] = df[col].map(parse_bool)
    target = df[df["review"] | df["soft_fail"] | df["severe_fail"] | (df["linear_max"] > 6.0)].copy()
    target["eval_role"] = "target"
    if include_watch:
        watch = df[df["file"].astype(str).isin(WATCH_FILES)].copy()
        watch["eval_role"] = "watch"
        target = pd.concat([target, watch], ignore_index=True, sort=False)
    controls = df[(~df["review"]) & (~df["soft_fail"]) & (~df["severe_fail"]) & (df["linear_max"] <= 5.0)].copy()
    controls = controls.sort_values(["source_group", "assay", "linear_max", "file"]).copy()
    if max_controls > 0 and len(controls) > max_controls:
        idx = np.linspace(0, len(controls) - 1, max_controls).round().astype(int)
        controls = controls.iloc[idx].copy()
    controls["eval_role"] = "control"
    rows = pd.concat([target, controls], ignore_index=True, sort=False)
    rows = rows.drop_duplicates(subset=["raw_path"], keep="first")
    return rows


def render_candidate(
    out_dir: Path,
    row: pd.Series,
    analysis: dict[str, Any],
    candidate: ShadowCandidate,
    status: str,
    metrics: tuple[float, float, float],
) -> str:
    raw_path = Path(str(row.raw_path))
    result = analysis["result"]
    raw = live_eval.raw_trace(raw_path, LIZ, analysis.get("channel") or result.get("size_standard_channel_guess") or "DATA105")
    if raw is None or raw.size == 0:
        return ""
    trace, trace_label = live_eval.corrected_display_trace(raw, LIZ)
    current = analysis["selected"]
    peaks = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or [] if parse_int(peak.get("index")) is not None]
    changed = changed_steps(current, candidate.selected)
    focus_scans = [current[idx - 1] for idx in changed if idx - 1 < len(current)] + [
        candidate.selected[idx - 1] for idx in changed if idx - 1 < len(candidate.selected)
    ]
    x_min = 1300
    x_max = min(5000, trace.size - 1)
    if focus_scans:
        x_min = max(1200, min(focus_scans) - 350)
        x_max = min(trace.size - 1, max(focus_scans) + 450, 5000)
    visible = trace[x_min:x_max]
    y_max = 700.0
    if visible.size:
        y_max = max(220.0, min(1200.0, float(np.nanpercentile(visible, 99.6) * 1.18)))

    fig, ax = plt.subplots(figsize=(13.5, 4.8), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.8, label=trace_label)
    visible_peaks = [idx for idx in peaks if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(visible_peaks, [trace[idx] for idx in visible_peaks], color="#9ca3af", s=18, alpha=0.55, label="possible")
    old_visible = [idx for idx in current if x_min <= idx <= x_max and 0 <= idx < trace.size]
    new_visible = [idx for idx in candidate.selected if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(old_visible, [trace[idx] for idx in old_visible], color="#dc2626", s=48, marker="x", linewidth=1.5, label="current")
    ax.scatter(
        new_visible,
        [trace[idx] for idx in new_visible],
        color="#059669",
        s=44,
        marker="o",
        facecolors="none",
        linewidth=1.7,
        label="shadow",
    )
    for idx, scan in enumerate(candidate.selected):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.annotate(str(LIZ_SIZES[idx]), (scan, trace[scan]), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=7, color="#065f46")
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-20, y_max)
    ax.grid(True, alpha=0.18)
    ax.set_title(
        f"{raw_path.name} | {candidate.kind} | {status} | "
        f"{float(analysis['linear_max']):.2f}/{float(analysis['linear_mean']):.2f} -> {metrics[0]:.2f}/{metrics[1]:.2f}"
    )
    ax.legend(loc="upper right", fontsize=8)
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{raw_path.stem}_{candidate.kind}".replace("/", "_")
    path = image_dir / f"{safe}.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def render_contact_sheet(images: list[str], out_path: Path, columns: int = 2) -> str:
    valid = [Path(path) for path in images if str(path).strip() and Path(str(path)).exists()]
    if not valid:
        return ""
    arrays = [plt.imread(path) for path in valid]
    widths = [arr.shape[1] for arr in arrays]
    heights = [arr.shape[0] for arr in arrays]
    cell_w = max(widths)
    cell_h = max(heights)
    rows = int(math.ceil(len(arrays) / max(columns, 1)))
    sheet = np.ones((rows * cell_h, columns * cell_w, 4), dtype=float)
    for idx, arr in enumerate(arrays):
        if arr.ndim == 2:
            arr = np.repeat(arr[:, :, None], 4, axis=2)
        if arr.shape[2] == 3:
            alpha = np.ones((arr.shape[0], arr.shape[1], 1), dtype=arr.dtype)
            arr = np.concatenate([arr, alpha], axis=2)
        row = idx // columns
        col = idx % columns
        sheet[row * cell_h : row * cell_h + arr.shape[0], col * cell_w : col * cell_w + arr.shape[1], : arr.shape[2]] = arr
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(out_path, np.clip(sheet, 0.0, 1.0))
    return str(out_path)


def should_render(file_name: str, status: str) -> bool:
    if file_name in WATCH_FILES:
        return True
    return status in {"residual_repair_candidate", "visual_family_tradeoff"}


def run(args: argparse.Namespace) -> None:
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    template_dir = args.template_dir if args.template_dir.is_absolute() else ROOT / args.template_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    _source_bp, _global_bp, source_gap, global_gap = load_stat_bands(template_dir)
    rows = choose_rows(input_path, args.controls, args.include_watch)
    if args.limit > 0:
        rows = rows.head(args.limit).copy()
    rows.to_csv(out_dir / "input_rows.tsv", sep="\t", index=False)

    out_rows: list[dict[str, Any]] = []
    for count, row in enumerate(rows.itertuples(index=False), start=1):
        raw_path = Path(str(row.raw_path))
        analysis = analyze_path(raw_path, args.timeout)
        if not analysis.get("ok") or analysis.get("ladder") != LIZ or len(analysis.get("selected") or []) != len(LIZ_SIZES):
            out_rows.append(
                {
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "eval_role": getattr(row, "eval_role", ""),
                    "status": "rust_error_or_wrong_ladder",
                    "error": analysis.get("error", ""),
                }
            )
            continue
        result = analysis["result"]
        peaks = peak_map(result.get("ladder_peak_preview") or [])
        current = analysis["selected"]
        current_metrics = (analysis["linear_max"], analysis["linear_mean"], analysis["linear_r2"])
        current_family = family_peak_penalty(current, peaks, LIZ)
        candidates = all_shadow_candidates(current, peaks, str(row.source_group), source_gap, global_gap)
        best_by_kind: dict[str, ShadowCandidate] = {}
        for candidate in candidates:
            existing = best_by_kind.get(candidate.kind)
            if existing is None or candidate.score < existing.score:
                best_by_kind[candidate.kind] = candidate
        if not best_by_kind:
            out_rows.append(
                {
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "eval_role": getattr(row, "eval_role", ""),
                    "source_group": getattr(row, "source_group", ""),
                    "assay": getattr(row, "assay", ""),
                    "status": "no_shadow_candidate",
                    "current_linear_max": current_metrics[0],
                    "current_linear_mean": current_metrics[1],
                    "current_linear_r2": current_metrics[2],
                    "current_selected": json.dumps(current, separators=(",", ":")),
                    "candidate_count": len(peaks),
                }
            )
            print(f"{count}/{len(rows)} {raw_path.name}: no_shadow_candidate")
            continue
        for candidate in sorted(best_by_kind.values(), key=lambda item: (item.score, item.kind)):
            cand_metrics = finite_metrics(candidate.selected)
            cand_family = family_peak_penalty(candidate.selected, peaks, LIZ)
            status = shadow_status(current_metrics, cand_metrics, current_family, cand_family)
            min_height_ratio, min_prom_ratio, max_height_ratio, max_prom_ratio = changed_peak_ratios(current, candidate.selected, peaks)
            height_spread, prom_spread = changed_ratio_spread(
                min_height_ratio,
                min_prom_ratio,
                max_height_ratio,
                max_prom_ratio,
            )
            apex_rank, apex_stronger_ratio, apex_stronger_count, apex_class = changed_apex_support(current, candidate.selected, peaks)
            changed_bp_values = changed_bps(current, candidate.selected)
            block_group = candidate_block_group(candidate.kind, changed_bp_values)
            residual_class = residual_delta_class(current_metrics, cand_metrics)
            visual_gate = visual_review_candidate(
                status,
                current_metrics,
                residual_class,
                block_group,
                min_height_ratio,
                min_prom_ratio,
                max_height_ratio,
                max_prom_ratio,
                height_spread,
                prom_spread,
                apex_class,
            )
            gated = production_gate_candidate(
                str(getattr(row, "eval_role", "")),
                status,
                residual_class,
                current_metrics,
                min_height_ratio,
                min_prom_ratio,
                max_height_ratio,
                max_prom_ratio,
                apex_class,
            )
            changed = changed_steps(current, candidate.selected)
            image = ""
            if should_render(raw_path.name, status) and changed:
                image = render_candidate(out_dir, row, analysis, candidate, status, cand_metrics)
            out_rows.append(
                {
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "eval_role": getattr(row, "eval_role", ""),
                    "source_group": getattr(row, "source_group", ""),
                    "assay": getattr(row, "assay", ""),
                    "candidate_kind": candidate.kind,
                    "block_group": block_group,
                    "status": status,
                    "residual_delta_class": residual_class,
                    "changed_steps": json.dumps(changed, separators=(",", ":")),
                    "changed_bps": json.dumps(changed_bp_values, separators=(",", ":")),
                    "current_linear_max": current_metrics[0],
                    "current_linear_mean": current_metrics[1],
                    "current_linear_r2": current_metrics[2],
                    "shadow_linear_max": cand_metrics[0],
                    "shadow_linear_mean": cand_metrics[1],
                    "shadow_linear_r2": cand_metrics[2],
                    "delta_linear_max": cand_metrics[0] - current_metrics[0],
                    "delta_linear_mean": cand_metrics[1] - current_metrics[1],
                    "current_family_peak_penalty": current_family,
                    "shadow_family_peak_penalty": cand_family,
                    "delta_family_peak_penalty": cand_family - current_family,
                    "changed_min_height_ratio": min_height_ratio,
                    "changed_min_prominence_ratio": min_prom_ratio,
                    "changed_max_height_ratio": max_height_ratio,
                    "changed_max_prominence_ratio": max_prom_ratio,
                    "changed_height_ratio_spread": height_spread,
                    "changed_prominence_ratio_spread": prom_spread,
                    "changed_local_apex_rank_max": apex_rank,
                    "changed_local_stronger_peak_ratio_max": apex_stronger_ratio,
                    "changed_local_stronger_peak_count": apex_stronger_count,
                    "changed_apex_support_class": apex_class,
                    "visual_review_candidate": visual_gate,
                    "production_gate_candidate": gated,
                    "template_penalty": candidate.template_penalty,
                    "peak_penalty": candidate.peak_penalty,
                    "shadow_score": candidate.score,
                    "current_selected": json.dumps(current, separators=(",", ":")),
                    "shadow_selected": json.dumps(candidate.selected, separators=(",", ":")),
                    "candidate_count": len(peaks),
                    "note": candidate.note,
                    "image": image,
                }
            )
        interesting = [item for item in out_rows if item.get("file") == raw_path.name and item.get("status") in {"residual_repair_candidate", "visual_family_tradeoff"}]
        print(f"{count}/{len(rows)} {raw_path.name}: {len(interesting)} interesting")

    df = pd.DataFrame(out_rows)
    df.to_csv(out_dir / "shadow_candidates.tsv", sep="\t", index=False)
    status_counts = df["status"].value_counts(dropna=False).to_dict() if "status" in df else {}
    kind_counts = df["candidate_kind"].value_counts(dropna=False).to_dict() if "candidate_kind" in df else {}
    block_counts = df["block_group"].value_counts(dropna=False).to_dict() if "block_group" in df else {}
    residual_class_counts = df["residual_delta_class"].value_counts(dropna=False).to_dict() if "residual_delta_class" in df else {}
    apex_class_counts = df["changed_apex_support_class"].value_counts(dropna=False).to_dict() if "changed_apex_support_class" in df else {}
    interesting = df[df["status"].isin(["residual_repair_candidate", "visual_family_tradeoff"])].copy() if "status" in df else pd.DataFrame()
    visual = df[df.get("visual_review_candidate", False).eq(True)].copy() if "visual_review_candidate" in df else pd.DataFrame()
    gated = df[df.get("production_gate_candidate", False).eq(True)].copy() if "production_gate_candidate" in df else pd.DataFrame()
    controls_visual = visual[visual["eval_role"].astype(str).eq("control")].copy() if not visual.empty and "eval_role" in visual else pd.DataFrame()
    controls_gated = gated[gated["eval_role"].astype(str).eq("control")].copy() if not gated.empty and "eval_role" in gated else pd.DataFrame()
    contact_sheet = ""
    if not interesting.empty and "image" in interesting:
        contact_sheet = render_contact_sheet(
            [str(value) for value in interesting["image"].dropna().tolist()],
            out_dir / "images" / "interesting_contact_sheet.png",
        )
    if not visual.empty:
        visual.sort_values(["eval_role", "block_group", "file", "shadow_score"]).to_csv(
            out_dir / "visual_review_candidates.tsv",
            sep="\t",
            index=False,
        )
    if not gated.empty:
        gated.sort_values(["eval_role", "block_group", "file", "shadow_score"]).to_csv(
            out_dir / "production_gate_candidates.tsv",
            sep="\t",
            index=False,
        )
    lines = [
        "# LIZ Family Block Shadow Eval",
        "",
        f"- input: `{input_path}`",
        f"- rows: `{len(rows)}`",
        f"- output: `{out_dir}`",
        f"- visual review candidates: `{len(visual)}`",
        f"- production-gated candidates: `{len(gated)}`",
        f"- control visual candidates: `{len(controls_visual)}`",
        f"- control production-gated candidates: `{len(controls_gated)}`",
        "",
        "## Status Counts",
    ]
    for key, value in status_counts.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Candidate Kinds"])
    for key, value in kind_counts.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Block Groups"])
    for key, value in block_counts.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Residual Delta Classes"])
    for key, value in residual_class_counts.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Apex Support Classes"])
    for key, value in apex_class_counts.items():
        lines.append(f"- `{key}`: `{value}`")
    if not interesting.empty:
        lines.extend(["", "## Interesting Shadow Candidates"])
        for item in interesting.sort_values(["eval_role", "status", "file", "shadow_score"]).head(30).itertuples(index=False):
            lines.append(
                f"- `{item.file}` `{item.candidate_kind}` {item.status}: "
                f"{float(item.current_linear_max):.2f}/{float(item.current_linear_mean):.2f} -> "
                f"{float(item.shadow_linear_max):.2f}/{float(item.shadow_linear_mean):.2f}; "
                f"bp {item.changed_bps}"
            )
    if not visual.empty:
        lines.extend(["", "## Visual Review Candidates"])
        for item in visual.sort_values(["eval_role", "block_group", "file", "shadow_score"]).head(40).itertuples(index=False):
            lines.append(
                f"- `{item.file}` `{item.block_group}` `{item.candidate_kind}` {item.residual_delta_class}: "
                f"{float(item.current_linear_max):.2f}/{float(item.current_linear_mean):.2f} -> "
                f"{float(item.shadow_linear_max):.2f}/{float(item.shadow_linear_mean):.2f}; "
                f"ratio min/max h {float(item.changed_min_height_ratio):.2f}/{float(item.changed_max_height_ratio):.2f}; "
                f"apex {item.changed_apex_support_class}; "
                f"bp {item.changed_bps}"
            )
    if not gated.empty:
        lines.extend(["", "## Production-Gated Candidates"])
        for item in gated.sort_values(["eval_role", "file", "shadow_score"]).head(30).itertuples(index=False):
            lines.append(
                f"- `{item.file}` `{item.block_group}` `{item.candidate_kind}` {item.status}: "
                f"{float(item.current_linear_max):.2f}/{float(item.current_linear_mean):.2f} -> "
                f"{float(item.shadow_linear_max):.2f}/{float(item.shadow_linear_mean):.2f}; "
                f"min height/prom ratio {float(item.changed_min_height_ratio):.2f}/{float(item.changed_min_prominence_ratio):.2f}; "
                f"max height/prom ratio {float(item.changed_max_height_ratio):.2f}/{float(item.changed_max_prominence_ratio):.2f}; "
                f"apex {item.changed_apex_support_class}; "
                f"bp {item.changed_bps}"
            )
    if not controls_visual.empty or not controls_gated.empty:
        lines.extend(["", "## Control Hits"])
        lines.append(
            f"- Controls passing visual gate: `{len(controls_visual)}`. "
            "These are not automatically bad; they show where the shadow method would need stronger gating."
        )
        lines.append(f"- Controls passing production gate: `{len(controls_gated)}`.")
    if contact_sheet:
        lines.extend(["", "## Images", f"- Interesting contact sheet: `{contact_sheet}`"])
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "input": str(input_path),
                "rows": int(len(rows)),
                "status_counts": status_counts,
                "candidate_kind_counts": kind_counts,
                "block_group_counts": block_counts,
                "residual_delta_class_counts": residual_class_counts,
                "apex_support_class_counts": apex_class_counts,
                "interesting_count": int(len(interesting)),
                "visual_review_candidate_count": int(len(visual)),
                "production_gate_candidate_count": int(len(gated)),
                "control_visual_review_candidate_count": int(len(controls_visual)),
                "control_production_gate_candidate_count": int(len(controls_gated)),
                "interesting_contact_sheet": contact_sheet,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out_dir / 'shadow_candidates.tsv'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--controls", type=int, default=120)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--include-watch", action="store_true", default=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
