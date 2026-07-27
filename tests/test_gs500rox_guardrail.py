from types import SimpleNamespace

import numpy as np

from core.rust_bridge import _allow_guardrail_review_hydration, _validate_rust_anchor_selection


GS500ROX_STEPS = [
    35.0,
    50.0,
    75.0,
    100.0,
    139.0,
    150.0,
    160.0,
    200.0,
    250.0,
    300.0,
    340.0,
    350.0,
    400.0,
    450.0,
    490.0,
    500.0,
]


def _model(linear_max: float = 3.8, linear_mean: float = 1.55, linear_r2: float = 0.99985):
    return {
        "qc_metrics": {
            "monotonic_on_ladder": True,
            "max_abs_error_bp": 0.0,
            "linear_trend_max_abs_error_bp": linear_max,
            "linear_trend_mean_abs_error_bp": linear_mean,
            "linear_trend_r2": linear_r2,
        }
    }


def test_guarded_gs500rox_fit_can_hydrate_before_general_rox_rules():
    fsa = SimpleNamespace(file_name="NTC_ITD_1-10__100125_H01_C990RHLW.fsa", ladder="GS500ROX", analysis_id="flt3")
    scans = [1728, 1809, 1972, 2127, 2379, 2442, 2506, 2770, 3089, 3443, 3702, 3769, 4112, 4427, 4683, 4736]

    assert _allow_guardrail_review_hydration(
        fsa,
        "GS500ROX first anchor too late (1728)",
        {"reason_codes": [], "summary": "Rust ladder fit looks internally consistent."},
        _model(),
        scans,
        GS500ROX_STEPS,
    )


def test_guarded_gs500rox_fit_still_requires_tail_coverage():
    fsa = SimpleNamespace(file_name="bad_tail.fsa", ladder="GS500ROX", analysis_id="flt3")
    scans = [1728, 1809, 1972, 2127, 2379, 2442, 2506, 2770, 3089, 3443, 3702, 3769, 4112, 4327, 4383, 4436]

    assert not _allow_guardrail_review_hydration(
        fsa,
        "GS500ROX first anchor too late (1728)",
        {"reason_codes": [], "summary": "Rust ladder fit looks internally consistent."},
        _model(),
        scans,
        GS500ROX_STEPS,
    )


def test_compact_3730_gs500rox_span_can_hydrate_when_fit_is_strong():
    fsa = SimpleNamespace(file_name="26OUM04955_ITD_ratio_250326_D08_H9H1DHZH.fsa", ladder="GS500ROX", analysis_id="flt3")
    scans = [1443, 1512, 1643, 1772, 1979, 2031, 2085, 2305, 2575, 2865, 3084, 3138, 3419, 3678, 3889, 3932]

    assert _allow_guardrail_review_hydration(
        fsa,
        "GS500ROX anchor span too small (2489)",
        {"reason_codes": ["blob_dominated_start"], "summary": "Early blob-like peaks dominate the start region."},
        _model(linear_max=3.8879, linear_mean=1.7784, linear_r2=0.999822),
        scans,
        GS500ROX_STEPS,
    )


def test_late_but_complete_gs500rox_fit_can_hydrate_for_review():
    fsa = SimpleNamespace(file_name="25OUM20181_p1_ITD__231225_E01_H9C0VCER.fsa", ladder="GS500ROX", analysis_id="flt3")
    scans = [1710, 1792, 1955, 2110, 2362, 2425, 2489, 2753, 3072, 3426, 3685, 3752, 4095, 4410, 4666, 4885]

    assert _allow_guardrail_review_hydration(
        fsa,
        "GS500ROX first anchor too late (1710)",
        {"reason_codes": [], "summary": "Rust ladder fit looks internally consistent."},
        _model(linear_max=5.856, linear_mean=2.178, linear_r2=0.999684),
        scans,
        GS500ROX_STEPS,
    )


def test_compressed_gs500rox_span_stays_rejected_even_if_operator_marks_minor():
    fsa = SimpleNamespace(file_name="25OUM12104_p1_ITD-ufort__080825_A01_H9C0ZIZ2.fsa", ladder="GS500ROX", analysis_id="flt3")
    scans = [1672, 1730, 1845, 1960, 2140, 2195, 2250, 2420, 2635, 2860, 3030, 3075, 3260, 3390, 3450, 3463]

    assert not _allow_guardrail_review_hydration(
        fsa,
        "GS500ROX anchor span too small (1791)",
        {"reason_codes": ["poor_gs500rox_linear_fit", "tail_missing"], "summary": "compressed ladder"},
        _model(linear_max=22.08, linear_mean=8.12, linear_r2=0.99582),
        scans,
        GS500ROX_STEPS,
    )


def test_gs500rox_rejects_anchor_family_beyond_absolute_scan_limit():
    fsa = SimpleNamespace(
        file_name="late_family.fsa",
        ladder="GS500ROX",
        analysis_id="flt3",
        size_standard=np.ones(13000) * 100.0,
    )
    scans = [1932, 2010, 2160, 2350, 2600, 2700, 2860, 3400, 4300, 6200, 7600, 8300, 9400, 10800, 11900, 12438]

    ok, reason = _validate_rust_anchor_selection(fsa, scans, GS500ROX_STEPS)

    assert not ok
    assert "absolute scan limit" in reason


def test_gs500rox_rejects_anchor_family_before_absolute_scan_limit():
    fsa = SimpleNamespace(
        file_name="early_blob_family.fsa",
        ladder="GS500ROX",
        analysis_id="flt3",
        size_standard=np.ones(5000) * 100.0,
    )
    scans = [543, 1550, 1700, 1850, 2100, 2200, 2350, 2600, 2900, 3200, 3450, 3520, 3800, 4100, 4350, 4450]

    ok, reason = _validate_rust_anchor_selection(fsa, scans, GS500ROX_STEPS)

    assert not ok
    assert "before absolute scan limit" in reason


def test_gs500rox_guardrail_hydration_rejects_anchor_family_beyond_absolute_scan_limit():
    fsa = SimpleNamespace(file_name="late_family.fsa", ladder="GS500ROX", analysis_id="flt3")
    scans = [1932, 2010, 2160, 2350, 2600, 2700, 2860, 3400, 4300, 6200, 7600, 8300, 9400, 10800, 11900, 12438]

    assert not _allow_guardrail_review_hydration(
        fsa,
        "GS500ROX last anchor beyond absolute scan limit (12438)",
        {"reason_codes": [], "summary": "Rust ladder fit looks internally consistent."},
        _model(),
        scans,
        GS500ROX_STEPS,
    )
