from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analyses.clonality.interpretation import (
    annotation_export_rows_to_frame,
    assay_interpretation_range,
    assay_interpretation_ranges,
    features_from_entry,
    peak_context_for_assay,
    write_rows_csv,
)
from core.analyses.clonality.config import NONSPECIFIC_PEAKS
from core.analyses.clonality.pipeline import _analyze_single_file


TRACE_BIN_COUNT = 32
TRACE_CHANNELS = ("DATA1", "DATA2", "DATA3")
REPLICATE_MATCH_WINDOW_BP = 1.5


def build_trace_feature_rows(annotation_path: Path, out_csv: Path, *, limit: int = 0) -> Path:
    annotations = _read_annotations(annotation_path)
    if annotations.empty:
        return write_rows_csv([], out_csv)

    rows: list[dict[str, Any]] = []
    usable = annotations[annotations.get("raw_path", "").fillna("").astype(str).str.len() > 0].copy()
    if limit and limit > 0:
        usable = usable.head(int(limit))

    for index, row in usable.iterrows():
        raw_path = Path(str(row.get("raw_path") or ""))
        output: dict[str, Any] = {
            "raw_path": str(raw_path),
            "file": str(row.get("file") or raw_path.name),
            "ordinal": int(row.get("ordinal", 0) or 0),
            "patient_id": _patient_id_from_file(str(row.get("file") or raw_path.name)),
            "label": str(row.get("label") or ""),
        }
        try:
            entry = _analyze_single_file(raw_path)
            if not isinstance(entry, dict):
                output["trace_feature_status"] = "analysis_skipped"
            else:
                output.update(features_from_entry(entry))
                output.update(trace_features_from_entry(entry))
                output["replicate_peak_basepairs"] = _interpretation_peak_basepairs_text(entry)
                output["trace_feature_status"] = "ok"
        except Exception as exc:
            output["trace_feature_status"] = f"error:{type(exc).__name__}"
            output["trace_feature_error"] = str(exc)[:300]
        rows.append(output)
        if len(rows) % 25 == 0 or len(rows) == len(usable):
            print(f"trace features {len(rows)}/{len(usable)}", flush=True)

    _attach_replicate_concordance_features(rows)
    return write_rows_csv(rows, out_csv)


def trace_features_from_entry(entry: dict[str, Any]) -> dict[str, float | str]:
    assay = str(entry.get("assay") or "")
    fsa = entry.get("fsa")
    primary_channel = str(entry.get("primary_peak_channel") or "")
    trace_channels = [str(ch) for ch in (entry.get("trace_channels") or []) if str(ch)]
    ranges = assay_interpretation_ranges(assay)
    merged_range = assay_interpretation_range(assay)
    if fsa is None or not primary_channel or not ranges or merged_range is None:
        return _empty_trace_features()

    channels = _trace_channels_for_entry(entry)
    primary = _channel_trace_in_ranges(fsa, primary_channel, ranges, assay=assay)
    union_values = []
    per_channel_values: dict[str, list[float]] = {}
    for channel in channels:
        values = _channel_trace_in_ranges(fsa, channel, ranges, assay=assay)
        per_channel_values[channel] = values
        union_values.extend(values)

    features = _summarize_trace_values(primary, prefix="trace_primary")
    features.update(_summarize_trace_values(union_values, prefix="trace_union"))
    features.update(_binned_trace_values(fsa, primary_channel, ranges, merged_range, prefix="trace_primary_bin", assay=assay))
    for channel in TRACE_CHANNELS:
        values = per_channel_values.get(channel, [])
        prefix = f"trace_{channel}"
        features.update(_summarize_trace_values(values, prefix=prefix))
        features.update(_binned_trace_values(fsa, channel, ranges, merged_range, prefix=f"{prefix}_bin", assay=assay))
    features.update(_channel_contrast_features(per_channel_values))
    features["trace_primary_channel"] = primary_channel
    features["trace_channels_evaluated"] = ",".join(channels)
    features["trace_reference_ranges_bp"] = ";".join(f"{lo:.0f}-{hi:.0f}" for lo, hi in ranges)
    return features


def _trace_channels_for_entry(entry: dict[str, Any]) -> list[str]:
    channels: list[str] = []
    fsa = entry.get("fsa")
    for channel in entry.get("trace_channels") or []:
        text = str(channel or "")
        if text and text not in channels:
            channels.append(text)
    primary = str(entry.get("primary_peak_channel") or "")
    if primary and primary not in channels:
        channels.insert(0, primary)
    if hasattr(fsa, "fsa"):
        for channel in TRACE_CHANNELS:
            if channel in fsa.fsa and channel not in channels:
                channels.append(channel)
    return [channel for channel in channels if channel in TRACE_CHANNELS]


def _read_annotations(path: Path) -> pd.DataFrame:
    path = Path(path).expanduser()
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return annotation_export_rows_to_frame(payload).fillna("")
    return pd.read_csv(path).fillna("")


def _channel_trace_in_ranges(fsa: Any, channel: str, ranges: Iterable[tuple[float, float]], *, assay: str) -> list[float]:
    raw_df = getattr(fsa, "sample_data_with_basepairs", None)
    if raw_df is None or "basepairs" not in raw_df.columns or "time" not in raw_df.columns:
        return []
    if not hasattr(fsa, "fsa") or channel not in fsa.fsa:
        return []
    bp = pd.to_numeric(raw_df["basepairs"], errors="coerce").to_numpy(dtype=float)
    time = pd.to_numeric(raw_df["time"], errors="coerce").to_numpy(dtype=float)
    mask = np.zeros(bp.shape, dtype=bool)
    for lo, hi in ranges:
        mask |= (bp >= float(lo)) & (bp <= float(hi))
    mask &= ~_known_nonspecific_bp_mask(bp, assay)
    trace = np.asarray(fsa.fsa[channel], dtype=float)
    idx = time[mask].astype(int)
    idx = idx[(idx >= 0) & (idx < trace.size)]
    if idx.size == 0:
        return []
    values = trace[idx]
    return [float(value) for value in values if math.isfinite(float(value))]


def _summarize_trace_values(values: Iterable[float], *, prefix: str) -> dict[str, float]:
    arr = np.asarray([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    result = {f"{prefix}_{name}": 0.0 for name in [
        "point_count",
        "raw_min",
        "raw_max",
        "raw_mean",
        "raw_std",
        "raw_p10",
        "raw_p50",
        "raw_p90",
        "raw_p95",
        "baseline_p10",
        "signal_area",
        "signal_max",
        "signal_mean",
        "signal_std",
        "signal_active_fraction",
        "signal_peakiness",
        "local_max_count",
        "local_max_density",
        "entropy",
    ]}
    if arr.size == 0:
        return result
    baseline = float(np.nanpercentile(arr, 10))
    signal = np.maximum(arr - baseline, 0.0)
    signal_sum = float(np.nansum(signal))
    signal_max = float(np.nanmax(signal)) if signal.size else 0.0
    active = signal > (signal_max * 0.1) if signal_max > 0 else np.zeros(signal.shape, dtype=bool)
    local_max_count = _local_max_count(signal, threshold=signal_max * 0.1 if signal_max > 0 else 0.0)
    probabilities = signal / signal_sum if signal_sum > 0 else np.zeros(signal.shape, dtype=float)
    entropy = float(-np.sum(probabilities[probabilities > 0] * np.log2(probabilities[probabilities > 0]))) if signal_sum > 0 else 0.0
    result.update(
        {
            f"{prefix}_point_count": float(arr.size),
            f"{prefix}_raw_min": float(np.nanmin(arr)),
            f"{prefix}_raw_max": float(np.nanmax(arr)),
            f"{prefix}_raw_mean": float(np.nanmean(arr)),
            f"{prefix}_raw_std": float(np.nanstd(arr)),
            f"{prefix}_raw_p10": baseline,
            f"{prefix}_raw_p50": float(np.nanpercentile(arr, 50)),
            f"{prefix}_raw_p90": float(np.nanpercentile(arr, 90)),
            f"{prefix}_raw_p95": float(np.nanpercentile(arr, 95)),
            f"{prefix}_baseline_p10": baseline,
            f"{prefix}_signal_area": signal_sum,
            f"{prefix}_signal_max": signal_max,
            f"{prefix}_signal_mean": float(np.nanmean(signal)),
            f"{prefix}_signal_std": float(np.nanstd(signal)),
            f"{prefix}_signal_active_fraction": float(np.mean(active)) if active.size else 0.0,
            f"{prefix}_signal_peakiness": float(signal_max / np.nanmean(signal)) if np.nanmean(signal) > 0 else 0.0,
            f"{prefix}_local_max_count": float(local_max_count),
            f"{prefix}_local_max_density": float(local_max_count / arr.size) if arr.size else 0.0,
            f"{prefix}_entropy": entropy,
        }
    )
    return result


def _channel_contrast_features(per_channel_values: dict[str, list[float]]) -> dict[str, float]:
    summaries = {
        channel: _summarize_trace_values(values, prefix=f"_tmp_{channel}")
        for channel, values in per_channel_values.items()
    }
    areas = {
        channel: float(summary.get(f"_tmp_{channel}_signal_area", 0.0) or 0.0)
        for channel, summary in summaries.items()
    }
    maxes = {
        channel: float(summary.get(f"_tmp_{channel}_signal_max", 0.0) or 0.0)
        for channel, summary in summaries.items()
    }
    total_area = sum(areas.values())
    total_max = sum(maxes.values())
    result: dict[str, float] = {
        "trace_channel_count": float(len([channel for channel in TRACE_CHANNELS if channel in per_channel_values])),
        "trace_channel_total_signal_area": float(total_area),
        "trace_channel_total_signal_max": float(total_max),
    }
    for channel in TRACE_CHANNELS:
        result[f"trace_{channel}_area_share"] = float(areas.get(channel, 0.0) / total_area) if total_area > 0 else 0.0
        result[f"trace_{channel}_max_share"] = float(maxes.get(channel, 0.0) / total_max) if total_max > 0 else 0.0
    for left, right in (("DATA1", "DATA2"), ("DATA1", "DATA3"), ("DATA2", "DATA3")):
        denominator = areas.get(right, 0.0)
        result[f"trace_{left}_to_{right}_area_ratio"] = float(areas.get(left, 0.0) / denominator) if denominator > 0 else float(areas.get(left, 0.0))
    return result


def _binned_trace_values(
    fsa: Any,
    channel: str,
    ranges: list[tuple[float, float]],
    merged_range: tuple[float, float],
    *,
    prefix: str,
    assay: str,
) -> dict[str, float]:
    result = {f"{prefix}_{idx:02d}": 0.0 for idx in range(TRACE_BIN_COUNT)}
    raw_df = getattr(fsa, "sample_data_with_basepairs", None)
    if raw_df is None or "basepairs" not in raw_df.columns or "time" not in raw_df.columns:
        return result
    if not hasattr(fsa, "fsa") or channel not in fsa.fsa:
        return result
    bp = pd.to_numeric(raw_df["basepairs"], errors="coerce").to_numpy(dtype=float)
    time = pd.to_numeric(raw_df["time"], errors="coerce").to_numpy(dtype=float)
    range_mask = np.zeros(bp.shape, dtype=bool)
    for lo, hi in ranges:
        range_mask |= (bp >= float(lo)) & (bp <= float(hi))
    range_mask &= ~_known_nonspecific_bp_mask(bp, assay)
    trace = np.asarray(fsa.fsa[channel], dtype=float)
    idx = time[range_mask].astype(int)
    valid = (idx >= 0) & (idx < trace.size)
    idx = idx[valid]
    bp_valid = bp[range_mask][valid]
    if idx.size == 0:
        return result
    values = trace[idx]
    baseline = float(np.nanpercentile(values, 10))
    signal = np.maximum(values - baseline, 0.0)
    max_signal = float(np.nanmax(signal)) if signal.size else 0.0
    lo, hi = merged_range
    edges = np.linspace(float(lo), float(hi), TRACE_BIN_COUNT + 1)
    for bin_idx in range(TRACE_BIN_COUNT):
        mask = (bp_valid >= edges[bin_idx]) & (bp_valid < edges[bin_idx + 1])
        if bin_idx == TRACE_BIN_COUNT - 1:
            mask |= bp_valid == edges[bin_idx + 1]
        if np.any(mask):
            value = float(np.nanmax(signal[mask]))
            result[f"{prefix}_{bin_idx:02d}"] = value / max_signal if max_signal > 0 else 0.0
    return result


def _local_max_count(values: np.ndarray, *, threshold: float) -> int:
    if values.size < 3:
        return 0
    center = values[1:-1]
    peaks = (center > values[:-2]) & (center >= values[2:]) & (center > threshold)
    return int(np.sum(peaks))


def _known_nonspecific_bp_mask(bp: np.ndarray, assay: str, *, window_bp: float = 1.5) -> np.ndarray:
    mask = np.zeros(bp.shape, dtype=bool)
    for known_bp in NONSPECIFIC_PEAKS.get(_assay_name(assay), []):
        mask |= np.abs(bp - float(known_bp)) <= float(window_bp)
    return mask


def _assay_name(assay: str) -> str:
    raw = str(assay or "").strip()
    upper = raw.upper().replace("-", "").replace("_", "")
    for name in NONSPECIFIC_PEAKS:
        if upper == name.upper().replace("-", "").replace("_", ""):
            return name
    return raw


def _empty_trace_features() -> dict[str, float | str]:
    result: dict[str, float | str] = {}
    result.update(_summarize_trace_values([], prefix="trace_primary"))
    result.update(_summarize_trace_values([], prefix="trace_union"))
    result.update({f"trace_primary_bin_{idx:02d}": 0.0 for idx in range(TRACE_BIN_COUNT)})
    for channel in TRACE_CHANNELS:
        result.update(_summarize_trace_values([], prefix=f"trace_{channel}"))
        result.update({f"trace_{channel}_bin_{idx:02d}": 0.0 for idx in range(TRACE_BIN_COUNT)})
        result[f"trace_{channel}_area_share"] = 0.0
        result[f"trace_{channel}_max_share"] = 0.0
    result["trace_channel_count"] = 0.0
    result["trace_channel_total_signal_area"] = 0.0
    result["trace_channel_total_signal_max"] = 0.0
    result["trace_DATA1_to_DATA2_area_ratio"] = 0.0
    result["trace_DATA1_to_DATA3_area_ratio"] = 0.0
    result["trace_DATA2_to_DATA3_area_ratio"] = 0.0
    result["trace_primary_channel"] = ""
    result["trace_channels_evaluated"] = ""
    result["trace_reference_ranges_bp"] = ""
    return result


def _interpretation_peak_basepairs_text(entry: dict[str, Any]) -> str:
    peaks = _combined_peak_frame(entry)
    context = peak_context_for_assay(str(entry.get("assay") or ""), peaks)
    frame = context.get("interpretation_peaks")
    if not isinstance(frame, pd.DataFrame) or frame.empty or "basepairs" not in frame.columns:
        return ""
    values = pd.to_numeric(frame["basepairs"], errors="coerce").dropna().to_numpy(dtype=float)
    return ";".join(f"{float(value):.2f}" for value in sorted(values) if math.isfinite(float(value)))


def _combined_peak_frame(entry: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    peaks_by_channel = entry.get("peaks_by_channel") or {}
    if not isinstance(peaks_by_channel, dict):
        return pd.DataFrame()
    for channel, frame in peaks_by_channel.items():
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        copy = frame.copy()
        copy["channel"] = str(channel)
        frames.append(copy)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _attach_replicate_concordance_features(rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        patient_id = str(row.get("patient_id") or "")
        assay = str(row.get("assay") or "")
        if patient_id and assay and str(row.get("sample_kind") or "") == "patient":
            groups.setdefault((patient_id, assay), []).append(row)

    for group_rows in groups.values():
        for row in group_rows:
            own = _parse_bp_list(row.get("replicate_peak_basepairs"))
            peer = []
            for other in group_rows:
                if other is row:
                    continue
                peer.extend(_parse_bp_list(other.get("replicate_peak_basepairs")))
            nearest = [_nearest_distance(bp, peer) for bp in own]
            matched = [distance for distance in nearest if math.isfinite(distance) and distance <= REPLICATE_MATCH_WINDOW_BP]
            discordant = max(0, len(own) - len(matched))
            row["replicate_group_size"] = len(group_rows)
            row["replicate_peer_peak_count"] = len(peer)
            row["replicate_peak_count"] = len(own)
            row["replicate_concordant_peak_count"] = len(matched)
            row["replicate_discordant_peak_count"] = discordant
            row["replicate_concordance_fraction"] = float(len(matched) / len(own)) if own else (1.0 if not peer and len(group_rows) > 1 else 0.0)
            finite_distances = [distance for distance in nearest if math.isfinite(distance)]
            row["replicate_nearest_peer_bp_delta_min"] = float(min(finite_distances)) if finite_distances else 0.0
            row["replicate_nearest_peer_bp_delta_median"] = float(np.median(finite_distances)) if finite_distances else 0.0
            row["replicate_has_bp_shift"] = int(discordant > 0)


def _parse_bp_list(value: Any) -> list[float]:
    result = []
    for token in str(value or "").replace(",", ";").split(";"):
        try:
            number = float(token)
        except ValueError:
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def _nearest_distance(value: float, candidates: list[float]) -> float:
    if not candidates:
        return math.inf
    return float(min(abs(float(value) - float(candidate)) for candidate in candidates))


def _patient_id_from_file(file_name: str) -> str:
    match = re.search(r"\d{2}OUM\d{5}", str(file_name or ""))
    return match.group(0) if match else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build trace-shape feature rows for clonality interpretation training.")
    parser.add_argument("--annotations", type=Path, required=True, help="Annotation JSON/CSV exported from the HTML panel.")
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for smoke testing.")
    args = parser.parse_args()
    out = build_trace_feature_rows(args.annotations.expanduser(), args.out_csv.expanduser(), limit=args.limit)
    print(json.dumps({"trace_feature_rows_csv": str(out)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
