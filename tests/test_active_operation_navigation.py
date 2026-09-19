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
