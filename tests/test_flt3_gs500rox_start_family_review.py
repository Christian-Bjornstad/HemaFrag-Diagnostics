from types import SimpleNamespace

import numpy as np

from core.analyses.flt3.pipeline import (
    _gs500rox_curved_review_band,
    _gs500rox_start_family_review_reason,
    _gs500rox_start_prior_trials,
)


GS500ROX_SIZES = np.asarray([35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500], dtype=float)


def _fsa(scans, candidates):
    return SimpleNamespace(
        ladder="GS500ROX",
        best_size_standard=scans,
        rust_ladder_peak_preview=[{"index": idx} for idx in candidates],
    )


def test_suspect_gs500rox_35_50_start_family_is_flagged():
    fsa = _fsa(
        [1589, 1647, 1875, 2025, 2258, 2318, 2376, 2620, 2920, 3250, 3490, 3550, 3860, 4190, 4480, 4525],
        [1569, 1607, 1647, 1875],
    )

    assert "suspect_gs500rox_35_50_start_family" in _gs500rox_start_family_review_reason(fsa)


def test_plain_gs500rox_start_without_alternatives_is_not_flagged():
    fsa = _fsa(
        [1589, 1647, 1875, 2025, 2258, 2318, 2376, 2620, 2920, 3250, 3490, 3550, 3860, 4190, 4480, 4525],
        [1589, 1647, 1875],
    )

    assert _gs500rox_start_family_review_reason(fsa) == ""


def test_compressed_missing_ladder_shape_is_not_marked_as_35_50_family():
    fsa = _fsa(
        [1515, 1587, 1726, 1860, 2080, 2135, 2190, 2410, 2650, 2870, 3050, 3095, 3280, 3420, 3520, 3753],
        [1480, 1515, 1587, 1726],
    )

    assert _gs500rox_start_family_review_reason(fsa) == ""


def test_suspect_gs500rox_35_only_start_family_is_flagged():
    fsa = _fsa(
        [1576, 1711, 1841, 2010, 2245, 2305, 2368, 2602, 2905, 3230, 3468, 3530, 3838, 4170, 4480, 4564],
        [1576, 1633, 1711, 1841],
    )

    assert "suspect_gs500rox_35_start_family" in _gs500rox_start_family_review_reason(fsa)


def test_gs500rox_start_prior_finds_simple_shift_review_band():
    selected = [1589, 1647, 1875, 2020, 2255, 2315, 2373, 2620, 2916, 3249, 3498, 3565, 3902, 4213, 4472, 4525]
    fsa = _fsa(selected, [1647, 1719, 1875, 2020])
    fsa.rust_ladder_peak_preview = [
        {"index": 1647, "height": 500, "prominence": 450},
        {"index": 1719, "height": 650, "prominence": 620},
        {"index": 1875, "height": 700, "prominence": 650},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials
    assert trials[0]["mode"] == "simple_shift"
    assert trials[0]["selected"][:2] == [1647, 1719]
    assert trials[0]["review_band"] is True


def test_gs500rox_start_prior_finds_35_earlier_mode():
    selected = [1488, 1538, 1717, 1849, 2063, 2117, 2172, 2398, 2676, 2980, 3208, 3265, 3563, 3837, 4056, 4101]
    fsa = _fsa(selected, [1513, 1579, 1717, 1849])
    fsa.rust_ladder_peak_preview = [
        {"index": 1513, "height": 850, "prominence": 760},
        {"index": 1579, "height": 800, "prominence": 780},
        {"index": 1717, "height": 700, "prominence": 650},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials
    assert trials[0]["mode"] == "35_earlier"
    assert trials[0]["selected"][:2] == [1513, 1579]
    assert trials[0]["review_band"] is True


def test_gs500rox_start_prior_finds_review_only_start_block():
    selected = [1518, 1595, 1820, 1966, 2204, 2264, 2326, 2581, 2897, 3254, 3523, 3593, 3955, 4290, 4568, 4625]
    fsa = _fsa(selected, [1494, 1595, 1668, 1766, 1966, 2204])
    fsa.rust_ladder_peak_preview = [
        {"index": 1494, "height": 700, "prominence": 520},
        {"index": 1595, "height": 500, "prominence": 430},
        {"index": 1668, "height": 320, "prominence": 260},
        {"index": 1766, "height": 480, "prominence": 420},
        {"index": 1966, "height": 450, "prominence": 400},
        {"index": 2204, "height": 650, "prominence": 600},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials
    assert trials[0]["mode"] == "start_block_35_50_75_100_139"
    assert trials[0]["selected"][:5] == [1494, 1595, 1766, 1966, 2204]
    assert trials[0]["review_band"] is True
    assert trials[0]["apply_band"] is False


def test_gs500rox_start_prior_finds_reverse_projected_pair():
    selected = [1550, 1648, 1822, 1964, 2194, 2252, 2310, 2553, 2847, 3178, 3422, 3486, 3809, 4104, 4345, 4395]
    fsa = _fsa(selected, [1573, 1627, 1700, 1822, 1964, 2194])
    fsa.rust_ladder_peak_preview = [
        {"index": 1573, "height": 32000, "prominence": 31000},
        {"index": 1627, "height": 2100, "prominence": 1900},
        {"index": 1700, "height": 2300, "prominence": 2200},
        {"index": 1822, "height": 2400, "prominence": 2300},
        {"index": 1964, "height": 2600, "prominence": 2400},
        {"index": 2194, "height": 2800, "prominence": 2600},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    pair_trials = [trial for trial in trials if str(trial["mode"]).startswith("reverse_pair_")]
    assert pair_trials
    assert pair_trials[0]["selected"][:2] == [1627, 1700]
    assert pair_trials[0]["review_band"] is True
    assert pair_trials[0]["apply_band"] is True


def test_gs500rox_curved_review_band_keeps_review_only_candidates():
    assert _gs500rox_curved_review_band(
        linear_max=10.7,
        linear_mean=5.0,
        linear_r2=0.9991,
        quadratic_max=2.9,
        quadratic_mean=1.2,
        quadratic_r2=0.9999,
    )
    assert not _gs500rox_curved_review_band(
        linear_max=10.7,
        linear_mean=5.0,
        linear_r2=0.9991,
        quadratic_max=5.2,
        quadratic_mean=2.5,
        quadratic_r2=0.9996,
    )
