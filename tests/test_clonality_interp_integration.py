"""Integration coverage for active interpretation features."""
from __future__ import annotations

# ---- features_from_entry integration ----

def test_features_from_entry_returns_full_v2_shape():
    import pandas as pd
    from core.analyses.clonality.interpretation import features_from_entry

    df = pd.DataFrame({"peaks": [10, 20, 30, 100, 200, 400]})
    features = features_from_entry({
        "assay": "FR1",
        "peaks_by_channel": {"DATA1": df},
        "dominant_peak_basepairs": 312.0,
    })
    expected = (
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
    for k in expected:
        assert k in features


def test_features_graceful_for_minimal_entry_no_crash():
    from core.analyses.clonality.interpretation import features_from_entry
    features = features_from_entry({})
    assert features["peak_count_per_channel"] == {}
    assert features["patient_assays_run_count"] == 0
    assert features["assay_panel_completeness_pct"] == 0.0
