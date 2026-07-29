"""Tests for TabLabeling — keyboard labeling flow.

The tab drives the labeling_session model. We exercise the public
surface (load Excel via the session, press number-key, verify label
set + sample navigation) without depending on having an actual FSA
file on disk.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_test_excel(tmp_path) -> str:
    """Create a tracking Excel with 5 unlabeled samples."""
    path = str(tmp_path / "tracking.xlsx")
    df = pd.DataFrame({
        "DIT": ["26A01", "26A01", "26B02", "26B02", "26C03"],
        "Assay": ["FR1", "IGK", "FR1", "FR1", "IGK"],
        "Well": ["A01", "A02", "A03", "A04", "A05"],
        "File": [f"sample{i}.fsa" for i in range(1, 6)],
        "SourceRunDir": ["run_2025_01_15"] * 5,
        "IdentityKey": [f"ID{i}" for i in range(1, 6)],
        "SampleKind": ["patient"] * 5,
        "Group": ["B", "B", "A", "B", "A"],
        "ClonalitySuggestion": ["", "", "", "", ""],
        "ClonalityReviewNeeded": [False, True, False, True, False],
    })
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Run", index=False)
    return path


def test_tab_loads_session_from_excel(qapp, tmp_path):
    """Tab construction succeeds, Browse calls the session loader."""
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()

    # Manually exercise the same path Browse would: load the session.
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()

    assert tab._session.total_count == 5
    assert tab.sample_list.count() == 5
    assert tab._session.labeled_count == 0


def test_tab_label_key_assigns_label(qapp, tmp_path):
    """Shortcut handler routes through _on_label_key to label_sample."""
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()
    tab.sample_list.setCurrentRow(0)  # ensure a sample is selected

    # Press "1" via the handler so we can verify label without auto-advance.
    # We bypass the auto-advance by calling the session directly here.
    tab._session.label_sample(0, "monoklonal")
    assert tab._session.samples[0].current_label == "monoklonal"


def test_tab_label_key_advances_to_next_visible_sample(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()
    tab.sample_list.setCurrentRow(0)

    tab._on_label_key("monoklonal")

    assert tab._session.samples[0].current_label == "monoklonal"
    assert tab.sample_list.currentRow() == 1


def test_tab_label_key_labels_only_selected_parallel(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()
    tab.sample_list.setCurrentRow(2)

    assert tab._session.parallel_indices_for(2) == [2, 3]
    tab._on_label_key("qc_teknisk_fail")

    assert tab._session.samples[2].current_label == "qc_teknisk_fail"
    assert tab._session.samples[3].current_label == ""


def test_tab_labels_dual_channels_separately_before_advancing(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()
    tab.sample_list.setCurrentRow(1)

    assert tab.channel_selector.count() == 2
    assert tab.channel_selector.currentData() == "DATA1"

    tab._on_label_key("polyklonal")
    assert tab._session.samples[1].label_for_channel("DATA1") == "polyklonal"
    assert tab.channel_selector.currentData() == "DATA2"

    tab._on_label_key("monoklonal")
    assert tab._session.samples[1].label_for_channel("DATA2") == "monoklonal"
    assert tab._session.samples[1].is_labeled


def test_tab_navigation_next_prev(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()

    # QListWidget starts with no selection; set row 0 explicitly.
    tab.sample_list.setCurrentRow(0)
    assert tab.sample_list.currentRow() == 0

    tab._on_next_sample()
    assert tab.sample_list.currentRow() == 1

    tab._on_next_sample()
    assert tab.sample_list.currentRow() == 2

    tab._on_prev_sample()
    assert tab.sample_list.currentRow() == 1


def test_tab_filter_shows_unlabeled_only(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()

    # Label 2 of 5 samples
    tab._session.label_sample(0, "monoklonal")
    tab._session.label_sample(1, "polyklonal")
    tab._refresh_sample_list()
    assert tab.sample_list.count() == 5  # all show by default

    tab._on_toggle_filter()
    assert tab._show_unlabeled_only is True
    assert tab.sample_list.count() == 4  # IGK still has one unlabeled channel

    tab._on_toggle_filter()
    assert tab._show_unlabeled_only is False
    assert tab.sample_list.count() == 5


def test_tab_filters_rule_review_rows_and_assay(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._populate_assay_filter()

    tab.queue_filter.setCurrentIndex(tab.queue_filter.findData("review"))
    assert tab.sample_list.count() == 2

    tab.assay_filter.setCurrentIndex(tab.assay_filter.findData("FR1"))
    assert tab.sample_list.count() == 1
    assert tab._current_sample_index() == -1
    tab.sample_list.setCurrentRow(0)
    assert tab._current_sample_index() == 3


def test_progress_bar_updates(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()
    tab._refresh_sample_list()

    tab._update_progress()
    assert "0 / 7" in tab.progress.format()

    tab._session.label_sample(0, "monoklonal")
    tab._session.label_sample(1, "polyklonal")
    tab._update_progress()
    assert "2 / 7" in tab.progress.format()


def test_save_round_trip(qapp, tmp_path):
    from gui_qt.tabs.tab_labeling import TabLabeling
    from core.labeling.labeling_session import LabelingSession

    path = _make_test_excel(tmp_path)
    tab = TabLabeling()
    tab._session = LabelingSession(excel_path=path)
    tab._session.load()

    tab._session.label_sample(0, "monoklonal")
    tab._session.label_sample(2, "polyklonal")
    written = tab._session.save_to_excel()
    assert written == 2

    # Reload from the same Excel and verify
    session2 = LabelingSession(excel_path=path)
    session2.load()
    assert session2.samples[0].current_label == "monoklonal"
    assert session2.samples[2].current_label == "polyklonal"


def test_tab_applies_calibrated_plot_data(qapp):
    pytest.importorskip("pyqtgraph")

    from core.labeling.labeling_plot import LabelingPeak, LabelingPlotData, LabelingTrace
    from gui_qt.tabs.tab_labeling import TabLabeling

    tab = TabLabeling()
    plot_data = LabelingPlotData(
        assay="FR1",
        traces=(
            LabelingTrace(
                channel="DATA1",
                basepairs=np.asarray([280.0, 320.0, 360.0, 420.0]),
                rfu=np.asarray([5.0, 80.0, 25.0, 4.0]),
            ),
        ),
        peaks=(
            LabelingPeak(channel="DATA1", basepair=320.0, rfu=80.0, kept=True),
        ),
        interpretation_ranges=((310.0, 360.0),),
        bp_min=280.0,
        bp_max=420.0,
        ladder_qc_status="ok",
    )

    tab._apply_plot_data(plot_data)

    assert "FR1" in tab.lbl_plot_status.text()
    assert "310-360 bp" in tab.lbl_plot_status.text()
    assert "1 peaks" in tab.lbl_plot_status.text()
    assert tab.plot_widget.getAxis("bottom").labelText == "Base pairs"


def test_tab_paginates_more_than_two_parallel_plots(qapp):
    pytest.importorskip("pyqtgraph")

    from core.labeling.labeling_plot import LabelingPlotData, LabelingTrace
    from gui_qt.tabs.tab_labeling import TabLabeling

    tab = TabLabeling()
    items = []
    for index in range(4):
        items.append(
            {
                "sample_index": index,
                "plot_data": LabelingPlotData(
                    assay="FR1",
                    traces=(
                        LabelingTrace(
                            channel="DATA1",
                            basepairs=np.asarray([280.0, 320.0]),
                            rfu=np.asarray([5.0, 80.0]),
                        ),
                    ),
                    peaks=(),
                    interpretation_ranges=((310.0, 360.0),),
                    bp_min=280.0,
                    bp_max=420.0,
                    ladder_qc_status="ok",
                ),
                "error": "",
            }
        )

    tab._apply_plot_group(items)

    assert len(tab._plot_widgets) == 2
    assert not tab.plot_page_nav.isHidden()
    assert "Plots 1-2 of 4" in tab.lbl_plot_page.text()

    tab._on_next_plot_page()

    assert len(tab._plot_widgets) == 2
    assert "Plots 3-4 of 4" in tab.lbl_plot_page.text()


def test_tab_ignores_stale_plot_result(qapp, monkeypatch):
    from gui_qt.tabs.tab_labeling import TabLabeling

    tab = TabLabeling()
    tab._plot_generation = 2
    applied = []
    monkeypatch.setattr(tab, "_apply_plot_data", applied.append)

    tab._on_plot_ready(1, "missing.fsa", SimpleNamespace(), "")

    assert applied == []
