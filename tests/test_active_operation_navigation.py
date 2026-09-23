"""Worker-backed operations must retain their analysis and review context."""

import copy
import os
import threading

import pytest
from PyQt6.QtWidgets import QApplication

from config import APP_SETTINGS
from gui_qt.main_window import MainWindow


@pytest.fixture
def window(monkeypatch, tmp_path, qapp):
    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(tmp_path / "ladder.sqlite"))
    monkeypatch.setattr("gui_qt.main_window.save_settings", lambda *_: None)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    widget = MainWindow()
    yield widget
    widget.close()
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_run_blocks_group_click_shortcut_and_settings_without_losing_review(window):
    run = window.tab_run
    job = object()
    run._active_run_jobs = [job]
    run._progress_job_rows = [0]
    run._active_run_cancel_event = threading.Event()
    original_page = window.stacked_widget.currentIndex()

    window.on_group_clicked(window.group_clonality)
    window.on_group_clicked(window.group_flt3)
    window._activate_group(1)
    window.on_sub_tab_clicked("flt3", 0)
    window._activate_settings()
    window._on_settings_saved("clonality")
    window._open_archive_ladder_review("clonality", "unused")

    assert APP_SETTINGS["active_analysis"] == "clonality"
    assert window.stacked_widget.currentIndex() == original_page
    assert run._active_run_jobs == [job]
    assert run._progress_job_rows == [0]
    assert run._active_run_cancel_event is not None
    assert not window.settings_changes_allowed()
    assert "active" in window.statusBar().currentMessage()
    assert window.group_clonality.btn_run.isChecked()
    assert not window.group_clonality.btn_settings.isChecked()

    window.on_sub_tab_clicked("clonality", window.group_clonality.sub_button_labels.index("Log"))
    assert window.stacked_widget.currentIndex() == window.tab_log_idx
    run._active_run_cancel_event = None
    assert window.settings_changes_allowed()
    window.on_group_clicked(window.group_flt3)
    assert APP_SETTINGS["active_analysis"] == "flt3"


@pytest.mark.parametrize("operation", ["archive", "ladder"])
def test_other_workers_block_programmatic_analysis_and_release(window, monkeypatch, operation):
    if operation == "archive":
        window.tab_archive_runner._active_worker = object()
    else:
        monkeypatch.setattr(window.tab_ladder, "is_operation_active", lambda: True)

    assert window._activate_analysis("flt3") is False
    window.on_sub_tab_clicked("flt3", 0)
    assert APP_SETTINGS["active_analysis"] == "clonality"
    assert not window.settings_changes_allowed()

    if operation == "archive":
        window.tab_archive_runner._active_worker = None
    else:
        monkeypatch.setattr(window.tab_ladder, "is_operation_active", lambda: False)
    assert window.settings_changes_allowed()
    window.on_sub_tab_clicked("flt3", 0)
    assert APP_SETTINGS["active_analysis"] == "flt3"


def test_run_error_and_cancelled_completion_release_guard(window):
    run = window.tab_run
    run._active_run_cancel_event = threading.Event()
    assert not window.settings_changes_allowed()
    run._on_run_error((None, "synthetic failure"))
    assert window.settings_changes_allowed()

    run._active_run_cancel_event = threading.Event()
    run._on_run_finished({"cancelled": True, "total_jobs": 0})
    assert window.settings_changes_allowed()


def test_ladder_rejects_direct_analysis_switch_during_rerun(window):
    ladder = window.tab_ladder
    ladder._single_rerun_active = True

    assert ladder.set_analysis("flt3") is False
    assert ladder._current_analysis_id == "clonality"
    assert "rerun" in ladder.status_lbl.text().lower()


@pytest.mark.parametrize("completion", ["success", "error"])
def test_scan_blocks_analysis_and_settings_until_its_callback(
    window,
    tmp_path,
    completion,
):
    class DeferredPool:
        def __init__(self):
            self.worker = None

        def start(self, worker):
            self.worker = worker

    source = tmp_path / "sample.fsa"
    source.write_bytes(b"synthetic")
    run = window.tab_run
    run.threadpool = DeferredPool()
    run._add_source_item(str(source))

    run.on_scan()

    assert window.active_operation() == "Run scan"
    scan_request_id = run._active_scan_request_id
    assert scan_request_id > 0
    assert run.set_analysis("flt3") is False
    assert window._activate_analysis("flt3") is False
    window.on_sub_tab_clicked("flt3", 0)
    window._activate_settings()
    window._on_settings_saved("clonality")
    assert APP_SETTINGS["active_analysis"] == "clonality"
    assert run._current_analysis_id == "clonality"
    assert run._active_scan_request_id == scan_request_id
    assert not window.settings_changes_allowed()

    window.on_sub_tab_clicked(
        "clonality",
        window.group_clonality.sub_button_labels.index("Log"),
    )
    assert window.stacked_widget.currentIndex() == window.tab_log_idx

    if completion == "success":
        run.threadpool.worker.signals.result.emit([])
    else:
        run.threadpool.worker.signals.error.emit(
            (RuntimeError, RuntimeError("synthetic scan failure"), "")
        )

    assert window.active_operation() is None
    assert window.settings_changes_allowed()
    window.on_sub_tab_clicked("flt3", 0)
    assert APP_SETTINGS["active_analysis"] == "flt3"


def test_scan_reset_releases_only_scan_owner_when_run_is_active(window):
    run = window.tab_run
    job = {"name": "active job"}
    cancellation = threading.Event()
    run._active_scan_request_id = 9
    run._detected_jobs = [job]
    run._active_run_jobs = [job]
    run._active_run_rows = [0]
    run._progress_job_rows = [0]
    run._active_run_cancel_event = cancellation

    run._reset_queue_state("Scan cancelled", "warning")

    assert run._active_scan_request_id == 0
    assert window.active_operation() == "Run"
    assert run._active_run_cancel_event is cancellation
    assert run._detected_jobs == [job]
    assert run._active_run_jobs == [job]
    assert run._active_run_rows == [0]
    assert run._progress_job_rows == [0]

    run._on_scan_result([{"name": "stale scan result"}], request_id=9)
    assert window.active_operation() == "Run"
    assert run._detected_jobs == [job]
    assert run._active_run_jobs == [job]


@pytest.mark.parametrize("mutation", ["add_source", "input_scope"])
@pytest.mark.parametrize("completion", ["success", "error"])
def test_input_mutation_cancels_scan_and_restores_controls_before_stale_callback(
    window,
    tmp_path,
    monkeypatch,
    mutation,
    completion,
):
    class DeferredPool:
        def __init__(self):
            self.worker = None

        def start(self, worker):
            self.worker = worker

    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.save_settings", lambda *_: None)
    first_source = tmp_path / "first.fsa"
    second_source = tmp_path / "second.fsa"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    run = window.tab_run
    run.threadpool = DeferredPool()
    run._add_source_item(str(first_source))
    run.on_scan()
    stale_request_id = run._active_scan_request_id

    assert stale_request_id > 0
    assert not run.btn_scan.isEnabled()

    if mutation == "add_source":
        run._add_source_item(str(second_source))
    else:
        next_index = 1 - run.input_scope_combo.currentIndex()
        run.input_scope_combo.setCurrentIndex(next_index)

    assert run._active_scan_request_id == 0
    assert run.btn_scan.isEnabled()
    assert not run.btn_run.isEnabled()
    assert run.progress.minimum() == 0
    assert run.progress.maximum() == 100
    state_after_mutation = (
        list(run._detected_jobs),
        run.status_lbl.text(),
        run.progress.value(),
    )

    if completion == "success":
        run.threadpool.worker.signals.result.emit([{"name": "stale scan result"}])
    else:
        run.threadpool.worker.signals.error.emit(
            (RuntimeError, RuntimeError("stale scan failure"), "")
        )

    assert run._active_scan_request_id == 0
    assert run.btn_scan.isEnabled()
    assert not run.btn_run.isEnabled()
    assert (
        list(run._detected_jobs),
        run.status_lbl.text(),
        run.progress.value(),
    ) == state_after_mutation
