from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402
from fraggler.fraggler import FsaFile  # noqa: E402


GS500ROX_SIZES = [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500]
DEFAULT_PANEL = (
    ROOT
    / "local_triage"
    / "hemafrag_rox500_large_run_after_start_shift_2026-05-11"
    / "review_figures_y2500"
    / "panel_rows.csv"
)
DEFAULT_DATA_ROOT = Path("/Volumes/T7 Shield/DATA/flt3")
DEFAULT_OUT_DIR = ROOT / "local_triage" / "hemafrag_rox500_35_50_shadow_2026-05-11"


@dataclass
class Candidate:
    scan: int
    height: float
    source: str
    prominence: float = 0.0


@dataclass
class Trial:
    strategy: str
    selected: list[int]
    linear_max: float
    linear_mean: float
    linear_r2: float
    score: float
    note: str


def parse_int(value: object) -> int | None:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def parse_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float("nan")


def selected_scans(preview: dict[str, Any]) -> list[int]:
    refinement = preview.get("refinement") or {}
    scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    return [value for item in scans if (value := parse_int(item)) is not None]


def linear_metrics(scans: list[int], sizes: list[int] = GS500ROX_SIZES) -> tuple[float, float, float]:
    if len(scans) != len(sizes) or len(scans) < 3:
        return float("nan"), float("nan"), float("nan")
    x = np.asarray(scans, dtype=float)
    y = np.asarray(sizes, dtype=float)
    coef = np.polyfit(x, y, deg=1)
    predicted = np.polyval(coef, x)
    residuals = np.abs(predicted - y)
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(np.max(residuals)), float(np.mean(residuals)), r2


def trial_score(linear_max: float, linear_mean: float, linear_r2: float, selected: list[int], current: list[int]) -> float:
    if not all(math.isfinite(value) for value in (linear_max, linear_mean, linear_r2)):
        return float("inf")
    changed = sum(1 for left, right in zip(selected, current) if left != right)
    gap_penalty = 0.0
    if len(selected) >= 5:
        gaps = np.diff(np.asarray(selected[:5], dtype=float))
        if np.any(gaps <= 8):
            gap_penalty += 500.0
        # Keep this intentionally soft. It is only shadow ranking, not production accept.
        gap_penalty += max(0.0, 35.0 - float(gaps[0])) * 0.06
        gap_penalty += max(0.0, 60.0 - float(gaps[1])) * 0.03
        gap_penalty += max(0.0, 45.0 - float(gaps[2])) * 0.03
    return linear_max * 8.0 + linear_mean * 3.0 + max(0.0, 0.9995 - linear_r2) * 800.0 + changed * 0.025 + gap_penalty


def resolve_path(row: dict[str, str], data_root: Path) -> Path:
    source = row.get("SourceRunDir") or row.get("run") or ""
    file_name = row.get("File") or row.get("file") or ""
    for prefix in ("2025", "2026", "2024"):
        candidate = data_root / prefix / source / file_name
        if candidate.exists():
            return candidate
    direct = data_root / source / file_name
    if direct.exists():
        return direct
    return direct


def analyze_path(path: Path, timeout: int) -> dict[str, Any]:
    worker = _get_rust_worker()
    if worker is None:
        return {"ok": False, "error": "Rust worker unavailable"}
    response = worker.request(path, "flt3", timeout)
    if not isinstance(response, dict) or not response.get("ok"):
        error = (response or {}).get("error") if isinstance(response, dict) else "no response"
        if error and "timeout" in str(error).lower():
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            if worker is not None:
                response = worker.request(path, "flt3", timeout * 2)
    if not isinstance(response, dict) or not response.get("ok"):
        return {"ok": False, "error": (response or {}).get("error", "no response") if isinstance(response, dict) else "no response"}
    result = response.get("result") if isinstance(response.get("result"), dict) else response
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    qc = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    return {
        "ok": True,
        "result": result,
        "selected": selected_scans(preview),
        "candidate_peaks": result.get("ladder_peak_preview") or [],
        "linear_max": parse_float(qc.get("linear_trend_max_abs_error_bp")),
        "linear_mean": parse_float(qc.get("linear_trend_mean_abs_error_bp")),
        "linear_r2": parse_float(qc.get("linear_trend_r2")),
        "review": bool(review.get("suggested_review")),
        "reason_codes": ";".join(review.get("reason_codes") or []),
        "channel": result.get("size_standard_channel_guess") or "DATA4",
    }


def raw_trace(path: Path, channel: str = "DATA4") -> np.ndarray:
    probe = FsaFile(
        file=str(path),
        ladder="GS500ROX",
        sample_channel="DATA1",
        min_distance_between_peaks=15,
        min_size_standard_height=50,
        size_standard_channel=channel,
    )
    return np.asarray(probe.fsa[channel], dtype=float)


def rolling_quantile_baseline(trace: np.ndarray, bin_size: int = 200, quantile: float = 0.10) -> np.ndarray:
    centers: list[float] = []
    values: list[float] = []
    for start in range(0, trace.size, bin_size):
        end = min(trace.size, start + bin_size)
        centers.append((start + end - 1) * 0.5)
        values.append(float(np.nanquantile(trace[start:end], quantile)))
    return np.interp(np.arange(trace.size), np.asarray(centers), np.asarray(values))


def corrected_trace(trace: np.ndarray) -> np.ndarray:
    return np.maximum(trace - rolling_quantile_baseline(trace, 200, 0.10), 0.0)


def local_prominence(trace: np.ndarray, idx: int, radius: int = 18) -> float:
    left = max(0, idx - radius)
    right = min(trace.size, idx + radius + 1)
    if left >= right:
        return 0.0
    local = trace[left:right]
    base = max(float(np.nanmin(local[: idx - left + 1])), float(np.nanmin(local[idx - left :])))
    return max(0.0, float(trace[idx]) - base)


def local_candidates(trace: np.ndarray, start: int, end: int) -> list[Candidate]:
    start = max(2, start)
    end = min(trace.size - 3, end)
    candidates: list[Candidate] = []
    for idx in range(start, end + 1):
        value = float(trace[idx])
        if value < 18.0:
            continue
        if value >= trace[idx - 1] and value > trace[idx + 1] and value >= trace[idx - 2] and value >= trace[idx + 2]:
            candidates.append(Candidate(idx, value, "local", local_prominence(trace, idx)))
    candidates.sort(key=lambda item: (-item.height, item.scan))
    kept: list[Candidate] = []
    for candidate in candidates:
        if any(abs(candidate.scan - existing.scan) <= 5 for existing in kept):
            continue
        kept.append(candidate)
        if len(kept) >= 80:
            break
    kept.sort(key=lambda item: item.scan)
    return kept


def build_candidates(analysis: dict[str, Any], trace: np.ndarray, current: list[int]) -> list[Candidate]:
    by_scan: dict[int, Candidate] = {}
    for peak in analysis.get("candidate_peaks") or []:
        scan = parse_int(peak.get("index"))
        if scan is None or not (1300 <= scan <= 6000):
            continue
        height = parse_float(peak.get("height"))
        by_scan[scan] = Candidate(
            scan,
            height if math.isfinite(height) else float(trace[scan]),
            "rust",
            local_prominence(trace, scan),
        )
    for candidate in local_candidates(trace, 1300, min(2500, trace.size - 1)):
        by_scan.setdefault(candidate.scan, candidate)
    for scan in current:
        if 0 <= scan < trace.size:
            by_scan.setdefault(scan, Candidate(scan, float(trace[scan]), "selected", local_prominence(trace, scan)))
    return sorted(by_scan.values(), key=lambda item: item.scan)


def top_in_window(candidates: list[Candidate], start: int, end: int, limit: int) -> list[int]:
    items = [item for item in candidates if start <= item.scan <= end]
    items.sort(key=lambda item: (-item.height, item.scan))
    chosen = sorted(item.scan for item in items[:limit])
    return chosen


def nearest_projected_candidates(candidates: list[Candidate], expected: float, *, radius: int = 45, limit: int = 7) -> list[int]:
    items = [item for item in candidates if abs(item.scan - expected) <= radius]
    items.sort(key=lambda item: (abs(item.scan - expected), -item.height, item.scan))
    return sorted({item.scan for item in items[:limit]})


def projected_apex_candidates(
    candidates: list[Candidate],
    expected: float,
    *,
    radius: int = 55,
    limit: int = 8,
    min_height: float = 35.0,
) -> list[int]:
    items = [item for item in candidates if abs(item.scan - expected) <= radius]
    if not items:
        return []
    local_max = max((item.height for item in items), default=0.0)
    support_floor = max(min_height, local_max * 0.08)
    supported = [
        item
        for item in items
        if item.height >= support_floor and item.prominence >= min(25.0, max(8.0, item.height * 0.12))
    ]
    if not supported:
        supported = [item for item in items if item.height >= min_height]
    if not supported:
        return []
    supported.sort(
        key=lambda item: (
            abs(item.scan - expected) * 0.8 - min(item.height, 2000.0) / 120.0 - min(item.prominence, 1500.0) / 180.0,
            item.scan,
        )
    )
    return sorted({item.scan for item in supported[:limit]})


def reverse_start_from_anchors(
    trials: list[Trial],
    strategy: str,
    current: list[int],
    candidates: list[Candidate],
    anchor_indices: list[int],
    target_prefix_len: int,
) -> None:
    anchor_scans = [current[idx] for idx in anchor_indices]
    anchor_bps = [GS500ROX_SIZES[idx] for idx in anchor_indices]
    if len(anchor_scans) < 2:
        return
    coef = np.polyfit(np.asarray(anchor_bps, dtype=float), np.asarray(anchor_scans, dtype=float), deg=1)
    pools: list[list[int]] = []
    for bp in GS500ROX_SIZES[:target_prefix_len]:
        expected = float(np.polyval(coef, bp))
        pools.append(nearest_projected_candidates(candidates, expected, radius=55, limit=8))
    if any(not pool for pool in pools):
        return
    beam: list[list[int]] = [[]]
    for step, pool in enumerate(pools):
        next_beam: list[list[int]] = []
        for prefix in beam:
            last = prefix[-1] if prefix else 0
            for scan in pool:
                if scan <= last + 6:
                    continue
                if step == 1 and prefix and not (35 <= scan - prefix[0] <= 160):
                    continue
                partial = prefix + [scan]
                filler = partial + current[len(partial):]
                lmax, lmean, lr2 = linear_metrics(filler)
                anchor_bonus = 0.0
                for item in candidates:
                    if item.scan in partial:
                        anchor_bonus += min(item.height / 1500.0, 2.5)
                next_beam.append((partial, trial_score(lmax, lmean, lr2, filler, current) - anchor_bonus))
        beam = [prefix for prefix, _score in sorted(next_beam, key=lambda item: item[1])[:80]]
        if not beam:
            return
    for prefix in beam[:30]:
        add_trial(
            trials,
            strategy,
            prefix + current[len(prefix):],
            current,
            json.dumps({"anchors": anchor_bps, "prefix": prefix}),
        )


def reverse_start_from_tail_fit(
    trials: list[Trial],
    strategy: str,
    current: list[int],
    candidates: list[Candidate],
    fit_indices: list[int],
    target_prefix_len: int,
) -> None:
    anchor_scans = [current[idx] for idx in fit_indices]
    anchor_bps = [GS500ROX_SIZES[idx] for idx in fit_indices]
    if len(anchor_scans) < 3:
        return
    coef = np.polyfit(np.asarray(anchor_bps, dtype=float), np.asarray(anchor_scans, dtype=float), deg=1)
    pools: list[list[int]] = []
    for bp in GS500ROX_SIZES[:target_prefix_len]:
        expected = float(np.polyval(coef, bp))
        radius = 70 if bp <= 50 else 55
        pools.append(nearest_projected_candidates(candidates, expected, radius=radius, limit=10))
    if any(not pool for pool in pools):
        return
    beam: list[list[int]] = [[]]
    for step, pool in enumerate(pools):
        next_beam: list[tuple[list[int], float]] = []
        for prefix in beam:
            last = prefix[-1] if prefix else 0
            for scan in pool:
                if scan <= last + 6:
                    continue
                if step == 1 and prefix and not (35 <= scan - prefix[0] <= 170):
                    continue
                partial = prefix + [scan]
                filler = partial + current[len(partial):]
                lmax, lmean, lr2 = linear_metrics(filler)
                height_bonus = 0.0
                projection_penalty = 0.0
                for idx, chosen in enumerate(partial):
                    expected = float(np.polyval(coef, GS500ROX_SIZES[idx]))
                    projection_penalty += abs(chosen - expected) * 0.015
                    for item in candidates:
                        if item.scan == chosen:
                            height_bonus += min(item.height / 1200.0, 3.0)
                            break
                next_beam.append((partial, trial_score(lmax, lmean, lr2, filler, current) + projection_penalty - height_bonus))
        beam = [prefix for prefix, _score in sorted(next_beam, key=lambda item: item[1])[:100]]
        if not beam:
            return
    for prefix in beam[:35]:
        add_trial(
            trials,
            strategy,
            prefix + current[len(prefix):],
            current,
            json.dumps({"fit_bps": anchor_bps, "prefix": prefix}),
        )


def reverse_start_from_tail_fit_apex(
    trials: list[Trial],
    strategy: str,
    current: list[int],
    candidates: list[Candidate],
    fit_indices: list[int],
    target_prefix_len: int,
) -> None:
    anchor_scans = [current[idx] for idx in fit_indices]
    anchor_bps = [GS500ROX_SIZES[idx] for idx in fit_indices]
    if len(anchor_scans) < 3:
        return
    coef = np.polyfit(np.asarray(anchor_bps, dtype=float), np.asarray(anchor_scans, dtype=float), deg=1)
    pools: list[list[int]] = []
    for bp in GS500ROX_SIZES[:target_prefix_len]:
        expected = float(np.polyval(coef, bp))
        radius = 85 if bp <= 50 else 70
        min_height = 55.0 if bp <= 50 else 35.0
        pools.append(projected_apex_candidates(candidates, expected, radius=radius, limit=7, min_height=min_height))
    if any(not pool for pool in pools):
        return
    beam: list[list[int]] = [[]]
    for step, pool in enumerate(pools):
        next_beam: list[tuple[list[int], float]] = []
        for prefix in beam:
            last = prefix[-1] if prefix else 0
            for scan in pool:
                if scan <= last + 8:
                    continue
                if step == 1 and prefix and not (45 <= scan - prefix[0] <= 150):
                    continue
                partial = prefix + [scan]
                filler = partial + current[len(partial):]
                lmax, lmean, lr2 = linear_metrics(filler)
                projection_penalty = 0.0
                support_bonus = 0.0
                weak_penalty = 0.0
                for idx, chosen in enumerate(partial):
                    expected = float(np.polyval(coef, GS500ROX_SIZES[idx]))
                    projection_penalty += abs(chosen - expected) * 0.025
                    match = next((item for item in candidates if item.scan == chosen), None)
                    if match is None:
                        weak_penalty += 4.0
                    else:
                        support_bonus += min(match.height / 350.0, 5.0) + min(match.prominence / 450.0, 3.0)
                        if match.height < (55.0 if idx <= 1 else 35.0):
                            weak_penalty += 8.0
                next_beam.append(
                    (
                        partial,
                        trial_score(lmax, lmean, lr2, filler, current) + projection_penalty + weak_penalty - support_bonus,
                    )
                )
        beam = [prefix for prefix, _score in sorted(next_beam, key=lambda item: item[1])[:80]]
        if not beam:
            return
    for prefix in beam[:30]:
        add_trial(
            trials,
            strategy,
            prefix + current[len(prefix):],
            current,
            json.dumps({"fit_bps": anchor_bps, "prefix": prefix, "apex": True}),
        )


def add_trial(trials: list[Trial], strategy: str, selected: list[int], current: list[int], note: str) -> None:
    if len(selected) != len(GS500ROX_SIZES):
        return
    if any(right <= left for left, right in zip(selected, selected[1:])):
        return
    linear_max, linear_mean, linear_r2 = linear_metrics(selected)
    score = trial_score(linear_max, linear_mean, linear_r2, selected, current)
    trials.append(Trial(strategy, selected, linear_max, linear_mean, linear_r2, score, note))


def evaluate_strategies(current: list[int], candidates: list[Candidate]) -> list[Trial]:
    trials: list[Trial] = []
    current_linear_max, current_linear_mean, current_linear_r2 = linear_metrics(current)
    trials.append(
        Trial(
            "current",
            current,
            current_linear_max,
            current_linear_mean,
            current_linear_r2,
            trial_score(current_linear_max, current_linear_mean, current_linear_r2, current, current),
            "",
        )
    )
    if len(current) != len(GS500ROX_SIZES):
        return trials

    third = current[2]
    fifth = current[4]
    sixth = current[5]
    early = [item.scan for item in candidates if 1300 <= item.scan < min(sixth, 2400)]

    # Strategy 1: user's observed pattern, current 50 becomes 35, insert a new 50 before current 75.
    inserted_seconds = top_in_window(candidates, current[1] + 18, third - 8, 12)
    for second in inserted_seconds:
        add_trial(
            trials,
            "shift_35_to_current_50_insert_new_50",
            [current[1], second] + current[2:],
            current,
            f"35={current[1]} 50={second}",
        )

    # Strategy 1b: same user pattern, but also allow the current 75 to become new 50
    # and re-insert 75/100/139 as a block before the current 150.
    shifted_pools = [
        [current[1]],
        [scan for scan in early if current[1] + 18 <= scan <= min(current[2] + 35, current[3] - 8)],
        [scan for scan in early if current[2] + 8 <= scan <= min(current[3] + 80, current[4] - 8)],
        [scan for scan in early if current[3] + 8 <= scan <= min(current[4] + 110, current[5] - 8)],
        [scan for scan in early if current[4] + 8 <= scan <= current[5] - 8],
    ]
    shifted_pools = [
        sorted(set(pool), key=lambda scan: -next((c.height for c in candidates if c.scan == scan), 0.0))[:12]
        for pool in shifted_pools
    ]
    shifted_beam: list[tuple[list[int], float]] = [([], 0.0)]
    for step, pool in enumerate(shifted_pools):
        next_beam: list[tuple[list[int], float]] = []
        for prefix, _score in shifted_beam:
            last = prefix[-1] if prefix else 0
            for scan in pool:
                if scan <= last + 6:
                    continue
                if step == 1 and prefix and not (35 <= scan - prefix[0] <= 210):
                    continue
                partial = prefix + [scan]
                filler = partial + current[len(partial) :]
                lmax, lmean, lr2 = linear_metrics(filler)
                # Give this a slight visual-prior discount so it is visible in
                # top trials even when pure residual prefers earlier starts.
                next_beam.append((partial, trial_score(lmax, lmean, lr2, filler, current) - 2.5))
        shifted_beam = sorted(next_beam, key=lambda item: item[1])[:60]
    for prefix, _score in shifted_beam[:30]:
        if len(prefix) == 5:
            add_trial(
                trials,
                "user_shift_current_50_to_35_block",
                prefix + current[5:],
                current,
                json.dumps(prefix),
            )

    # Strategy 2: enumerate just 35/50 while keeping the rest fixed.
    firsts = top_in_window(candidates, max(1300, current[0] - 120), min(third - 50, current[1] + 35), 16)
    seconds = top_in_window(candidates, max(1320, current[0] + 20), third - 8, 18)
    for first in firsts:
        for second in seconds:
            if not (35 <= second - first <= 190):
                continue
            add_trial(trials, "pair_enum_keep_75_plus", [first, second] + current[2:], current, f"35={first} 50={second}")

    # Strategy 3: re-fit first five anchors as a block, then keep 150+ fixed.
    pools = [
        [scan for scan in early if max(1300, current[0] - 180) <= scan <= min(current[1] + 45, 1800)],
        [scan for scan in early if max(1320, current[0] + 18) <= scan <= min(current[2] - 10, 1950)],
        [scan for scan in early if max(1360, current[1] + 18) <= scan <= min(current[3] + 90, 2150)],
        [scan for scan in early if max(1400, current[2] + 18) <= scan <= min(current[4] + 140, 2300)],
        [scan for scan in early if max(1450, current[3] + 18) <= scan <= min(current[5] - 8, 2450)],
    ]
    pools = [sorted(set(pool), key=lambda scan: -next((c.height for c in candidates if c.scan == scan), 0.0))[:12] for pool in pools]
    beam: list[tuple[list[int], float]] = [([], 0.0)]
    for step, pool in enumerate(pools):
        next_beam: list[tuple[list[int], float]] = []
        for prefix, _score in beam:
            last = prefix[-1] if prefix else 0
            for scan in pool:
                if scan <= last + 8:
                    continue
                if step == 1 and prefix and not (35 <= scan - prefix[0] <= 190):
                    continue
                partial = prefix + [scan]
                filler = partial + current[len(partial) :]
                lmax, lmean, lr2 = linear_metrics(filler)
                next_beam.append((partial, trial_score(lmax, lmean, lr2, filler, current)))
        beam = sorted(next_beam, key=lambda item: item[1])[:80]
    for prefix, _score in beam[:40]:
        if len(prefix) == 5:
            add_trial(trials, "start_block_35_50_75_100_139", prefix + current[5:], current, json.dumps(prefix))

    # Strategy 4: re-fit through 160 bp when the 139/150/160 cluster is implicated.
    pools7 = pools + [
        [scan for scan in early if max(current[4] + 8, 1500) <= scan <= min(current[6] + 70, 2600)],
        [scan for scan in early if max(current[5] + 8, 1520) <= scan <= min(current[7] - 8, 2800)],
    ]
    pools7 = [sorted(set(pool), key=lambda scan: -next((c.height for c in candidates if c.scan == scan), 0.0))[:10] for pool in pools7]
    beam = [([], 0.0)]
    for step, pool in enumerate(pools7):
        next_beam = []
        for prefix, _score in beam:
            last = prefix[-1] if prefix else 0
            for scan in pool:
                if scan <= last + 6:
                    continue
                if step == 1 and prefix and not (35 <= scan - prefix[0] <= 190):
                    continue
                partial = prefix + [scan]
                filler = partial + current[len(partial) :]
                lmax, lmean, lr2 = linear_metrics(filler)
                next_beam.append((partial, trial_score(lmax, lmean, lr2, filler, current)))
        beam = sorted(next_beam, key=lambda item: item[1])[:60]
    for prefix, _score in beam[:25]:
        if len(prefix) == 7:
            add_trial(trials, "start_block_35_to_160", prefix + current[7:], current, json.dumps(prefix))

    # Strategy 5: reverse-project the early ladder from stable later anchor
    # families. This is meant to avoid letting noisy 35/50 starts drive the fit.
    reverse_start_from_anchors(trials, "reverse_from_139_150_160_to_35_100", current, candidates, [4, 5, 6], 4)
    reverse_start_from_anchors(trials, "reverse_from_340_350_to_35_100", current, candidates, [10, 11], 4)
    reverse_start_from_anchors(trials, "reverse_from_490_500_to_35_100", current, candidates, [14, 15], 4)
    reverse_start_from_anchors(trials, "reverse_from_139_150_160_to_35_139", current, candidates, [4, 5, 6], 5)
    reverse_start_from_anchors(trials, "reverse_from_340_350_to_35_139", current, candidates, [10, 11], 5)
    reverse_start_from_anchors(trials, "reverse_from_490_500_to_35_139", current, candidates, [14, 15], 5)
    reverse_start_from_tail_fit(trials, "reverse_tailfit_139_500_to_35_100", current, candidates, list(range(4, 16)), 4)
    reverse_start_from_tail_fit(trials, "reverse_tailfit_200_500_to_35_100", current, candidates, list(range(7, 16)), 4)
    reverse_start_from_tail_fit(trials, "reverse_tailfit_300_500_to_35_100", current, candidates, list(range(9, 16)), 4)
    reverse_start_from_tail_fit(trials, "reverse_tailfit_139_500_to_35_139", current, candidates, list(range(4, 16)), 5)
    reverse_start_from_tail_fit(trials, "reverse_tailfit_200_500_to_35_139", current, candidates, list(range(7, 16)), 5)
    reverse_start_from_tail_fit(trials, "reverse_tailfit_300_500_to_35_139", current, candidates, list(range(9, 16)), 5)
    reverse_start_from_tail_fit_apex(trials, "reverse_tailfit_apex_139_500_to_35_139", current, candidates, list(range(4, 16)), 5)
    reverse_start_from_tail_fit_apex(trials, "reverse_tailfit_apex_200_500_to_35_139", current, candidates, list(range(7, 16)), 5)
    reverse_start_from_tail_fit_apex(trials, "reverse_tailfit_apex_300_500_to_35_139", current, candidates, list(range(9, 16)), 5)

    unique: dict[tuple[int, ...], Trial] = {}
    for trial in sorted(trials, key=lambda item: item.score):
        unique.setdefault(tuple(trial.selected), trial)
    return sorted(unique.values(), key=lambda item: item.score)


def render_case(row: dict[str, Any], trace: np.ndarray, current: list[int], best: Trial, out_dir: Path) -> str:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    file_name = row["file"]
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in Path(file_name).stem)
    out = image_dir / f"{int(row['panel_no']):03d}_{safe}_{best.strategy}.png"

    x_min = 1300
    focus = current[:7] + best.selected[:7]
    x_max = min(trace.size - 1, max(focus + [2400]) + 260)
    window = trace[x_min:x_max]
    y_max = max(250.0, min(2500.0, float(np.nanpercentile(window, 99.6) * 1.15))) if window.size else 2500.0

    fig, ax = plt.subplots(figsize=(12, 4.8), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.85, label="DATA4 corrected")
    visible_current = [scan for scan in current if x_min <= scan <= x_max]
    visible_best = [scan for scan in best.selected if x_min <= scan <= x_max]
    ax.scatter(visible_current, [trace[scan] for scan in visible_current], marker="x", s=58, color="#dc2626", label="current")
    ax.scatter(visible_best, [trace[scan] for scan in visible_best], marker="o", s=34, facecolors="none", edgecolors="#2563eb", label=best.strategy)
    for idx, scan in enumerate(best.selected[:7]):
        if x_min <= scan <= x_max:
            ax.text(scan, min(y_max * 0.96, trace[scan] + y_max * 0.045), str(GS500ROX_SIZES[idx]), ha="center", fontsize=8, color="#2563eb")
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-50, y_max)
    ax.grid(alpha=0.18)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(
        f"#{row['panel_no']} {file_name} | current {row['current_linear_max']:.2f}/{row['current_linear_mean']:.2f} "
        f"-> {best.strategy} {best.linear_max:.2f}/{best.linear_mean:.2f}"
    )
    ax.set_xlabel("scan time")
    ax.set_ylabel("RFU")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return str(out.relative_to(out_dir))


def contact_sheet(image_paths: list[str], out_dir: Path) -> str:
    if not image_paths:
        return ""
    from PIL import Image, ImageDraw

    thumbs = []
    for rel in image_paths:
        path = out_dir / rel
        img = Image.open(path).convert("RGB")
        img.thumbnail((720, 300))
        canvas = Image.new("RGB", (740, 330), "white")
        canvas.paste(img, (10, 10))
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 305), rel, fill=(20, 20, 20))
        thumbs.append(canvas)
    cols = 2
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * 740, rows * 330), "#f5f5f5")
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * 740, (idx // cols) * 330))
    out = out_dir / "contact_sheet.jpg"
    sheet.save(out, quality=92)
    return str(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow-evaluate GS500ROX 35/50 start strategies.")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--start-row", type=int, default=9, help="1-based panel row to start from.")
    parser.add_argument("--end-row", type=int, default=36, help="1-based panel row to end at.")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with args.panel.open(newline="", encoding="utf-8") as handle:
        panel_rows = list(csv.DictReader(handle))

    summary_rows: list[dict[str, Any]] = []
    trial_rows: list[dict[str, Any]] = []
    rendered: list[str] = []

    for panel_no, panel_row in enumerate(panel_rows, start=1):
        if panel_no < args.start_row or panel_no > args.end_row:
            continue
        path = resolve_path(panel_row, args.data_root)
        base_row: dict[str, Any] = {
            "panel_no": panel_no,
            "file": panel_row.get("File", ""),
            "path": str(path),
            "exists": path.exists(),
            "qc_status": panel_row.get("QCStatus", ""),
            "panel_note": panel_row.get("note", ""),
        }
        if not path.exists():
            summary_rows.append({**base_row, "ok": False, "error": "missing raw path"})
            continue
        analysis = analyze_path(path, args.timeout)
        if not analysis.get("ok"):
            summary_rows.append({**base_row, "ok": False, "error": analysis.get("error", "")})
            continue
        current = [int(value) for value in analysis["selected"]]
        if len(current) != len(GS500ROX_SIZES):
            summary_rows.append({**base_row, "ok": False, "error": f"selected_count={len(current)}"})
            continue
        trace = corrected_trace(raw_trace(path, analysis.get("channel") or "DATA4"))
        candidates = build_candidates(analysis, trace, current)
        trials = evaluate_strategies(current, candidates)
        current_trial = next(trial for trial in trials if trial.strategy == "current")
        best = trials[0]
        best_noncurrent = next((trial for trial in trials if trial.strategy != "current"), None)
        chosen = best_noncurrent if best_noncurrent and best_noncurrent.score + 0.001 < current_trial.score else current_trial
        image = ""
        if chosen.strategy != "current":
            image = render_case(
                {
                    **base_row,
                    "current_linear_max": current_trial.linear_max,
                    "current_linear_mean": current_trial.linear_mean,
                },
                trace,
                current,
                chosen,
                args.out_dir,
            )
            rendered.append(image)

        summary_rows.append(
            {
                **base_row,
                "ok": True,
                "channel": analysis.get("channel", ""),
                "candidate_count": len(candidates),
                "current_selected": json.dumps(current, separators=(",", ":")),
                "current_linear_max": current_trial.linear_max,
                "current_linear_mean": current_trial.linear_mean,
                "current_linear_r2": current_trial.linear_r2,
                "best_strategy": chosen.strategy,
                "best_selected": json.dumps(chosen.selected, separators=(",", ":")),
                "best_linear_max": chosen.linear_max,
                "best_linear_mean": chosen.linear_mean,
                "best_linear_r2": chosen.linear_r2,
                "delta_linear_max": chosen.linear_max - current_trial.linear_max,
                "delta_linear_mean": chosen.linear_mean - current_trial.linear_mean,
                "changed_steps": json.dumps(
                    [GS500ROX_SIZES[idx] for idx, (left, right) in enumerate(zip(current, chosen.selected)) if left != right],
                    separators=(",", ":"),
                ),
                "image": image,
            }
        )
        # Keep the top candidates and all explicit user-shift candidates so
        # the CSV can show whether the visual hypothesis was considered.
        visible_trials: list[Trial] = []
        for trial in trials:
            if len(visible_trials) < 12 or trial.strategy.startswith("shift_35") or trial.strategy.startswith("user_shift"):
                visible_trials.append(trial)
        for rank, trial in enumerate(visible_trials, start=1):
            trial_rows.append(
                {
                    **base_row,
                    "rank": rank,
                    "strategy": trial.strategy,
                    "selected": json.dumps(trial.selected, separators=(",", ":")),
                    "linear_max": trial.linear_max,
                    "linear_mean": trial.linear_mean,
                    "linear_r2": trial.linear_r2,
                    "score": trial.score,
                    "note": trial.note,
                }
            )

    for name, rows in [("summary.csv", summary_rows), ("trials.csv", trial_rows)]:
        with (args.out_dir / name).open("w", newline="", encoding="utf-8") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            else:
                handle.write("")

    sheet = contact_sheet(rendered, args.out_dir)
    summary = {
        "panel": str(args.panel),
        "rows": len(summary_rows),
        "changed": sum(1 for row in summary_rows if row.get("best_strategy") not in ("", "current")),
        "contact_sheet": sheet,
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
