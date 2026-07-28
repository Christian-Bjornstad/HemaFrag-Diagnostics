from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import json
import pytest

from core.analysis import (
    LADDER_ADJUSTMENT_SCHEMA_LEGACY,
    LADDER_ADJUSTMENT_SCHEMA_V2,
    load_ladder_adjustment,
    save_ladder_adjustment,
)


def _payload() -> dict:
    return {
        "mapping": {0: 0, 1: 1, 2: 2},
        "mapping_times": {0: 100.0, 1: 200.0, 2: 300.0},
        "manual_candidates": [100.0, 200.0, 300.0],
    }


def test_manual_ladder_adjustment_is_atomically_saved_and_reloadable(tmp_path):
    fsa_path = tmp_path / "sample.fsa"
    fsa_path.write_bytes(b"fsa")
    fsa = SimpleNamespace(file=str(fsa_path))

    saved_path = save_ladder_adjustment(fsa, _payload())

    assert saved_path == fsa_path.with_suffix(".ladder_adj.json")
    loaded = load_ladder_adjustment(fsa)
    assert loaded is not None
    assert loaded["schema_version"] == LADDER_ADJUSTMENT_SCHEMA_V2
    assert {key: loaded[key] for key in _payload()} == _payload()
    assert loaded["source"]["sha256"]
    assert loaded["validation"]["save_verified"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_manual_ladder_adjustment_write_failure_is_not_reported_as_success(tmp_path):
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("x", encoding="utf-8")
    fsa = SimpleNamespace(file=str(blocking_file / "sample.fsa"))

    with pytest.raises(RuntimeError, match="Could not save ladder adjustment"):
        save_ladder_adjustment(fsa, _payload())


def test_legacy_index_only_ladder_adjustment_remains_saveable(tmp_path):
    fsa = SimpleNamespace(file=str(tmp_path / "legacy.fsa"))

    save_ladder_adjustment(fsa, {0: 2, 1: 4, 2: 6})

    loaded = load_ladder_adjustment(fsa)
    assert loaded is not None
    assert {key: loaded[key] for key in _payload()} == {
        "mapping": {0: 2, 1: 4, 2: 6},
        "mapping_times": {},
        "manual_candidates": [],
    }


def test_legacy_ladder_adjustment_remains_loadable(tmp_path):
    fsa_path = tmp_path / "legacy.fsa"
    fsa_path.write_bytes(b"legacy")
    fsa_path.with_suffix(".ladder_adj.json").write_text(
        json.dumps({"0": 2, "1": 4, "2": 6}),
        encoding="utf-8",
    )

    loaded = load_ladder_adjustment(SimpleNamespace(file=str(fsa_path)))

    assert loaded == {
        "schema_version": LADDER_ADJUSTMENT_SCHEMA_LEGACY,
        "mapping": {0: 2, 1: 4, 2: 6},
        "mapping_times": {},
        "manual_candidates": [],
    }


def test_v2_adjustment_rejects_different_source_bytes(tmp_path):
    fsa_path = tmp_path / "sample.fsa"
    fsa_path.write_bytes(b"original")
    fsa = SimpleNamespace(file=str(fsa_path))
    save_ladder_adjustment(fsa, _payload())
    fsa_path.write_bytes(b"different")

    assert load_ladder_adjustment(fsa) is None


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("ladder", "LIZ500_250"),
        ("size_standard_channel", "DATA105"),
    ],
)
def test_v2_adjustment_rejects_different_ladder_identity(
    tmp_path,
    changed_field,
    changed_value,
):
    fsa_path = tmp_path / "sample.fsa"
    fsa_path.write_bytes(b"same")
    fsa = SimpleNamespace(
        file=str(fsa_path),
        ladder="GS500ROX",
        size_standard_channel="DATA4",
    )
    save_ladder_adjustment(fsa, _payload())
    setattr(fsa, changed_field, changed_value)

    assert load_ladder_adjustment(fsa) is None


def test_v2_adjustment_records_review_and_selected_peak_provenance(tmp_path):
    fsa_path = tmp_path / "sample.fsa"
    fsa_path.write_bytes(b"fsa")
    fsa = SimpleNamespace(
        file=str(fsa_path),
        analysis_id="flt3",
        assay="ITD",
        ladder="GS500ROX",
        size_standard_channel="DATA4",
        expected_ladder_steps=[35.0, 50.0, 75.0],
    )

    save_ladder_adjustment(
        fsa,
        _payload(),
        operator="chemist",
        comment="confirmed",
        before_qc={"linear_r2": 0.99},
        after_qc={"r2": 0.9999},
    )
    loaded = load_ladder_adjustment(fsa)

    assert loaded is not None
    assert loaded["analysis"] == {
        "analysis_id": "flt3",
        "assay": "ITD",
        "ladder": "GS500ROX",
        "size_standard_channel": "DATA4",
    }
    assert loaded["review"]["operator"] == "chemist"
    assert loaded["review"]["comment"] == "confirmed"
    assert loaded["review"]["before_qc"]["linear_r2"] == 0.99
    assert loaded["review"]["after_qc"]["r2"] == 0.9999
    assert loaded["selected_peaks"] == [
        {
            "step_index": 0,
            "candidate_index": 0,
            "expected_bp": 35.0,
            "observed_time": 100.0,
        },
        {
            "step_index": 1,
            "candidate_index": 1,
            "expected_bp": 50.0,
            "observed_time": 200.0,
        },
        {
            "step_index": 2,
            "candidate_index": 2,
            "expected_bp": 75.0,
            "observed_time": 300.0,
        },
    ]


@pytest.mark.parametrize(
    ("analysis_function", "ladder_name", "profile", "strict"),
    [
        ("analyse_fsa_liz", "LIZ500_250", "clonality_liz500", True),
        ("analyse_fsa_rox", "GS500ROX", "flt3_gs500rox", False),
    ],
)
def test_saved_manual_ladder_is_used_when_rust_returns_no_fit(
    tmp_path,
    monkeypatch,
    analysis_function,
    ladder_name,
    profile,
    strict,
):
    from config import APP_SETTINGS
    from core.analysis import _legacy as analysis
    import core.rust_bridge as rust_bridge

    class FakeFsa:
        def __init__(self, **kwargs):
            self.file = kwargs["file"]
            self.file_name = Path(self.file).name
            self.ladder = kwargs["ladder"]
            self.analysis_id = ""

    sentinel = SimpleNamespace(ladder_fit_strategy="manual_adjustment")
    calls = []

    monkeypatch.setitem(APP_SETTINGS.setdefault("engine", {}), "use_rust", True)
    if strict:
        monkeypatch.setenv("HEMAFRAG_STRICT_RUST_LADDER", "1")
    else:
        monkeypatch.delenv("HEMAFRAG_STRICT_RUST_LADDER", raising=False)
    monkeypatch.setattr(analysis, "FsaFile", FakeFsa)
    monkeypatch.setattr(rust_bridge, "run_ladder_fit_hybrid", lambda *_args: None)
    monkeypatch.setattr(analysis, "load_ladder_adjustment", lambda _fsa: _payload())

    def apply_saved(_fsa, adjustment, label):
        calls.append((adjustment, label))
        return sentinel

    monkeypatch.setattr(analysis, "_try_apply_saved_ladder_adjustment", apply_saved)

    result = getattr(analysis, analysis_function)(
        tmp_path / "sample.fsa",
        "DATA1",
        ladder_name=ladder_name,
        ladder_fit_profile=profile,
    )

    assert result is sentinel
    assert calls == [(_payload(), "LIZ" if "liz" in analysis_function else "ROX")]


def test_review_finalize_rebuild_preserves_cached_qc_entries(tmp_path, monkeypatch):
    from gui_qt.tabs.tab_batch import TabBatch
    import core.batch as batch
    import core.html_reports as html_reports
    from core.analyses.clonality import tracking_excel

    patient_path = tmp_path / "patient.fsa"
    qc_path = tmp_path / "PK_control.fsa"
    patient_path.write_bytes(b"patient")
    qc_path.write_bytes(b"control")
    old_patient = {"original_file_path": str(patient_path), "kind": "old_patient"}
    corrected_patient = {"original_file_path": str(patient_path), "kind": "corrected_patient"}
    cached_qc = {"original_file_path": str(qc_path), "kind": "qc"}
    built = {}

    monkeypatch.setattr(
        batch,
        "run_batch_jobs",
        lambda **_kwargs: {
            "collected_entries": [corrected_patient],
            "qc_report_entries": [],
            "failed_jobs": [],
            "ladder_review_gate": {},
        },
    )
    monkeypatch.setattr(
        html_reports,
        "build_dit_html_reports",
        lambda entries, outdir: built.update(entries=list(entries), outdir=outdir),
    )
    monkeypatch.setattr(tracking_excel, "update_clonality_tracking_workbook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tracking_excel, "update_global_clonality_tracking_workbook", lambda *_args, **_kwargs: None)
    from core.run_manifest import BatchRunManifest

    parent_manifest = BatchRunManifest.create(
        output_dir=tmp_path,
        jobs=[
            {
                "name": "patient",
                "type": "pipeline",
                "path": tmp_path,
                "files": [patient_path],
            },
            {
                "name": "QC",
                "type": "qc",
                "path": tmp_path,
                "files": [qc_path],
            },
        ],
        analysis="clonality",
        settings={},
        execution={},
    )
    parent_manifest.finalize(
        result={
            "completed_jobs": ["patient", "QC"],
            "failed_jobs": [],
            "dit_report_entries": [old_patient, cached_qc],
            "qc_report_entries": [cached_qc],
        },
        aggregate_output_dir=tmp_path,
        review_gate={},
    )

    payload = TabBatch._review_finalize_worker(
        jobs_to_run=[{"name": "patient", "type": "pipeline", "files": [patient_path]}],
        corrected_paths=[patient_path],
        session_entries=[old_patient, cached_qc],
        resolved_review_rows={},
        output_root=tmp_path,
        analysis_id="clonality",
        pipeline_scope="all",
        assay_filter="",
        aggregate_dit_reports=True,
        aggregate_outdir_name="reports_test",
        parent_run_manifest_path=parent_manifest.path,
    )

    assert payload["final_reports_built"] is True
    assert payload["finalization_validation"]["passed"] is True
    assert payload["finalization_validation"]["actual_qc_entries"] == 1
    assert {entry["kind"] for entry in built["entries"]} == {"corrected_patient", "qc"}


def test_review_finalize_blocks_when_original_qc_cohort_is_missing(
    tmp_path,
    monkeypatch,
):
    from core.run_manifest import BatchRunManifest
    from gui_qt.tabs.tab_batch import TabBatch
    import core.batch as batch
    import core.html_reports as html_reports

    patient_path = tmp_path / "patient.fsa"
    qc_path = tmp_path / "PK_control.fsa"
    patient_path.write_bytes(b"patient")
    qc_path.write_bytes(b"control")
    patient_entry = {
        "original_file_path": str(patient_path),
        "kind": "patient",
    }
    qc_entry = {"original_file_path": str(qc_path), "kind": "qc"}
    parent_manifest = BatchRunManifest.create(
        output_dir=tmp_path,
        jobs=[
            {
                "name": "patient",
                "type": "pipeline",
                "path": tmp_path,
                "files": [patient_path],
            },
            {
                "name": "QC",
                "type": "qc",
                "path": tmp_path,
                "files": [qc_path],
            },
        ],
        analysis="clonality",
        settings={},
        execution={},
    )
    parent_manifest.finalize(
        result={
            "completed_jobs": ["patient", "QC"],
            "failed_jobs": [],
            "dit_report_entries": [patient_entry, qc_entry],
            "qc_report_entries": [qc_entry],
        },
        aggregate_output_dir=tmp_path,
        review_gate={},
    )
    monkeypatch.setattr(
        batch,
        "run_batch_jobs",
        lambda **_kwargs: {
            "collected_entries": [patient_entry],
            "qc_report_entries": [],
            "failed_jobs": [],
            "ladder_review_gate": {},
        },
    )
    built = []
    monkeypatch.setattr(
        html_reports,
        "build_dit_html_reports",
        lambda *_args, **_kwargs: built.append(True),
    )

    payload = TabBatch._review_finalize_worker(
        jobs_to_run=[
            {
                "name": "patient",
                "type": "pipeline",
                "files": [patient_path],
            }
        ],
        corrected_paths=[patient_path],
        session_entries=[patient_entry],
        resolved_review_rows={},
        output_root=tmp_path,
        analysis_id="clonality",
        pipeline_scope="all",
        assay_filter="",
        aggregate_dit_reports=True,
        aggregate_outdir_name="reports_test",
        parent_run_manifest_path=parent_manifest.path,
    )

    assert payload["final_reports_built"] is False
    assert payload["finalization_validation"]["passed"] is False
    assert payload["finalization_validation"]["expected_qc_entries"] == 1
    assert payload["finalization_validation"]["actual_qc_entries"] == 0
    assert built == []


def test_review_bundle_restart_recovers_original_patient_and_qc_jobs(
    tmp_path,
    monkeypatch,
):
    import core.batch as batch
    from core.run_manifest import BatchRunManifest
    from gui_qt.tabs.tab_ladder._workers import review_bundle_rerun_worker

    patient_path = tmp_path / "patient.fsa"
    qc_path = tmp_path / "PK_control.fsa"
    patient_path.write_bytes(b"patient")
    qc_path.write_bytes(b"control")
    output_root = tmp_path / "output"
    output_root.mkdir()
    manifest = BatchRunManifest.create(
        output_dir=output_root,
        jobs=[
            {
                "name": "patient",
                "type": "pipeline",
                "path": tmp_path,
                "files": [patient_path],
            },
            {
                "name": "QC",
                "type": "qc",
                "path": tmp_path,
                "files": [qc_path],
            },
        ],
        analysis="clonality",
        settings={},
        execution={"aggregate_dit_reports": True},
    )
    captured = {}

    def fake_run_batch_jobs(**kwargs):
        captured.update(kwargs)
        return {
            "collected_entries": [],
            "qc_report_entries": [],
            "failed_jobs": [],
            "ladder_review_gate": {},
        }

    monkeypatch.setattr(batch, "run_batch_jobs", fake_run_batch_jobs)

    payload = review_bundle_rerun_worker(
        file_paths=[patient_path],
        session_entries=[],
        output_root=output_root,
        analysis_id="clonality",
        pipeline_scope="all",
        assay_filter="",
        aggregate_dit_reports=True,
        aggregate_by_patient=True,
        patient_regex=r"\d{2}OUM\d{5}",
        aggregate_outdir_name="reports_test",
        run_manifest_path=manifest.path,
    )

    assert payload["recovered_from_run_manifest"] is True
    assert captured["parent_run_manifest_path"] == manifest.path
    assert [job["name"] for job in captured["jobs"]] == ["patient", "QC"]
    assert captured["jobs"][1]["files"] == [qc_path.resolve()]
