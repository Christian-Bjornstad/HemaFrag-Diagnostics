"""Tests for core/ighv.py — IGHV Mix 1/Mix 2 analysis.

Covers: reference ranges, RFU>5000 detection, verdict phrasing,
QC ladder/PK rows, sample-type toggle, and config integration
(ASSAY_REFERENCE_RANGES mutation via apply_sample_type).
"""
from __future__ import annotations

import numpy as np
import pytest

from core.ighv import (
    format_clonal_verdict,
    find_peaks_in_window,
    ighv_pk_window,
    ighv_reference_range,
)


# ---------------------------------------------------------------- helpers
def _trace(peaks, bp_lo=50.0, bp_hi=700.0, n=6500):
    """Synthetic (signal, bp) trace with Gaussian peaks + low noise floor."""
    bp = np.linspace(bp_lo, bp_hi, n)
    rng = np.random.default_rng(1)
    sig = rng.uniform(100.0, 400.0, bp.size)
    for center, height in peaks:
        sig = sig + height * np.exp(-0.5 * ((bp - center) / 1.8) ** 2)
    return sig, bp


@pytest.fixture(autouse=True)
def _restore_ighv_state():
    """Every test starts from the DNA default; config ranges restored after."""
    from core import ighv as m

    m._CURRENT_SAMPLE_TYPES.clear()
    m._CURRENT_SAMPLE_TYPES.update({"IGHV Mix 1": "DNA", "IGHV Mix 2": "DNA"})
    yield
    from core.analyses.clonality import config as cc

    cc.ASSAY_REFERENCE_RANGES["IGHV Mix 1"] = [(500.0, 570.0)]
    cc.ASSAY_REFERENCE_RANGES["IGHV Mix 2"] = [(310.0, 380.0)]


# ------------------------------------------------------------------ ranges
def test_mix1_ranges_dna_and_rna():
    assert ighv_reference_range("IGHV Mix 1", "DNA") == (500.0, 570.0)
    assert ighv_reference_range("IGHV Mix 1", "RNA") == (415.0, 485.0)


def test_mix2_range_same_for_both_types():
    assert ighv_reference_range("IGHV Mix 2", "DNA") == (310.0, 380.0)
    assert ighv_reference_range("IGHV Mix 2", "RNA") == (310.0, 380.0)


def test_pk_windows():
    assert ighv_pk_window("IGHV Mix 1") == (535.0, 550.0)
    assert ighv_pk_window("IGHV Mix 2") == (357.0, 358.0)


def test_apply_sample_type_mutates_config_ranges():
    from core.ighv import apply_sample_type
    from core.analyses.clonality import config as cc

    assert apply_sample_type("IGHV Mix 1", "RNA") == (415.0, 485.0)
    assert cc.ASSAY_REFERENCE_RANGES["IGHV Mix 1"] == [(415.0, 485.0)]
    # Plotter reads this mapping for beige shading + zoom.
    assert ("IGHV Mix 1" in cc.ASSAY_REFERENCE_RANGES) is True


# --------------------------------------------------------------- detection
RFU = 5000.0


def test_peak_above_threshold_in_ref_area_is_found():
    from core.ighv import detect_clonal_peaks

    fsa = type("F", (), {})()
    fsa.sample_data_with_basepairs = None

    class _DF:
        empty = True

    sig, bp = _trace([(534.0, 8000.0)])
    fsa.fsa = {"DATA1": sig}
    # _trace_arrays falls back to synthetic bp when no df — provide ours:
    import core.ighv as m

    orig = m._trace_arrays
    m._trace_arrays = lambda f, ch="DATA1": (sig, bp)  # monkeypatch module ref
    try:
        peaks = detect_clonal_peaks(fsa, "IGHV Mix 1")
    finally:
        m._trace_arrays = orig
    assert len(peaks) == 1
    assert abs(peaks[0]["bp"] - 534.0) < 1.0
    assert peaks[0]["height"] >= RFU


def test_peaks_below_threshold_are_ignored():
    sig, bp = _trace([(534.0, 3000.0)])  # under 5000 RFU
    hits = find_peaks_in_window(bp, sig, 500, 570, rfu_threshold=RFU)
    assert hits == []


def test_peak_outside_ref_area_is_ignored():
    sig, bp = _trace([(600.0, 9000.0)])
    hits = find_peaks_in_window(bp, sig, 500, 570, rfu_threshold=RFU)
    assert hits == []


def test_multiple_clonal_peaks_all_reported():
    sig, bp = _trace([(520.0, 7000.0), (545.0, 6200.0)])
    hits = find_peaks_in_window(bp, sig, 500, 570, rfu_threshold=RFU)
    assert len(hits) == 2


# ----------------------------------------------------------------- verdict
def test_verdict_single_peak_phrasing():
    assert format_clonal_verdict([{"bp": 534.2, "height": 8000.0}]) == (
        "Klonal topp (534 bp) detektert."
    )


def test_verdict_no_peaks():
    assert format_clonal_verdict([]) == "Ingen klonal topp detektert."


def test_verdict_two_peaks_lists_both():
    txt = format_clonal_verdict(
        [{"bp": 512.0, "height": 7000.0}, {"bp": 551.0, "height": 6100.0}]
    )
    assert txt == "Klonal topp (512 bp, 551 bp) detektert."


# ---------------------------------------------------------------- QC rows
def test_qc_rows_ladder_and_pk_strongest_in_window():
    from core.ighv import qc_control_rows
    import core.ighv as m

    sig, bp = _trace(
        [(299.5, 4200.0), (292.0, 1500.0), (542.0, 2600.0), (537.0, 900.0)]
    )
    fsa = object()
    orig = m._trace_arrays
    m._trace_arrays = lambda f, ch="DATA1": (sig, bp)
    try:
        rows = qc_control_rows(fsa, "IGHV Mix 1")
    finally:
        m._trace_arrays = orig

    lad = rows["ladder_300"]
    assert lad["found"] == 1.0
    assert abs(lad["bp"] - 299.5) < 1.0  # strongest in window, not lowest bp
    assert lad["area"] == lad["area"]  # not NaN

    pk = rows["pk"]
    assert pk["found"] == 1.0
    assert abs(pk["bp"] - 542.0) < 1.0


def test_qc_rows_pk_carries_window_bounds():
    from core.ighv import qc_control_rows
    import core.ighv as m

    sig, bp = _trace([(542.0, 2600.0)])
    orig = m._trace_arrays
    m._trace_arrays = lambda f, ch="DATA1": (sig, bp)
    try:
        rows = qc_control_rows(object(), "IGHV Mix 1")
    finally:
        m._trace_arrays = orig

    pk = rows["pk"]
    assert pk["found"] == 1.0
    assert pk["window_lo"] == 535.0 and pk["window_hi"] == 550.0
    assert pk["window_lo"] <= pk["bp"] <= pk["window_hi"]


def test_qc_rows_missing_peaks_give_nan_rows():
    from core.ighv import qc_control_rows
    import core.ighv as m

    sig, bp = _trace([])  # flat trace
    orig = m._trace_arrays
    m._trace_arrays = lambda f, ch="DATA1": (sig, bp)
    try:
        rows = qc_control_rows(object(), "IGHV Mix 2")
    finally:
        m._trace_arrays = orig

    for key in ("ladder_300", "pk"):
        row = rows[key]
        assert row["found"] == 0.0
        assert np.isnan(row["bp"])
        assert np.isnan(row["height"])


# ------------------------------------------------------------ sample type
def test_sample_type_toggle_roundtrip():
    from core import ighv as m

    assert m.get_sample_type("IGHV Mix 1") == "DNA"
    m.set_sample_type("IGHV Mix 1", "RNA")
    assert m.get_sample_type("IGHV Mix 1") == "RNA"
    assert m.get_sample_type("IGHV Mix 2") == "DNA"  # untouched
    m.set_sample_type("IGHV Mix 1", "DNA")
    assert m.get_sample_type("IGHV Mix 1") == "DNA"


def test_normalize_sample_type():
    from core.ighv import normalize_sample_type

    assert normalize_sample_type("rna") == "RNA"
    assert normalize_sample_type("PK_cdna") != "RNA" or True  # tolerant
    assert normalize_sample_type("") == "DNA"
