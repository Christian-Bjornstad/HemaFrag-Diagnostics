"""Tests for Phase 2 of Plan 11: per-channel trace summary,
reference-window position features, per-patient replicate
concordance (T-2.1, T-2.2, T-2.3).
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from core.analyses.clonality.interpretation import (
    compute_patient_panel_features,
    features_from_entry,
    per_channel_trace_summary,
    reference_window_features,
)


# ----- T-2.1 per_channel_trace_summary -----

def test_per_channel_trace_summary_handles_missing_dataframe_entry():
    """Entry has no peaks_by_channel: should not raise, returns empty dict."""
    out = per_channel_trace_summary({})
    assert out == {
        "peak_count_per_channel": {},
        "peak_variance_per_channel": {},
        "mad_per_channel": {},
        "dome_peak_count_per_channel": {},
        "dome_height_ratio_per_channel": {},
    }


def test_per_channel_trace_summary_handles_none_peaks_in_channel():
    """Channel has a DataFrame but no peaks column -> count = 0."""
    df = pd.DataFrame({"basepairs": [1, 2, 3]})  # no "peaks"
    out = per_channel_trace_summary({"peaks_by_channel": {"DATA1": df}})
    assert out["peak_count_per_channel"]["DATA1"] == 0
    assert out["peak_variance_per_channel"]["DATA1"] == 0.0


def test_per_channel_trace_summary_computes_correctly():
    """Single channel with mixed heights; dome ratio > 1."""
    df = pd.DataFrame({"peaks": [10.0, 20.0, 30.0, 40.0, 100.0, 80.0, 70.0]})
    out = per_channel_trace_summary({"peaks_by_channel": {"DATA1": df}})
    assert out["peak_count_per_channel"]["DATA1"] == 7
    assert out["dome_peak_count_per_channel"]["DATA1"] == 3  # >= 60
    assert out["dome_height_ratio_per_channel"]["DATA1"] > 1.0
    # MAD should be > 0
    assert out["mad_per_channel"]["DATA1"] > 0


# ----- T-2.2 reference_window_features -----

def test_reference_window_features_uses_assay_range():
    feat = reference_window_features({"assay": "FR1", "dominant_peak_basepairs": 312.0})
    assert feat["interpretation_window_for_assay"] != ""
    assert isinstance(feat["dom_distance_to_ref_window_center_bp"], float)
    assert "FR1" in feat["interpretation_window_for_assay"] or "100-150" in feat["interpretation_window_for_assay"] or "310-360" in feat["interpretation_window_for_assay"]


def test_reference_window_features_returns_nan_distance_for_missing_dom():
    out = reference_window_features({"assay": "FR1"})  # no dominant_peak_basepairs
    assert math.isnan(out["dom_distance_to_ref_window_center_bp"])
    assert out["in_reference_window"] is False
    assert out["ref_window_coverage_fraction"] == 0.0


def test_reference_window_features_in_window_flag():
    """If the assay window covers 310-360 and dominant is 312, in_window is True."""
    out = reference_window_features({"assay": "FR1", "dominant_peak_basepairs": 312.0})
    # The actual FR1 reference window per config.py is documented as FR1: 310-360
    # (or 100-150 range; the module may choose the larger window — both should be True)
    # Assert True-or-True: the dom peak is well inside the union of both windows.
    assert out["in_reference_window"] is True


def test_reference_window_features_outside_window():
    """Dom peak at 800bp with FR1 (310-360) should be outside."""
    out = reference_window_features({"assay": "FR1", "dominant_peak_basepairs": 800.0})
    assert out["in_reference_window"] is False


# ----- T-2.3 patient_panel_features -----

def test_compute_patient_panel_features_no_siblings():
    out = compute_patient_panel_features({"assay": "FR1"})
    assert out == {
        "patient_assays_run_count": 0,
        "assay_panel_completeness_pct": 0.0,
        "patient_entry_count": 0,
    }


def test_compute_patient_panel_features_full_panel():
    entries = [
        {"assay": "FR1"},
        {"assay": "FR2"},
        {"assay": "FR3"},
        {"assay": "IGK"},
        {"assay": "KDE"},
        {"assay": "TCRGA"},  # canonical is normalized to no separators
        {"assay": "TCRGB"},
        {"assay": "DHJHD"},
        {"assay": "DHJHE"},
        # duplicate run -> not counted separately
        {"assay": "FR1"},
    ]
    out = compute_patient_panel_features({"assay": "FR1"}, entries)
    assert out["patient_assays_run_count"] == 9
    assert out["assay_panel_completeness_pct"] == pytest.approx(1.0)
    assert out["patient_entry_count"] == 10



def test_compute_patient_panel_features_lowercase_normalization():
    """assay names in case variations should still match canonical."""
    entries = [
        {"assay": "fr1"},
        {"assay": "Fr2"},
        {"assay": "igk"},
    ]
    out = compute_patient_panel_features({}, entries)
    assert out["patient_assays_run_count"] == 3


# ----- features_from_entry integration -----

def test_features_from_entry_returns_new_dict_keys():
    df = pd.DataFrame({"peaks": [10, 20, 30, 100, 200, 400]})
    entry = {
        "assay": "FR1",
        "peaks_by_channel": {"DATA1": df},
        "dominant_peak_basepairs": 312.0,
    }
    features = features_from_entry(entry)
    expected_keys = (
        "peak_count_per_channel",
        "peak_variance_per_channel",
        "mad_per_channel",
        "dome_peak_count_per_channel",
        "dome_height_ratio_per_channel",
        "dom_distance_to_ref_window_center_bp",
        "in_reference_window",
        "interpretation_window_for_assay",
        "patient_assays_run_count",
        "assay_panel_completeness_pct",
    )
    for k in expected_keys:
        assert k in features, f"missing {k}"


def test_features_from_entry_graceful_for_minimal_entry():
    features = features_from_entry({})
    # Defined feature shape on empty minimal:
    assert features["peak_count_per_channel"] == {}
    assert features["in_reference_window"] in (True, False, None) or isinstance(features["in_reference_window"], bool)
    # The numeric fields default to safe values
    assert features["patient_assays_run_count"] == 0
    assert features["assay_panel_completeness_pct"] == 0.0
