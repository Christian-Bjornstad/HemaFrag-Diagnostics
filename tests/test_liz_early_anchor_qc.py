"""Strong complete LIZ cores must not fail only on early-anchor heuristics."""
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.interpolate import PchipInterpolator

from core.analysis import _legacy as analysis
from core.rust_bridge import _legacy as bridge
from fraggler.ladders import LADDERS


def make_liz(*, first_height=4500.0, second_height=4500.0, first_shift=0, weak_core=False, shifted_core=False):
    sizes = LADDERS["LIZ500_250"]["sizes"].astype(float)
    scans = np.rint(1400.0 + (sizes - 35.0) * 5.5).astype(int)
    scans[0] += first_shift
    if shifted_core:
        scans[9] += 85
    x = np.arange(4600)
    trace = np.zeros(x.size)
    for i, scan in enumerate(scans):
        height = first_height if i == 0 else 4500.0
        if i == 1:
            height = second_height
        if weak_core and i == 9:
            height = 100.0
        trace += height * np.exp(-0.5 * ((x - scan) / 2.0) ** 2)
    fsa = SimpleNamespace(
        file_name="synthetic-liz.fsa", ladder="LIZ500_250", analysis_id="clonality",
        ladder_fit_profile="clonality_liz500", size_standard=trace, sample_data=trace,
        ladder_steps=sizes.copy(), expected_ladder_steps=sizes.copy(),
        min_size_standard_height=300.0,
    )
    return fsa, scans.tolist(), sizes.tolist()


@pytest.mark.parametrize("kwargs", [{"first_height": 1100.0}, {"first_shift": -23}])
def test_strong_complete_liz_core_waives_relative_early_height_and_fixed_scan_gap(kwargs):
    fsa, scans, sizes = make_liz(**kwargs)
    ok, reason = bridge._validate_rust_anchor_selection(fsa, scans, sizes)
    assert ok, reason


@pytest.mark.parametrize("kwargs", [
    {"first_height": 1100.0, "weak_core": True},
    {"first_height": 1100.0, "shifted_core": True},
    {"first_height": 20.0},
    {"first_shift": -100},
    {"first_shift": -23, "second_height": 20.0},
])
def test_waiver_does_not_accept_missing_signal_or_bad_core(kwargs):
    fsa, scans, sizes = make_liz(**kwargs)
    assert not bridge._validate_rust_anchor_selection(fsa, scans, sizes)[0]


def test_waiver_requires_every_expected_core_anchor():
    fsa, scans, sizes = make_liz(first_height=1100.0)
    del scans[8]
    del sizes[8]
    assert not bridge._validate_rust_anchor_selection(fsa, scans, sizes)[0]


def test_accepted_early_waiver_preserves_native_mapping_and_sample_window():
    fsa, scans, sizes = make_liz(first_height=1100.0, first_shift=-23)
    tangents = PchipInterpolator(scans, sizes).derivative()(scans).tolist()
    result = {
        "ladder": "LIZ500_250",
        "ladder_review_assessment": {"reason_codes": [], "selected_strong_baseline_anchor_count": 0},
        "ladder_fit_preview": {
            "best_scan_indices": scans,
            "sizing_model": {"strategy": "willros_monotone_spline", "coefficients": tangents,
                             "predicted_ladder_basepairs": sizes},
        },
    }
    hydrated = bridge._apply_rust_result_to_fsa(fsa, result)
    assert hydrated is not None
    qc = analysis.compute_ladder_qc_metrics(hydrated)
    analysis._finalize_auto_fit_metadata(hydrated)
    analysis._annotate_fit_qc_review(hydrated, qc)
    assert hydrated.ladder_qc_status == "ok"
    assert not hydrated.ladder_review_required
    np.testing.assert_array_equal(hydrated.best_size_standard, scans)
    np.testing.assert_array_equal(hydrated.ladder_steps, sizes)
    # TCRgB starts at 60 bp, so removing all sizing below 75 is not acceptable.
    assert (hydrated.sample_data_with_basepairs.basepairs < 60).any()
