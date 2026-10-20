import numpy as np
import pytest

from core.analyses.flt3.distance import calculate_bp_distance_metrics


def test_invalid_wt_keeps_remaining_channel_identity():
    metrics = calculate_bp_distance_metrics(
        [float("nan"), 330], [339],
        wt_channels=["DATA1", "DATA2"], mutant_channels=["DATA2"],
    )
    assert metrics[0]["channel"] == "DATA2"
    assert metrics[0]["delta_bp"] == 9
    assert calculate_bp_distance_metrics(
        [float("nan"), 330], [339],
        wt_channels=["DATA1", "DATA2"], mutant_channels=["DATA1"],
    ) == []


def test_invalid_mutant_does_not_shift_channel_pairing():
    metrics = calculate_bp_distance_metrics(
        [320, 330], [None, 339],
        wt_channels=["DATA1", "DATA2"], mutant_channels=["DATA1", "DATA2"],
    )
    assert len(metrics) == 1
    assert metrics[0]["channel"] == "DATA2"
    assert metrics[0]["delta_bp"] == 9


def test_distance_does_not_pair_across_explicit_channels():
    assert calculate_bp_distance_metrics(
        [330], [339], wt_channels=["DATA1"], mutant_channels=["DATA2"],
    ) == []


def test_distance_accepts_numpy_arrays():
    metrics = calculate_bp_distance_metrics(
        np.array([320, 330]), np.array([329, 339]),
        wt_channels=np.array(["DATA1", "DATA2"]),
        mutant_channels=np.array(["DATA1", "DATA2"]),
    )
    assert [metric["delta_bp"] for metric in metrics] == [9, 9]


@pytest.mark.parametrize("delta,rounded", [(8.5, 9), (-8.5, -8), (9.5, 10), (-9.5, -9)])
def test_distance_rounding_matches_html_javascript(delta, rounded):
    assert calculate_bp_distance_metrics([330], [330 + delta])[0]["rounded_delta_bp"] == rounded
