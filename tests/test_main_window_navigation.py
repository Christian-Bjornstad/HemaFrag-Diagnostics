import os
import copy

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from gui_qt.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    from config import APP_SETTINGS

    original = copy.deepcopy(APP_SETTINGS)
    monkeypatch.setattr("gui_qt.main_window.save_settings", lambda _settings: True)
    yield
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


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
        "Log",
        "Settings",
    ]
    assert window.group_flt3.sub_button_labels == [
        "Run",
        "Ladder",
        "Archive Runner",
        "Log",
        "Settings",
    ]
    assert window.group_general.sub_button_labels == [
        "Run",
        "Ladder",
        "Log",
        "Settings",
    ]
    assert not hasattr(window, "tab_labeling")
    assert all("Labeling" not in group.sub_button_labels for group in window.groups)
    assert "Ladder" in window.group_clonality.sub_button_labels
    assert not hasattr(window, "tab_ml_training")


def test_semantic_shortcuts_do_not_depend_on_clonality_positions(qapp, monkeypatch):
    from config import APP_SETTINGS

    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    window = MainWindow()

    window.on_group_clicked(window.group_clonality)
    window._activate_sub_label("Ladder")
    assert window.stacked_widget.currentIndex() == window.tab_ladder_idx

    window.on_group_clicked(window.group_flt3)
    window._activate_sub_label("Settings")
    assert window.stacked_widget.currentIndex() == window.tab_settings_flt3_idx

    window._activate_settings()
    assert window.stacked_widget.currentIndex() == window.tab_app_settings_idx
    assert window.btn_app_settings.isChecked()

    window.on_group_clicked(window.group_general)
    window._activate_sub_label("Log")
    assert window.stacked_widget.currentIndex() == window.tab_log_idx


def test_sidebar_has_branded_lockup(qapp):
    window = MainWindow()

    lockup = window.findChild(QWidget, "SidebarBrandLockup")

    assert lockup is not None
    assert lockup.findChild(QWidget, "SidebarBrandMark") is not None
    assert lockup.findChild(QWidget, "SidebarBrandText") is not None
