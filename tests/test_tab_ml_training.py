"""Tests for TabMlTraining — minimal smoke tests confirming the tab
constructs with the expected assays checkable + a status pill that
responds to the absence of an xlsx.
"""
from __future__ import annotations

import os

import pytest

# Headless Qt — set the QT_QPA_PLATFORM before importing QtWidgets.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt

QAPP = None


def _qapp_or_skip():
    """Return a single QApplication for the test session, or skip."""
    global QAPP
    if QAPP is not None:
        return QAPP
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    QAPP = QApplication.instance() or QApplication([])
    return QAPP


def test_tab_construction_yields_checkable_assays():
    _qapp_or_skip()
    from gui_qt.tabs.tab_ml_training import TabMlTraining
    tab = TabMlTraining()
    assert tab._assays_list.count() >= 9
    checked = []
    for i in range(tab._assays_list.count()):
        item = tab._assays_list.item(i)
        if item.checkState() == Qt.CheckState.Checked:
            checked.append(item.text())
    assert "FR1" in checked
    assert "TCRgA" in checked
    assert tab._classifier_combo.currentText() == "auto"
    assert tab._min_samples.value() == 200


def test_tab_toggle_all_is_idempotent():
    _qapp_or_skip()
    from gui_qt.tabs.tab_ml_training import TabMlTraining
    tab = TabMlTraining()
    initial = [tab._assays_list.item(i).checkState()
               for i in range(tab._assays_list.count())]
    # Initially, the builder sets all to Checked. Toggling twice returns
    # to the same state.
    tab._toggle_all_assays()
    tab._toggle_all_assays()
    final = [tab._assays_list.item(i).checkState()
             for i in range(tab._assays_list.count())]
    assert initial == final


def test_tab_toggle_all_can_flip_all_off():
    _qapp_or_skip()
    from gui_qt.tabs.tab_ml_training import TabMlTraining
    tab = TabMlTraining()
    # First toggle (from "all checked") moves to "all unchecked".
    tab._toggle_all_assays()
    after_one = [tab._assays_list.item(i).checkState()
                 for i in range(tab._assays_list.count())]
    assert all(s == Qt.CheckState.Unchecked for s in after_one)


def test_selected_assays_returns_checked_only():
    _qapp_or_skip()
    from gui_qt.tabs.tab_ml_training import TabMlTraining
    tab = TabMlTraining()
    # Build a controlled state: only FR1 checked
    for i in range(tab._assays_list.count()):
        tab._assays_list.item(i).setCheckState(Qt.CheckState.Unchecked)
    item = tab._assays_list.item(0)  # first item is FR1
    item.setCheckState(Qt.CheckState.Checked)
    selected = tab._selected_assays()
    assert selected == ["FR1"]


def test_status_text_initialised_as_empty():
    _qapp_or_skip()
    from gui_qt.tabs.tab_ml_training import TabMlTraining
    tab = TabMlTraining()
    # The status label exists and starts empty.
    assert tab._status_label is not None
    assert tab._status_label.text() == ""
    assert tab._features_edit is not None


def test_successful_training_does_not_auto_promote_model_path(tmp_path, monkeypatch):
    _qapp_or_skip()
    from gui_qt.tabs import tab_ml_training

    settings = {
        "analyses": {
            "clonality": {
                "interpretation": {"model_path": "validated-model"}
            }
        }
    }
    monkeypatch.setattr(tab_ml_training, "APP_SETTINGS", settings)
    tab = tab_ml_training.TabMlTraining()
    tab._on_finished(True, "", str(tmp_path / "candidate-model"))

    assert (
        settings["analyses"]["clonality"]["interpretation"]["model_path"]
        == "validated-model"
    )
