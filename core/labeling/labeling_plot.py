"""Build display-only, base-pair calibrated traces for clonality labeling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from core.analyses.clonality.config import ASSAY_CONFIG
from core.analyses.clonality.interpretation import assay_interpretation_ranges


@dataclass(frozen=True)
class LabelingTrace:
    channel: str
    basepairs: np.ndarray
    rfu: np.ndarray


@dataclass(frozen=True)
class LabelingPeak:
    channel: str
    basepair: float
    rfu: float
    kept: bool


@dataclass(frozen=True)
class LabelingPlotData:
    assay: str
    traces: tuple[LabelingTrace, ...]
    peaks: tuple[LabelingPeak, ...]
    interpretation_ranges: tuple[tuple[float, float], ...]
    bp_min: float
    bp_max: float
    ladder_qc_status: str


def build_labeling_plot_data(entry: Mapping) -> LabelingPlotData:
    """Convert one analyzed clonality entry into a GUI-safe plot model."""
    assay = str(entry.get("assay") or "")
    fsa = entry.get("fsa")
    mapping = getattr(fsa, "sample_data_with_basepairs", None)
    raw_channels = getattr(fsa, "fsa", None)
    if not isinstance(mapping, pd.DataFrame) or mapping.empty:
        raise ValueError("The analyzed FSA has no base-pair calibration.")
    if not {"time", "basepairs"}.issubset(mapping.columns):
        raise ValueError("The analyzed FSA calibration is missing time/basepairs.")
    if not isinstance(raw_channels, Mapping):
        raise ValueError("The analyzed FSA has no channel traces.")

    time = pd.to_numeric(mapping["time"], errors="coerce").to_numpy(dtype=float)
    basepairs = pd.to_numeric(mapping["basepairs"], errors="coerce").to_numpy(dtype=float)
    valid_mapping = np.isfinite(time) & np.isfinite(basepairs)
    if not np.any(valid_mapping):
        raise ValueError("The analyzed FSA has no finite base-pair calibration.")
    time = time[valid_mapping].astype(int)
    basepairs = basepairs[valid_mapping]

    config = ASSAY_CONFIG.get(assay, {})
    bp_min = _finite_float(entry.get("bp_min"), config.get("bp_min"))
    bp_max = _finite_float(entry.get("bp_max"), config.get("bp_max"))
    if bp_min is None:
        bp_min = float(np.nanmin(basepairs))
    if bp_max is None:
        bp_max = float(np.nanmax(basepairs))
    if bp_max <= bp_min:
        raise ValueError(f"Invalid base-pair plot range: {bp_min:g}-{bp_max:g}.")
    reference_bp_min = float(bp_min)
    reference_bp_max = float(bp_max)
    display_margin = max(20.0, (reference_bp_max - reference_bp_min) * 0.08)
    display_bp_min = max(float(np.nanmin(basepairs)), reference_bp_min - display_margin)
    display_bp_max = min(float(np.nanmax(basepairs)), reference_bp_max + display_margin)

    configured_channels = entry.get("trace_channels") or config.get("trace_channels") or []
    if isinstance(configured_channels, str):
        configured_channels = [configured_channels]

    traces: list[LabelingTrace] = []
    window = (basepairs >= display_bp_min) & (basepairs <= display_bp_max)
    for channel_value in configured_channels:
        channel = str(channel_value)
        raw_trace = raw_channels.get(channel)
        if raw_trace is None:
            continue
        trace = np.asarray(raw_trace, dtype=float)
        valid = window & (time >= 0) & (time < trace.size)
        if not np.any(valid):
            continue
        x = basepairs[valid]
        y = trace[time[valid]]
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            continue
        traces.append(
            LabelingTrace(
                channel=channel,
                basepairs=x[finite],
                rfu=y[finite],
            )
        )
    if not traces:
        raise ValueError("No configured assay traces overlap the calibrated range.")

    peaks: list[LabelingPeak] = []
    peaks_by_channel = entry.get("peaks_by_channel")
    if isinstance(peaks_by_channel, Mapping):
        for channel_value, frame in peaks_by_channel.items():
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            if not {"basepairs", "peaks"}.issubset(frame.columns):
                continue
            for _, row in frame.iterrows():
                peak_bp = _finite_float(row.get("basepairs"))
                peak_rfu = _finite_float(row.get("peaks"))
                if peak_bp is None or peak_rfu is None:
                    continue
                if not display_bp_min <= peak_bp <= display_bp_max:
                    continue
                peaks.append(
                    LabelingPeak(
                        channel=str(channel_value),
                        basepair=peak_bp,
                        rfu=peak_rfu,
                        kept=_as_bool(row.get("keep"), default=True),
                    )
                )

    ranges = tuple(
        (max(reference_bp_min, float(start)), min(reference_bp_max, float(end)))
        for start, end in assay_interpretation_ranges(assay)
        if min(reference_bp_max, float(end)) > max(reference_bp_min, float(start))
    )
    return LabelingPlotData(
        assay=assay,
        traces=tuple(traces),
        peaks=tuple(peaks),
        interpretation_ranges=ranges,
        bp_min=display_bp_min,
        bp_max=display_bp_max,
        ladder_qc_status=str(entry.get("ladder_qc_status") or "unknown"),
    )


def _finite_float(value, fallback=None) -> float | None:
    for candidate in (value, fallback):
        try:
            result = float(candidate)
        except (TypeError, ValueError):
            continue
        if np.isfinite(result):
            return result
    return None


def _as_bool(value, *, default: bool) -> bool:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "ja"}:
            return True
        if normalized in {"false", "0", "no", "nei"}:
            return False
    return bool(value)
