"""GUI round-trip test for the FLT3 peak-area settings card.

Single Qt-light test: instantiate ``TabAnalysisSettings(\"flt3\")`` (offscreen),
set the spinbox values the GUI exposes, and confirm the bound
``APP_SETTINGS[\"analyses\"][\"flt3\"][\"peak_window\"]`` block is populated
correctly when ``save()`` is invoked. No filesystem writes — we patch
``save_settings`` to a no-op so the test never touches the user's
settings.yaml.

Mirrors the Plan 12 §15 cadence: helper test pins the saved-values
contract; GUI live-Qt test is one widget short test.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import config as _config
from gui_qt.tabs.tab_settings import TabAnalysisSettings


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def patched_save_settings(monkeypatch):
    """Avoid persisting to disk during the test."""
    captured: dict = {}

    def _fake_save(settings, settings_path=None):
        captured["settings"] = settings

    monkeypatch.setattr("gui_qt.tabs.tab_settings.save_settings", _fake_save)
    return captured


@pytest.fixture
def snapshot_flt3_settings():
    """Snapshot / restore the live APP_SETTINGS[flt3] block so test
    mutations do not leak into other test modules sharing the same
    pytest session / interpreter.
    """
    import config as _config
    flt3_before = dict(_config.APP_SETTINGS.get("analyses", {}).get("flt3", {}))
    yield
    # restore peak_window specifically (the rest is fixture noise we do not touch)
    flt3_now = _config.APP_SETTINGS.setdefault("analyses", {}).setdefault("flt3", {})
    if "peak_window" in flt3_before:
        flt3_now["peak_window"] = flt3_before["peak_window"]
    elif "peak_window" in flt3_now:
        # was added by the test, remove it
        flt3_now.pop("peak_window", None)


class TestFlt3PeakWindowGui:
    def test_card_present_for_flt3(self, qapp):
        widget = TabAnalysisSettings("flt3")
        assert hasattr(widget, "npm1_half_width")
        assert hasattr(widget, "npm1_x_min")
        assert hasattr(widget, "npm1_x_max")
        # spinboxes populated with backend defaults
        assert widget.npm1_half_width.value() == pytest.approx(1.0, abs=1e-9)
        assert widget.npm1_x_min.value() == pytest.approx(290.0, abs=1e-9)
        assert widget.npm1_x_max.value() == pytest.approx(330.0, abs=1e-9)
        widget.deleteLater()

    def test_card_added_to_layout_only_for_flt3(self, qapp):
        # Spinboxes are always built (cheap QDoubleSpinBox instances) but the
        # card is *added to the layout* only for the FLT3 analysis — pinning
        # the user-visible contract rather than the implementation detail.
        from PyQt6.QtWidgets import QLayout

        flt3_widget = TabAnalysisSettings("flt3")
        clonality_widget = TabAnalysisSettings("clonality")

        def _is_in_layout(layout: QLayout, target) -> bool:
            for idx in range(layout.count()):
                item = layout.itemAt(idx)
                if item is None:
                    continue
                if item.widget() is target:
                    return True
                inner = item.layout()
                if isinstance(inner, QLayout) and _is_in_layout(inner, target):
                    return True
            return False

        assert hasattr(flt3_widget, "peak_window_card")
        assert hasattr(clonality_widget, "peak_window_card")
        assert _is_in_layout(flt3_widget.layout(), flt3_widget.peak_window_card)
        assert not _is_in_layout(clonality_widget.layout(), clonality_widget.peak_window_card)

        flt3_widget.deleteLater()
        clonality_widget.deleteLater()

    def test_save_persists_peak_window_block(
        self, qapp, patched_save_settings, snapshot_flt3_settings
    ):
        widget = TabAnalysisSettings("flt3")
        # edit the spinboxes as the chemist would
        widget.npm1_half_width.setValue(1.5)
        widget.npm1_x_min.setValue(285.0)
        widget.npm1_x_max.setValue(335.0)
        widget.save()

        analyses = patched_save_settings["settings"]["analyses"]
        peak_window = analyses["flt3"]["peak_window"]
        assert peak_window["npm1_half_width_bp"] == pytest.approx(1.5)
        assert peak_window["npm1_x_min"] == pytest.approx(285.0)
        assert peak_window["npm1_x_max"] == pytest.approx(335.0)
        widget.deleteLater()

    def test_save_clamps_collapsed_window_through_settings_helper(
        self, qapp, patched_save_settings, snapshot_flt3_settings
    ):
        # The GUI keeps xmax > xmin + 1 via the spinbox sync slot; if the
        # helper is bypassed and a malformed block lands in settings, the
        # backend accessor must fall back to defaults.
        widget = TabAnalysisSettings("flt3")
        # simulate malformed collapse: shrink xmax <= xmin via the spinboxes
        # (the GUI nudges one back, so we set the block by hand)
        analyses_section = _config.APP_SETTINGS.setdefault("analyses", {})
        flt3_section = analyses_section.setdefault("flt3", {})
        flt3_section["peak_window"] = {
            "npm1_half_width_bp": 99.0,
            "npm1_x_min": 320.0,
            "npm1_x_max": 300.0,
        }
        from core.analyses.flt3.config import (
            get_flt3_npm1_half_width_bp,
            get_flt3_plot_window,
        )

        # half width clamps to 5.0, window collapses to defaults
        assert get_flt3_npm1_half_width_bp() == pytest.approx(5.0)
        assert get_flt3_plot_window("NPM1") == (290.0, 330.0)
        widget.deleteLater()
