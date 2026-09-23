import copy
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from config import APP_SETTINGS
from gui_qt.operation_coordinator import OperationStartRejected
from gui_qt.tabs.tab_ladder import TabLadder


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class _Handle:
    def __init__(self):
        self.running = False
        self.critical_write = False
        self.settled = False

    def mark_running(self):
        self.running = True

    def mark_critical_write(self):
        self.critical_write = True

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
        self.calls.append({"kind": kind, "cancel": cancel, "handle": handle})
        return handle


class _ThreadPool:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.started = []

    def start(self, worker):
        self.started.append(worker)
        if self.fail:
            raise RuntimeError("thread pool unavailable")


@pytest.fixture
def ladder_tab(qapp, monkeypatch):
    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args, **_kwargs: None)
    tab = TabLadder()
    tab.threadpool = _ThreadPool()
    yield tab
    tab.close()
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


def _settings(tmp_path: Path) -> dict:
    return {
        "analysis_id": "clonality",
        "output_root": tmp_path,
        "pipeline_scope": "all",
        "assay_filter": "",
        "aggregate_dit_reports": True,
        "aggregate_by_patient": True,
        "patient_regex": r"\d+",
        "aggregate_outdir_name": None,
    }


def _prepare_single(ladder_tab, tmp_path, monkeypatch):
    source = tmp_path / "single.fsa"
    source.write_bytes(b"synthetic")
    ladder_tab._current_file = source
    ladder_tab.btn_rerun_file.setEnabled(True)
    monkeypatch.setattr(ladder_tab, "_run_tab_for_review", lambda: None)
    monkeypatch.setattr(
        ladder_tab,
        "_resolve_rerun_settings",
        lambda *_: _settings(tmp_path),
    )
    return source


def _prepare_bundle(ladder_tab, tmp_path, monkeypatch):
    source = tmp_path / "bundle.fsa"
    source.write_bytes(b"synthetic")
    ladder_tab._review_bundle_dir = tmp_path / "review"
    ladder_tab._review_bundle_dir.mkdir()
    ladder_tab._review_bundle_cases = [
        {"full_path": str(source), "label": "manual_adjusted"}
    ]
    monkeypatch.setattr(
        ladder_tab,
        "_resolve_rerun_settings",
        lambda *_: _settings(tmp_path),
    )
    return source


def _prepare_exclusion(ladder_tab, tmp_path, monkeypatch):
    source = tmp_path / "excluded.fsa"
    source.write_bytes(b"synthetic")
    cache_key = ladder_tab._resolve_cache_key(source)
    ladder_tab._current_file = source
    ladder_tab._review_bundle_dir = tmp_path / "review"
    ladder_tab._review_bundle_dir.mkdir()
    ladder_tab._review_case_by_path = {
        cache_key: {"full_path": str(source), "label": "", "adjustment_path": ""}
    }
    ladder_tab.btn_exclude_missing_ladder.setEnabled(True)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    return cache_key


def test_single_rerun_registers_before_start_and_settles_on_finish(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_single(ladder_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)

    ladder_tab._rerun_current_file_reports()

    assert coordinator.calls[0]["kind"] == "Ladder single-file rerun"
    assert coordinator.calls[0]["handle"].running is True
    assert coordinator.calls[0]["handle"].critical_write is True
    assert len(ladder_tab.threadpool.started) == 1
    coordinator.calls[0]["cancel"]()
    assert coordinator.calls[0]["handle"].settled is False

    ladder_tab.threadpool.started[0].signals.finished.emit()
    assert coordinator.calls[0]["handle"].settled is True


def test_single_rerun_rejection_leaves_tab_idle(ladder_tab, tmp_path, monkeypatch):
    _prepare_single(ladder_tab, tmp_path, monkeypatch)
    ladder_tab.set_operation_coordinator(_Coordinator(reject=True))

    ladder_tab._rerun_current_file_reports()

    assert ladder_tab.threadpool.started == []
    assert ladder_tab._single_rerun_active is False
    assert ladder_tab.source_dir.isEnabled()
    assert "closing" in ladder_tab.status_lbl.text().lower()


def test_single_rerun_start_failure_settles_and_restores_ui(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_single(ladder_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)
    ladder_tab.threadpool = _ThreadPool(fail=True)

    ladder_tab._rerun_current_file_reports()

    assert coordinator.calls[0]["handle"].settled is True
    assert ladder_tab._single_rerun_active is False
    assert ladder_tab.source_dir.isEnabled()
    assert ladder_tab.btn_rerun_file.isEnabled()
    assert "could not start" in ladder_tab.status_lbl.text().lower()


def test_bundle_rerun_registers_and_settles_on_finish(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_bundle(ladder_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)

    ladder_tab._rerun_review_bundle_reports()

    assert coordinator.calls[0]["kind"] == "Ladder review-bundle rerun"
    assert coordinator.calls[0]["handle"].running is True
    assert coordinator.calls[0]["handle"].critical_write is True
    assert len(ladder_tab.threadpool.started) == 1
    ladder_tab.threadpool.started[0].signals.finished.emit()
    assert coordinator.calls[0]["handle"].settled is True


def test_bundle_rerun_rejection_leaves_tab_idle(ladder_tab, tmp_path, monkeypatch):
    _prepare_bundle(ladder_tab, tmp_path, monkeypatch)
    ladder_tab.set_operation_coordinator(_Coordinator(reject=True))

    ladder_tab._rerun_review_bundle_reports()

    assert ladder_tab.threadpool.started == []
    assert ladder_tab._review_bundle_rerun_active is False
    assert ladder_tab.source_dir.isEnabled()
    assert "closing" in ladder_tab.status_lbl.text().lower()


def test_bundle_rerun_start_failure_settles_and_restores_ui(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_bundle(ladder_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)
    ladder_tab.threadpool = _ThreadPool(fail=True)

    ladder_tab._rerun_review_bundle_reports()

    assert coordinator.calls[0]["handle"].settled is True
    assert ladder_tab._review_bundle_rerun_active is False
    assert ladder_tab.source_dir.isEnabled()
    assert "could not start" in ladder_tab.status_lbl.text().lower()


def test_missing_ladder_exclusion_registers_write_and_settles_on_finish(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_exclusion(ladder_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)

    ladder_tab._exclude_current_missing_ladder_signal()

    assert coordinator.calls[0]["kind"] == "Ladder missing-ladder exclusion"
    assert coordinator.calls[0]["handle"].running is True
    assert coordinator.calls[0]["handle"].critical_write is True
    assert len(ladder_tab.threadpool.started) == 1
    ladder_tab.threadpool.started[0].signals.finished.emit()
    assert coordinator.calls[0]["handle"].settled is True


def test_missing_ladder_exclusion_rejection_keeps_action_available(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_exclusion(ladder_tab, tmp_path, monkeypatch)
    ladder_tab.set_operation_coordinator(_Coordinator(reject=True))

    ladder_tab._exclude_current_missing_ladder_signal()

    assert ladder_tab.threadpool.started == []
    assert ladder_tab.btn_exclude_missing_ladder.isEnabled()
    assert "closing" in ladder_tab.status_lbl.text().lower()


def test_missing_ladder_exclusion_start_failure_settles_and_restores_action(
    ladder_tab, tmp_path, monkeypatch
):
    _prepare_exclusion(ladder_tab, tmp_path, monkeypatch)
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)
    ladder_tab.threadpool = _ThreadPool(fail=True)

    ladder_tab._exclude_current_missing_ladder_signal()

    assert coordinator.calls[0]["handle"].settled is True
    assert ladder_tab.btn_exclude_missing_ladder.isEnabled()
    assert "could not start" in ladder_tab.status_lbl.text().lower()


def _start_read_worker(tab, tmp_path, operation):
    source = tmp_path / "read.fsa"
    source.write_bytes(b"synthetic")
    if operation == "scan":
        tab.source_dir.setText(str(tmp_path))
        tab._scan_files()
    elif operation == "bundle":
        tab.review_bundle_dir.setText(str(tmp_path))
        tab._load_review_bundle()
    elif operation == "metadata":
        tab._current_file = source
        tab._start_metadata_load(source)
    else:
        tab._current_file = source
        tab.report_root.setText(str(tmp_path))
        tab._refresh_report_matches()


@pytest.mark.parametrize(
    ("operation", "kind"),
    [
        ("scan", "Ladder source scan"),
        ("bundle", "Ladder review-bundle load"),
        ("metadata", "Ladder metadata load"),
        ("report", "Ladder report search"),
    ],
)
def test_read_workers_register_and_settle(ladder_tab, tmp_path, operation, kind):
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)

    _start_read_worker(ladder_tab, tmp_path, operation)

    assert coordinator.calls[0]["kind"] == kind
    assert coordinator.calls[0]["handle"].running is True
    assert coordinator.calls[0]["handle"].critical_write is False
    assert len(ladder_tab.threadpool.started) == 1
    coordinator.calls[0]["cancel"]()
    ladder_tab.threadpool.started[0].signals.finished.emit()
    assert coordinator.calls[0]["handle"].settled is True


def test_failed_worker_still_settles(ladder_tab, tmp_path):
    coordinator = _Coordinator()
    ladder_tab.set_operation_coordinator(coordinator)
    _start_read_worker(ladder_tab, tmp_path, "scan")

    worker = ladder_tab.threadpool.started[0]
    worker.signals.error.emit((RuntimeError, RuntimeError("scan failed"), ""))
    worker.signals.finished.emit()

    assert coordinator.calls[0]["handle"].settled is True
    assert ladder_tab._source_load_active is False


@pytest.mark.parametrize("operation", ["scan", "bundle", "metadata", "report"])
@pytest.mark.parametrize("failure", ["reject", "start"])
def test_read_worker_failure_restores_ui(ladder_tab, tmp_path, operation, failure):
    coordinator = _Coordinator(reject=failure == "reject")
    ladder_tab.set_operation_coordinator(coordinator)
    ladder_tab.threadpool = _ThreadPool(fail=failure == "start")

    _start_read_worker(ladder_tab, tmp_path, operation)

    if failure == "reject":
        assert ladder_tab.threadpool.started == []
        assert "closing" in ladder_tab.status_lbl.text().lower()
    else:
        assert coordinator.calls[0]["handle"].settled is True
        assert "could not start" in ladder_tab.status_lbl.text().lower()
    if operation in {"scan", "bundle"}:
        assert ladder_tab._source_load_active is False
        assert ladder_tab.btn_scan.isEnabled()
    elif operation == "metadata":
        assert ladder_tab._metadata_loading is False
        assert ladder_tab._metadata_request_context is None
        assert ladder_tab.btn_open_editor.isEnabled()
    else:
        assert ladder_tab.btn_find_reports.isEnabled()
