import os

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from gui_qt.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_analysis_groups_keep_exact_navigation_contract(qapp):
    window = MainWindow()

    assert window.group_clonality.sub_button_labels == [
        "Run",
        "Ladder",
        "Archive Runner",
        "Compare",
        "Log",
        "Labeling",
        "Settings",
    ]
    assert window.group_flt3.sub_button_labels == [
        "Run",
        "Ladder",
        "Archive Runner",
        "Compare",
        "Log",
        "Settings",
    ]
    assert window.group_general.sub_button_labels == [
        "Run",
        "Ladder",
        "Archive Runner",
        "Compare",
        "Log",
        "Settings",
    ]
    assert not hasattr(window, "tab_ml_training")


def test_semantic_shortcuts_do_not_depend_on_clonality_positions(qapp, monkeypatch):
    from config import APP_SETTINGS

    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr("gui_qt.main_window.save_settings", lambda settings: None)
    window = MainWindow()

    window.on_group_clicked(window.group_clonality)
    window._activate_sub_label("Labeling")
    assert window.stacked_widget.currentIndex() == window.tab_labeling_idx

    window.on_group_clicked(window.group_flt3)
    window._activate_sub_label("Settings")
    assert window.stacked_widget.currentIndex() == window.tab_settings_flt3_idx

    window.on_group_clicked(window.group_general)
    window._activate_sub_label("Log")
    assert window.stacked_widget.currentIndex() == window.tab_log_idx


def test_sidebar_has_branded_lockup(qapp):
    window = MainWindow()

    lockup = window.findChild(QWidget, "SidebarBrandLockup")

    assert lockup is not None
    assert lockup.findChild(QWidget, "SidebarBrandMark") is not None
    assert lockup.findChild(QWidget, "SidebarBrandText") is not None
