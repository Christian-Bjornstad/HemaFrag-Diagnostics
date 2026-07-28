"""Offline baseline and peak-detection comparisons."""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy import signal

from core.analysis import estimate_running_baseline
from core.analysis._legacy import _rolling_quantile_baseline
from fraggler.fraggler import baseline_arPLS


BASELINE_SHADOW_SCHEMA = "hemafrag_baseline_shadow_v1"


def _airpls_baseline(
    trace: np.ndarray,
    *,
    lam: float = 100.0,
    max_iter: int = 30,
    tolerance: float = 1e-3,
) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    if values.size < 3:
        return np.zeros_like(values)
    difference = sparse.diags(
        [np.ones(values.size - 2), -2.0 * np.ones(values.size - 2), np.ones(values.size - 2)],
        [0, 1, 2],
        shape=(values.size - 2, values.size),
        format="csc",
    )
    penalty = float(lam) * (difference.T @ difference)
    weights = np.ones(values.size, dtype=float)
    scale = max(float(np.sum(np.abs(values))), 1.0)
    baseline = np.zeros_like(values)
    for iteration in range(1, max(2, int(max_iter)) + 1):
        weighted = sparse.spdiags(weights, 0, values.size, values.size, format="csc")
        baseline = np.asarray(
            spsolve(weighted + penalty, weights * values),
            dtype=float,
        )
        residual = values - baseline
        negative = residual[residual < 0]
        negative_sum = float(np.sum(np.abs(negative)))
        if negative.size == 0 or negative_sum <= tolerance * scale:
            break
        weights[residual >= 0] = 0.0
        exponent = np.minimum(iteration * np.abs(negative) / max(negative_sum, 1e-9), 60.0)
        weights[residual < 0] = np.exp(exponent)
        endpoint = float(np.exp(np.min([iteration * np.max(np.abs(negative)) / negative_sum, 60.0])))
        weights[0] = endpoint
        weights[-1] = endpoint
    if not np.all(np.isfinite(baseline)):
        raise ValueError("airPLS produced a non-finite baseline.")
    return baseline


def _detect(
    trace: np.ndarray,
    baseline: np.ndarray,
    *,
    min_height: float,
    min_distance: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    corrected = np.maximum(trace - baseline, 0.0)
    residual = trace - baseline
    noise = float(1.4826 * np.median(np.abs(residual - np.median(residual))))
    peaks, _ = signal.find_peaks(
        corrected,
        height=max(float(min_height), 4.0 * noise),
        prominence=max(1.0, 3.0 * noise),
        distance=max(1, int(min_distance)),
    )
    return corrected, peaks, noise


def _match_peaks(reference: np.ndarray, candidate: np.ndarray, tolerance: int = 3) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    used: set[int] = set()
    for reference_index in reference:
        if not candidate.size:
            break
        distances = np.abs(candidate - reference_index)
        for position in np.argsort(distances):
            candidate_index = int(candidate[position])
            if int(distances[position]) > tolerance:
                break
            if candidate_index not in used:
                used.add(candidate_index)
                matches.append((int(reference_index), candidate_index))
                break
    return matches


def _area(trace: np.ndarray, center: int, radius: int = 5) -> float:
    left = max(0, center - radius)
    right = min(trace.size, center + radius + 1)
    return float(np.trapezoid(trace[left:right])) if right - left >= 2 else 0.0


def _method_evidence(
    raw: np.ndarray,
    baseline: np.ndarray,
    *,
    min_height: float,
    min_distance: int,
    reference_corrected: np.ndarray,
    reference_peaks: np.ndarray,
) -> dict[str, object]:
    corrected, peaks, noise = _detect(
        raw,
        baseline,
        min_height=min_height,
        min_distance=min_distance,
    )
    matches = _match_peaks(reference_peaks, peaks)
    shifts = [candidate - reference for reference, candidate in matches]
    height_biases = [
        (corrected[candidate] - reference_corrected[reference])
        / max(abs(reference_corrected[reference]), 1e-9)
        for reference, candidate in matches
    ]
    area_biases = [
        (_area(corrected, candidate) - _area(reference_corrected, reference))
        / max(abs(_area(reference_corrected, reference)), 1e-9)
        for reference, candidate in matches
    ]
    return {
        "peak_count": int(peaks.size),
        "matched_reference_peak_count": len(matches),
        "reference_peak_recall": (
            float(len(matches) / reference_peaks.size) if reference_peaks.size else None
        ),
        "median_abs_apex_shift_scans": (
            float(np.median(np.abs(shifts))) if shifts else None
        ),
        "max_abs_apex_shift_scans": float(np.max(np.abs(shifts))) if shifts else None,
        "median_height_bias_fraction": (
            float(np.median(height_biases)) if height_biases else None
        ),
        "median_local_area_bias_fraction": (
            float(np.median(area_biases)) if area_biases else None
        ),
        "robust_residual_noise_rfu": noise,
        "negative_residual_fraction": float(np.mean((raw - baseline) < 0)),
        "baseline_roughness": (
            float(np.median(np.abs(np.diff(baseline)))) if baseline.size > 1 else 0.0
        ),
    }


def evaluate_baseline_detection_shadow(
    trace: np.ndarray | list[float],
    *,
    min_height: float = 50.0,
    min_distance: int = 5,
) -> dict[str, object]:
    """Compare bounded preprocessing alternatives against today's output."""
    raw = np.asarray(trace, dtype=float)
    if raw.size < 20 or not np.all(np.isfinite(raw)):
        raise ValueError("Baseline shadow requires at least 20 finite trace samples.")
    current = estimate_running_baseline(raw, use_arpls=True, lam=100.0)
    methods = {
        "current_guarded_arpls": current,
        "arpls_lambda_1000": np.asarray(
            baseline_arPLS(raw, ratio=0.99, lam=1000.0),
            dtype=float,
        ),
        "airpls_lambda_100": _airpls_baseline(raw, lam=100.0),
        "rolling_quantile_0_05": _rolling_quantile_baseline(raw, quantile=0.05),
        "rolling_quantile_0_10": _rolling_quantile_baseline(raw, quantile=0.10),
    }
    reference_corrected, reference_peaks, _ = _detect(
        raw,
        current,
        min_height=min_height,
        min_distance=min_distance,
    )
    return {
        "schema_version": BASELINE_SHADOW_SCHEMA,
        "evaluation": "current_preprocessing_relative_bakeoff",
        "promotion_eligible": False,
        "trace_length": int(raw.size),
        "reference_method": "current_guarded_arpls",
        "methods": {
            name: _method_evidence(
                raw,
                baseline,
                min_height=min_height,
                min_distance=min_distance,
                reference_corrected=reference_corrected,
                reference_peaks=reference_peaks,
            )
            for name, baseline in methods.items()
        },
        "warnings": {
            "current_method_is_not_ground_truth": True,
            "quantitative_area_trace_must_remain_separate": True,
            "reviewed_peak_labels_required": True,
        },
    }


__all__ = [
    "BASELINE_SHADOW_SCHEMA",
    "_airpls_baseline",
    "evaluate_baseline_detection_shadow",
]
