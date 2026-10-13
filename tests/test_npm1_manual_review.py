from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.analyses.flt3.pipeline import _legacy as pipeline


def npm1_entry():
    scans = np.arange(800)
    trace = np.zeros(800)
    trace[400] = 2000
    trace[404] = 500
    fsa = SimpleNamespace(
        file_name="26OUM00001_NPM1.fsa", ladder="GS500ROX", fsa={"DATA3": trace},
        sample_data_with_basepairs=pd.DataFrame({"time": scans, "basepairs": scans - 100.0, "peaks": trace}),
        ladder_steps=np.array([35, 50, 75, 100, 150, 200, 250, 300, 350, 400, 450, 500.0]),
        best_size_standard=np.array([135, 150, 175, 200, 250, 300, 350, 400, 450, 500, 550, 600.0]),
        ladder_model=SimpleNamespace(predict=lambda t: np.asarray(t).ravel() - 100),
        size_standard=np.zeros(800), size_standard_peaks=np.array([135, 150, 175]),
        fitted_to_model=True, ladder_fit_strategy="auto_full", ladder_review_required=False,
    )
    return {
        "fsa": fsa, "assay": "NPM1", "group": "sample", "primary_peak_channel": "DATA3",
        "trace_channels": ["DATA3"], "bp_min": 280, "bp_max": 320,
        "peaks_by_channel": {"DATA3": pd.DataFrame([
            {"peak_id": "wt", "label": "WT", "basepairs": 300.5, "peaks": 2000, "area": 20000, "keep": True},
            {"peak_id": "mut", "label": "MUT", "basepairs": 304.5, "peaks": 500, "area": 5000, "keep": True},
        ])},
        "ratio": 0.25, "ratio_numerator_area": 5000, "ratio_denominator_area": 20000,
        "mutant_fraction": 0.2, "selected_wt_bp": 300.5, "selected_mutant_bps": [304.5],
        "manual_ratio_selection": {"enabled": True, "wt": {"peak_id": "wt"}, "mutants": [{"peak_id": "mut"}]},
    }


@pytest.mark.parametrize("group", ["sample", "reactive_control", "negative_control"])
def test_npm1_never_detects_sample_peaks_automatically(group, monkeypatch, tmp_path):
    entry = npm1_entry()
    fsa = entry["fsa"]
    fsa.file = str(tmp_path / fsa.file_name)
    fsa.rust_flt3_preview = {"assay_name": "NPM1", "positive_call": True, "wt_peak": {"basepair": 300.5}}
    monkeypatch.setattr(pipeline, "_analyse_fsa_candidate", lambda *_args: fsa)

    def forbidden(*_args, **_kwargs):
        pytest.fail("NPM1 invoked automatic sample-peak detection")

    monkeypatch.setattr(pipeline, "_build_peaks_from_rust_flt3_preview", forbidden)
    monkeypatch.setattr(pipeline, "_detect_peaks", forbidden)
    meta = {
        "assay": "NPM1", "primary_peak_channel": "DATA3", "trace_channels": ["DATA3"],
        "peak_channels": ["DATA3"], "wt_bp": 300, "mut_bp": 304, "group": group,
        "analysis_type": "standard", "bp_min": 280, "bp_max": 320, "injection_time": 3,
    }
    result = pipeline._build_entry_from_candidate(tmp_path / fsa.file_name, meta)
    assert result["peaks_by_channel"]["DATA3"].empty
    assert result["ratio_mode"] == "not_applicable"
    assert np.isnan(result["ratio"])
    assert result["peak_qc_status"] == "manual_selection_required"


def test_npm1_discards_ratio_and_diagnosis_even_with_stale_selected_peaks(monkeypatch):
    entry = npm1_entry()
    monkeypatch.setattr(pipeline, "_resolve_auto_ratio_selection", lambda *_args: pytest.fail("automatic ratio"))
    pipeline._calculate_ratios([entry])
    for name in ("ratio", "mutant_fraction", "ratio_numerator_area", "ratio_denominator_area"):
        assert np.isnan(entry[name])
    assert entry["ratio_mode"] == "not_applicable"
    assert entry["selected_wt_peak_ids"] == []
    assert entry["selected_mutant_peak_ids"] == []
    assert pipeline._interpret_entry(entry) == ""
    summary = pipeline._summarize_detected_peaks(entry)
    assert np.isnan(summary["wt_bp"])
    assert summary["mut_bps"] == []
    assert summary["bp_distance_metrics"] == []


def test_npm1_tracking_has_no_ratio_or_automatic_result():
    entry = npm1_entry()
    entry.update({"dit": "26OUM00001", "specimen_id": "26OUM00001", "ladder_qc_status": "ok"})
    runs, _peaks = pipeline._build_flt3_npm1_tracker_frames([entry])
    row = runs.iloc[0]
    for column in ("WT_BP", "WT_Area", "MutantBPs", "MutantAreaTotal", "Ratio", "PositiveCall", "MutantFraction"):
        assert pd.isna(row[column]) or row[column] == ""
    assert row["ResultStatus"] == "manual_peak_selection_required"
    assert row["Interpretation"] == ""


def test_npm1_control_status_requires_manual_review():
    entry = npm1_entry()
    entry["group"] = "negative_control"
    result = pipeline._build_control_qc_row(entry)
    assert result["Status"] == "MANUAL_REVIEW"
    assert np.isnan(result["Ratio"])


def test_npm1_config_matches_operator_selected_ranges():
    from core.analyses.flt3.config import ASSAY_CONFIG, ASSAY_REFERENCE_RANGES

    assert ASSAY_CONFIG["NPM1"]["bp_min"] == 280
    assert ASSAY_CONFIG["NPM1"]["bp_max"] == 320
    assert ASSAY_REFERENCE_RANGES["NPM1"] == [(299, 301), (304, 306)]
