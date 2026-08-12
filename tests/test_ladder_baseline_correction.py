from types import SimpleNamespace

import numpy as np
import pytest

from core.analysis import (
    baseline_correct_ladder_trace,
    get_ladder_candidates,
    prepare_size_standard_trace,
)


def _negative_drift_ladder() -> tuple[np.ndarray, list[int]]:
    scans = np.arange(1600, dtype=float)
    # The entire raw channel, including every ladder apex, remains below zero.
    raw = -1280.0 + 0.09 * scans + 3.0 * np.sin(scans / 23.0)
    peak_indices = [180, 370, 610, 920, 1260, 1480]
    for index in peak_indices:
        raw[index - 2 : index + 3] += np.array([80.0, 300.0, 650.0, 300.0, 80.0])
    return raw, peak_indices


def test_ladder_baseline_correction_recovers_negative_trace_and_preserves_peaks():
    raw, peak_indices = _negative_drift_ladder()
    assert float(np.max(raw)) < 0.0

    corrected = baseline_correct_ladder_trace(raw)

    assert np.all(np.isfinite(corrected))
    assert float(np.min(corrected)) >= 0.0
    for index in peak_indices:
        assert corrected[index] >= 620.0


def test_prepare_size_standard_trace_keeps_raw_data_for_diagnostics():
    raw, _ = _negative_drift_ladder()
    assert float(np.max(raw)) < 0.0
    fsa = SimpleNamespace(
        size_standard_channel="DATA105",
        fsa={"DATA105": raw.copy()},
        size_standard=raw.copy(),
    )

    prepare_size_standard_trace(fsa)

    assert fsa.size_standard_baseline_corrected is True
    assert fsa.size_standard_baseline_method == "rolling_quantile_peak_preserving"
    assert fsa.size_standard_raw_min < 0.0
    assert fsa.size_standard_raw_negative_fraction > 0.5
    assert np.array_equal(fsa.size_standard_raw, raw)
    assert np.array_equal(fsa.fsa["DATA105"], raw)
    assert float(np.min(fsa.size_standard)) >= 0.0


@pytest.mark.parametrize("channel", ["DATA4", "DATA105"])
def test_ladder_editor_candidates_are_recovered_from_negative_size_standard_trace(channel):
    raw, peak_indices = _negative_drift_ladder()
    assert float(np.max(raw)) < 0.0
    fsa = SimpleNamespace(
        size_standard_channel=channel,
        fsa={channel: raw.copy()},
        size_standard=raw.copy(),
        size_standard_peaks=None,
        min_size_standard_height=150.0,
        min_distance_between_peaks=15,
    )

    candidates = get_ladder_candidates(fsa)

    assert float(np.min(fsa.size_standard)) >= 0.0
    candidate_times = candidates["time"].round().astype(int).tolist()
    for index in peak_indices:
        assert index in candidate_times
