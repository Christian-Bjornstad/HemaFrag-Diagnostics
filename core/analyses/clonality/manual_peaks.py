"""Fresh raw sample peaks for a manually remapped clonality sizing domain.

Mirror the existing Rust sample-preview rules in ``fraggler-core/src/signal.rs``
(``find_peaks`` / ``describe_peak_shape`` / ``peak_score``) and ``primitives.rs``
(``estimate_sample_peak_min_height`` / ``build_sample_peak_preview``). The native
binding cannot accept a manual domain. This path retains those detection rules,
but joins raw scan indices to the current domain rather than old Rust sizes or
groups. It does not assign clonality calls; existing interpretation handles that.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

PEAK_COLUMNS = ["time", "basepairs", "peaks", "area", "keep"]


def _raw_sample_peaks(trace: np.ndarray) -> list[tuple[int, float, float, float]]:
    positives = np.sort(trace[trace > 0])
    threshold = (
        max(25.0, float(positives[-1]) * 0.05, float(positives[len(positives) // 2]) * 3.0)
        if positives.size else 1.0
    )
    candidates = []
    for index in np.flatnonzero((trace[1:-1] >= threshold) & (trace[1:-1] >= trace[:-2]) & (trace[1:-1] > trace[2:])) + 1:
        height = float(trace[index])
        left_min = right_min = height
        for value in trace[index - 1::-1]:
            left_min = min(left_min, float(value))
            if value > height:
                break
        for value in trace[index + 1:]:
            right_min = min(right_min, float(value))
            if value > height:
                break
        baseline = max(left_min, right_min)
        prominence = max(0.0, height - baseline)
        half = baseline + prominence * 0.5
        left = right = int(index)
        while left > 0 and trace[left - 1] > half:
            left -= 1
        while right + 1 < trace.size and trace[right + 1] > half:
            right += 1
        width = right - left + 1
        purity = np.clip(prominence / max(height, 1.0), 0, 1.25)
        width_term = np.sqrt(min(width, 8)) / (1.0 + 0.1 * max(width - 8, 0))
        penalty = 1.0 / (1.0 + 1.6 * np.clip(max(baseline, 0) / max(height, 1), 0, 1.5))
        score = prominence * width_term * (0.55 + 0.95 * purity) * penalty + height * 0.08
        candidates.append((int(index), height, prominence, width, float(score)))
    candidates.sort(key=lambda peak: (-peak[4], -peak[2], -peak[1], peak[0]))
    accepted = []
    for candidate in candidates:
        if all(abs(candidate[0] - peak[0]) >= 8 for peak in accepted):
            accepted.append(candidate)
    return [(index, height, prominence, width) for index, height, prominence, width, _score in accepted]


def build_manual_clonality_peaks(
    fsa,
    peak_channels: Sequence[str],
    *,
    bp_min: float,
    bp_max: float,
) -> dict[str, pd.DataFrame]:
    """Detect again in raw scan space and report only sizes in the fitted domain."""
    domain = getattr(fsa, "sample_data_with_basepairs", None)
    if domain is None or domain.empty or not {"time", "basepairs"}.issubset(domain.columns):
        raise ValueError("Manual clonality peaks need a current sizing domain.")
    times = domain["time"].to_numpy(dtype=float)
    sizes = domain["basepairs"].to_numpy(dtype=float)
    if (
        not np.isfinite(times).all() or not np.isfinite(sizes).all()
        or np.any(times != np.floor(times)) or np.any(times < 0)
        or np.any(np.diff(times) <= 0) or np.any(np.diff(sizes) <= 0)
    ):
        raise ValueError("Manual clonality sizing domain must have increasing finite scan indices and sizes.")
    if not np.isfinite([bp_min, bp_max]).all() or bp_max < bp_min:
        raise ValueError("Manual clonality assay bounds must be finite and ordered.")
    scans = times.astype(int)
    size_by_scan = dict(zip(scans.tolist(), sizes.tolist()))
    results = {}
    for channel in peak_channels:
        raw = getattr(fsa, "fsa", {}).get(channel)
        if raw is None:
            results[channel] = pd.DataFrame(columns=PEAK_COLUMNS)
            continue
        trace = np.asarray(raw, dtype=float)
        if trace.ndim != 1 or scans[-1] >= trace.size or not np.isfinite(trace).all():
            raise ValueError(f"Channel {channel} does not cover the current sizing domain with a finite raw trace.")
        # Detection uses real raw neighbours even at a mapped endpoint. Joining
        # by actual scan excludes unavailable end steps without extrapolation.
        detected = [peak for peak in _raw_sample_peaks(trace) if peak[0] in size_by_scan]
        detected.sort(key=lambda peak: (-peak[1], size_by_scan[peak[0]]))
        rows = [
            {"time": scan, "basepairs": size_by_scan[scan], "peaks": height,
             "area": round(prominence * width, 2), "keep": True}
            for scan, height, prominence, width in detected[:32]
            if bp_min <= size_by_scan[scan] <= bp_max
        ]
        results[channel] = pd.DataFrame(rows, columns=PEAK_COLUMNS).sort_values("basepairs").reset_index(drop=True)
    return results
