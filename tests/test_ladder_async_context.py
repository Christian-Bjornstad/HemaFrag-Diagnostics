"""Ladder worker callbacks must stay bound to the context that started them."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from PyQt6.QtWidgets import QApplication

from config import APP_SETTINGS
from gui_qt.tabs.tab_ladder import TabLadder


class ControlledThreadPool:
    """Collect workers so tests can emit their results in a chosen order."""

    def __init__(self) -> None:
        self.workers = []

    def start(self, worker) -> None:
        self.workers.append(worker)


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ladder(qapp, monkeypatch):
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    widget = TabLadder()
    widget.threadpool = ControlledThreadPool()
    yield widget
    widget.close()


def _metadata_result(file_path: Path) -> dict:
    return {
        "file_path": file_path,
        "meta": {"analysis": "clonality", "ladder": "ROX400HD"},
        "fsa": object(),
    }


def _rerun_settings(tmp_path: Path) -> dict:
    return {
        "analysis_id": "clonality",
        "output_root": tmp_path / "output",
        "aggregate_outdir_name": None,
        "aggregate_dit_reports": True,
        "aggregate_by_patient": True,
        "patient_regex": r"\d+",
        "pipeline_scope": "all",
        "assay_filter": "",
    }


def _start_source_operation(ladder, kind: str, source_dir: Path, bundle_dir: Path):
    if kind == "scan":
        ladder.source_dir.setText(str(source_dir))
        ladder._scan_files()
    else:
        ladder.load_review_bundle_from_path(bundle_dir)
    return ladder.threadpool.workers[-1]


def _emit_source_outcome(
    worker,
    *,
    kind: str,
    outcome: str,
    scan_file: Path,
    bundle_dir: Path,
) -> None:
    if outcome == "error":
        worker.signals.error.emit(
            (RuntimeError, RuntimeError(f"{kind} source failure"), "")
        )
    elif kind == "scan":
        worker.signals.result.emit([scan_file])
    else:
        worker.signals.result.emit(
            {
                "bundle_dir": bundle_dir,
                "run_manifest_path": None,
                "rows": [],
                "missing_paths": [],
            }
        )


def _start_rerun(ladder, monkeypatch, tmp_path: Path, rerun_kind: str) -> None:
    current_file = ladder._current_file
    assert current_file is not None
    monkeypatch.setattr(
        ladder,
        "_resolve_rerun_settings",
        lambda *_: _rerun_settings(tmp_path),
    )
    if rerun_kind == "single":
        ladder._rerun_current_file_reports()
        assert ladder._single_rerun_active
        return

    ladder._review_bundle_dir = tmp_path / "loaded-bundle"
    ladder._review_bundle_cases = [
        {
            "full_path": str(current_file),
            "file": current_file.name,
            "label": "manual_adjusted",
        }
    ]
    ladder._rerun_review_bundle_reports()
    assert ladder._review_bundle_rerun_active


def test_metadata_callback_is_discarded_after_analysis_switch(
    ladder, monkeypatch, tmp_path
):
    source = tmp_path / "sample.fsa"
    source.touch()
    ladder._current_file = source
    ladder._pending_open_editor_after_metadata = True
    apply_result = Mock()
    monkeypatch.setattr(ladder, "_apply_metadata_result", apply_result)

    ladder._start_metadata_load(source)
    worker = ladder.threadpool.workers[-1]

    APP_SETTINGS["active_analysis"] = "flt3"
    ladder.set_analysis("flt3")
    worker.signals.result.emit(_metadata_result(source))

    apply_result.assert_not_called()
    assert ladder._current_analysis_id == "flt3"
    assert ladder._current_meta is None
    assert not ladder._pending_open_editor_after_metadata
    assert not ladder.btn_open_editor.isEnabled()


def test_metadata_callback_is_discarded_after_visible_file_changes(
    ladder, monkeypatch, tmp_path
):
    first = tmp_path / "first.fsa"
    second = tmp_path / "second.fsa"
    first.touch()
    second.touch()
    ladder._current_file = first
    apply_result = Mock()
    monkeypatch.setattr(ladder, "_apply_metadata_result", apply_result)

    ladder._start_metadata_load(first)
    worker = ladder.threadpool.workers[-1]
    ladder._current_file = second
    worker.signals.result.emit(_metadata_result(first))

    apply_result.assert_not_called()
    assert ladder._current_file == second
    assert not ladder.btn_open_editor.isEnabled()


def test_stale_metadata_error_does_not_finish_the_current_file_load(
    ladder, tmp_path
):
    first = tmp_path / "first.fsa"
    second = tmp_path / "second.fsa"
    first.touch()
    second.touch()
    ladder._current_file = first
    ladder._start_metadata_load(first)
    first_worker = ladder.threadpool.workers[-1]

    ladder._current_file = second
    ladder._start_metadata_load(second)
    first_worker.signals.error.emit((RuntimeError, RuntimeError("old failure"), ""))

    assert ladder._current_file == second
    assert ladder._metadata_loading
    assert not ladder.btn_open_editor.isEnabled()
    assert "old failure" not in ladder.status_lbl.text()


@pytest.mark.parametrize(
    ("owner_kind", "attempted_kind"),
    [("scan", "bundle_load"), ("bundle_load", "scan")],
)
@pytest.mark.parametrize("owner_outcome", ["success", "error"])
def test_active_source_operation_rejects_programmatic_competitor_and_finishes_owner(
    ladder,
    tmp_path,
    owner_kind,
    attempted_kind,
    owner_outcome,
):
    source_dir = tmp_path / "source"
    bundle_dir = tmp_path / "bundle"
    original_bundle = tmp_path / "original-bundle"
    original_file = tmp_path / "original.fsa"
    scan_file = tmp_path / "scan-result.fsa"
    source_dir.mkdir()
    bundle_dir.mkdir()
    original_bundle.mkdir()
    original_file.touch()
    scan_file.touch()
    ladder._review_bundle_dir = original_bundle
    ladder.review_bundle_dir.setText(str(original_bundle))
    ladder._all_files = [original_file]

    owner_worker = _start_source_operation(
        ladder, owner_kind, source_dir, bundle_dir
    )
    request_id = ladder._scan_request_id
    _start_source_operation(ladder, attempted_kind, source_dir, bundle_dir)

    assert ladder.threadpool.workers == [owner_worker]
    assert ladder._scan_request_id == request_id
    assert "source load is already active" in ladder.status_lbl.text().lower()
    expected_bundle_text = (
        str(bundle_dir) if owner_kind == "bundle_load" else str(original_bundle)
    )
    assert ladder.review_bundle_dir.text() == expected_bundle_text
    assert not ladder.btn_scan.isEnabled()
    assert not ladder.btn_load_bundle.isEnabled()

    _emit_source_outcome(
        owner_worker,
        kind=owner_kind,
        outcome=owner_outcome,
        scan_file=scan_file,
        bundle_dir=bundle_dir,
    )

    assert ladder.btn_scan.isEnabled()
    assert ladder.btn_load_bundle.isEnabled()

    if owner_kind == "scan":
        assert ladder._review_bundle_dir == original_bundle
        if owner_outcome == "success":
            assert ladder._all_files == [scan_file.resolve()]
        else:
            assert ladder._all_files == [original_file]
            assert "scan source failure" in ladder.status_lbl.text()
    elif owner_outcome == "success":
        assert ladder._review_bundle_dir == bundle_dir
        assert ladder._all_files == []
    else:
        assert ladder._review_bundle_dir == original_bundle
        assert ladder._all_files == [original_file]
        assert "bundle_load source failure" in ladder.status_lbl.text()


@pytest.mark.parametrize("source_kind", ["scan", "bundle_load"])
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_analysis_switch_discards_stale_source_callback(
    ladder,
    tmp_path,
    source_kind,
    outcome,
):
    source_dir = tmp_path / "source"
    bundle_dir = tmp_path / "bundle"
    original_bundle = tmp_path / "original-bundle"
    original_file = tmp_path / "original.fsa"
    stale_file = tmp_path / "stale.fsa"
    source_dir.mkdir()
    bundle_dir.mkdir()
    original_bundle.mkdir()
    original_file.touch()
    stale_file.touch()
    ladder._review_bundle_dir = original_bundle
    ladder._all_files = [original_file]

    stale_worker = _start_source_operation(
        ladder,
        source_kind,
        source_dir,
        bundle_dir,
    )

    assert ladder.set_analysis("flt3") is True
    switched_status = ladder.status_lbl.text()
    _emit_source_outcome(
        stale_worker,
        kind=source_kind,
        outcome=outcome,
        scan_file=stale_file,
        bundle_dir=bundle_dir,
    )

    assert ladder._current_analysis_id == "flt3"
    assert ladder._all_files == [original_file]
    assert ladder._review_bundle_dir == original_bundle
    assert ladder.status_lbl.text() == switched_status
    assert ladder.btn_scan.isEnabled()


@pytest.mark.parametrize("rerun_attr", ["_single_rerun_active", "_review_bundle_rerun_active"])
def test_active_rerun_rejects_programmatic_source_file_and_bundle_switches(
    ladder, tmp_path, rerun_attr
):
    original_file = tmp_path / "original.fsa"
    other_file = tmp_path / "other.fsa"
    source = tmp_path / "source"
    bundle = tmp_path / "bundle"
    original_file.touch()
    other_file.touch()
    source.mkdir()
    bundle.mkdir()
    ladder._current_file = original_file
    ladder.source_dir.setText(str(source))
    original_bundle_text = ladder.review_bundle_dir.text()
    setattr(ladder, rerun_attr, True)

    ladder._scan_files()
    ladder._update_current_file(other_file)
    ladder.load_review_bundle_from_path(bundle, auto_open_first=True)

    assert ladder.threadpool.workers == []
    assert ladder._current_file == original_file
    assert ladder.review_bundle_dir.text() == original_bundle_text
    assert not ladder._auto_open_review_editor_once
    assert "rerun" in ladder.status_lbl.text().lower()


@pytest.mark.parametrize("rerun_kind", ["single", "bundle"])
@pytest.mark.parametrize("source_kind", ["scan", "bundle_load"])
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_source_callback_started_before_rerun_cannot_mutate_or_unlock_context(
    ladder, monkeypatch, tmp_path, rerun_kind, source_kind, outcome
):
    current_file = tmp_path / "current.fsa"
    intruder_file = tmp_path / "intruder.fsa"
    source_dir = tmp_path / "source"
    pending_bundle = tmp_path / "pending-bundle"
    current_file.touch()
    intruder_file.touch()
    source_dir.mkdir()
    pending_bundle.mkdir()
    ladder._current_file = current_file
    ladder._all_files = [current_file]

    if source_kind == "scan":
        ladder.source_dir.setText(str(source_dir))
        ladder._scan_files()
    else:
        ladder.review_bundle_dir.setText(str(pending_bundle))
        ladder._load_review_bundle()
    stale_worker = ladder.threadpool.workers[-1]

    _start_rerun(ladder, monkeypatch, tmp_path, rerun_kind)
    rerun_status = ladder.status_lbl.text()
    expected_bundle = ladder._review_bundle_dir

    if outcome == "error":
        stale_worker.signals.error.emit(
            (RuntimeError, RuntimeError("stale source failure"), "")
        )
    elif source_kind == "scan":
        stale_worker.signals.result.emit([intruder_file])
    else:
        stale_worker.signals.result.emit(
            {
                "bundle_dir": pending_bundle,
                "run_manifest_path": None,
                "rows": [
                    {
                        "full_path": str(intruder_file),
                        "file": intruder_file.name,
                        "label": "",
                    }
                ],
                "missing_paths": [],
            }
        )

    assert ladder._current_file == current_file
    assert ladder._all_files == [current_file]
    assert ladder._review_bundle_dir == expected_bundle
    assert ladder.status_lbl.text() == rerun_status
    assert not ladder.btn_scan.isEnabled()
    assert not ladder.btn_load_bundle.isEnabled()
    assert not ladder.file_list.isEnabled()


@pytest.mark.parametrize("rerun_kind", ["single", "bundle"])
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_metadata_callback_started_before_rerun_cannot_mutate_or_unlock_context(
    ladder, monkeypatch, tmp_path, rerun_kind, outcome
):
    current_file = tmp_path / "current.fsa"
    current_file.touch()
    ladder._current_file = current_file
    apply_result = Mock()
    monkeypatch.setattr(ladder, "_apply_metadata_result", apply_result)
    ladder._pending_open_editor_after_metadata = True
    ladder._start_metadata_load(current_file)
    stale_worker = ladder.threadpool.workers[-1]

    _start_rerun(ladder, monkeypatch, tmp_path, rerun_kind)
    rerun_status = ladder.status_lbl.text()
    if outcome == "success":
        stale_worker.signals.result.emit(_metadata_result(current_file))
    else:
        stale_worker.signals.error.emit(
            (RuntimeError, RuntimeError("stale metadata failure"), "")
        )

    apply_result.assert_not_called()
    assert ladder._current_file == current_file
    assert ladder._current_meta is None
    assert not ladder._pending_open_editor_after_metadata
    assert ladder.status_lbl.text() == rerun_status
    assert not ladder.btn_open_editor.isEnabled()
    assert not ladder.btn_refresh_meta.isEnabled()
    assert not ladder.file_list.isEnabled()
