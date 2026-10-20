"""Partial manual sizing must respect the observed anchors and their range."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

GS500_STEPS = np.array(
    [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    dtype=float,
)


def _fsa(times, *, trace_length=800):
    return SimpleNamespace(
        ladder="GS500ROX",
        file_name="partial.fsa",
        expected_ladder_steps=GS500_STEPS.copy(),
        ladder_steps=GS500_STEPS.copy(),
        size_standard_peaks=np.asarray(times, dtype=float),
        size_standard=np.zeros(trace_length),
        sample_data=np.arange(trace_length, dtype=float),
        fitted_to_model=False,
    )


@pytest.mark.parametrize("approved", [False, True])
def test_ten_of_sixteen_anchors_cannot_reverse_sizing(approved):
    from core.analysis import apply_manual_ladder_mapping, compute_ladder_qc_metrics

    # The former quadratic B-spline reversed at scans 438--524 despite these
    # strictly increasing observed anchors, and missed some anchors by 12 bp.
    times = np.array([100, 130, 160, 190, 220, 250, 280, 310, 340, 500], dtype=float)
    result = apply_manual_ladder_mapping(
        _fsa(times),
        {"mapping_times": dict(enumerate(times)), "review": {"partial_approved": approved}},
    )

    frame = result.sample_data_with_basepairs
    assert np.isfinite(frame.basepairs).all()
    assert np.all(np.diff(frame.basepairs) > 0)
    np.testing.assert_allclose(result.ladder_model.predict(times.reshape(-1, 1)), GS500_STEPS[:10])
    assert frame.time.tolist() == list(range(100, 501))
    np.testing.assert_array_equal(frame.peaks, np.arange(100, 501, dtype=float))
    assert compute_ladder_qc_metrics(result)["max_abs_error_bp"] == pytest.approx(0)
    assert result.ladder_steps.tolist() == GS500_STEPS[:10].tolist()
    assert result.best_size_standard.tolist() == times.tolist()
    assert result.manual_ladder_missing_step_indices == list(range(10, 16))
    assert result.ladder_fit_strategy == "manual_partial"
    assert result.ladder_review_required is not approved
    assert result.ladder_qc_status == ("manual_partial_reviewed" if approved else "review_required")
    assert result.manual_ladder_sizing_method == "bounded_linear"
    assert result.manual_ladder_sizing_time_range == [100.0, 500.0]
    assert result.manual_ladder_sizing_bp_range == [35.0, 300.0]


def test_partial_fractional_anchors_do_not_extrapolate_missing_end_steps():
    from core.analysis import apply_manual_ladder_mapping

    indices = [1, 3, 4, 5, 6, 8, 9, 10, 11, 13]
    times = np.array([100.25, 140.5, 180.75, 220.25, 250.5, 280.75, 310.25, 340.5, 380.75, 450.25])
    result = apply_manual_ladder_mapping(
        _fsa(times),
        {"mapping_times": dict(zip(indices, times)), "review": {"partial_approved": True}},
    )

    np.testing.assert_allclose(result.ladder_model.predict(times.reshape(-1, 1)), GS500_STEPS[indices])
    assert np.isnan(result.ladder_model.predict(np.array([[0.0], [100.0], [450.5], [799.0]]))).all()
    assert result.sample_data_with_basepairs.time.tolist() == list(range(101, 451))
    assert result.manual_ladder_mapped_step_indices == indices
    assert result.manual_ladder_missing_step_indices == [0, 2, 7, 12, 14, 15]


def test_partial_fit_keeps_sub_centibasepair_resolution_monotonic():
    from core.analysis import apply_manual_ladder_mapping

    # Rounding every size to two decimals used to produce plateaus and reject
    # an otherwise usable long trace. Stored sizing must keep its precision.
    times = np.array([1000.25, 17000.5, 33000.75])
    result = apply_manual_ladder_mapping(
        _fsa(times, trace_length=34000),
        {"mapping_times": {0: times[0], 1: times[1], 2: times[2]}},
    )

    assert result.fitted_to_model is True
    delta = np.diff(result.sample_data_with_basepairs.basepairs)
    assert np.all(delta > 0)
    assert np.any(delta < 0.01)


def test_saved_partial_approval_reloads_the_same_bounded_domain(tmp_path):
    import core.analysis._legacy as analysis

    times = np.array([100, 130, 160, 190, 220, 250, 280, 310, 340, 500], dtype=float)
    source = tmp_path / "partial.fsa"
    source.write_bytes(b"synthetic source identity")
    current = _fsa(times)
    current.file = str(source)
    payload = {
        "mapping_times": dict(enumerate(times)),
        "expected_step_indices": list(range(16)),
        "mapped_step_indices": list(range(10)),
        "missing_step_indices": list(range(10, 16)),
        "partial_mapping": True,
    }
    analysis.save_ladder_adjustment(current, payload, partial_approved=True)
    loaded = analysis.load_ladder_adjustment(current)
    result = analysis._try_apply_saved_ladder_adjustment(current, loaded, "GS500ROX")

    assert result is not None
    assert result.manual_ladder_partial_approved is True
    assert result.ladder_qc_status == "manual_partial_reviewed"
    assert result.sample_data_with_basepairs.time.tolist() == list(range(100, 501))
    assert result.manual_ladder_missing_step_indices == list(range(10, 16))
    np.testing.assert_allclose(result.ladder_model.predict(times.reshape(-1, 1)), GS500_STEPS[:10])


def test_partial_sizing_domain_is_preserved_in_provenance_and_flt3_method():
    from core.analyses.flt3.pipeline import _infer_sizing_method
    from core.analysis import apply_manual_ladder_mapping
    from core.analysis_provenance import build_analysis_provenance

    times = [100.0, 200.0, 300.0]
    current = _fsa(times)
    current._flt3_sizing_method = "rust_hybrid"
    result = apply_manual_ladder_mapping(current, {"mapping_times": {0: 100, 1: 200, 2: 300}})
    provenance = build_analysis_provenance({"fsa": result, "ladder_fit_strategy": "manual_partial"})

    assert provenance["manual_adjustment_sizing_method"] == "bounded_linear"
    assert provenance["manual_adjustment_sizing_time_range"] == [100.0, 300.0]
    assert provenance["manual_adjustment_sizing_bp_range"] == [35.0, 75.0]
    assert _infer_sizing_method(result) == "bounded_linear"


def test_completing_a_partial_mapping_removes_its_old_sizing_limits():
    from core.analysis import apply_manual_ladder_mapping

    times = 100.0 + GS500_STEPS
    current = apply_manual_ladder_mapping(_fsa(times), {"mapping_times": dict(enumerate(times[:10]))})
    assert current.manual_ladder_sizing_bp_range == [35.0, 300.0]
    result = apply_manual_ladder_mapping(current, {"mapping_times": dict(enumerate(times))})

    assert result.manual_ladder_partial is False
    assert result.ladder_fit_strategy == "manual_adjustment"
    assert result.ladder_review_required is False
    assert not hasattr(result, "manual_ladder_sizing_method")
    assert not hasattr(result, "manual_ladder_sizing_time_range")
    assert not hasattr(result, "manual_ladder_sizing_bp_range")


@pytest.mark.parametrize("partial", [False, True])
def test_manual_remap_invalidates_sized_automatic_previews(partial):
    from core.analyses.clonality.pipeline import (
        _build_peaks_from_rust_clonality_preview,
    )
    from core.analyses.flt3.pipeline import (
        _build_peaks_from_rust_flt3_preview,
        _detect_peaks,
    )
    from core.analysis import apply_manual_ladder_mapping

    times = 100.0 + GS500_STEPS
    current = _fsa(times)
    trace = np.zeros(800)
    trace[350] = 1000  # New size 250 bp, inside the partial domain.
    trace[600] = 2000  # Outside the partial end anchor at scan 400.
    current.sample_data = trace.copy()
    current.fsa = {"DATA1": trace.copy()}
    current.rust_flt3_preview = {
        "assay_name": "FLT3-ITD",
        "wt_peak": {"time": 600, "basepair": 330.0, "intensity": 2000},
    }
    current.rust_clonality_preview = {
        "ranked_assays": [{"assay_name": "FR1", "channels": ["DATA1"]}],
        "channel_peak_previews": {"DATA1": [{"time": 600, "basepair": 330.0, "intensity": 2000}]},
    }
    current.rust_ladder_qc_metrics = {"max_abs_error_bp": 100.0}
    current._flt3_sizing_method = "rust_hybrid"
    selected = times[:10] if partial else times
    result = apply_manual_ladder_mapping(current, {"mapping_times": dict(enumerate(selected))})

    assert _build_peaks_from_rust_clonality_preview(result, "FR1", "DATA1") == {}
    assert _build_peaks_from_rust_flt3_preview(result, "FLT3-ITD", "DATA1", trace) is None
    assert not hasattr(result, "rust_ladder_qc_metrics")
    assert not hasattr(result, "_flt3_sizing_method")
    # Exercise the actual fallback detector, with raw scans beyond the domain.
    peaks = _detect_peaks(
        result, "FLT3-ITD", 330.0, trace,
        area_channel_traces={"DATA1": trace}, fast_area=True,
    )
    assert not peaks.empty
    if partial:
        assert peaks.basepairs.tolist() == [pytest.approx(250.0)]
    else:
        assert peaks.basepairs.between(35, 500).all()
    assert 330.0 not in peaks.basepairs.tolist()


@pytest.mark.parametrize("approved", [False, True])
def test_saved_partial_remap_clears_only_stale_automatic_rejection(approved):
    import core.analysis._legacy as analysis

    current = _fsa([100.0, 200.0, 300.0])
    current.rust_guardrail_review_required = True
    current.analysis_status = "ladder_review_only"
    current.rust_review_reason_codes = ["rust_ladder_fit_rejected"]
    result = analysis._try_apply_saved_ladder_adjustment(
        current,
        {"mapping_times": {0: 100, 1: 200, 2: 300}, "review": {"partial_approved": approved}},
        "GS500ROX",
    )

    assert result is not None
    assert result.ladder_review_required is not approved
    assert not getattr(result, "rust_guardrail_review_required", False)
    assert getattr(result, "analysis_status", "") != "ladder_review_only"
    assert result.rust_review_reason_codes == ["rust_ladder_fit_rejected"]
    assert current.rust_guardrail_review_required is True
    assert current.analysis_status == "ladder_review_only"


@pytest.mark.parametrize("strategy", ["manual_adjustment", "manual_partial"])
def test_flt3_automatic_start_prior_cannot_replace_manual_anchors(strategy, monkeypatch):
    import core.analyses.flt3.pipeline._legacy as pipeline

    current = _fsa(100 + GS500_STEPS)
    current.ladder_fit_strategy = strategy
    called = []
    monkeypatch.setattr(pipeline, "_gs500rox_start_prior_trials", lambda *args: called.append(args) or [])
    result = pipeline._apply_gs500rox_start_family_prior_if_review_band(current)

    assert result is current
    assert called == []


def test_flt3_pipeline_recomputes_peaks_within_approved_partial_domain(tmp_path, monkeypatch):
    from core.analyses.flt3.pipeline import _legacy as pipeline
    from core.analysis import apply_manual_ladder_mapping

    times = 100.0 + GS500_STEPS
    current = _fsa(times)
    source = tmp_path / "sample_D835.fsa"
    source.write_bytes(b"synthetic source identity")
    current.file = str(source)
    current.file_name = source.name
    trace = np.zeros(800)
    trace[180] = 1000  # New WT size 80 bp.
    trace[229] = 500   # New MUT size 129 bp.
    trace[550] = 2000  # Outside the last assigned anchor, scan 400.
    current.fsa = {"DATA3": trace}
    current.sample_data = trace
    current.rust_flt3_preview = {
        "assay_name": "FLT3-D835",
        "wt_peak": {"time": 550, "basepair": 80.0, "intensity": 2000},
    }
    current = apply_manual_ladder_mapping(current, {
        "mapping_times": dict(enumerate(times[:10])), "review": {"partial_approved": True},
    })
    monkeypatch.setattr(pipeline, "_analyse_fsa_candidate", lambda *_args: current)
    meta = {
        "assay": "FLT3-D835", "primary_peak_channel": "DATA3",
        "trace_channels": ["DATA3"], "peak_channels": ["DATA3"],
        "analysis_type": "standard", "group": "sample", "wt_bp": 80.0,
        "mut_bp": 129.0, "bp_min": 50.0, "bp_max": 250.0,
        "injection_time": 3,
    }
    entry = pipeline._build_entry_from_candidate(source, meta)
    peaks = entry["peaks_by_channel"]["DATA3"]

    assert peaks.basepairs.tolist() == [80.0, 129.0]
    assert peaks.peaks.tolist() == [990.0, 490.0]  # Existing 10 RFU baseline correction.
    assert peaks.label.tolist() == ["WT", "MUT"]
    assert entry["ladder_fit_strategy"] == "manual_partial"
    assert entry["ladder_qc_status"] == "manual_partial_reviewed"
    assert entry["ladder_review_required"] is False
    assert entry["sizing_method"] == "bounded_linear"


def test_editor_previews_and_approves_ten_anchor_mapping_with_visible_limits(qapp, monkeypatch):
    import pandas as pd
    from PyQt6.QtWidgets import QDialog, QMessageBox

    from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog

    times = np.array([100, 130, 160, 190, 220, 250, 280, 310, 340, 500], dtype=float)
    candidates = pd.DataFrame({
        "index": np.arange(10), "time": times, "intensity": np.full(10, 100.0),
        "source": ["auto"] * 10, "marker_id": [f"peak-{index}" for index in range(10)],
        "requested_x": times,
    })
    monkeypatch.setattr(LadderAdjustmentDialog, "_get_candidates", lambda self: candidates.copy())
    monkeypatch.setattr(LadderAdjustmentDialog, "_suggest_auto", lambda self, store_initial: None)
    approval_messages = []

    def approve(_parent, _title, message, *_args):
        approval_messages.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", approve)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: pytest.fail(str(args[-1])))
    dialog = LadderAdjustmentDialog(_fsa(times))
    try:
        dialog.mapping = {index: index for index in range(10)}
        dialog._refresh_preview_state(show_errors=True)
        dialog._refresh_all()
        assert dialog._preview_fsa is not None
        assert dialog._fit_grade == "check"
        assert "35" in dialog.qc_reason_label.text()
        assert "300" in dialog.qc_reason_label.text()
        assert "outside" in dialog.qc_reason_label.text()
        dialog._on_apply()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.get_review_payload()["partial_approved"] is True
        assert len(approval_messages) == 1
        assert "35" in approval_messages[0] and "300" in approval_messages[0]
        assert "outside" in approval_messages[0]
    finally:
        dialog.close()
