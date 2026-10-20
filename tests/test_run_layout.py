import copy
import os
from pathlib import Path

import pytest
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from config import APP_SETTINGS
from gui_qt.styles import VIBRANT_PRO_QSS
from gui_qt.tabs.tab_batch import TabBatch


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
    if font_path.is_file():
        assert QFontDatabase.addApplicationFont(str(font_path)) >= 0
        app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(VIBRANT_PRO_QSS)
    yield app


@pytest.fixture
def run_tab(qapp, monkeypatch, tmp_path):
    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.save_settings", lambda *_: None)
    tab = TabBatch()
    tab.resize(1072, 700)
    tab.show()
    qapp.processEvents()
    yield tab
    tab.close()
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


def test_input_and_queue_enter_laptop_viewport_before_scroll(run_tab):
    assert run_tab.input_card.geometry().top() < run_tab.dashboard_card.geometry().top()
    assert run_tab.dashboard_card.geometry().top() < run_tab.queue_card.geometry().top()
    assert run_tab.queue_card.geometry().top() < run_tab.height()
    assert run_tab.table.geometry().top() < run_tab.height()


def test_empty_and_loaded_source_labels_describe_operator_next_step(run_tab, tmp_path):
    run_tab.folder_list.clear()
    run_tab._reset_queue_state()
    assert run_tab.source_count_lbl.text() == "0 sources"
    assert "add sources" in run_tab.queue_summary_lbl.text().lower()

    source = tmp_path / "sample.fsa"
    source.write_bytes(b"synthetic")
    run_tab._add_source_item(str(source))

    assert run_tab.source_count_lbl.text() == "1 source"
    assert run_tab.folder_list.item(0).text() == str(source)


def test_running_state_keeps_stop_and_status_available(run_tab):
    run_tab._set_batch_controls_busy(True)
    run_tab._set_workflow_status("Running 1 job...", "running")

    assert run_tab.btn_stop.isVisible()
    assert run_tab.btn_stop.isEnabled()
    assert not run_tab.btn_scan.isEnabled()
    assert run_tab.status_badge.text() == "RUNNING"
    assert "Running" in run_tab.status_lbl.text()
