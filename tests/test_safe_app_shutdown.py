"""Application shutdown drains registered work without blocking Qt's GUI thread."""

from __future__ import annotations

import copy
import os
import threading
import time

import pytest
from PyQt6.QtWidgets import QApplication

from config import APP_SETTINGS
from gui_qt.main_window import MainWindow
from gui_qt.operation_coordinator import (
    OperationStartRejected,
    OperationStatus,
)
from gui_qt.worker import Worker


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(monkeypatch, tmp_path, qapp):
    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB",
        str(tmp_path / "ladder.sqlite"),
    )
    monkeypatch.setattr("gui_qt.main_window.save_settings", lambda *_: None)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    widget = MainWindow()
    widget.show()
    qapp.processEvents()
    yield widget
    for handle in widget.operation_coordinator.active_handles():
        handle.settle()
    qapp.processEvents()
    widget.close()
    qapp.processEvents()
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


def test_operation_handle_keeps_identity_and_settles_once(qapp, window):
    handle = window.operation_coordinator.register(
        "Run batch",
        cancel=lambda: None,
        run_id="run-123",
        operation_id="operation-123",
    )

    assert handle.operation_id == "operation-123"
    assert handle.kind == "Run batch"
    assert handle.run_id == "run-123"
    assert handle.status is OperationStatus.QUEUED

    handle.mark_running()
    qapp.processEvents()
    assert handle.status is OperationStatus.RUNNING

    handle.settle()
    handle.settle()
    qapp.processEvents()
    assert window.operation_coordinator.active_handles() == ()


def test_window_wires_one_coordinator_to_all_worker_tabs(window):
    coordinator = window.operation_coordinator

    assert window.tab_run.operation_coordinator is coordinator
    assert window.tab_archive_runner._operation_coordinator is coordinator
    assert window.tab_ladder._operation_coordinator is coordinator


def test_close_requests_cancel_once_stays_responsive_and_rejects_new_work(
    qapp,
    window,
):
    cancelled = threading.Event()
    handle = window.operation_coordinator.register(
        "synthetic writer",
        cancel=cancelled.set,
    )
    handle.mark_running()
    qapp.processEvents()

    started = time.perf_counter()
    close_result = window.close()
    elapsed = time.perf_counter() - started

    assert close_result is False
    assert elapsed < 0.1
    assert cancelled.is_set()
    assert window.isVisible()
    assert window.operation_coordinator.draining
    assert "registered" in window.statusBar().currentMessage().lower()
    with pytest.raises(OperationStartRejected):
        window.operation_coordinator.register("too late", cancel=lambda: None)

    cancelled.clear()
    assert window.close() is False
    assert not cancelled.is_set()

    handle.settle()
    qapp.processEvents()
    qapp.processEvents()
    assert not window.isVisible()


def test_close_deadline_leaves_window_open_for_unresponsive_operation(
    qapp,
    window,
):
    window._shutdown_deadline_ms = 0
    handle = window.operation_coordinator.register(
        "unresponsive worker",
        cancel=lambda: None,
    )

    assert window.close() is False
    qapp.processEvents()

    assert window.isVisible()
    assert window.operation_coordinator.draining
    assert "remains open" in window.statusBar().currentMessage().lower()

    assert window.close() is False
    assert window.isVisible()

    handle.settle()
    qapp.processEvents()
    qapp.processEvents()
    assert window.isVisible(), "deadline must not silently auto-close the app"

    prompt = window._shutdown_prompt
    assert prompt is not None
    wait_button = next(
        button for button in prompt.buttons() if button.text() == "Wait longer"
    )
    wait_button.click()
    qapp.processEvents()
    qapp.processEvents()
    assert not window.isVisible()


def test_deadline_can_cancel_close_and_reenable_registration(qapp, window):
    window._shutdown_deadline_ms = 0
    handle = window.operation_coordinator.register(
        "unresponsive worker",
        cancel=lambda: None,
    )

    assert window.close() is False
    qapp.processEvents()
    prompt = window._shutdown_prompt
    assert prompt is not None
    cancel_button = next(
        button for button in prompt.buttons() if button.text() == "Cancel close"
    )
    cancel_button.click()
    qapp.processEvents()

    assert window.isVisible()
    assert not window.operation_coordinator.draining
    extra = window.operation_coordinator.register("new work", cancel=lambda: None)
    extra.settle()
    handle.settle()
    qapp.processEvents()


def test_dismissing_deadline_prompt_cancels_close_instead_of_trapping_window(
    qapp,
    window,
):
    window._shutdown_deadline_ms = 0
    handle = window.operation_coordinator.register(
        "unresponsive worker",
        cancel=lambda: None,
    )

    assert window.close() is False
    qapp.processEvents()
    prompt = window._shutdown_prompt
    assert prompt is not None
    prompt.reject()
    qapp.processEvents()

    assert window.isVisible()
    assert not window.operation_coordinator.draining
    assert window._shutdown_prompt is None

    handle.settle()
    qapp.processEvents()


def test_worker_error_still_settles_registered_operation(qapp, window):
    handle = window.operation_coordinator.register(
        "failing worker",
        cancel=lambda: None,
    )
    worker = Worker(lambda: (_ for _ in ()).throw(RuntimeError("synthetic")))
    worker.signals.finished.connect(handle.settle)

    thread = threading.Thread(target=worker.run)
    thread.start()
    thread.join(timeout=1)
    assert not thread.is_alive()
    qapp.processEvents()
    qapp.processEvents()

    assert window.operation_coordinator.active_handles() == ()


def test_queued_status_updates_cannot_regress_cancelling_or_critical_write(
    qapp,
    window,
):
    handle = window.operation_coordinator.register("race", cancel=lambda: None)
    handle.mark_running()  # queued, but draining wins before delivery
    window.operation_coordinator.begin_draining()
    qapp.processEvents()
    assert handle.status is OperationStatus.CANCELLING

    handle.mark_critical_write()
    qapp.processEvents()
    assert handle.status is OperationStatus.CRITICAL_WRITE

    handle.mark_running()
    qapp.processEvents()
    assert handle.status is OperationStatus.CRITICAL_WRITE

    handle.settle()
    qapp.processEvents()
