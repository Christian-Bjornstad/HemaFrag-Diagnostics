"""WT-to-mutant fragment distance helpers for FLT3/NPM1 reporting."""
from __future__ import annotations

import math
from typing import Iterable


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_bp_distance_metrics(
    wt_bps: Iterable[object] | None,
    mutant_bps: Iterable[object] | None,
    *,
    wt_channels: Iterable[object] | None = None,
    mutant_channels: Iterable[object] | None = None,
    fallback_wt_bp: object = None,
) -> list[dict[str, object]]:
    """Pair each mutant with its channel WT and calculate codon-frame metrics.

    Fragment sizing is not perfectly integral, so divisibility by three is
    evaluated on the nearest whole base pair while retaining the measured
    floating-point distance for display and export.
    """
    valid_wts = [value for value in (_finite_float(v) for v in (wt_bps or [])) if value is not None]
    valid_mutants = [value for value in (_finite_float(v) for v in (mutant_bps or [])) if value is not None]
    fallback = _finite_float(fallback_wt_bp)
    if not valid_wts and fallback is not None:
        valid_wts = [fallback]
    if not valid_wts or not valid_mutants:
        return []

    wt_channel_values = list(wt_channels or [])
    mutant_channel_values = list(mutant_channels or [])
    wt_by_channel: dict[str, float] = {}
    for index, wt_bp in enumerate(valid_wts):
        if index < len(wt_channel_values) and wt_channel_values[index]:
            wt_by_channel[str(wt_channel_values[index])] = wt_bp

    metrics: list[dict[str, object]] = []
    for index, mutant_bp in enumerate(valid_mutants):
        channel = str(mutant_channel_values[index]) if index < len(mutant_channel_values) and mutant_channel_values[index] else ""
        wt_bp = wt_by_channel.get(channel, valid_wts[0])
        delta_bp = mutant_bp - wt_bp
        rounded_delta_bp = int(round(delta_bp))
        divisible_by_3 = rounded_delta_bp % 3 == 0
        metrics.append(
            {
                "wt_bp": wt_bp,
                "mutant_bp": mutant_bp,
                "channel": channel,
                "delta_bp": delta_bp,
                "rounded_delta_bp": rounded_delta_bp,
                "codon_distance": rounded_delta_bp / 3.0,
                "divisible_by_3": divisible_by_3,
                "frame_remainder": abs(rounded_delta_bp) % 3,
            }
        )
    return metrics


def calculate_entry_bp_distance_metrics(entry: dict) -> list[dict[str, object]]:
    """Calculate metrics from the normalized peak selections on an entry."""
    wt_bps = entry.get("selected_wt_bps") or []
    mutant_bps = entry.get("selected_mutant_bps") or []
    return calculate_bp_distance_metrics(
        wt_bps,
        mutant_bps,
        wt_channels=entry.get("selected_wt_channels") or [],
        mutant_channels=entry.get("selected_mutant_channels") or [],
        fallback_wt_bp=entry.get("selected_wt_bp"),
    )
