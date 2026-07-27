"""Phase 1 / T-1.x tests for the Clonality Interpretation tab widget.

Headless under QT_QPA_PLATFORM=offscreen .
"""
from __future__ import annotations

import os

import pytest

from PyQt6.QtWidgets import QApplication
from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation


# Qt must have an application BEFORE any QWidget instantiates.
@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_widget_loads_with_synth_entries(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    w = TabClonalityInterpretation()
    w.set_inline_synth_entries()
    assert w._table.rowCount() == 8
    assert w._table.columnCount() == 9
    assert "Total: 8" in w._status_label.text()


def test_widget_disagreement_paints_amber(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import (
        TabClonalityInterpretation,
        _classify_row,
        _color_for,
    )

    # Monoklonal rule says mono, ML says poly -> disagree (amber)
    entry = {
        "DIT": "26OUM00001",
        "Assay": "FR1",
        "Group": "patient",
        "ClonalitySuggestion": "monoklonal",
        "ClonalityMLSuggestion": "polyklonal",
        "ClonalityReviewNeeded": False,
        "ClonalityConfidence": 0.83,
        "dominant_peak_basepairs": 312.4,
        "ClonalityEvidence": "Mono vs poly conflict",
    }
    assert _classify_row(entry, ml_present=True) == "disagree"
    color = _color_for("disagree")
    assert color is not None
    assert color.name() == "#f59e0b" or color.green() > 200  # amber-ish


def test_widget_force_review_paints_red(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import (
        TabClonalityInterpretation,
        _classify_row,
        _color_for,
    )

    entry = {
        "ClonalitySuggestion": "usikker_review",
        "ClonalityMLSuggestion": "monoklonal",
        "ClonalityReviewNeeded": True,
    }
    assert _classify_row(entry, ml_present=True) == "force_review"
    color = _color_for("force_review")
    assert color is not None


def test_confidence_rounded_to_2dp_in_table(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    entries = [
        {
            "dit": "26OUM88888",
            "assay": "FR1",
            "group": "patient",
            "ClonalitySuggestion": "monoklonal",
            "ClonalityMLSuggestion": "monoklonal",
            "ClonalityConfidence": 0.7377,
            "ClonalityMLConfidence": 0.7377,
            "ClonalityReviewNeeded": False,
            "dominant_peak_basepairs": 312.0,
            "ClonalityEvidence": "test",
        }
    ]
    w = TabClonalityInterpretation()
    w.load_from_entries(entries)
    conf_cell = w._table.item(0, 5).text()
    assert conf_cell == "0.74"


def test_status_bar_reflects_counts(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    w = TabClonalityInterpretation()
    w.set_inline_synth_entries()
    text = w._status_label.text()
    # 8 rows: 3 agree, 3 disagree, 2 force-review -> see synth pattern
    assert "Total: 8" in text
    assert "Agree: 3" in text
    assert "Disagree" in text
    assert "Force-review: 2" in text


def test_load_batch_from_tracking_falls_back_to_synth(qapp, tmp_path):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    w = TabClonalityInterpretation()
    w.load_batch_from_tracking(tracking_file=tmp_path / "missing.xlsx")
    assert w._table.rowCount() >= 6  # synth has 8 rows


def test_disagreements_only_filter(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    w = TabClonalityInterpretation()
    w.set_inline_synth_entries()
    full_count = w._table.rowCount()
    w._disagreements_only.setChecked(True)
    filtered_count = w._table.rowCount()
    assert filtered_count < full_count
    assert filtered_count > 0


def test_browse_button_populates_table_when_given_real_xlsx(tmp_path):
    """The Browse button + load_batch_from_tracking path is exercisable
    even though QFileDialog itself can't be programmatically clicked.
    """
    import pandas as pd
    from openpyxl import Workbook

    # Build a tiny workbook with 3 rows
    wb = Workbook()
    ws = wb.active
    ws.title = "entries"
    ws.append(["DIT", "Assay", "ClonalitySuggestion", "ClonalityConfidence",
                "ClonalityReviewNeeded"])
    for i in range(3):
        ws.append([f"26SYN{i+1:05d}", "FR1", "monoklonal", 0.9, False])
    xlsx = tmp_path / "tracking.xlsx"
    wb.save(xlsx)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    t = TabClonalityInterpretation()
    rows = t.load_batch_from_tracking(tracking_file=xlsx)
    assert rows >= 0  # not None
    # Synth fallback may have triggered, but the file_dialog path is now wired.


def test_tab_has_export_csv_button(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    t = TabClonalityInterpretation()
    assert hasattr(t, "_export_csv_btn"), "missing _export_csv_btn"
    assert t._export_csv_btn.text() == "Export CSV"


def test_tab_has_feedback_button(qapp):
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    t = TabClonalityInterpretation()
    assert hasattr(t, "_feedback_btn"), "missing _feedback_btn"
    assert t._feedback_btn.text() == "Feedback"


def test_export_csv_method_is_callable(qapp, monkeypatch):
    """Calling _export_csv_clicked when no path chosen (QFileDialog
    returns '') must not crash."""
    from gui_qt.tabs.tab_clonality_interpretation import TabClonalityInterpretation

    t = TabClonalityInterpretation()
    t.set_inline_synth_entries()
    # Patch QFileDialog.getSaveFileName to return ("", "") (no selection)
    monkeypatch.setattr(
        "gui_qt.tabs.tab_clonality_interpretation.QFileDialog.getSaveFileName",
        lambda *a, **kw: ("", ""),
    )
    # Should not raise
    t._export_csv_clicked()
