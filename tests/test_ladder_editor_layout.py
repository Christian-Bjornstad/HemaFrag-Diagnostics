import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea, QWidget

from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog
from gui_qt.tabs.tab_ladder import TabLadder


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


def test_ladder_editor_residual_refresh_leaves_no_deferred_canvas_draw(
    qapp,
    monkeypatch,
):
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
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)

    dialog = LadderAdjustmentDialog(_fake_fsa())
    assert dialog.residual_canvas._draw_pending is False
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


def test_ladder_editor_saves_two_anchor_mapping_as_unapproved_draft(
    qapp,
    monkeypatch,
):
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_get_candidates",
        lambda self: pd.DataFrame(
            {
                "index": [0, 1],
                "time": [100.0, 300.0],
                "requested_x": [100.0, 300.0],
                "intensity": [120.0, 180.0],
                "source": ["auto", "auto"],
                "marker_id": ["detected-a", "detected-b"],
            }
        ),
    )
    monkeypatch.setattr(LadderAdjustmentDialog, "_suggest_auto", lambda self, store_initial: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_all", lambda self: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    dialog = LadderAdjustmentDialog(_fake_fsa())
    dialog.mapping = {0: 0, 2: 1}
    dialog._on_apply()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.get_review_payload()["action"] == "save_draft"
    assert dialog.get_review_payload()["partial_approved"] is False
    assert dialog.get_adjustment_payload()["mapping_times"] == {0: 100.0, 2: 300.0}
    dialog.close()


def test_save_action_names_draft_partial_and_complete_states(qapp, monkeypatch):
    monkeypatch.setattr(
        LadderAdjustmentDialog, "_get_candidates",
        lambda self: pd.DataFrame(columns=["index", "time", "intensity", "source"]),
    )
    monkeypatch.setattr(LadderAdjustmentDialog, "_suggest_auto", lambda self, store_initial: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_preview_state", lambda self, show_errors: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)
    dialog = LadderAdjustmentDialog(_fake_fsa())

    dialog.mapping = {0: 0, 2: 1}
    dialog._sync_save_action()
    assert dialog.btn_apply.text() == "Save Draft (2 anchors)"
    assert "cannot be rerun" in dialog.btn_apply.toolTip()

    dialog.mapping = {0: 0, 2: 1, 4: 2}
    dialog._sync_save_action()
    assert dialog.btn_apply.text() == "Review & Save Partial Fit"

    dialog.mapping = {index: index for index in range(len(dialog.ladder_steps))}
    dialog._sync_save_action()
    assert dialog.btn_apply.text() == "Save Adjustment"
    dialog.close()


@pytest.mark.parametrize("width,height", [(1280, 720), (1366, 768)])
def test_ladder_page_keeps_optional_review_controls_collapsed_at_laptop_sizes(
    qapp, width, height
):
    previous_font = qapp.font()
    qapp.setFont(QFont("Segoe UI", 9))
    tab = TabLadder()
    tab.resize(width, height)
    tab.show()
    qapp.processEvents()

    assert not tab.review_bundle_options.isVisible()
    assert tab.btn_toggle_review_bundle.isVisible()
    assert not tab.btn_load_bundle.isEnabled()
    assert not tab.btn_open_editor.isEnabled()
    assert not tab.btn_rerun_file.isEnabled()
    assert not tab.btn_remove_adjustment.isEnabled()
    assert tab.status_lbl.geometry().bottom() <= tab.rect().bottom()

    tab.btn_toggle_review_bundle.click()
    qapp.processEvents()
    assert tab.review_bundle_options.isVisible()
    assert not tab.btn_load_bundle.isEnabled()
    tab.close()
    qapp.setFont(previous_font)


def test_ladder_editor_approves_previewed_partial_mapping_with_three_anchors(
    qapp,
    monkeypatch,
):
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_get_candidates",
        lambda self: pd.DataFrame(
            {
                "index": [0, 1, 2],
                "time": [100.0, 300.0, 500.0],
                "requested_x": [100.0, 300.0, 500.0],
                "intensity": [120.0, 180.0, 160.0],
                "source": ["auto", "auto", "auto"],
                "marker_id": ["detected-a", "detected-b", "detected-c"],
            }
        ),
    )
    monkeypatch.setattr(LadderAdjustmentDialog, "_suggest_auto", lambda self, store_initial: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_all", lambda self: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_refresh_preview_state",
        lambda self, show_errors: setattr(self, "_preview_metrics", {"r2": 0.999}),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog = LadderAdjustmentDialog(_fake_fsa())
    dialog.mapping = {0: 0, 2: 1, 4: 2}
    dialog._on_apply()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.get_review_payload()["action"] == "apply"
    assert dialog.get_review_payload()["partial_approved"] is True
    dialog.close()


def test_nearest_candidate_hit_area_scales_with_visible_trace():
    dialog = LadderAdjustmentDialog.__new__(LadderAdjustmentDialog)
    dialog.candidates = pd.DataFrame(
        {
            "time": [100.0, 700.0],
            "intensity": [80.0, 20.0],
        }
    )
    dialog._trace_current_limits = lambda: ((0.0, 1000.0), (0.0, 100.0))

    assert dialog._nearest_candidate_from_position(108.0, 80.0) == 0
    assert dialog._nearest_candidate_from_position(108.0, 0.0) is None


def test_ladder_editor_restores_saved_draft_mapping(qapp, monkeypatch):
    draft = {
        "mapping": {0: 0, 2: 1},
        "mapping_times": {0: 100.25, 2: 300.75},
        "manual_candidates": [100.25, 300.75],
        "markers": [
            {
                "marker_id": "draft-a",
                "scan_x": 100.25,
                "requested_x": 100.25,
                "intensity": 120.0,
                "source_kind": "manual_exact",
            },
            {
                "marker_id": "draft-b",
                "scan_x": 300.75,
                "requested_x": 300.75,
                "intensity": 180.0,
                "source_kind": "manual_exact",
            },
        ],
        "marker_id_by_step": {0: "draft-a", 2: "draft-b"},
        "partial_mapping": True,
        "review": {"partial_approved": False},
    }
    monkeypatch.setattr(
        LadderAdjustmentDialog,
        "_get_candidates",
        lambda self: pd.DataFrame(
            {
                "index": [0, 1],
                "time": [100.25, 300.75],
                "requested_x": [100.25, 300.75],
                "intensity": [120.0, 180.0],
                "source": ["manual_exact", "manual_exact"],
                "marker_id": ["draft-a", "draft-b"],
            }
        ),
    )
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_preview_state", lambda self, show_errors: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_all", lambda self: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)

    dialog = LadderAdjustmentDialog(_fake_fsa(), initial_adjustment=draft)

    assert dialog.mapping == {0: 0, 2: 1}
    assert dialog._manual_candidate_times == [100.25, 300.75]
    dialog.close()
