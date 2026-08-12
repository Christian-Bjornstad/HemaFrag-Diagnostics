import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_fsa():
    steps = np.array(
        [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400],
        dtype=float,
    )
    return SimpleNamespace(
        file_name="compact-layout.fsa",
        ladder="ROX400HD",
        analysis_id="clonality",
        ladder_steps=steps,
        expected_ladder_steps=steps,
        size_standard=np.zeros(1200, dtype=float),
        best_size_standard=np.array([], dtype=float),
    )


def test_ladder_editor_exposes_grouped_controls_and_scrollable_qc(qapp, monkeypatch):
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_get_candidates",
        lambda self: pd.DataFrame(columns=["index", "time", "intensity", "source"]),
    )
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_suggest_auto",
        lambda self, store_initial: None,
    )
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_refresh_preview_state",
        lambda self, show_errors: None,
    )
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_all", lambda self: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)

    dialog = LadderAdjustmentDialog(_fake_fsa())
    dialog.resize(1024, 700)
    dialog.show()
    qapp.processEvents()

    assert dialog.minimumWidth() <= 1024
    assert dialog.minimumHeight() <= 700
    assert dialog.findChild(QWidget, "TraceViewControls") is not None
    assert dialog.findChild(QWidget, "TraceAssignControls") is not None
    qc_scroll = dialog.findChild(QScrollArea, "SizingQcScroll")
    assert qc_scroll is not None
    assert qc_scroll.horizontalScrollBarPolicy().name == "ScrollBarAlwaysOff"
    assert dialog.findChild(QWidget, "LadderActionBar") is not None
    dialog.close()
