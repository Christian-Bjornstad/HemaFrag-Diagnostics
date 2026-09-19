"""Settings tab save round-trip — exercise the ML model path slot."""
from __future__ import annotations

import copy
import os
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

import config
from config import APP_SETTINGS


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    original = copy.deepcopy(APP_SETTINGS)
    APP_SETTINGS.clear()
    APP_SETTINGS.update(copy.deepcopy(config.DEFAULT_SETTINGS))
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.yaml")
    monkeypatch.setattr(config, "LEGACY_SETTINGS_PATH", tmp_path / "legacy.yaml")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app, tmp_path / "settings.yaml"
    APP_SETTINGS.clear()
    APP_SETTINGS.update(original)


def test_tab_save_publishes_only_after_persistence(isolated_settings):
    from gui_qt.tabs.tab_settings import TabAnalysisSettings

    _app, target = isolated_settings
    tab = TabAnalysisSettings("flt3")
    signals = []
    tab.settings_saved.connect(signals.append)
    tab.author.setText("New author")
    with patch.object(config.os, "replace", side_effect=PermissionError("denied")):
        assert tab.save() is False
    assert APP_SETTINGS["general"]["author"] == "OUS"
    assert tab.author.text() == "New author"
    assert signals == []
    assert "denied" in tab.status_lbl.text()
    assert not target.exists()
    assert tab.save() is True
    assert APP_SETTINGS["general"]["author"] == "New author"
    assert signals == ["flt3"]
    assert config.load_settings(target)["general"]["author"] == "New author"


def test_tab_save_respects_operation_guard(isolated_settings):
    from PyQt6.QtWidgets import QWidget
    from gui_qt.tabs.tab_settings import TabAnalysisSettings

    _app, target = isolated_settings
    class GuardedWindow(QWidget):
        def settings_changes_allowed(self):
            return False

    parent = GuardedWindow()
    tab = TabAnalysisSettings("flt3", parent)
    tab.author.setText("Blocked")
    assert tab.save() is False
    assert not target.exists()
    assert APP_SETTINGS["general"]["author"] == "OUS"


def test_ml_model_path_round_trip(tmp_path, isolated_settings):
    from gui_qt.tabs.tab_settings import TabAnalysisSettings

    _app, target = isolated_settings
    tab = TabAnalysisSettings("clonality")
    tab.chk_clonality_interpretation.setChecked(True)
    tab.clonality_model_path.setText(str(tmp_path))
    assert tab.save() is True
    reloaded = config.load_settings(target)
    assert reloaded["analyses"]["clonality"]["interpretation"]["model_path"] == str(tmp_path)
