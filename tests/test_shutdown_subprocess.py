"""Exercise real Qt event-loop shutdown without touching operator data."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_SHUTDOWN_PROBE = r'''
import json
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QThreadPool, QTimer
from PyQt6.QtWidgets import QApplication

from gui_qt.main_window import MainWindow
from gui_qt.worker import Worker

output = Path(sys.argv[1])
app = QApplication([])
window = MainWindow()
window.show()

def write_report():
    with output.open("w", encoding="utf-8") as report:
        report.write("phase-1\n")
        report.flush()
        time.sleep(0.25)
        report.write("phase-2\n")

worker = Worker(write_report)
handle = window.operation_coordinator.register("synthetic report", cancel=lambda: None)
worker.signals.finished.connect(handle.settle)
handle.mark_running()
QThreadPool.globalInstance().start(worker)
QTimer.singleShot(20, window.close)
QTimer.singleShot(5000, app.quit)
started = time.perf_counter()
app.exec()
print(json.dumps({
    "elapsed": time.perf_counter() - started,
    "visible": window.isVisible(),
    "content": output.read_text(encoding="utf-8"),
    "active": len(window.operation_coordinator.active_handles()),
}))
'''


def test_qt_process_drains_synthetic_writer_before_event_loop_exits(tmp_path):
    report_path = tmp_path / "synthetic-report.txt"
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"

    result = subprocess.run(
        [sys.executable, "-c", _SHUTDOWN_PROBE, str(report_path)],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )

    import json

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["content"] == "phase-1\nphase-2\n"
    assert payload["active"] == 0
    assert payload["visible"] is False
    assert payload["elapsed"] >= 0.2
