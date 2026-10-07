from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


def _fsa(*, domain_start=100, domain_end=300):
    primary = np.full(500, 10.0)
    secondary = np.full(500, 10.0)
    # Raw maxima at different actual scans, including ones outside sized domain.
    for center, height in [(50, 6000), (120, 1500), (200, 2000), (330, 7000)]:
        primary[center - 1:center + 2] = [height / 2, height, height / 2]
    secondary[240 - 1:240 + 2] = [900, 1800, 900]
    scans = np.arange(domain_start, domain_end + 1)
    return SimpleNamespace(
        fsa={"DATA1": primary, "DATA2": secondary},
        sample_data_with_basepairs=pd.DataFrame({
            "time": scans, "basepairs": 100.0 + (scans - 100) * 0.5,
            "peaks": primary[scans],
        }),
        # These records represent the old automatic ladder and must be ignored.
        rust_clonality_preview={"channel_peak_previews": {"DATA1": [
            {"time": 200, "basepair": 999, "intensity": 2000, "area": 5000},
        ]}},
    )


def test_manual_peaks_use_exact_remapped_scans_and_preserve_channel_identity():
    from core.analyses.clonality.manual_peaks import build_manual_clonality_peaks

    current = _fsa()
    peaks = build_manual_clonality_peaks(current, ["DATA1", "DATA2"], bp_min=90, bp_max=250)
    assert peaks["DATA1"].time.tolist() == [120, 200]
    assert peaks["DATA1"].basepairs.tolist() == [110, 150]
    assert peaks["DATA1"].peaks.tolist() == [1500, 2000]
    assert peaks["DATA1"].area.tolist() == [1490, 1990]
    assert peaks["DATA2"].time.tolist() == [240]
    assert peaks["DATA2"].basepairs.tolist() == [170]
    assert peaks["DATA2"].peaks.tolist() == [1800]
    assert peaks["DATA1"].keep.tolist() == [True, True]
    assert "rust_group_id" not in peaks["DATA1"]


def test_manual_peak_range_filters_use_new_bp_and_never_extrapolate():
    from core.analyses.clonality.manual_peaks import build_manual_clonality_peaks

    current = _fsa(domain_start=120, domain_end=200)
    peaks = build_manual_clonality_peaks(current, ["DATA1", "DATA2"], bp_min=130, bp_max=180)
    assert peaks["DATA1"].time.tolist() == [200]
    assert peaks["DATA1"].basepairs.tolist() == [150]
    assert peaks["DATA2"].empty


def test_manual_peak_detector_keeps_rust_sample_threshold_and_plateau_rule():
    from core.analyses.clonality.manual_peaks import build_manual_clonality_peaks

    current = _fsa()
    trace = np.full(500, 10.0)
    trace[150:153] = [200, 200, 200]  # Rust selects the last plateau point.
    trace[200] = 24.0  # Existing absolute floor is 25 RFU.
    current.fsa = {"DATA1": trace}
    peaks = build_manual_clonality_peaks(current, ["DATA1"], bp_min=0, bp_max=1000)
    assert peaks["DATA1"].time.tolist() == [152]
    assert peaks["DATA1"].area.tolist() == [570]


def test_manual_peak_detector_uses_existing_shape_score_to_resolve_close_peaks():
    from core.analyses.clonality.manual_peaks import build_manual_clonality_peaks

    current = _fsa()
    trace = np.full(500, 10.0)
    trace[150] = 1000.0
    trace[155:158] = 900.0  # Broader lower peak outranks the narrow one, as in Rust.
    current.fsa = {"DATA1": trace}
    peaks = build_manual_clonality_peaks(current, ["DATA1"], bp_min=0, bp_max=1000)
    assert peaks["DATA1"].time.tolist() == [157]
    assert peaks["DATA1"].area.tolist() == [2670]


def test_manual_peak_detector_retains_existing_top_32_preview_limit():
    from core.analyses.clonality.manual_peaks import build_manual_clonality_peaks

    current = _fsa(domain_start=10, domain_end=490)
    trace = np.full(500, 10.0)
    for index in range(10, 491, 10):
        trace[index] = 1000 + index
    current.fsa = {"DATA1": trace}
    peaks = build_manual_clonality_peaks(current, ["DATA1"], bp_min=0, bp_max=1000)
    assert peaks["DATA1"].time.tolist() == list(range(180, 491, 10))


@pytest.mark.parametrize("column,value", [("time", 101.5), ("basepairs", np.nan)])
def test_manual_peak_detector_rejects_invalid_domain_instead_of_using_old_preview(column, value):
    from core.analyses.clonality.manual_peaks import build_manual_clonality_peaks

    current = _fsa()
    current.sample_data_with_basepairs[column] = current.sample_data_with_basepairs[column].astype(float)
    current.sample_data_with_basepairs.loc[0, column] = value
    with pytest.raises(ValueError, match="sizing domain"):
        build_manual_clonality_peaks(current, ["DATA1"], bp_min=0, bp_max=1000)


@pytest.mark.parametrize("usable", [False, True])
def test_clonality_pipeline_uses_fresh_peaks_or_visible_review_after_manual_remap(tmp_path, monkeypatch, usable):
    from core.analyses.clonality import pipeline
    from core.analysis import apply_manual_ladder_mapping

    current = _fsa()
    source = tmp_path / "IGK.fsa"
    source.write_bytes(b"synthetic source identity")
    current.file = str(source)
    current.file_name = source.name
    current.ladder = "LIZ500"
    current.expected_ladder_steps = np.array([50, 100, 150, 200, 250], dtype=float)
    current.ladder_steps = current.expected_ladder_steps.copy()
    current.size_standard_peaks = np.array([100, 200, 300], dtype=float)
    current.size_standard = np.zeros(500)
    current.sample_data = current.fsa["DATA1"]
    current = apply_manual_ladder_mapping(current, {
        "mapping_times": {1: 100, 2: 200, 3: 300}, "review": {"partial_approved": True},
    })
    if not usable:
        current.fsa["DATA2"] = current.fsa["DATA2"][:200]
    monkeypatch.setattr(pipeline, "classify_fsa", lambda _path: (
        "IGK", "patient", "LIZ", ["DATA1", "DATA2"], ["DATA1", "DATA2"], "DATA1", 90, 250,
    ))
    monkeypatch.setattr(pipeline, "analyse_fsa_liz", lambda *_args, **_kwargs: current)
    monkeypatch.setattr(pipeline, "compute_zoom_ymax", lambda *_args, **_kwargs: 7000)
    monkeypatch.setattr(pipeline, "_build_tracking_marker_results", lambda **_kwargs: ({}, {}, {}))
    monkeypatch.setattr(pipeline, "attach_interpretation_if_enabled", lambda entry, **_kwargs: entry)

    result = pipeline._analyze_single_file(source)

    if not usable:
        assert result["analysis_status"] == "ladder_review_only"
        assert result["ladder_qc_status"] == "ladder_qc_failed"
        assert result["ladder_review_required"] is True
        assert "DATA2" in result["ladder_fit_note"]
        assert all(frame.empty for frame in result["peaks_by_channel"].values())
        assert "Interpretation" not in result
        return
    assert result["peaks_by_channel"]["DATA1"].time.tolist() == [120, 200]
    assert result["peaks_by_channel"]["DATA1"].basepairs.tolist() == [110, 150]
    assert result["peaks_by_channel"]["DATA2"].basepairs.tolist() == [170]
    assert result["ladder_fit_strategy"] == "manual_partial"
    assert result["ladder_review_required"] is False
    assert result["rust_preview_top_assay"] == ""
