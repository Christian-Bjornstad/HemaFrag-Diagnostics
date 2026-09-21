import copy
import os

import pytest
from PyQt6.QtWidgets import QApplication

from config import APP_SETTINGS
from gui_qt.tabs.tab_batch import TabBatch


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def run_tab(qapp, monkeypatch):
    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.save_settings", lambda *_: None)
    tab = TabBatch()
    yield tab
    tab.close()
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


def _prepare_jobs(run_tab, count):
    run_tab._detected_jobs = [
        {
            "name": f"Patient {index + 1}",
            "type": "pipeline",
            "files": [],
        }
        for index in range(count)
    ]
    run_tab._active_run_rows = list(range(count))
    run_tab._job_states = {index: "running" for index in range(count)}
    run_tab._rebuild_table()


def test_output_failure_is_error_without_overwriting_successful_job_row(run_tab):
    _prepare_jobs(run_tab, 1)

    run_tab._on_run_finished(
        {
            "total_jobs": 1,
            "completed_job_indexes": [0],
            "failed_job_indexes": [],
            "failed_jobs": ["DIT aggregation"],
        }
    )

    assert run_tab._workflow_state == "error"
    assert "DIT aggregation" in run_tab.status_lbl.text()
    assert run_tab._job_states[0] == "success"
    assert run_tab.table.item(0, 4).text() == "SUCCESS"


def test_job_and_output_failures_are_reported_as_separate_failure_classes(run_tab):
    _prepare_jobs(run_tab, 2)

    run_tab._on_run_finished(
        {
            "total_jobs": 2,
            "completed_job_indexes": [0],
            "failed_job_indexes": [1],
            "failed_jobs": ["Patient 2", "DIT aggregation"],
        }
    )

    assert run_tab._workflow_state == "error"
    assert "1 failed job(s)" in run_tab.status_lbl.text()
    assert "DIT aggregation" in run_tab.status_lbl.text()
    assert run_tab._job_states == {0: "success", 1: "error"}


def test_batch_is_complete_only_when_jobs_and_outputs_succeed(run_tab):
    _prepare_jobs(run_tab, 1)

    run_tab._on_run_finished(
        {
            "total_jobs": 1,
            "completed_job_indexes": [0],
            "failed_job_indexes": [],
            "failed_jobs": [],
        }
    )

    assert run_tab._workflow_state == "success"
    assert run_tab.status_lbl.text() == "Batch complete."
    assert run_tab._job_states[0] == "success"
    assert run_tab.progress.value() == run_tab.progress.maximum()


def test_cancellation_keeps_warning_status_and_marks_unprocessed_rows(run_tab):
    _prepare_jobs(run_tab, 2)

    run_tab._on_run_finished(
        {
            "total_jobs": 2,
            "completed_job_indexes": [0],
            "failed_job_indexes": [],
            "failed_jobs": [],
            "cancelled": True,
            "cancelled_job_indexes": [1],
            "unprocessed_job_indexes": [1],
        }
    )

    assert run_tab._workflow_state == "warning"
    assert "Batch stopped" in run_tab.status_lbl.text()
    assert run_tab._job_states == {0: "success", 1: "unprocessed"}
