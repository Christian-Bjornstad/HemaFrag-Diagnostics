from __future__ import annotations

from pathlib import Path

from gui_qt.operation_coordinator import OperationStartRejected
from gui_qt.tabs.tab_archive_runner import TabArchiveRunner


class _Handle:
    def __init__(self) -> None:
        self.running = False
        self.critical_write = False
        self.settled = False

    def mark_running(self) -> None:
        self.running = True

    def mark_critical_write(self) -> None:
        self.critical_write = True

    def settle(self) -> None:
        self.settled = True


class _Coordinator:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.registrations: list[tuple[str, object]] = []
        self.handle = _Handle()

    def register(self, kind, *, cancel, **_kwargs):
        if self.reject:
            raise OperationStartRejected("draining")
        self.registrations.append((kind, cancel))
        return self.handle


class _ThreadPool:
    def __init__(self) -> None:
        self.started: list[object] = []

    def start(self, worker) -> None:
        self.started.append(worker)


def _archive_tab(qapp, tmp_path: Path) -> TabArchiveRunner:
    tab = TabArchiveRunner()
    tab.threadpool = _ThreadPool()
    tab._runner = lambda: lambda **_kwargs: {}
    tab._validated_inputs = lambda: (
        "2026",
        tmp_path,
        tmp_path,
        ["2026_01"],
    )
    tab._persist_settings = lambda: None
    return tab


def test_yearly_worker_registers_cancellable_operation_before_start(qapp, tmp_path):
    tab = _archive_tab(qapp, tmp_path)
    coordinator = _Coordinator()
    tab.set_operation_coordinator(coordinator)

    tab.on_run_yearly()

    assert len(coordinator.registrations) == 1
    kind, cancel = coordinator.registrations[0]
    assert kind == "Archive yearly"
    assert coordinator.handle.running is True
    assert len(tab.threadpool.started) == 1
    worker = tab.threadpool.started[0]
    assert worker.kwargs["cancel_event"].is_set() is False
    cancel()
    assert worker.kwargs["cancel_event"].is_set() is True
    worker.signals.finished.emit()
    assert coordinator.handle.settled is True
    tab.close()


def test_yearly_worker_rejection_restores_idle_ui(qapp, tmp_path):
    tab = _archive_tab(qapp, tmp_path)
    previous_run = tmp_path / "previous-run"
    previous_run.mkdir()
    tab._current_run_root = previous_run
    tab._refresh_output_labels()
    tab.set_operation_coordinator(_Coordinator(reject=True))

    tab.on_run_yearly()

    assert tab.threadpool.started == []
    assert tab._active_worker is None
    assert tab.btn_run.isEnabled()
    assert tab._workflow_state == "warning"
    assert tab._current_run_root == previous_run
    assert tab.selected_run_root.text() == str(previous_run)
    tab.close()


def test_rejected_yearly_start_does_not_create_output_or_save_settings(qapp, tmp_path):
    tab = TabArchiveRunner()
    tab.threadpool = _ThreadPool()
    tab._runner = lambda: lambda **_kwargs: {}
    source = tmp_path / "input"
    source.mkdir()
    destination = tmp_path / "new-output"
    tab.input_root.setText(str(source))
    tab.output_root.setText(str(destination))
    tab.year_input.setText("2026")
    saved = []
    tab._persist_settings = lambda: saved.append(True)
    tab.set_operation_coordinator(_Coordinator(reject=True))

    tab.on_run_yearly()

    assert not destination.exists()
    assert saved == []
    assert tab.threadpool.started == []
    assert tab.btn_run.isEnabled()
    tab.close()


def test_threadpool_start_failure_settles_operation_and_restores_idle_ui(qapp, tmp_path):
    tab = _archive_tab(qapp, tmp_path)
    coordinator = _Coordinator()
    tab.set_operation_coordinator(coordinator)

    def fail_start(_worker):
        raise RuntimeError("start failed")

    tab.threadpool.start = fail_start
    tab.on_run_yearly()

    assert coordinator.handle.settled is True
    assert tab._active_worker is None
    assert tab.btn_run.isEnabled()
    assert tab._workflow_state == "error"
    tab.close()


def test_combine_worker_registers_noncancellable_write(qapp, tmp_path):
    tab = _archive_tab(qapp, tmp_path)
    tab._current_run_root = tmp_path
    tab._combiner = lambda: lambda *_args, **_kwargs: tmp_path / "combined.xlsx"
    coordinator = _Coordinator()
    tab.set_operation_coordinator(coordinator)

    tab.on_build_combined_workbook()

    kind, cancel = coordinator.registrations[0]
    assert kind == "Archive combine"
    assert cancel() is None
    assert coordinator.handle.running is True
    assert coordinator.handle.critical_write is True
    assert len(tab.threadpool.started) == 1
    tab.threadpool.started[0].signals.finished.emit()
    assert coordinator.handle.settled is True
    tab.close()
