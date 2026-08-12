from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np


def _rejected_fsa(path: Path, *, ladder: str = "ROX400HD") -> SimpleNamespace:
    return SimpleNamespace(
        file=str(path),
        file_name=path.name,
        ladder=ladder,
        expected_ladder_steps=np.asarray([50.0, 75.0, 100.0]),
        ladder_steps=np.asarray([50.0, 75.0, 100.0]),
        best_size_standard=np.asarray([100, 200, 300]),
        fitted_to_model=True,
        sample_data_with_basepairs=object(),
        ladder_model=object(),
        fsa={"DATA1": np.asarray([0.0, 20.0, 5.0]), "DATA4": np.asarray([0.0, 30.0, 4.0])},
        size_standard_channel="DATA4",
        rust_review_reason_codes=["selected_baseline_like_ladder_peaks"],
        rust_review_primary_reason="Selected anchors resemble baseline noise.",
        rust_review_summary="Two strong baseline-like anchors were selected.",
        rust_selected_baseline_like_anchor_count=2,
        rust_selected_cleaner_neighbor_count=1,
        rust_selected_strong_baseline_anchor_count=2,
    )


def test_rust_rejection_becomes_zero_fit_review_scaffold(tmp_path):
    from core.analysis._legacy import _mark_rust_ladder_rejection_for_review

    fsa = _rejected_fsa(tmp_path / "sample.fsa")
    result = _mark_rust_ladder_rejection_for_review(fsa, "ROX")

    assert result is fsa
    assert result.analysis_status == "ladder_review_only"
    assert result.ladder_qc_status == "review_required"
    assert result.ladder_review_required is True
    assert result.fitted_to_model is False
    assert result.ladder_steps.size == 0
    assert result.ladder_fitted_step_count == 0
    assert result.ladder_missing_expected_steps == [50.0, 75.0, 100.0]
    assert "rust_ladder_fit_rejected" in result.rust_review_reason_codes
    assert result.rust_selected_strong_baseline_anchor_count == 2


def test_clonality_review_entry_is_visible_to_ladder_gate(tmp_path):
    from core.analysis._legacy import _mark_rust_ladder_rejection_for_review
    from core.analyses.clonality.ladder_review_gate import collect_ladder_review_cases
    from core.analyses.clonality.pipeline import _build_ladder_review_only_entry

    source = tmp_path / "PK_FR1_no_patient_number.fsa"
    fsa = _mark_rust_ladder_rejection_for_review(_rejected_fsa(source), "ROX")
    entry = _build_ladder_review_only_entry(
        source,
        fsa,
        assay="FR1",
        group="positive_control",
        ladder="ROX",
        trace_channels=["DATA1"],
        peak_channels=["DATA1"],
        primary_peak_channel="DATA1",
        bp_min=80.0,
        bp_max=400.0,
    )

    rows = collect_ladder_review_cases([entry])
    assert entry["analysis_status"] == "ladder_review_only"
    assert entry["peaks_by_channel"]["DATA1"].empty
    assert len(rows) == 1
    assert rows[0]["full_path"] == str(source)
    assert rows[0]["suggested_action"] == "open_ladder_review"
    assert rows[0]["fitted_count"] == "0"


def test_flt3_review_entry_has_no_peak_result(tmp_path):
    from core.analysis._legacy import _mark_rust_ladder_rejection_for_review
    from core.analyses.flt3.pipeline import _legacy as flt3

    source = tmp_path / "sample_D835__010126_A01_run.fsa"
    fsa = _mark_rust_ladder_rejection_for_review(
        _rejected_fsa(source, ladder="GS500ROX"),
        "GS500ROX",
    )
    meta = {
        "primary_peak_channel": "DATA1",
        "trace_channels": ["DATA1"],
        "assay": "FLT3-D835",
        "analysis_type": "standard",
        "group": "sample",
        "bp_min": 80.0,
        "bp_max": 500.0,
        "injection_time": 10,
        "selection_key": "sample_D835",
    }
    entry = flt3._build_ladder_review_only_entry(source, meta, fsa)
    flt3._calculate_ratios([entry])

    assert entry["analysis_status"] == "ladder_review_only"
    assert entry["peak_qc_pass"] is False
    assert entry["peaks_by_channel"]["DATA1"].empty
    assert entry["ratio_mode"] == "not_available_ladder_review"
    assert flt3._interpret_entry(entry) == "Ingen resultat - ladder review kreves"


def test_general_review_entry_still_generates_html_without_patient_id(tmp_path):
    from core.analysis._legacy import _mark_rust_ladder_rejection_for_review
    from core.analyses.general.pipeline import _build_ladder_review_only_entry
    from core.analyses.general.reporting import build_general_html_report

    source = tmp_path / "research_alias_only.fsa"
    fsa = _mark_rust_ladder_rejection_for_review(_rejected_fsa(source), "ROX")
    classified = {
        "assay": "GENERAL",
        "group": "sample",
        "ladder": "ROX400HD",
        "trace_channels": ["DATA1"],
        "peak_channels": ["DATA1"],
        "primary_peak_channel": "DATA1",
        "sample_channel": "DATA1",
        "bp_min": 80.0,
        "bp_max": 400.0,
        "general_profile": {"profile_id": "default", "profile_version": 1},
    }
    entry = _build_ladder_review_only_entry(source, fsa, classified)
    report = build_general_html_report([entry], tmp_path / "reports", run_label="alias-run")

    assert report is not None and report.exists()
    html = report.read_text(encoding="utf-8")
    assert "research_alias_only.fsa" in html
    assert "Ladder review required" in html
    assert "No sample peaks or result were reported" in html


def test_general_job_generation_does_not_require_or_split_on_patient_id(tmp_path, monkeypatch):
    from config import APP_SETTINGS
    from core.batch import generate_jobs

    first = tmp_path / "research_alias_only.fsa"
    second = tmp_path / "PK_is_just_my_alias.fsa"
    first.write_bytes(b"fsa")
    second.write_bytes(b"fsa")
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "general")

    jobs = generate_jobs([first, second], aggregate_patients=True)

    assert len(jobs) == 1
    assert jobs[0]["name"] == "GENERAL"
    assert jobs[0]["type"] == "pipeline"
    assert jobs[0]["files"] == sorted([first, second])


def test_qc_control_display_order_is_pk_rk_nk():
    from core.qc.qc_html import _control_display_sort_key

    entries = [
        {"fsa": SimpleNamespace(file_name="NK_FR1_test.fsa")},
        {"fsa": SimpleNamespace(file_name="RK_FR1_test.fsa")},
        {"fsa": SimpleNamespace(file_name="PK_FR1_test.fsa")},
    ]
    ordered = sorted(entries, key=_control_display_sort_key)

    assert [entry["fsa"].file_name[:2] for entry in ordered] == ["PK", "RK", "NK"]
