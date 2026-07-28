from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.analysis import load_ladder_adjustment, save_ladder_adjustment


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
    assert load_ladder_adjustment(fsa) == _payload()
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

    assert load_ladder_adjustment(fsa) == {
        "mapping": {0: 2, 1: 4, 2: 6},
        "mapping_times": {},
        "manual_candidates": [],
    }


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
    )

    assert payload["final_reports_built"] is True
    assert {entry["kind"] for entry in built["entries"]} == {"corrected_patient", "qc"}
