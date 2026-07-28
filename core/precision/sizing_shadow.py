"""Shadow-only sizing model comparisons for reviewed ladder anchors.

The leave-one-out result is an interpolation-stability proxy, not independent
fragment-sizing accuracy. It must not be used to promote a runtime model.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from scipy.interpolate import PchipInterpolator


SIZING_SHADOW_SCHEMA = "hemafrag_sizing_shadow_v1"


def _local_southern_triplet(
    times: np.ndarray,
    sizes: np.ndarray,
    target_time: float,
) -> float:
    """Fit L = c / (m - m0) + L0 to one three-anchor neighborhood."""
    if times.size != 3 or sizes.size != 3:
        raise ValueError("Local Southern triplet requires exactly three anchors.")
    matrix = np.asarray(
        [
            [sizes[1] - sizes[0], times[1] - times[0]],
            [sizes[2] - sizes[1], times[2] - times[1]],
        ],
        dtype=float,
    )
    right_hand = np.asarray(
        [
            (sizes[1] * times[1]) - (sizes[0] * times[0]),
            (sizes[2] * times[2]) - (sizes[1] * times[1]),
        ],
        dtype=float,
    )
    try:
        m0_value, l0_value = np.linalg.solve(matrix, right_hand)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Local Southern triplet is singular.") from exc
    c_value = float((sizes[0] - l0_value) * (times[0] - m0_value))
    denominator = float(target_time) - float(m0_value)
    if abs(denominator) < 1e-8:
        raise ValueError("Local Southern target is at the fitted mobility asymptote.")
    prediction = float(c_value / denominator + l0_value)
    if not np.isfinite(prediction):
        raise ValueError("Local Southern prediction is not finite.")
    return prediction


def _local_southern_predict(
    times: np.ndarray,
    sizes: np.ndarray,
    target_time: float,
) -> float:
    right = int(np.searchsorted(times, target_time, side="right"))
    if right < 2 or right + 1 >= times.size:
        raise ValueError("Local Southern requires two anchors on each side.")
    neighborhood_times = times[right - 2 : right + 2]
    neighborhood_sizes = sizes[right - 2 : right + 2]
    lower_curve = _local_southern_triplet(
        neighborhood_times[:3],
        neighborhood_sizes[:3],
        target_time,
    )
    upper_curve = _local_southern_triplet(
        neighborhood_times[1:],
        neighborhood_sizes[1:],
        target_time,
    )
    return float((lower_curve + upper_curve) / 2.0)


def _predict_linear(times: np.ndarray, sizes: np.ndarray, target_time: float) -> float:
    if target_time <= times[0] or target_time >= times[-1]:
        raise ValueError("Linear shadow evaluation does not extrapolate.")
    return float(np.interp(target_time, times, sizes))


def _predict_quadratic(
    times: np.ndarray,
    sizes: np.ndarray,
    target_time: float,
) -> float:
    if times.size < 3:
        raise ValueError("Quadratic sizing requires at least three anchors.")
    centered = times - float(np.mean(times))
    coefficients = np.polyfit(centered, sizes, 2)
    return float(np.polyval(coefficients, target_time - float(np.mean(times))))


def _predict_pchip(times: np.ndarray, sizes: np.ndarray, target_time: float) -> float:
    if target_time <= times[0] or target_time >= times[-1]:
        raise ValueError("PCHIP shadow evaluation does not extrapolate.")
    model = PchipInterpolator(times, sizes, extrapolate=False)
    return float(model(target_time))


def _method_summary(rows: list[dict[str, float]]) -> dict[str, object]:
    errors = np.asarray([row["error_bp"] for row in rows], dtype=float)
    absolute = np.abs(errors)
    return {
        "count": len(rows),
        "mae_bp": float(np.mean(absolute)) if rows else None,
        "p95_abs_error_bp": (
            float(np.percentile(absolute, 95)) if rows else None
        ),
        "max_abs_error_bp": float(np.max(absolute)) if rows else None,
        "bias_bp": float(np.mean(errors)) if rows else None,
        "points": rows,
    }


def evaluate_anchor_leave_one_out(
    anchor_times: list[float] | np.ndarray,
    anchor_sizes: list[float] | np.ndarray,
) -> dict[str, object]:
    """Compare sizing methods without changing the fitted HemaFrag model."""
    times = np.asarray(anchor_times, dtype=float)
    sizes = np.asarray(anchor_sizes, dtype=float)
    valid = np.isfinite(times) & np.isfinite(sizes)
    times = times[valid]
    sizes = sizes[valid]
    if times.size < 5 or times.size != sizes.size:
        raise ValueError("Sizing shadow evaluation requires at least five paired anchors.")
    order = np.argsort(times)
    times = times[order]
    sizes = sizes[order]
    if np.any(np.diff(times) <= 0) or np.any(np.diff(sizes) <= 0):
        raise ValueError("Sizing shadow anchors must be strictly increasing.")

    methods: dict[str, Callable[[np.ndarray, np.ndarray, float], float]] = {
        "linear": _predict_linear,
        "global_quadratic": _predict_quadratic,
        "monotone_pchip": _predict_pchip,
        "local_southern": _local_southern_predict,
    }
    rows_by_method: dict[str, list[dict[str, float]]] = {
        method: [] for method in methods
    }
    for held_out in range(times.size):
        train_times = np.delete(times, held_out)
        train_sizes = np.delete(sizes, held_out)
        target_time = float(times[held_out])
        expected_bp = float(sizes[held_out])
        for method, predictor in methods.items():
            try:
                predicted_bp = predictor(train_times, train_sizes, target_time)
            except (ValueError, FloatingPointError):
                continue
            rows_by_method[method].append(
                {
                    "anchor_index": int(held_out),
                    "time": target_time,
                    "expected_bp": expected_bp,
                    "predicted_bp": predicted_bp,
                    "error_bp": predicted_bp - expected_bp,
                }
            )

    return {
        "schema_version": SIZING_SHADOW_SCHEMA,
        "evaluation": "ladder_anchor_leave_one_out_proxy",
        "promotion_eligible": False,
        "anchor_count": int(times.size),
        "methods": {
            method: _method_summary(rows)
            for method, rows in rows_by_method.items()
        },
    }
