"""MlLearning QThread workers.

Phase A (Plan 13).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from gui_qt.tabs.tab_ml_learning._summary import entry_payload
from gui_qt.tabs.tab_ml_learning._io import write_json


class AnalyzeWorker(QThread):
    """Run ``_analyze_single_file`` over a list of paths on a background thread.

    Emits ``progress(i, n)`` after each entry; ``finished(entries)`` with the
    serialized list of payloads on completion. Per-file exceptions are caught
    and skipped, so one bad file does not kill the run.
    """

    progress = pyqtSignal(int, int)
    finished_with_entries = pyqtSignal(list)
    status = pyqtSignal(str)

    def __init__(self, paths: list[Path], *, parent=None) -> None:
        super().__init__(parent)
        self._paths = [Path(p) for p in paths]
        self._entries: list[dict[str, Any]] = []
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        # Late import keeps the QWidget instantiable in headless tests
        # even when the package's Optional deps (e.g. scipy) are missing.
        try:
            from core.analyses.clonality.pipeline import _analyze_single_file
            from core.analyses.clonality.interpretation import (
                features_from_entry,
                interpret_entry,
            )
        except Exception as exc:
            self.status.emit(f"[ERROR] Analyze worker import failed: {exc}")
            self.finished_with_entries.emit([])
            return

        total = len(self._paths)
        payloads: list[dict[str, Any]] = []
        for ordinal, raw_path in enumerate(self._paths, start=1):
            if self._cancelled:
                break
            try:
                entry = _analyze_single_file(raw_path)
            except Exception as exc:
                self.status.emit(f"[WARN] {raw_path.name}: {exc}")
                self.progress.emit(ordinal, total)
                continue

            if not isinstance(entry, dict):
                self.status.emit(f"[skip] {raw_path.name}: analyzer returned None")
                self.progress.emit(ordinal, total)
                continue

            try:
                features = features_from_entry(entry)
                interp_dict = interpret_entry({**entry, "features": features})
            except Exception as exc:
                self.status.emit(f"[WARN] {raw_path.name}: features/interp failed: {exc}")
                features = {}
                interp_dict = {}

            payload = entry_payload(
                ordinal=ordinal,
                raw_path=raw_path,
                features=features,
                interpretation=interp_dict,
                peaks_by_channel=entry.get("peaks_by_channel") or {},
                image_path=None,
            )
            payloads.append(payload)
            self.progress.emit(ordinal, total)

        self._entries = payloads
        self.finished_with_entries.emit(payloads)

    def write_entries_to(self, target: Path) -> Path:
        """Persist to disk - convenience for tests + main window alike."""
        return write_json(Path(target), self._entries)


__all__ = [
    "AnalyzeWorker",
]
