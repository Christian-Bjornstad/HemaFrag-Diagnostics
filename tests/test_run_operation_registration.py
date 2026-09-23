import copy
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from config import APP_SETTINGS
from gui_qt.operation_coordinator import OperationStartRejected
from gui_qt.tabs.tab_batch import TabBatch


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class _Handle:
    def __init__(self):
        self.running = False
        self.settled = False

    def mark_running(self):
        self.running = True

    def settle(self):
        self.settled = True


class _Coordinator:
    def __init__(self, *, reject=False):
        self.reject = reject
        self.calls = []

    def register(self, kind, *, cancel, run_id=None, operation_id=None):
        if self.reject:
            raise OperationStartRejected("Application is closing")
        handle = _Handle()
        self.calls.append(
            {
                "kind": kind,
                "cancel": cancel,
                "run_id": run_id,
                "operation_id": operation_id,
                "handle": handle,
            }
        )
        return handle


class _ThreadPool:
    def __init__(self):
        self.started = []

    def start(self, worker):
        self.started.append(worker)


class _FailingThreadPool(_ThreadPool):
    def start(self, worker):
        self.started.append(worker)
        raise RuntimeError("thread pool unavailable")


@pytest.fixture
def run_tab(qapp, monkeypatch):
    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.save_settings", lambda *_: None)
    tab = TabBatch()
    tab.threadpool = _ThreadPool()
    yield tab
    tab.close()
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


def _prepare_batch(tab: TabBatch, output_root: Path, monkeypatch) -> None:
    tab._detected_jobs = [
        {"name": "Patient 1", "type": "pipeline", "files": []},
    ]
    tab._job_states = {0: "pending"}
    tab._rebuild_table()
    tab.table.selectRow(0)
    tab.btn_run.setEnabled(True)
    monkeypatch.setattr(tab, "_resolve_output_path_str", lambda: str(output_root))


def test_run_batch_registers_before_start_and_settles_on_worker_finish(
    run_tab, tmp_path, monkeypatch
):
    _prepare_batch(run_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    run_tab.set_operation_coordinator(coordinator)

    run_tab.on_run()

    assert len(coordinator.calls) == 1
    registration = coordinator.calls[0]
    assert registration["kind"] == "Run batch"
    assert registration["handle"].running is True
    assert len(run_tab.threadpool.started) == 1

    registration["cancel"]()
    assert run_tab._active_run_cancel_event.is_set()

    run_tab.threadpool.started[0].signals.finished.emit()
    assert registration["handle"].settled is True


def test_run_scan_registers_before_start_and_settles_on_finish(
    run_tab, tmp_path, monkeypatch
):
    source = tmp_path / "scan.fsa"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(run_tab, "_general_selected_paths", lambda: [source])
    coordinator = _Coordinator()
    run_tab.set_operation_coordinator(coordinator)

    run_tab.on_scan()

    assert coordinator.calls[0]["kind"] == "Run scan"
    assert coordinator.calls[0]["handle"].running is True
    assert len(run_tab.threadpool.started) == 1
    coordinator.calls[0]["cancel"]()
    assert coordinator.calls[0]["handle"].settled is False
    run_tab.threadpool.started[0].signals.finished.emit()
    assert coordinator.calls[0]["handle"].settled is True


def test_run_scan_rejected_during_close_restores_controls(
    run_tab, tmp_path, monkeypatch
):
    source = tmp_path / "scan.fsa"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(run_tab, "_general_selected_paths", lambda: [source])
    run_tab.set_operation_coordinator(_Coordinator(reject=True))

    run_tab.on_scan()

    assert run_tab.threadpool.started == []
    assert run_tab.is_scan_active() is False
    assert run_tab.btn_scan.isEnabled() is True
    assert "closing" in run_tab.status_lbl.text().lower()


def test_run_scan_pool_failure_settles_and_restores_controls(
    run_tab, tmp_path, monkeypatch
):
    source = tmp_path / "scan.fsa"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(run_tab, "_general_selected_paths", lambda: [source])
    coordinator = _Coordinator()
    run_tab.set_operation_coordinator(coordinator)

    class FailingPool:
        def start(self, _worker):
            raise RuntimeError("pool unavailable")

    run_tab.threadpool = FailingPool()
    run_tab.on_scan()

    assert coordinator.calls[0]["handle"].settled is True
    assert run_tab.is_scan_active() is False
    assert run_tab.btn_scan.isEnabled() is True
    assert "pool unavailable" in run_tab.status_lbl.text().lower()


def test_run_batch_rejection_leaves_previous_review_and_idle_controls_intact(
    run_tab, tmp_path, monkeypatch
):
    _prepare_batch(run_tab, tmp_path, monkeypatch)
    run_tab._review_session_active = True
    run_tab._review_session_jobs = [{"name": "existing review"}]
    run_tab.set_operation_coordinator(_Coordinator(reject=True))
    persisted = []
    monkeypatch.setattr(run_tab, "_is_general_analysis", lambda: True)
    monkeypatch.setattr(run_tab, "_persist_general_runtime_settings", lambda: persisted.append(True))

    run_tab.on_run()

    assert run_tab.threadpool.started == []
    assert run_tab._active_run_cancel_event is None
    assert run_tab._review_session_active is True
    assert run_tab._review_session_jobs == [{"name": "existing review"}]
    assert run_tab.btn_stop.isVisible() is False
    assert run_tab.btn_run.isEnabled() is True
    assert run_tab._job_states[0] == "pending"
    assert "closing" in run_tab.status_lbl.text().lower()
    assert persisted == []


def test_run_batch_start_failure_settles_handle_and_restores_idle_state(
    run_tab, tmp_path, monkeypatch
):
    _prepare_batch(run_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    run_tab.set_operation_coordinator(coordinator)
    run_tab.threadpool = _FailingThreadPool()
    run_tab._review_session_active = True
    run_tab._review_session_jobs = [{"name": "existing review"}]

    run_tab.on_run()

    handle = coordinator.calls[0]["handle"]
    assert handle.settled is True
    assert run_tab._active_run_cancel_event is None
    assert run_tab.btn_stop.isVisible() is False
    assert run_tab.btn_run.isEnabled() is True
    assert run_tab._job_states[0] == "pending"
    assert run_tab._review_session_active is True
    assert run_tab._review_session_jobs == [{"name": "existing review"}]
    assert "could not start" in run_tab.status_lbl.text().lower()


def test_review_finalization_is_registered_and_close_waits_for_worker_finish(
    run_tab, tmp_path, monkeypatch
):
    coordinator = _Coordinator()
    run_tab.set_operation_coordinator(coordinator)
    run_tab._review_session_active = True
    run_tab._review_corrected_paths = {tmp_path / "case.fsa"}
    run_tab._review_session_output_root = tmp_path
    run_tab._review_session_entries_by_path = {}
    run_tab._review_session_bundle_dir = tmp_path / "review"
    run_tab._review_session_jobs = [{"name": "Patient 1", "type": "pipeline", "files": []}]
    run_tab.btn_run_reviewed.setEnabled(True)
    monkeypatch.setattr(run_tab, "_review_bundle_resolution_counts", lambda *_: (1, 0))
    monkeypatch.setattr(
        run_tab,
        "_linked_jobs_for_corrected_files",
        lambda *_: [{"name": "Patient 1", "type": "pipeline", "files": []}],
    )
    monkeypatch.setattr(run_tab, "_resolved_review_rows_from_bundle", lambda *_: {})

    run_tab.on_run_reviewed()

    assert len(coordinator.calls) == 1
    registration = coordinator.calls[0]
    assert registration["kind"] == "Run review finalization"
    assert registration["handle"].running is True
    assert len(run_tab.threadpool.started) == 1

    # This writer has no safe mid-operation boundary. Cancellation is therefore
    # intentionally deferred while the coordinator keeps the app open.
    registration["cancel"]()
    assert registration["handle"].settled is False

    run_tab.threadpool.started[0].signals.finished.emit()
    assert registration["handle"].settled is True


def test_review_finalization_rejection_restores_review_action(
    run_tab, tmp_path, monkeypatch
):
    run_tab.set_operation_coordinator(_Coordinator(reject=True))
    run_tab._review_session_active = True
    run_tab._review_corrected_paths = {tmp_path / "case.fsa"}
    run_tab._review_session_output_root = tmp_path
    run_tab._review_session_entries_by_path = {}
    run_tab._review_session_bundle_dir = tmp_path / "review"
    run_tab._review_session_jobs = [{"name": "Patient 1", "type": "pipeline", "files": []}]
    run_tab.btn_run_reviewed.setEnabled(True)
    monkeypatch.setattr(run_tab, "_review_bundle_resolution_counts", lambda *_: (1, 0))
    monkeypatch.setattr(
        run_tab,
        "_linked_jobs_for_corrected_files",
        lambda *_: [{"name": "Patient 1", "type": "pipeline", "files": []}],
    )
    monkeypatch.setattr(run_tab, "_resolved_review_rows_from_bundle", lambda *_: {})

    run_tab.on_run_reviewed()

    assert run_tab.threadpool.started == []
    assert run_tab._review_finalize_active is False
    assert run_tab.btn_scan.isEnabled() is True
    assert run_tab.btn_run_reviewed.isEnabled() is True
    assert "closing" in run_tab.status_lbl.text().lower()


def test_review_finalization_start_failure_settles_and_restores_review_action(
    run_tab, tmp_path, monkeypatch
):
    coordinator = _Coordinator()
    run_tab.set_operation_coordinator(coordinator)
    run_tab.threadpool = _FailingThreadPool()
    run_tab._review_session_active = True
    run_tab._review_corrected_paths = {tmp_path / "case.fsa"}
    run_tab._review_session_output_root = tmp_path
    run_tab._review_session_entries_by_path = {}
    run_tab._review_session_bundle_dir = tmp_path / "review"
    run_tab._review_session_jobs = [{"name": "Patient 1", "type": "pipeline", "files": []}]
    run_tab.btn_run_reviewed.setEnabled(True)
    monkeypatch.setattr(run_tab, "_review_bundle_resolution_counts", lambda *_: (1, 0))
    monkeypatch.setattr(
        run_tab,
        "_linked_jobs_for_corrected_files",
        lambda *_: [{"name": "Patient 1", "type": "pipeline", "files": []}],
    )
    monkeypatch.setattr(run_tab, "_resolved_review_rows_from_bundle", lambda *_: {})

    run_tab.on_run_reviewed()

    handle = coordinator.calls[0]["handle"]
    assert handle.settled is True
    assert run_tab._review_finalize_active is False
    assert run_tab.btn_scan.isEnabled() is True
    assert run_tab.btn_run_reviewed.isEnabled() is True
    assert "could not start" in run_tab.status_lbl.text().lower()
