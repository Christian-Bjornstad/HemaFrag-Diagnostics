"""Offline ladder-confidence evidence that never changes the selected fit."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import signal

from core.analysis import estimate_running_baseline


LADDER_CONFIDENCE_SHADOW_SCHEMA = "hemafrag_ladder_confidence_shadow_v1"


def _as_strict_pairs(fsa: Any) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(getattr(fsa, "best_size_standard", []), dtype=float)
    sizes = np.asarray(getattr(fsa, "ladder_steps", []), dtype=float)
    count = min(times.size, sizes.size)
    times = times[:count]
    sizes = sizes[:count]
    valid = np.isfinite(times) & np.isfinite(sizes)
    times = times[valid]
    sizes = sizes[valid]
    if times.size < 5 or np.any(np.diff(times) <= 0) or np.any(np.diff(sizes) <= 0):
        raise ValueError("Confidence shadow requires five strictly increasing fitted anchors.")
    return times, sizes


def _candidate_times(fsa: Any, selected: np.ndarray) -> np.ndarray:
    candidates = np.asarray(getattr(fsa, "size_standard_peaks", []), dtype=float)
    candidates = candidates[np.isfinite(candidates)]
    trace = np.asarray(getattr(fsa, "size_standard", []), dtype=float)
    if trace.size >= 3:
        baseline = estimate_running_baseline(trace, use_arpls=True)
        corrected = np.maximum(trace - baseline, 0.0)
        threshold = max(
            5.0,
            0.50 * float(getattr(fsa, "min_size_standard_height", 50.0) or 50.0),
        )
        detected, details = signal.find_peaks(
            corrected,
            height=threshold,
            prominence=max(2.0, threshold * 0.10),
            distance=max(
                1,
                int(getattr(fsa, "min_distance_between_peaks", 5) or 5),
            ),
        )
        if detected.size > 80:
            prominences = np.asarray(details.get("prominences", np.zeros(detected.size)))
            keep = np.argsort(prominences, kind="stable")[-80:]
            detected = detected[keep]
        candidates = np.concatenate([candidates, detected.astype(float)])
    candidates = np.unique(np.concatenate([candidates, selected]))
    return np.sort(candidates)


def _peak_properties(trace: np.ndarray, scans: np.ndarray) -> dict[int, dict[str, float]]:
    indices = np.rint(scans).astype(int)
    valid = (indices >= 0) & (indices < trace.size)
    indices = np.unique(indices[valid])
    if not indices.size:
        return {}
    detected, details = signal.find_peaks(trace, prominence=0.0, width=0.0)
    detected_properties = {
        int(index): {
            "prominence": float(prominence),
            "width_scans": float(width),
        }
        for index, prominence, width in zip(
            detected,
            details.get("prominences", np.zeros(detected.size)),
            details.get("widths", np.zeros(detected.size)),
        )
    }
    return {
        int(index): {
            "height": float(trace[index]),
            **detected_properties.get(
                int(index),
                {"prominence": 0.0, "width_scans": 0.0},
            ),
        }
        for index in indices
    }


def _sequence_score(
    scans: np.ndarray,
    sizes: np.ndarray,
    properties: dict[int, dict[str, float]],
) -> dict[str, float]:
    centered = scans - float(np.mean(scans))
    coefficients = np.polyfit(centered, sizes, 2)
    predicted = np.polyval(coefficients, centered)
    residuals = np.abs(predicted - sizes)

    bp_gaps = np.diff(sizes)
    scan_per_bp = np.diff(scans) / bp_gaps
    gap_reference = float(np.median(scan_per_bp))
    gap_deviation = float(
        np.median(np.abs(scan_per_bp - gap_reference)) / max(abs(gap_reference), 1e-9)
    )

    selected_properties = [
        properties.get(int(round(scan)), {"height": 0.0, "prominence": 0.0, "width_scans": 0.0})
        for scan in scans
    ]
    heights = np.asarray([item["height"] for item in selected_properties], dtype=float)
    prominences = np.asarray([item["prominence"] for item in selected_properties], dtype=float)
    height_reference = float(np.median(heights[heights > 0])) if np.any(heights > 0) else 1.0
    purity = prominences / np.maximum(heights, 1.0)
    weak_fraction = float(np.mean(heights < 0.25 * height_reference))
    low_purity_fraction = float(np.mean(purity < 0.50))
    morphology_penalty = weak_fraction + low_purity_fraction

    mae = float(np.mean(residuals))
    maximum = float(np.max(residuals))
    blended = mae + (0.25 * maximum) + (2.0 * gap_deviation) + (0.25 * morphology_penalty)
    return {
        "score": blended,
        "quadratic_mae_bp": mae,
        "quadratic_max_error_bp": maximum,
        "gap_ratio_mad": gap_deviation,
        "morphology_penalty": morphology_penalty,
    }


def _local_alternatives(
    selected: np.ndarray,
    candidates: np.ndarray,
    properties: dict[int, dict[str, float]],
    *,
    per_anchor_limit: int,
) -> list[list[float]]:
    output: list[list[float]] = []
    for index, current in enumerate(selected):
        lower = (
            float(selected[index - 1]) + 0.5
            if index > 0
            else min(
                float(np.min(candidates)) - 1.0,
                float(current) - max(float(selected[1] - current), 8.0),
            )
        )
        upper = (
            float(selected[index + 1]) - 0.5
            if index + 1 < selected.size
            else max(
                float(np.max(candidates)) + 1.0,
                float(current) + max(float(current - selected[-2]), 8.0),
            )
        )
        local = candidates[
            (candidates > lower)
            & (candidates < upper)
            & (~np.isclose(candidates, current, atol=0.5))
        ]
        ranked = sorted(
            local.tolist(),
            key=lambda value: (
                abs(float(value) - float(current)),
                -properties.get(int(round(value)), {}).get("prominence", 0.0),
                float(value),
            ),
        )
        output.append([float(value) for value in ranked[:per_anchor_limit]])
    return output


def _rank_sequences(
    selected: np.ndarray,
    sizes: np.ndarray,
    alternatives: list[list[float]],
    properties: dict[int, dict[str, float]],
    *,
    top_k: int,
) -> tuple[list[dict[str, object]], int | None]:
    sequences: list[tuple[str, np.ndarray]] = [("runtime_selected", selected.copy())]
    for anchor_index, replacements in enumerate(alternatives):
        for replacement in replacements:
            trial = selected.copy()
            trial[anchor_index] = replacement
            if np.all(np.diff(trial) > 0):
                sequences.append((f"replace_anchor_{anchor_index}", trial))

    ranked: list[dict[str, object]] = []
    seen: set[tuple[float, ...]] = set()
    for source, scans in sequences:
        key = tuple(float(value) for value in scans)
        if key in seen:
            continue
        seen.add(key)
        ranked.append(
            {
                "source": source,
                "scan_indices": list(key),
                **_sequence_score(scans, sizes, properties),
            }
        )
    ranked.sort(
        key=lambda row: (
            float(row["score"]),
            tuple(float(value) for value in row["scan_indices"]),
        )
    )
    selected_rank = next(
        (index + 1 for index, row in enumerate(ranked) if row["source"] == "runtime_selected"),
        None,
    )
    return ranked[: max(2, int(top_k))], selected_rank


def _perturbation_support(
    trace: np.ndarray,
    selected: np.ndarray,
    *,
    min_height: float,
    min_distance: int,
    threshold_multipliers: tuple[float, ...],
) -> list[dict[str, object]]:
    baseline = estimate_running_baseline(trace, use_arpls=True)
    corrected = np.maximum(trace - baseline, 0.0)
    output: list[dict[str, object]] = []
    for multiplier in threshold_multipliers:
        threshold = max(1.0, float(min_height) * float(multiplier))
        peaks, _ = signal.find_peaks(
            corrected,
            height=threshold,
            distance=max(1, int(min_distance)),
        )
        distances = [
            float(np.min(np.abs(peaks.astype(float) - anchor))) if peaks.size else None
            for anchor in selected
        ]
        supported = [distance is not None and distance <= 3.0 for distance in distances]
        output.append(
            {
                "height_multiplier": float(multiplier),
                "detected_peak_count": int(peaks.size),
                "supported_anchor_count": int(sum(supported)),
                "support_fraction": float(np.mean(supported)),
                "max_nearest_distance_scans": (
                    float(max(distance for distance in distances if distance is not None))
                    if any(distance is not None for distance in distances)
                    else None
                ),
            }
        )
    return output


def evaluate_ladder_confidence_shadow(
    fsa: Any,
    *,
    top_k: int = 5,
    per_anchor_alternatives: int = 3,
    threshold_multipliers: tuple[float, ...] = (0.8, 1.0, 1.2),
) -> dict[str, object]:
    """Export bounded ambiguity and perturbation evidence for a fitted ladder."""
    selected, sizes = _as_strict_pairs(fsa)
    trace = np.asarray(getattr(fsa, "size_standard", []), dtype=float)
    if trace.size < 3:
        raise ValueError("Confidence shadow requires the size-standard trace.")
    candidates = _candidate_times(fsa, selected)
    properties = _peak_properties(trace, candidates)
    alternatives = _local_alternatives(
        selected,
        candidates,
        properties,
        per_anchor_limit=max(1, int(per_anchor_alternatives)),
    )
    ranked, selected_rank = _rank_sequences(
        selected,
        sizes,
        alternatives,
        properties,
        top_k=top_k,
    )
    score_margin = None
    relative_margin = None
    if len(ranked) >= 2:
        score_margin = float(ranked[1]["score"]) - float(ranked[0]["score"])
        relative_margin = score_margin / max(abs(float(ranked[0]["score"])), 1e-9)

    anchor_evidence: list[dict[str, object]] = []
    for index, (scan, size, local) in enumerate(zip(selected, sizes, alternatives)):
        details = properties.get(int(round(scan)), {})
        nearest = local[0] if local else None
        anchor_evidence.append(
            {
                "anchor_index": index,
                "expected_bp": float(size),
                "selected_scan": float(scan),
                "height": details.get("height"),
                "prominence": details.get("prominence"),
                "width_scans": details.get("width_scans"),
                "local_alternative_count": len(local),
                "nearest_alternative_scan": nearest,
                "nearest_alternative_distance_scans": (
                    abs(float(nearest) - float(scan)) if nearest is not None else None
                ),
            }
        )

    perturbations = _perturbation_support(
        trace,
        selected,
        min_height=float(getattr(fsa, "min_size_standard_height", 50.0) or 50.0),
        min_distance=int(getattr(fsa, "min_distance_between_peaks", 5) or 5),
        threshold_multipliers=threshold_multipliers,
    )
    expected = np.asarray(getattr(fsa, "expected_ladder_steps", sizes), dtype=float)
    missing_expected = [
        float(value)
        for value in expected
        if not np.any(np.isclose(sizes, value, atol=1e-6))
    ]
    return {
        "schema_version": LADDER_CONFIDENCE_SHADOW_SCHEMA,
        "evaluation": "bounded_local_sequence_and_threshold_perturbation_proxy",
        "promotion_eligible": False,
        "anchor_count": int(selected.size),
        "candidate_peak_count": int(candidates.size),
        "runtime_selected_rank": selected_rank,
        "top_k": ranked,
        "top1_top2_score_margin": score_margin,
        "top1_top2_relative_margin": relative_margin,
        "anchor_evidence": anchor_evidence,
        "perturbations": perturbations,
        "stable_under_tested_thresholds": bool(
            perturbations and all(float(row["support_fraction"]) == 1.0 for row in perturbations)
        ),
        "missing_expected_steps_bp": missing_expected,
        "warnings": {
            "candidate_space_bounded": True,
            "score_is_not_runtime_score": True,
            "independent_reference_required": True,
        },
    }


__all__ = [
    "LADDER_CONFIDENCE_SHADOW_SCHEMA",
    "evaluate_ladder_confidence_shadow",
]
