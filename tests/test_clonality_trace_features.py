from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from core.analyses.clonality.interpretation import features_from_entry
from core.analyses.clonality.interpretation import interpret_entry
from core.analyses.clonality.trace_features import (
    PER_CHANNEL_TRACE_FIELDS,
    TRACE_FEATURE_SCHEMA_VERSION,
    flatten_numeric_features,
    raw_trace_shape_features,
)


def _gaussian(bp, center, height, sigma):
    return height * np.exp(-0.5 * ((bp - center) / sigma) ** 2)


def _synthetic_entry():
    bp = np.linspace(50.0, 450.0, 4001)
    time = np.arange(bp.size)
    baseline = 100.0 + 0.03 * (bp - bp.min()) + 3.0 * np.sin(bp / 7.0)
    data1 = (
        baseline
        + _gaussian(bp, 325.0, 1200.0, 0.8)
        + _gaussian(bp, 331.0, 300.0, 0.7)
        + _gaussian(bp, 342.0, 650.0, 1.3)
        + _gaussian(bp, 200.0, 500.0, 1.0)
    )
    data2 = (
        baseline
        + _gaussian(bp, 315.0, 300.0, 0.7)
        + _gaussian(bp, 325.0, 350.0, 0.8)
        + _gaussian(bp, 335.0, 280.0, 0.8)
        + _gaussian(bp, 345.0, 320.0, 0.9)
    )
    fsa = SimpleNamespace(
        sample_data_with_basepairs=pd.DataFrame(
            {"time": time, "basepairs": bp}
        ),
        fsa={
            "DATA1": data1,
            "DATA2": data2,
            "DATA4": np.zeros_like(data1),
            "DATA105": data1,
        },
        size_standard_channel="DATA4",
    )
    return {
        "fsa": fsa,
        "assay": "FR1",
        "bp_min": 100.0,
        "bp_max": 400.0,
        "trace_channels": ["DATA1", "DATA2"],
        "primary_peak_channel": "DATA1",
        "peaks_by_channel": {},
    }


def test_raw_trace_shape_features_extracts_reference_geometry():
    features = raw_trace_shape_features(_synthetic_entry())

    assert features["trace_feature_schema_version"] == TRACE_FEATURE_SCHEMA_VERSION
    assert features["trace_available_channel_count"] == 2
    assert "DATA105" not in features["trace_peak_count_raw_per_channel"]
    assert features["trace_peak_count_raw_per_channel"]["DATA1"] >= 3
    assert features["trace_dominant_height_raw_per_channel"]["DATA1"] > 1000
    assert 0 < features["trace_dominant_height_share_raw_per_channel"]["DATA1"] < 1
    assert features["trace_total_area_raw_per_channel"]["DATA1"] > 0
    assert 0 < features["trace_dominant_area_share_raw_per_channel"]["DATA1"] <= 1
    assert features["trace_outside_window_area_share_per_channel"]["DATA1"] > 0
    assert features["trace_peak_spacing_mean_bp_per_channel"]["DATA1"] > 0
    assert features["trace_dominant_width_bp_per_channel"]["DATA1"] > 0
    assert 0 <= features["trace_dominant_symmetry_per_channel"]["DATA1"] <= 1
    assert features["trace_signal_to_noise_per_channel"]["DATA1"] > 10


def test_raw_trace_shape_features_has_stable_empty_shape():
    features = raw_trace_shape_features({})

    for field in PER_CHANNEL_TRACE_FIELDS:
        assert features[field] == {}
    assert features["trace_available_channel_count"] == 0
    assert features["trace_total_reference_area_all_channels"] == 0.0


def test_features_from_entry_includes_raw_trace_features():
    features = features_from_entry(_synthetic_entry())

    assert features["trace_feature_schema_version"] == TRACE_FEATURE_SCHEMA_VERSION
    assert features["trace_peak_count_raw_per_channel"]["DATA1"] >= 3


def test_rule_interpreter_does_not_compute_raw_trace_features():
    result = interpret_entry(_synthetic_entry())

    assert "trace_peak_count_raw_per_channel" not in result["features"]


def test_flatten_numeric_features_uses_dotted_channel_columns():
    features = raw_trace_shape_features(_synthetic_entry())
    flat = flatten_numeric_features(features)

    assert "trace_peak_count_raw_per_channel.DATA1" in flat
    assert "trace_dominant_height_raw_per_channel.DATA2" in flat
    assert "trace_feature_schema_version" not in flat
    assert flat["trace_available_channel_count"] == 2.0
