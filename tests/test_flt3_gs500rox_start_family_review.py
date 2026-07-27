from types import SimpleNamespace

import numpy as np

from core.analyses.flt3.pipeline import (
    _gs500rox_curved_review_band,
    _gs500rox_current_suppresses_35_earlier_noise,
    _gs500rox_current_start_suppresses_start_block,
    _gs500rox_current_start_is_preferred,
    _gs500rox_current_start_is_stable,
    _gs500rox_late_first_anchor_guardrail_can_pass,
    _gs500rox_learned_right_shift_apply_band,
    _gs500rox_simple_shift_curved_apply_band,
    _gs500rox_start_family_review_reason,
    _gs500rox_start_prior_requires_review,
    _gs500rox_start_prior_trials,
    GS500ROX_LATE_FIRST_35_RIGHT_SHIFT_MODE,
    GS500ROX_RIGHT_SHIFTED_35_50_75_MODE,
    GS500ROX_SUPPORTED_35_NEAR_FIXED50_MODE,
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
    assert trials[0]["apply_band"] is True


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
    start_block_trials = [trial for trial in trials if trial["mode"] == "start_block_35_50_75_100_139"]
    assert start_block_trials
    assert start_block_trials[0]["selected"][:5] == [1494, 1595, 1766, 1966, 2204]
    assert start_block_trials[0]["review_band"] is True
    assert start_block_trials[0]["apply_band"] is False


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
    assert pair_trials[0]["apply_band"] is False


def test_gs500rox_reverse_pair_rejects_baseline_and_first_blob_pair():
    selected = [1550, 1648, 1822, 1964, 2194, 2252, 2310, 2553, 2847, 3178, 3422, 3486, 3809, 4104, 4345, 4395]
    fsa = _fsa(selected, [1573, 1627, 1700, 1822, 1964, 2194])
    fsa.rust_ladder_peak_preview = [
        {"index": 1573, "height": 34000, "prominence": 32000},
        {"index": 1627, "height": 40, "prominence": 30},
        {"index": 1700, "height": 2600, "prominence": 2400},
        {"index": 1822, "height": 2400, "prominence": 2300},
        {"index": 1964, "height": 2600, "prominence": 2400},
        {"index": 2194, "height": 2800, "prominence": 2600},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    pair_trials = [trial for trial in trials if str(trial["mode"]).startswith("reverse_pair_")]
    assert not pair_trials


def test_stable_current_start_suppresses_hard_start_proposals():
    assert _gs500rox_current_start_is_stable(
        gap_35_50=72,
        gap_50_75=143,
        gap_75_100=138,
        gap_100_139=221,
        linear_max=3.24,
        linear_mean=1.34,
        linear_r2=0.999888,
    )
    assert not _gs500rox_current_start_is_stable(
        gap_35_50=58,
        gap_50_75=185,
        gap_75_100=138,
        gap_100_139=221,
        linear_max=5.7,
        linear_mean=1.9,
        linear_r2=0.9997,
    )


def test_preferred_current_start_covers_reviewed_current_correct_band():
    assert _gs500rox_current_start_is_preferred(
        gap_35_50=69,
        gap_50_75=145,
        gap_75_100=138,
        gap_100_139=223,
        linear_max=4.55,
        linear_mean=1.68,
        linear_r2=0.999812,
    )
    assert not _gs500rox_current_start_is_preferred(
        gap_35_50=98,
        gap_50_75=234,
        gap_75_100=151,
        gap_100_139=245,
        linear_max=5.78,
        linear_mean=2.02,
        linear_r2=0.99969,
    )


def test_current_start_suppresses_reviewed_start_block_false_positive_band():
    assert _gs500rox_current_start_suppresses_start_block(
        gap_35_50=73,
        gap_50_75=141,
        gap_75_100=138,
        gap_100_139=223,
        linear_max=4.68,
        linear_mean=1.96,
        linear_r2=0.999768,
    )
    assert not _gs500rox_current_start_suppresses_start_block(
        gap_35_50=98,
        gap_50_75=234,
        gap_75_100=151,
        gap_100_139=245,
        linear_max=5.78,
        linear_mean=2.02,
        linear_r2=0.99969,
    )


def test_hard_start_proposals_are_not_suggested_for_reviewed_current_correct_band():
    selected = [1529, 1602, 1744, 1882, 2106, 2163, 2221, 2458, 2751, 3070, 3308, 3368, 3678, 3962, 4193, 4240]
    fsa = _fsa(selected, [1504, 1559, 1602, 1744, 1882, 2106])
    fsa.rust_ladder_peak_preview = [
        {"index": 1504, "height": 700, "prominence": 520},
        {"index": 1559, "height": 690, "prominence": 520},
        {"index": 1602, "height": 500, "prominence": 430},
        {"index": 1744, "height": 480, "prominence": 420},
        {"index": 1882, "height": 450, "prominence": 400},
        {"index": 2106, "height": 650, "prominence": 600},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert not [trial for trial in trials if trial["mode"] == "start_block_35_50_75_100_139"]
    assert not [trial for trial in trials if str(trial["mode"]).startswith("reverse_pair_")]


def test_mild_current_correct_band_suppresses_start_block_at_68_scan_gap():
    assert _gs500rox_current_start_suppresses_start_block(
        68,
        146,
        137,
        223,
        5.03,
        1.867,
        0.999763,
    )


def test_preferred_current_start_suppresses_bad_35_earlier_proposal():
    selected = [1520, 1591, 1729, 1862, 2076, 2131, 2186, 2412, 2688, 2987, 3210, 3266, 3556, 3820, 4036, 4079]
    fsa = _fsa(selected, [1572, 1645, 1729, 1862])
    fsa.rust_ladder_peak_preview = [
        {"index": 1572, "height": 850, "prominence": 760},
        {"index": 1645, "height": 800, "prominence": 780},
        {"index": 1729, "height": 700, "prominence": 650},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert not [trial for trial in trials if trial["mode"] == "35_earlier"]


def test_good_current_fit_suppresses_bad_35_earlier_review_noise():
    assert _gs500rox_current_suppresses_35_earlier_noise(
        current_linear_max=3.114,
        current_linear_mean=1.499,
        current_linear_r2=0.999870,
        trial_linear_max=8.682,
        trial_linear_mean=2.911,
        trial_linear_r2=0.999424,
        trial_curved_review_band=False,
    )
    assert not _gs500rox_current_suppresses_35_earlier_noise(
        current_linear_max=6.446,
        current_linear_mean=3.046,
        current_linear_r2=0.999442,
        trial_linear_max=7.692,
        trial_linear_mean=3.864,
        trial_linear_r2=0.999136,
        trial_curved_review_band=True,
    )


def test_late_50_after_current_50_review_only_candidate():
    selected = [1560, 1658, 1892, 2043, 2288, 2350, 2413, 2673, 2990, 3342, 3602, 3669, 4011, 4326, 4583, 4636]
    fsa = _fsa(selected, [1612, 1658, 1695, 1892])
    fsa.rust_ladder_peak_preview = [
        {"index": 1612, "height": 520, "prominence": 480},
        {"index": 1658, "height": 900, "prominence": 850},
        {"index": 1695, "height": 780, "prominence": 730},
        {"index": 1892, "height": 700, "prominence": 650},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    late_trials = [trial for trial in trials if trial["mode"] == "late_50_after_current_50"]
    assert late_trials
    assert late_trials[0]["selected"][:2] == [1658, 1695]
    assert late_trials[0]["apply_band"] is False


def test_late_50_after_current_50_prefers_later_real_peak_after_review_learning():
    selected = [1560, 1658, 1892, 2043, 2288, 2350, 2413, 2673, 2990, 3342, 3602, 3669, 4011, 4326, 4583, 4636]
    fsa = _fsa(selected, [1612, 1658, 1695, 1734, 1892, 2043])
    fsa.rust_ladder_peak_preview = [
        {"index": 1612, "height": 500, "prominence": 450},
        {"index": 1658, "height": 430, "prominence": 390},
        {"index": 1695, "height": 35, "prominence": 20},
        {"index": 1734, "height": 500, "prominence": 460},
        {"index": 1892, "height": 600, "prominence": 560},
        {"index": 2043, "height": 620, "prominence": 580},
    ]
    fsa.ladder_review_required = True

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials[0]["mode"] == "late_50_after_current_50"
    assert trials[0]["selected"][:2] == [1658, 1734]
    assert trials[0]["apply_band"] is True
    assert trials[0]["learned_apply_band"] is True


def test_right_shifted_start_review_can_apply_in_learned_band():
    selected = [1478, 1605, 1752, 1892, 2121, 2179, 2238, 2480, 2776, 3108, 3354, 3418, 3744, 4040, 4283, 4331]
    fsa = _fsa(selected, [1495, 1514, 1534, 1605, 1752, 1892, 2121])
    fsa.rust_ladder_peak_preview = [
        {"index": 1495, "height": 600, "prominence": 120},
        {"index": 1514, "height": 180, "prominence": 140},
        {"index": 1534, "height": 260, "prominence": 250},
        {"index": 1605, "height": 300, "prominence": 290},
        {"index": 1752, "height": 340, "prominence": 330},
        {"index": 1892, "height": 360, "prominence": 350},
        {"index": 2121, "height": 380, "prominence": 360},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials[0]["mode"] == "right_shifted_start_review"
    assert trials[0]["selected"][:2] == [1534, 1605]
    assert trials[0]["apply_band"] is True
    assert trials[0]["learned_apply_band"] is True


def test_supported_35_near_fixed50_reviewed_probe_can_apply():
    selected = [1501, 1579, 1756, 1894, 2120, 2177, 2235, 2475, 2770, 3093, 3334, 3394, 3707, 3991, 4221, 4268]
    fsa = _fsa(selected, [1541, 1579, 1615, 1756, 1894, 2120])
    fsa.rust_ladder_peak_preview = [
        {"index": 1541, "height": 360, "prominence": 310},
        {"index": 1579, "height": 420, "prominence": 380},
        {"index": 1615, "height": 390, "prominence": 350},
        {"index": 1756, "height": 520, "prominence": 480},
        {"index": 1894, "height": 540, "prominence": 500},
        {"index": 2120, "height": 570, "prominence": 520},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials[0]["mode"] == GS500ROX_SUPPORTED_35_NEAR_FIXED50_MODE
    assert trials[0]["selected"][:2] == [1541, 1615]
    assert trials[0]["apply_band"] is True
    assert trials[0]["learned_apply_band"] is True
    assert not _gs500rox_start_prior_requires_review(trials[0])


def test_late_first_35_right_shift_moves_to_supported_peak():
    selected = [1729, 1837, 1996, 2153, 2402, 2464, 2524, 2778, 3094, 3437, 3696, 3762, 4105, 4418, 4670, 4723]
    fsa = _fsa(selected, [1729, 1758, 1837, 1996, 2153])
    fsa.rust_review_primary_reason = "GS500ROX first anchor too late (1729)"
    fsa.rust_ladder_peak_preview = [
        {"index": 1729, "height": 302, "prominence": 152},
        {"index": 1758, "height": 1372, "prominence": 1369},
        {"index": 1837, "height": 1517, "prominence": 1602},
        {"index": 1996, "height": 900, "prominence": 850},
        {"index": 2153, "height": 900, "prominence": 850},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials[0]["mode"] == GS500ROX_LATE_FIRST_35_RIGHT_SHIFT_MODE
    assert trials[0]["selected"][:2] == [1758, 1837]
    assert trials[0]["apply_band"] is True
    assert not _gs500rox_start_prior_requires_review(trials[0])


def test_right_shifted_35_50_75_curved_case_can_apply():
    selected = [1405, 1526, 1704, 1890, 2124, 2183, 2243, 2493, 2803, 3152, 3415, 3483, 3844, 4185, 4476, 4535]
    fsa = _fsa(selected, [1405, 1526, 1597, 1704, 1746, 1890, 2124])
    fsa.rust_review_primary_reason = "blob_dominated_start"
    fsa.ladder_review_required = True
    fsa.rust_ladder_peak_preview = [
        {"index": 1405, "height": 2742, "prominence": 2742},
        {"index": 1526, "height": 223, "prominence": 297},
        {"index": 1597, "height": 242, "prominence": 353},
        {"index": 1704, "height": 80, "prominence": 22},
        {"index": 1746, "height": 218, "prominence": 352},
        {"index": 1890, "height": 350, "prominence": 330},
        {"index": 2124, "height": 380, "prominence": 360},
    ]

    trials = _gs500rox_start_prior_trials(fsa, GS500ROX_SIZES)

    assert trials[0]["mode"] == GS500ROX_RIGHT_SHIFTED_35_50_75_MODE
    assert trials[0]["selected"][:3] == [1526, 1597, 1746]
    assert trials[0]["apply_band"] is True
    assert trials[0]["learned_apply_band"] is True
    assert not _gs500rox_start_prior_requires_review(trials[0])


def test_learned_right_shift_apply_band_rejects_weak_curved_fit():
    assert _gs500rox_learned_right_shift_apply_band(
        "right_shifted_start_review",
        linear_max=6.5,
        linear_mean=2.4,
        linear_r2=0.99962,
        quadratic_max=4.1,
        quadratic_mean=1.8,
        quadratic_r2=0.99981,
        cubic_max=2.2,
        cubic_mean=0.75,
        cubic_r2=0.99996,
    )
    assert not _gs500rox_learned_right_shift_apply_band(
        "start_block_35_50_75_100_139",
        linear_max=6.5,
        linear_mean=2.4,
        linear_r2=0.99962,
        quadratic_max=4.1,
        quadratic_mean=1.8,
        quadratic_r2=0.99981,
        cubic_max=2.2,
        cubic_mean=0.75,
        cubic_r2=0.99996,
    )
    assert not _gs500rox_learned_right_shift_apply_band(
        "right_shifted_start_review",
        linear_max=7.2,
        linear_mean=2.4,
        linear_r2=0.99962,
        quadratic_max=4.1,
        quadratic_mean=1.8,
        quadratic_r2=0.99981,
        cubic_max=2.2,
        cubic_mean=0.75,
        cubic_r2=0.99996,
    )


def test_simple_shift_curved_apply_band_matches_reviewed_correct_case():
    assert _gs500rox_simple_shift_curved_apply_band(
        linear_max=10.087,
        linear_mean=4.183,
        linear_r2=0.998970,
        quadratic_max=4.789,
        quadratic_mean=2.512,
        quadratic_r2=0.999668,
        cubic_max=2.008,
        cubic_mean=0.660,
        cubic_r2=0.999970,
    )
    assert not _gs500rox_simple_shift_curved_apply_band(
        linear_max=9.715,
        linear_mean=3.030,
        linear_r2=0.999342,
        quadratic_max=6.392,
        quadratic_mean=2.969,
        quadratic_r2=0.999557,
        cubic_max=3.067,
        cubic_mean=1.002,
        cubic_r2=0.999938,
    )


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


def test_35_earlier_start_prior_can_auto_pass_after_review_learning():
    assert not _gs500rox_start_prior_requires_review(
        {"mode": "35_earlier", "apply_band": True}
    )
    assert not _gs500rox_start_prior_requires_review(
        {"mode": "reverse_pair_tail_200_500", "apply_band": True}
    )
    assert not _gs500rox_start_prior_requires_review(
        {"mode": "simple_shift", "apply_band": True}
    )
    assert not _gs500rox_start_prior_requires_review(
        {"mode": "late_50_after_current_50", "apply_band": True}
    )
    assert not _gs500rox_start_prior_requires_review(
        {"mode": "35_earlier", "apply_band": False}
    )


def test_late_first_anchor_guardrail_can_pass_for_good_compact_gs500rox_fit():
    fsa = _fsa(
        [1707, 1787, 1946, 2078, 2291, 2345, 2401, 2628, 2906, 3207, 3432, 3488, 3779, 4045, 4262, 4306],
        [],
    )
    fsa.rust_review_primary_reason = "GS500ROX first anchor too late (1707)"

    assert _gs500rox_late_first_anchor_guardrail_can_pass(
        fsa,
        linear_max=4.47,
        linear_mean=1.58,
        linear_r2=0.999824,
        max_residual=0.9,
    )


def test_late_first_anchor_guardrail_still_rejects_poor_fit():
    fsa = _fsa(
        [1707, 1787, 1946, 2078, 2291, 2345, 2401, 2628, 2906, 3207, 3432, 3488, 3779, 4045, 4262, 4306],
        [],
    )
    fsa.rust_review_primary_reason = "GS500ROX first anchor too late (1707)"

    assert not _gs500rox_late_first_anchor_guardrail_can_pass(
        fsa,
        linear_max=7.0,
        linear_mean=1.58,
        linear_r2=0.999824,
        max_residual=0.9,
    )
