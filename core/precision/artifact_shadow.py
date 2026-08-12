"""Shadow-only capillary-electrophoresis artifact candidates."""
from __future__ import annotations

import re
from typing import Any

import numpy as np
from scipy import signal

from core.analysis import estimate_running_baseline


ARTIFACT_SHADOW_SCHEMA = "hemafrag_artifact_shadow_v1"
_DATA_CHANNEL = re.compile(r"^DATA(\d+)$", re.IGNORECASE)


def _analysis_channels(fsa: Any) -> dict[str, np.ndarray]:
    raw = getattr(fsa, "fsa", {})
    channels: list[tuple[int, str, np.ndarray]] = []
    for name, values in getattr(raw, "items", lambda: [])():
        match = _DATA_CHANNEL.match(str(name))
        if not match:
            continue
        array = np.asarray(values, dtype=float)
        if array.size < 3 or not np.all(np.isfinite(array)):
            continue
        channels.append((int(match.group(1)), str(name), array))
    primary = [item for item in channels if 1 <= item[0] <= 4]
    selected = primary if primary else sorted(channels)[:4]
    return {name: array for _, name, array in sorted(selected)}


def _max_run(mask: np.ndarray) -> int:
    if not np.any(mask):
        return 0
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return int(np.max(edges[1::2] - edges[::2]))


def _channel_evidence(
    trace: np.ndarray,
    *,
    signal_limit_rfu: float,
) -> tuple[dict[str, object], list[dict[str, float]]]:
    baseline = estimate_running_baseline(trace, use_arpls=True)
    corrected = np.maximum(trace - baseline, 0.0)
    negative = trace - baseline
    noise = float(1.4826 * np.median(np.abs(negative - np.median(negative))))
    threshold = max(50.0, 6.0 * noise)
    peaks, properties = signal.find_peaks(
        corrected,
        prominence=threshold,
        distance=2,
        width=1,
    )
    widths = np.asarray(properties.get("widths", np.zeros(peaks.size)), dtype=float)
    prominences = np.asarray(
        properties.get("prominences", np.zeros(peaks.size)),
        dtype=float,
    )
    peak_rows = [
        {
            "scan": float(index),
            "height": float(corrected[index]),
            "raw_height": float(trace[index]),
            "prominence": float(prominence),
            "width_scans": float(width),
        }
        for index, prominence, width in zip(peaks, prominences, widths)
    ]

    maximum = float(np.max(trace))
    near_limit = trace >= max(signal_limit_rfu, maximum * 0.995)
    flat_at_max = np.isclose(trace, maximum, rtol=0.0, atol=max(1.0, abs(maximum) * 1e-6))
    broad = sorted(
        (row for row in peak_rows if row["width_scans"] >= 20.0),
        key=lambda row: (-row["prominence"], row["scan"]),
    )[:10]
    return (
        {
            "trace_length": int(trace.size),
            "max_rfu": maximum,
            "robust_noise_rfu": noise,
            "detected_peak_count": int(peaks.size),
            "signal_limit_rfu": float(signal_limit_rfu),
            "samples_at_or_above_limit": int(np.sum(trace >= signal_limit_rfu)),
            "near_limit_fraction": float(np.mean(near_limit)),
            "flat_top_max_run_scans": _max_run(flat_at_max),
            "saturation_candidate": bool(
                maximum >= signal_limit_rfu
                and (_max_run(flat_at_max) >= 2 or np.sum(trace >= signal_limit_rfu) >= 2)
            ),
            "broad_morphology_candidates": broad,
        },
        peak_rows,
    )


def _pull_up_candidates(
    channel_peaks: dict[str, list[dict[str, float]]],
    channel_evidence: dict[str, dict[str, object]],
    *,
    alignment_tolerance_scans: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    names = sorted(channel_peaks)
    for source in names:
        for target in names:
            if source == target:
                continue
            target_noise = float(channel_evidence[target]["robust_noise_rfu"])
            target_floor = max(50.0, 6.0 * target_noise)
            for primary in channel_peaks[source]:
                aligned = [
                    candidate
                    for candidate in channel_peaks[target]
                    if abs(candidate["scan"] - primary["scan"]) <= alignment_tolerance_scans
                    and candidate["height"] >= target_floor
                    and primary["height"] >= 4.0 * candidate["height"]
                ]
                if not aligned:
                    continue
                secondary = max(aligned, key=lambda row: row["height"])
                rows.append(
                    {
                        "source_channel": source,
                        "target_channel": target,
                        "source_scan": primary["scan"],
                        "target_scan": secondary["scan"],
                        "scan_delta": secondary["scan"] - primary["scan"],
                        "source_height": primary["height"],
                        "target_height": secondary["height"],
                        "target_to_source_ratio": secondary["height"]
                        / max(primary["height"], 1e-9),
                        "source_saturation_candidate": bool(
                            channel_evidence[source]["saturation_candidate"]
                        ),
                    }
                )
    rows.sort(
        key=lambda row: (
            float(row["source_scan"]),
            str(row["source_channel"]),
            str(row["target_channel"]),
        )
    )
    return rows[:100]


def _ladder_tail_evidence(fsa: Any, trace_length: int) -> dict[str, object]:
    expected = np.asarray(getattr(fsa, "expected_ladder_steps", []), dtype=float)
    fitted = np.asarray(getattr(fsa, "ladder_steps", []), dtype=float)
    scans = np.asarray(getattr(fsa, "best_size_standard", []), dtype=float)
    missing = [
        float(value)
        for value in expected
        if not np.any(np.isclose(fitted, value, atol=1e-6))
    ]
    last_scan = float(scans[-1]) if scans.size else None
    tail_margin = float(trace_length - 1 - last_scan) if last_scan is not None else None
    high_end_missing = bool(
        expected.size
        and (not fitted.size or float(np.max(fitted)) < float(np.max(expected)) - 1e-6)
    )
    return {
        "expected_anchor_count": int(expected.size),
        "fitted_anchor_count": int(fitted.size),
        "missing_expected_steps_bp": missing,
        "last_fitted_scan": last_scan,
        "trace_tail_margin_scans": tail_margin,
        "missing_high_end_ladder_candidate": high_end_missing,
    }


def _ladder_height_decay(fsa: Any) -> dict[str, object]:
    trace = np.asarray(getattr(fsa, "size_standard", []), dtype=float)
    scans = np.rint(
        np.asarray(getattr(fsa, "best_size_standard", []), dtype=float)
    ).astype(int)
    scans = scans[(scans >= 0) & (scans < trace.size)]
    if scans.size < 6:
        return {"available": False}
    heights = trace[scans]
    third = max(1, heights.size // 3)
    early = float(np.median(heights[:third]))
    late = float(np.median(heights[-third:]))
    return {
        "available": True,
        "early_median_rfu": early,
        "late_median_rfu": late,
        "late_to_early_ratio": late / max(early, 1e-9),
        "abnormal_decay_candidate": bool(late < 0.15 * max(early, 1e-9)),
    }


def evaluate_artifact_shadow(
    fsa: Any,
    *,
    signal_limit_rfu: float = 30000.0,
    alignment_tolerance_scans: float = 2.0,
) -> dict[str, object]:
    """Collect conservative artifact candidates from the four analysis dyes."""
    channels = _analysis_channels(fsa)
    if not channels:
        raise ValueError("Artifact shadow requires at least one DATA channel.")
    summaries: dict[str, dict[str, object]] = {}
    peaks: dict[str, list[dict[str, float]]] = {}
    for name, trace in channels.items():
        summaries[name], peaks[name] = _channel_evidence(
            trace,
            signal_limit_rfu=signal_limit_rfu,
        )
    pull_up = _pull_up_candidates(
        peaks,
        summaries,
        alignment_tolerance_scans=alignment_tolerance_scans,
    )
    ladder_channel = str(getattr(fsa, "size_standard_channel", "") or "")
    ladder_length = int(
        channels.get(ladder_channel, np.asarray(getattr(fsa, "size_standard", []))).size
    )
    return {
        "schema_version": ARTIFACT_SHADOW_SCHEMA,
        "evaluation": "raw_trace_artifact_candidate_screen",
        "promotion_eligible": False,
        "channels": summaries,
        "pull_up_candidates": pull_up,
        "pull_up_candidate_count": len(pull_up),
        "ladder_tail": _ladder_tail_evidence(fsa, ladder_length),
        "ladder_height_decay": _ladder_height_decay(fsa),
        "warnings": {
            "candidates_are_not_diagnoses": True,
            "instrument_specific_limits_require_validation": True,
            "neighboring_capillary_metadata_not_evaluated": True,
        },
    }


__all__ = ["ARTIFACT_SHADOW_SCHEMA", "evaluate_artifact_shadow"]
