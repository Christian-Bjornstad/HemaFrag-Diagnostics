"""IGHV detection must use raw scan positions from a bounded sizing domain."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def _partial_ighv_fsa():
    from core.analysis import apply_manual_ladder_mapping

    steps = np.array([50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600], dtype=float)
    trace = np.zeros(1000)
    trace[358:363] = [6000, 8000, 10000, 8000, 6000]
    # Large peaks outside the bounded domain must never enter the results.
    trace[60] = 30000
    trace[700] = 40000
    fsa = SimpleNamespace(
        ladder="ROX400HD", file_name="IGHV.fsa", expected_ladder_steps=steps.copy(),
        ladder_steps=steps.copy(), size_standard_peaks=np.array([300, 400, 500], dtype=float),
        size_standard=np.zeros(1000), sample_data=trace, fitted_to_model=False,
        fsa={"DATA1": trace},
    )
    return apply_manual_ladder_mapping(
        fsa,
        {"mapping_times": {5: 300, 6: 400, 7: 500}, "review": {"partial_approved": True}},
    )


def test_ighv_detection_aligns_bounded_basepairs_with_observed_scans(monkeypatch):
    import core.area
    from core import ighv

    fsa = _partial_ighv_fsa()
    area_calls = []

    def integrate_selected_scans(signal, times, bp, center_bp, window_bp):
        area_calls.append((signal.copy(), bp.copy()))
        return float(signal[(bp >= center_bp - window_bp) & (bp <= center_bp + window_bp)].sum())

    monkeypatch.setattr(core.area, "compute_peak_area_gaussian", integrate_selected_scans)
    peaks = ighv.detect_clonal_peaks(fsa, "IGHV Mix 2")
    assert len(peaks) == 1
    assert peaks[0]["bp"] == pytest.approx(330.0)
    assert peaks[0]["height"] == 10000
    assert peaks[0]["area"] == 38000
    signal, bp = area_calls[0]
    assert signal[60] == 10000
    assert bp[60] == pytest.approx(330.0)
    assert signal.max() == 10000


def test_ighv_pipeline_uses_the_same_bounded_scan_alignment(tmp_path, monkeypatch):
    from core import ighv
    from core.analyses.clonality import pipeline

    fsa = _partial_ighv_fsa()
    source = tmp_path / "IGHV.fsa"
    fsa.file = str(source)
    monkeypatch.setattr(
        pipeline, "classify_fsa",
        lambda _path: ("IGHV Mix 2", "patient", "ROX", ["DATA1"], ["DATA1"], "DATA1", 300, 400),
    )
    monkeypatch.setattr(pipeline, "analyse_fsa_rox", lambda *_args, **_kwargs: fsa)
    monkeypatch.setattr(pipeline, "compute_zoom_ymax", lambda *_args, **_kwargs: 10000)
    monkeypatch.setattr(pipeline, "_build_tracking_marker_results", lambda **_kwargs: ({}, {}, {}))
    monkeypatch.setattr(pipeline, "attach_interpretation_if_enabled", lambda entry, **_kwargs: entry)
    monkeypatch.setattr(ighv, "_peak_area_near", lambda *_args, **_kwargs: 38000)
    result = pipeline._analyze_single_file(Path(source))
    peaks = result["peaks_by_channel"]["DATA1"]
    assert len(peaks) == 1
    assert peaks.iloc[0]["basepairs"] == pytest.approx(330.0)
    assert peaks.iloc[0]["peaks"] == 10000
    assert result["ighv_clonal_peaks"][0]["bp"] == pytest.approx(330.0)


def test_ighv_trace_alignment_ignores_invalid_or_outside_domain_scan_rows():
    import pandas as pd

    from core.ighv import _trace_arrays

    fsa = SimpleNamespace(
        fsa={"DATA1": np.array([100, 200, 300, 400])},
        sample_data_with_basepairs=pd.DataFrame({
            "time": [-1, 1, 3, 4, np.nan], "basepairs": [10, 20, 30, 40, 50],
        }),
    )
    signal, bp = _trace_arrays(fsa)
    np.testing.assert_array_equal(signal, [200, 400])
    np.testing.assert_array_equal(bp, [20, 30])
