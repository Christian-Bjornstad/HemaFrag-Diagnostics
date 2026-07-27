"""Raw electropherogram trace-shape features for clonality ML.

The extractor consumes the ladder-fitted ``FsaFile`` already produced by the
normal clonality pipeline. It summarizes raw DATA channels without retaining
the raw trace arrays in the exported feature artifact.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, peak_widths

from core.analyses.clonality.config import ASSAY_REFERENCE_RANGES, NONSPECIFIC_PEAKS


TRACE_FEATURE_SCHEMA_VERSION = "clonality_trace_features_v1"
NONSPECIFIC_HALF_WIDTH_BP = 1.5

PER_CHANNEL_TRACE_FIELDS = (
    "trace_point_count_per_channel",
    "trace_reference_point_count_per_channel",
    "trace_reference_coverage_per_channel",
    "trace_peak_count_raw_per_channel",
    "trace_dominant_height_raw_per_channel",
    "trace_second_height_raw_per_channel",
    "trace_dominant_height_share_raw_per_channel",
    "trace_total_area_raw_per_channel",
    "trace_dominant_area_raw_per_channel",
    "trace_dominant_area_share_raw_per_channel",
    "trace_noise_mad_raw_per_channel",
    "trace_baseline_raw_per_channel",
    "trace_baseline_drift_raw_per_channel",
    "trace_baseline_drift_normalized_per_channel",
    "trace_outside_window_area_share_per_channel",
    "trace_nonspecific_area_share_per_channel",
    "trace_peak_spacing_mean_bp_per_channel",
    "trace_peak_spacing_min_bp_per_channel",
    "trace_peak_spacing_std_bp_per_channel",
    "trace_dominant_width_bp_per_channel",
    "trace_dominant_width_fraction_per_channel",
    "trace_dominant_symmetry_per_channel",
    "trace_shoulder_count_per_channel",
    "trace_multi_peak_density_per_100bp_per_channel",
    "trace_signal_to_noise_per_channel",
    "trace_clipped_point_fraction_per_channel",
)


def raw_trace_shape_features(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic per-channel raw-trace features.

    Empty/missing raw traces return the same stable field shape with empty
    channel mappings. This lets rule-only fixtures and historical artifacts
    continue to load while real analyzed entries receive the richer features.
    """
    result: dict[str, Any] = {
        field: {} for field in PER_CHANNEL_TRACE_FIELDS
    }
    result.update(
        {
            "trace_feature_schema_version": TRACE_FEATURE_SCHEMA_VERSION,
            "trace_available_channel_count": 0,
            "trace_total_reference_area_all_channels": 0.0,
            "trace_total_peak_count_all_channels": 0,
            "trace_dominant_channel_area_share": 0.0,
            "trace_max_signal_to_noise": 0.0,
        }
    )

    fsa = entry.get("fsa")
    raw_mapping = getattr(fsa, "sample_data_with_basepairs", None)
    raw_channels = getattr(fsa, "fsa", None)
    if not isinstance(raw_mapping, pd.DataFrame) or raw_mapping.empty:
        return result
    if not isinstance(raw_channels, Mapping):
        return result
    if not {"time", "basepairs"}.issubset(raw_mapping.columns):
        return result

    mapping = raw_mapping[["time", "basepairs"]].copy()
    mapping["time"] = pd.to_numeric(mapping["time"], errors="coerce")
    mapping["basepairs"] = pd.to_numeric(mapping["basepairs"], errors="coerce")
    mapping = mapping.replace([np.inf, -np.inf], np.nan).dropna()
    if mapping.empty:
        return result
    mapping = mapping.sort_values("time", kind="stable").drop_duplicates("time")
    times = mapping["time"].astype(int).to_numpy()
    basepairs = mapping["basepairs"].astype(float).to_numpy()

    assay = str(entry.get("assay") or "")
    ranges = _assay_ranges(assay)
    analysis_range = _analysis_range(entry, ranges, basepairs)
    if not ranges:
        ranges = [analysis_range]
    nonspecific_bps = NONSPECIFIC_PEAKS.get(_assay_name(assay), [])
    channels = _trace_channels(entry, raw_channels, fsa)

    total_areas: list[float] = []
    total_peaks = 0
    max_snr = 0.0
    for channel in channels:
        trace = np.asarray(raw_channels.get(channel, []), dtype=float)
        valid = (times >= 0) & (times < trace.size)
        if not valid.any():
            continue
        channel_bp = basepairs[valid]
        channel_y = trace[times[valid]]
        features = _summarize_channel(
            channel_bp,
            channel_y,
            ranges=ranges,
            analysis_range=analysis_range,
            nonspecific_bps=nonspecific_bps,
        )
        for field in PER_CHANNEL_TRACE_FIELDS:
            result[field][channel] = features[field]
        total_areas.append(float(features["trace_total_area_raw_per_channel"]))
        total_peaks += int(features["trace_peak_count_raw_per_channel"])
        max_snr = max(max_snr, float(features["trace_signal_to_noise_per_channel"]))

    total_area = float(sum(total_areas))
    result["trace_available_channel_count"] = len(total_areas)
    result["trace_total_reference_area_all_channels"] = total_area
    result["trace_total_peak_count_all_channels"] = int(total_peaks)
    result["trace_dominant_channel_area_share"] = (
        float(max(total_areas) / total_area) if total_area > 0 and total_areas else 0.0
    )
    result["trace_max_signal_to_noise"] = float(max_snr)
    return result


def flatten_numeric_features(features: Mapping[str, Any]) -> dict[str, float]:
    """Flatten scalar and one-level nested numeric feature mappings."""
    flat: dict[str, float] = {}
    for key, value in features.items():
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                numeric = _finite_number(nested_value)
                if numeric is not None:
                    flat[f"{key}.{str(nested_key).upper()}"] = numeric
            continue
        numeric = _finite_number(value)
        if numeric is not None:
            flat[str(key)] = numeric
    return flat


def _summarize_channel(
    bp: np.ndarray,
    raw_y: np.ndarray,
    *,
    ranges: Sequence[tuple[float, float]],
    analysis_range: tuple[float, float],
    nonspecific_bps: Sequence[float],
) -> dict[str, float | int]:
    finite = np.isfinite(bp) & np.isfinite(raw_y)
    bp = np.asarray(bp[finite], dtype=float)
    raw_y = np.asarray(raw_y[finite], dtype=float)
    order = np.argsort(bp, kind="stable")
    bp = bp[order]
    raw_y = raw_y[order]

    analysis_mask = (bp >= analysis_range[0]) & (bp <= analysis_range[1])
    analysis_bp = bp[analysis_mask]
    analysis_y = raw_y[analysis_mask]
    if analysis_bp.size < 3:
        return _empty_channel_features(point_count=int(analysis_bp.size))

    baseline, noise = _baseline_and_noise(analysis_y)
    corrected_analysis = np.clip(analysis_y - baseline, 0.0, None)
    analysis_area = _integrate(analysis_bp, corrected_analysis)
    drift, drift_normalized = _baseline_drift(
        analysis_bp,
        analysis_y,
        signal_scale=float(np.max(corrected_analysis)) if corrected_analysis.size else 0.0,
    )

    peak_rows: list[dict[str, float]] = []
    reference_area = 0.0
    reference_point_count = 0
    nonspecific_area = 0.0
    covered_width = 0.0
    configured_width = sum(max(0.0, float(hi) - float(lo)) for lo, hi in ranges)

    for lo, hi in ranges:
        segment_mask = (bp >= float(lo)) & (bp <= float(hi))
        segment_bp = bp[segment_mask]
        segment_y = raw_y[segment_mask]
        if segment_bp.size < 3:
            continue
        reference_point_count += int(segment_bp.size)
        covered_width += min(float(hi) - float(lo), max(0.0, float(segment_bp[-1] - segment_bp[0])))
        corrected = np.clip(segment_y - baseline, 0.0, None)
        nonspecific_mask = _nonspecific_mask(segment_bp, nonspecific_bps)
        nonspecific_area += _integrate(segment_bp, np.where(nonspecific_mask, corrected, 0.0))
        corrected_for_model = np.where(nonspecific_mask, 0.0, corrected)
        reference_area += _integrate(segment_bp, corrected_for_model)
        peak_rows.extend(
            _segment_peaks(
                segment_bp,
                corrected_for_model,
                noise=noise,
            )
        )

    peak_rows.sort(key=lambda item: item["bp"])
    heights = np.asarray([row["height"] for row in peak_rows], dtype=float)
    peak_bps = np.asarray([row["bp"] for row in peak_rows], dtype=float)
    spacings = np.diff(peak_bps) if peak_bps.size > 1 else np.asarray([], dtype=float)
    dominant = max(peak_rows, key=lambda item: item["height"]) if peak_rows else None
    second_height = (
        float(np.partition(heights, -2)[-2]) if heights.size >= 2 else 0.0
    )
    height_sum = float(np.sum(heights))
    dominant_height = float(dominant["height"]) if dominant else 0.0
    dominant_area = float(dominant["area"]) if dominant else 0.0
    dominant_width = float(dominant["width_bp"]) if dominant else 0.0
    dominant_symmetry = float(dominant["symmetry"]) if dominant else 0.0
    shoulder_count = 0
    if dominant:
        shoulder_radius = max(5.0, 2.0 * dominant_width)
        shoulder_count = sum(
            1
            for row in peak_rows
            if row is not dominant
            and abs(float(row["bp"]) - float(dominant["bp"])) <= shoulder_radius
            and float(row["height"]) >= 0.2 * dominant_height
        )

    outside_area = max(0.0, analysis_area - reference_area - nonspecific_area)
    width_for_density = max(configured_width, 1e-9)
    coverage = min(1.0, covered_width / width_for_density) if configured_width > 0 else 0.0
    max_raw = float(np.max(analysis_y)) if analysis_y.size else 0.0
    clipped_fraction = (
        float(np.mean(analysis_y >= 0.995 * max_raw)) if max_raw > 0 else 0.0
    )
    signal_to_noise = dominant_height / max(noise, 1e-9) if dominant_height > 0 else 0.0
    return {
        "trace_point_count_per_channel": int(analysis_bp.size),
        "trace_reference_point_count_per_channel": int(reference_point_count),
        "trace_reference_coverage_per_channel": float(coverage),
        "trace_peak_count_raw_per_channel": int(len(peak_rows)),
        "trace_dominant_height_raw_per_channel": dominant_height,
        "trace_second_height_raw_per_channel": second_height,
        "trace_dominant_height_share_raw_per_channel": (
            dominant_height / height_sum if height_sum > 0 else 0.0
        ),
        "trace_total_area_raw_per_channel": float(reference_area),
        "trace_dominant_area_raw_per_channel": dominant_area,
        "trace_dominant_area_share_raw_per_channel": (
            dominant_area / reference_area if reference_area > 0 else 0.0
        ),
        "trace_noise_mad_raw_per_channel": float(noise),
        "trace_baseline_raw_per_channel": float(baseline),
        "trace_baseline_drift_raw_per_channel": float(drift),
        "trace_baseline_drift_normalized_per_channel": float(drift_normalized),
        "trace_outside_window_area_share_per_channel": (
            outside_area / analysis_area if analysis_area > 0 else 0.0
        ),
        "trace_nonspecific_area_share_per_channel": (
            nonspecific_area / analysis_area if analysis_area > 0 else 0.0
        ),
        "trace_peak_spacing_mean_bp_per_channel": (
            float(np.mean(spacings)) if spacings.size else 0.0
        ),
        "trace_peak_spacing_min_bp_per_channel": (
            float(np.min(spacings)) if spacings.size else 0.0
        ),
        "trace_peak_spacing_std_bp_per_channel": (
            float(np.std(spacings)) if spacings.size else 0.0
        ),
        "trace_dominant_width_bp_per_channel": dominant_width,
        "trace_dominant_width_fraction_per_channel": (
            dominant_width / width_for_density if dominant_width > 0 else 0.0
        ),
        "trace_dominant_symmetry_per_channel": dominant_symmetry,
        "trace_shoulder_count_per_channel": int(shoulder_count),
        "trace_multi_peak_density_per_100bp_per_channel": (
            100.0 * len(peak_rows) / width_for_density
        ),
        "trace_signal_to_noise_per_channel": float(signal_to_noise),
        "trace_clipped_point_fraction_per_channel": clipped_fraction,
    }


def _segment_peaks(
    bp: np.ndarray,
    corrected: np.ndarray,
    *,
    noise: float,
) -> list[dict[str, float]]:
    if bp.size < 3 or not np.any(corrected > 0):
        return []
    max_signal = float(np.max(corrected))
    median_step = float(np.median(np.diff(bp))) if bp.size > 1 else 1.0
    median_step = max(abs(median_step), 1e-6)
    height_threshold = max(4.0 * noise, 0.025 * max_signal)
    prominence_threshold = max(3.0 * noise, 0.02 * max_signal)
    min_distance = max(1, int(round(0.8 / median_step)))
    peaks, _properties = find_peaks(
        corrected,
        height=height_threshold,
        prominence=prominence_threshold,
        distance=min_distance,
    )
    if peaks.size == 0:
        return []

    widths, _height, left_ips, right_ips = peak_widths(
        corrected,
        peaks,
        rel_height=0.5,
    )
    rows: list[dict[str, float]] = []
    sample_index = np.arange(bp.size, dtype=float)
    for ordinal, peak_index in enumerate(peaks):
        left_index = float(left_ips[ordinal])
        right_index = float(right_ips[ordinal])
        left_bp = float(np.interp(left_index, sample_index, bp))
        right_bp = float(np.interp(right_index, sample_index, bp))
        lo = max(0, int(math.floor(left_index)))
        hi = min(bp.size, int(math.ceil(right_index)) + 1)
        peak_bp = float(bp[peak_index])
        left_mask = (bp[lo:hi] >= left_bp) & (bp[lo:hi] <= peak_bp)
        right_mask = (bp[lo:hi] >= peak_bp) & (bp[lo:hi] <= right_bp)
        local_bp = bp[lo:hi]
        local_y = corrected[lo:hi]
        area = _integrate(local_bp, local_y)
        left_area = _integrate(local_bp[left_mask], local_y[left_mask])
        right_area = _integrate(local_bp[right_mask], local_y[right_mask])
        symmetry = (
            min(left_area, right_area) / max(left_area, right_area)
            if max(left_area, right_area) > 0
            else 0.0
        )
        rows.append(
            {
                "bp": peak_bp,
                "height": float(corrected[peak_index]),
                "area": float(area),
                "width_bp": max(0.0, right_bp - left_bp),
                "symmetry": float(symmetry),
                "width_samples": float(widths[ordinal]),
            }
        )
    return rows


def _baseline_and_noise(values: np.ndarray) -> tuple[float, float]:
    finite = np.asarray(values[np.isfinite(values)], dtype=float)
    if finite.size == 0:
        return 0.0, 0.0
    baseline_pool = finite[finite <= np.percentile(finite, 60.0)]
    if baseline_pool.size == 0:
        baseline_pool = finite
    baseline = float(np.median(baseline_pool))
    mad = float(np.median(np.abs(baseline_pool - baseline)))
    return baseline, 1.4826 * mad


def _baseline_drift(
    bp: np.ndarray,
    values: np.ndarray,
    *,
    signal_scale: float,
) -> tuple[float, float]:
    if bp.size < 8:
        return 0.0, 0.0
    edges = np.linspace(float(bp[0]), float(bp[-1]), 9)
    centers: list[float] = []
    baselines: list[float] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (bp >= lo) & (bp <= hi)
        if mask.sum() < 2:
            continue
        centers.append((lo + hi) / 2.0)
        baselines.append(float(np.percentile(values[mask], 20.0)))
    if len(centers) < 2:
        return 0.0, 0.0
    slope = float(np.polyfit(np.asarray(centers), np.asarray(baselines), 1)[0])
    span = max(float(bp[-1] - bp[0]), 1e-9)
    normalized = slope * span / max(float(signal_scale), 1e-9)
    return slope, normalized


def _analysis_range(
    entry: Mapping[str, Any],
    ranges: Sequence[tuple[float, float]],
    bp: np.ndarray,
) -> tuple[float, float]:
    try:
        lo = float(entry.get("bp_min"))
        hi = float(entry.get("bp_max"))
        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            return lo, hi
    except (TypeError, ValueError):
        pass
    if ranges:
        lo = min(float(start) for start, _end in ranges)
        hi = max(float(end) for _start, end in ranges)
        flank = max(25.0, 0.25 * (hi - lo))
        return lo - flank, hi + flank
    finite = bp[np.isfinite(bp)]
    if finite.size:
        return float(np.min(finite)), float(np.max(finite))
    return 0.0, 1.0


def _trace_channels(
    entry: Mapping[str, Any],
    raw_channels: Mapping[str, Any],
    fsa: Any,
) -> list[str]:
    requested: list[str] = []
    configured = entry.get("trace_channels") or []
    if isinstance(configured, str):
        configured = [configured]
    for value in configured:
        requested.append(str(value))
    peaks_by_channel = entry.get("peaks_by_channel")
    if isinstance(peaks_by_channel, Mapping):
        requested.extend(str(value) for value in peaks_by_channel)
    if not requested:
        requested.extend(
            str(name)
            for name in raw_channels
            if str(name).upper().startswith("DATA")
        )
    size_standard = str(getattr(fsa, "size_standard_channel", "") or "")
    return sorted(
        {
            channel
            for channel in requested
            if channel in raw_channels and channel != size_standard
        }
    )


def _assay_ranges(assay: str) -> list[tuple[float, float]]:
    return [
        (float(lo), float(hi))
        for lo, hi in ASSAY_REFERENCE_RANGES.get(_assay_name(assay), [])
    ]


def _assay_name(assay: str) -> str:
    key = _assay_key(assay)
    for name in set(ASSAY_REFERENCE_RANGES) | set(NONSPECIFIC_PEAKS):
        if _assay_key(name) == key:
            return name
    return str(assay or "")


def _assay_key(assay: str) -> str:
    return str(assay or "").replace(" ", "").replace("-", "").replace("_", "").upper()


def _nonspecific_mask(bp: np.ndarray, nonspecific_bps: Sequence[float]) -> np.ndarray:
    mask = np.zeros(bp.shape, dtype=bool)
    for target in nonspecific_bps:
        mask |= np.abs(bp - float(target)) <= NONSPECIFIC_HALF_WIDTH_BP
    return mask


def _integrate(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2 or y.size < 2:
        return 0.0
    widths = np.diff(x)
    values = 0.5 * (y[:-1] + y[1:])
    valid = np.isfinite(widths) & np.isfinite(values) & (widths >= 0)
    return float(np.sum(widths[valid] * values[valid]))


def _empty_channel_features(*, point_count: int = 0) -> dict[str, float | int]:
    result: dict[str, float | int] = {
        field: 0.0 for field in PER_CHANNEL_TRACE_FIELDS
    }
    result["trace_point_count_per_channel"] = int(point_count)
    result["trace_reference_point_count_per_channel"] = 0
    result["trace_peak_count_raw_per_channel"] = 0
    result["trace_shoulder_count_per_channel"] = 0
    return result


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (bool, np.bool_)):
        return float(bool(value))
    if not isinstance(value, (int, float, np.integer, np.floating)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


__all__ = [
    "NONSPECIFIC_HALF_WIDTH_BP",
    "PER_CHANNEL_TRACE_FIELDS",
    "TRACE_FEATURE_SCHEMA_VERSION",
    "flatten_numeric_features",
    "raw_trace_shape_features",
]
