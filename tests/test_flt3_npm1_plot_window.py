"""FLT3 / NPM1 plot-window guards (Phase 15).

Covers the three cases that motivated this phase:

1. NPM1 with no app override / no entry override lands at the
   config-default ``(290.0, 330.0)`` so the chemist sees the
   WT (299-301) and MUT (303-305) hybridisation rectangles plus a
   small sideband.
2. Per-app override (live settings dict) wins over the config default
   so the chemist can dial it in from the Settings tab.
3. Per-entry override (``forced_xmin`` / ``forced_xmax`` set on the
   entry itself) wins over both — the report-side pipeline can still
   pin a window tightly without touching settings.
4. Non-FLT3 assays fall through to ``None`` so the figure builder
   keeps using detector-driven ``bp_min`` / ``bp_max``.
"""
from __future__ import annotations

import unittest

from core.analyses.flt3.config import (
    FLT3_NPM1_DEFAULT_HALF_WIDTH_BP,
    FLT3_PLOT_BP_WINDOWS,
    get_flt3_npm1_half_width_bp,
    get_flt3_peak_window_settings,
    get_flt3_plot_window,
)
from core.plotting_plotly._legacy import (
    _resolved_plot_xmax,
    _resolved_plot_xmin,
)


def _entry(assay="NPM1", *, forced_xmin=None, forced_xmax=None) -> dict:
    return {
        "assay": assay,
        "primary_peak_channel": "DATA3",
        "trace_channels": ["DATA3"],
        "peaks_by_channel": {},
        "file_name": "x.fsa",
        "wt_bp": 300.0,
        "mut_bp": 304.0,
        "bp_min": 50.0,
        "bp_max": 1000.0,
    } | ({"forced_xmin": forced_xmin} if forced_xmin is not None else {}) | (
        {"forced_xmax": forced_xmax} if forced_xmax is not None else {}
    )


class Flt3PlotWindowConfigTests(unittest.TestCase):
    def test_default_npm1_window_is_290_330(self) -> None:
        self.assertEqual(get_flt3_plot_window("NPM1"), (290.0, 330.0))
        self.assertEqual(FLT3_PLOT_BP_WINDOWS["NPM1"], (290.0, 330.0))

    def test_non_flt3_assay_returns_none(self) -> None:
        self.assertIsNone(get_flt3_plot_window("FLT3-ITD"))
        self.assertIsNone(get_flt3_plot_window("FR1"))
        self.assertIsNone(get_flt3_plot_window(""))

    def test_app_setting_overrides_default(self) -> None:
        settings = {
            "analyses": {
                "flt3": {
                    "peak_window": {
                        "npm1_x_min": 295.0,
                        "npm1_x_max": 312.0,
                    }
                }
            }
        }
        self.assertEqual(get_flt3_plot_window("NPM1", settings=settings), (295.0, 312.0))

    def test_malformed_window_collapsed_falls_back_to_default(self) -> None:
        # xmax <= xmin collapses; must revert to defaults
        settings = {"analyses": {"flt3": {"peak_window": {"npm1_x_min": 320.0, "npm1_x_max": 300.0}}}}
        self.assertEqual(get_flt3_plot_window("NPM1", settings=settings), (290.0, 330.0))

    def test_half_width_default_is_1bp(self) -> None:
        self.assertEqual(FLT3_NPM1_DEFAULT_HALF_WIDTH_BP, 1.0)
        self.assertEqual(get_flt3_npm1_half_width_bp(), 1.0)

    def test_half_width_clamps_outside_safe_range(self) -> None:
        # too small / too big -> clamp to [0.3, 5.0]
        settings = {"analyses": {"flt3": {"peak_window": {"npm1_half_width_bp": 0.05}}}}
        self.assertAlmostEqual(get_flt3_npm1_half_width_bp(settings=settings), 0.3)
        settings = {"analyses": {"flt3": {"peak_window": {"npm1_half_width_bp": 99.0}}}}
        self.assertAlmostEqual(get_flt3_npm1_half_width_bp(settings=settings), 5.0)

    def test_bundle_accessor_returns_consistent_values(self) -> None:
        bundle = get_flt3_peak_window_settings()
        self.assertEqual(set(bundle), {"npm1_half_width_bp", "npm1_x_min", "npm1_x_max"})
        self.assertEqual(bundle["npm1_x_min"], 290.0)
        self.assertEqual(bundle["npm1_x_max"], 330.0)
        self.assertEqual(bundle["npm1_half_width_bp"], 1.0)


class Flt3ResolvedPlotXMinMaxTests(unittest.TestCase):
    def test_npm1_with_no_entry_override_uses_setting_default(self) -> None:
        self.assertEqual(_resolved_plot_xmin(_entry("NPM1")), 290.0)
        self.assertEqual(_resolved_plot_xmax(_entry("NPM1")), 330.0)

    def test_entry_override_wins_over_app_setting(self) -> None:
        # entry-level forced_xmin sits on top of npm1 default
        self.assertEqual(_resolved_plot_xmin(_entry("NPM1", forced_xmin=288.5)), 288.5)
        self.assertEqual(_resolved_plot_xmax(_entry("NPM1", forced_xmax=325.0)), 325.0)

    def test_non_flt3_assay_returns_none(self) -> None:
        self.assertIsNone(_resolved_plot_xmin(_entry("FLT3-ITD")))
        self.assertIsNone(_resolved_plot_xmax(_entry("FLT3-ITD")))

    def test_unknown_assay_returns_none(self) -> None:
        self.assertIsNone(_resolved_plot_xmin(_entry("")))
        self.assertIsNone(_resolved_plot_xmin(_entry("FR1")))


if __name__ == "__main__":
    unittest.main()
