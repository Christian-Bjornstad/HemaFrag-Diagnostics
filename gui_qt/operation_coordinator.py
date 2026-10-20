"""App-level lifecycle for worker-backed operations.

Registrations and draining are GUI-thread operations.  Handle state changes may
be requested from any thread; Qt queues them back to the coordinator's thread.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from threading import Lock
from uuid import uuid4

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot


class OperationStartRejected(RuntimeError):
    """Raised when work is registered after application draining begins."""


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CRITICAL_WRITE = "critical_write"
    SETTLED = "settled"


class OperationHandle(QObject):
    """Identity and lifecycle controls for one registered operation."""

    _status_requested = pyqtSignal(str, object)

    def __init__(
        self,
        *,
        coordinator: "OperationCoordinator",
        operation_id: str,
        kind: str,
        run_id: str | None,
        cancel: Callable[[], None],
    ) -> None:
        super().__init__(coordinator)
        self.operation_id = operation_id
        self.kind = kind
        self.run_id = run_id
        self._cancel = cancel
        self._status = OperationStatus.QUEUED
        self._settle_lock = Lock()
        self._settle_requested = False
        self._status_requested.connect(
            coordinator._apply_requested_status,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def status(self) -> OperationStatus:
        return self._status

    def mark_running(self) -> None:
        self._request_status(OperationStatus.RUNNING)

    def mark_cancelling(self) -> None:
        self._request_status(OperationStatus.CANCELLING)

    def mark_critical_write(self) -> None:
        self._request_status(OperationStatus.CRITICAL_WRITE)

    def settle(self) -> None:
        """Remove this operation once its worker has finished, even on error."""
        with self._settle_lock:
            if self._settle_requested:
                return
            self._settle_requested = True
        self._status_requested.emit(self.operation_id, OperationStatus.SETTLED)

    def _request_status(self, status: OperationStatus) -> None:
        with self._settle_lock:
            if self._settle_requested:
                return
        self._status_requested.emit(self.operation_id, status)

    def _request_cancel(self) -> None:
        self._cancel()


class OperationCoordinator(QObject):
    """Own active operation handles and coordinate cooperative shutdown."""

    operations_changed = pyqtSignal()
    drained = pyqtSignal()
    cancel_failed = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handles: dict[str, OperationHandle] = {}
        self._draining = False

    @property
    def draining(self) -> bool:
        return self._draining

    def active_handles(self) -> tuple[OperationHandle, ...]:
        return tuple(self._handles.values())

    def register(
        self,
        kind: str,
        *,
        cancel: Callable[[], None],
        run_id: str | None = None,
        operation_id: str | None = None,
    ) -> OperationHandle:
        """Register new work on the GUI thread or reject it while draining."""
        self._require_owner_thread()
        if self._draining:
            raise OperationStartRejected(
                "Application shutdown is in progress; new work is disabled."
            )
        if not kind.strip():
            raise ValueError("kind must be a non-empty display name")
        if not callable(cancel):
            raise TypeError("cancel must be callable")
        resolved_id = operation_id or str(uuid4())
        if resolved_id in self._handles:
            raise ValueError(f"operation_id is already active: {resolved_id}")
        handle = OperationHandle(
            coordinator=self,
            operation_id=resolved_id,
            kind=kind,
            run_id=run_id,
            cancel=cancel,
        )
        self._handles[resolved_id] = handle
        self.operations_changed.emit()
        return handle

    def begin_draining(self) -> int:
        """Reject new work and request cancellation exactly once per drain."""
        self._require_owner_thread()
        if self._draining:
            return len(self._handles)
        self._draining = True
        for handle in tuple(self._handles.values()):
            if handle.status is not OperationStatus.CRITICAL_WRITE:
                self._set_status(handle, OperationStatus.CANCELLING)
            try:
                handle._request_cancel()
            except Exception as exc:  # cancellation must not break draining
                self.cancel_failed.emit(handle.operation_id, str(exc))
        self.operations_changed.emit()
        if not self._handles:
            self.drained.emit()
        return len(self._handles)

    def cancel_draining(self) -> None:
        """Abort the close attempt and allow new registrations again."""
        self._require_owner_thread()
        self._draining = False
        self.operations_changed.emit()

    @pyqtSlot(str, object)
    def _apply_requested_status(
        self,
        operation_id: str,
        status: OperationStatus,
    ) -> None:
        handle = self._handles.get(operation_id)
        if handle is None:
            return
        self._set_status(handle, status)

    def _set_status(
        self,
        handle: OperationHandle,
        status: OperationStatus,
    ) -> None:
        if handle._status is OperationStatus.SETTLED:
            return
        if status is OperationStatus.SETTLED:
            handle._status = status
            self._handles.pop(handle.operation_id, None)
            self.operations_changed.emit()
            if self._draining and not self._handles:
                self.drained.emit()
            handle.deleteLater()
            return
        if not self._transition_allowed(handle._status, status):
            return
        handle._status = status
        self.operations_changed.emit()

    def _transition_allowed(
        self,
        current: OperationStatus,
        requested: OperationStatus,
    ) -> bool:
        if current is OperationStatus.CANCELLING:
            return requested is OperationStatus.CRITICAL_WRITE
        if current is OperationStatus.CRITICAL_WRITE:
            return False
        if self._draining and requested is OperationStatus.RUNNING:
            return False
        return requested is not OperationStatus.QUEUED

    def _require_owner_thread(self) -> None:
        if QThread.currentThread() is not self.thread():
            raise RuntimeError(
                "Operation registration and draining must run on the GUI thread."
            )
