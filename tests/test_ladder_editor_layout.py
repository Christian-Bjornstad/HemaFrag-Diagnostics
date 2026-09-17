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


def test_ladder_editor_round_trips_distinct_exact_markers_in_partial_payload(
    qapp,
    monkeypatch,
):
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_get_candidates",
        lambda self: pd.DataFrame(
            columns=[
                "index",
                "time",
                "requested_x",
                "intensity",
                "source",
                "marker_id",
            ]
        ),
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
    first = dialog._insert_manual_candidate(
        100.25,
        120.0,
        requested_x=100.25,
    )
    second = dialog._insert_manual_candidate(
        100.25,
        121.0,
        requested_x=100.25,
    )
    third = dialog._insert_manual_candidate(
        260.75,
        200.0,
        requested_x=260.75,
    )
    dialog._assign_candidate_to_step(0, first)
    dialog._assign_candidate_to_step(1, second)
    dialog._assign_candidate_to_step(2, third)

    dialog.show()
    qapp.processEvents()
    payload = dialog._build_adjustment_payload()

    assert payload["partial_mapping"] is True
    assert payload["mapping_times"] == {0: 100.25, 1: 100.25, 2: 260.75}
    assert len(set(payload["marker_id_by_step"].values())) == 3
    assert [marker["requested_x"] for marker in payload["markers"]] == [
        100.25,
        100.25,
        260.75,
    ]
    dialog.close()
