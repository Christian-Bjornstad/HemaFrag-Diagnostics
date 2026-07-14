"""End-to-end render smoke for FLT3 selected-peak area shading (Phase 15.3).

The JS shading lives inside a Plotly f-string in
``core.plotting_plotly/_legacy.py``. There is no Qt-driven rendering
test path for it (headless Plotly on Windows CI is flaky), so this
file pins:

1. The Python helpers ``_selected_peak_area_shape`` and ``_hex_to_rgba``
   produce the *shape-dicts* Plotly expects (round-trippable JSON).
2. The ``build_interactive_peak_plot_for_entry`` call for a synthetic
   FLT3-NPM1 entry emits a JS bootstrap that contains the new layout
   symbols (``peakHalfWidthBp`` for NPM1 branch, ``peakYMax``,
   ``npm1HalfWidthBp``, ``hexToRgba``, ``baselineRfuForPeak``,
   ``computeSelectedAreaShapes``, and the relayout ``selectedAreaShapes``
   concat).

Both are byte-grep "anchor" tests - the same pattern Plan 12's
html-report-jss-css-editing.md recommends for embedded JS /
CSS modules that don't have a clean Playwright/Qt cover.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from core.plotting_plotly._legacy import (
    _hex_to_rgba,
    _selected_peak_area_shape,
    build_interactive_peak_plot_for_entry,
)


def _synth_npm1_entry(seed: int = 7) -> dict:
    """Build a minimal synthetic FLT3-NPM1 entry for the renderer."""
    N = 401
    time_all = np.arange(N)
    bp_all = np.linspace(280.0, 320.0, N)
    rng = np.random.default_rng(seed)
    sigma = 0.6
    peak_wt = 250.0 * np.exp(-0.5 * ((bp_all - 300.0) / sigma) ** 2)
    peak_mut = 180.0 * np.exp(-0.5 * ((bp_all - 304.0) / sigma) ** 2)
    trace = 60.0 + peak_wt + peak_mut + 1.0 * rng.normal(size=N)
    fsa = SimpleNamespace(
        file_name="synthetic_NPM1.fsa",
        fsa={"DATA3": trace},
        sample_data_with_basepairs=pd.DataFrame({"time": time_all, "basepairs": bp_all}),
    )
    return {
        "fsa": fsa,
        "assay": "NPM1",
        "primary_peak_channel": "DATA3",
        "trace_channels": ["DATA3"],
        "peaks_by_channel": {
            "DATA3": pd.DataFrame(
                [
                    {"basepairs": 300.0, "peaks": 305.0, "area": 380.0, "channel": "DATA3", "label": "WT"},
                    {"basepairs": 304.0, "peaks": 240.0, "area": 280.0, "channel": "DATA3", "label": "MUT"},
                ]
            )
        },
        "bp_min": 50.0,
        "bp_max": 1000.0,
        "wt_bp": 300.0,
        "mut_bp": 304.0,
        "group": None,
    }


class HexToRgbaTests(unittest.TestCase):
    def test_converts_canonical_hex(self):
        self.assertEqual(_hex_to_rgba("#dc2626", 0.5), "rgba(220,38,38,0.5)")
        self.assertEqual(_hex_to_rgba("#2563eb", 0.18), "rgba(37,99,235,0.18)")

    def test_pads_short_hex(self):
        self.assertEqual(_hex_to_rgba("#f00", 1.0), "rgba(255,0,0,1)")

    def test_bad_inputs_fall_back_to_black(self):
        self.assertEqual(_hex_to_rgba("zzz", 0.18), "rgba(0,0,0,0.18)")
        self.assertEqual(_hex_to_rgba(None, 0.18), "rgba(0,0,0,0.18)")


class SelectedPeakAreaShapeTests(unittest.TestCase):
    def test_emits_rect_and_dashed_line_when_baseline_set(self):
        peak = {"x": 300.0}
        shapes = _selected_peak_area_shape(
            peak,
            half_width_bp=1.0,
            baseline_rfu=60.0,
            ymax=400.0,
            accent_hex="#dc2626",
        )
        self.assertEqual(len(shapes), 2)
        rect, line = shapes
        self.assertEqual(rect["type"], "rect")
        self.assertEqual(rect["x0"], 299.0)
        self.assertEqual(rect["x1"], 301.0)
        self.assertEqual(rect["y1"], 400.0)
        self.assertEqual(rect["fillcolor"], "rgba(220,38,38,0.18)")
        self.assertEqual(line["type"], "line")
        self.assertEqual(line["y0"], 60.0)
        self.assertEqual(line["y1"], 60.0)
        self.assertEqual(line["line"]["dash"], "dash")

    def test_emits_only_rect_when_baseline_missing(self):
        peak = {"x": 300.0}
        shapes = _selected_peak_area_shape(
            peak,
            half_width_bp=1.0,
            baseline_rfu=None,
            ymax=400.0,
            accent_hex="#dc2626",
        )
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["type"], "rect")

    def test_skips_when_half_width_zero(self):
        peak = {"x": 300.0}
        shapes = _selected_peak_area_shape(
            peak, half_width_bp=0.0, baseline_rfu=60.0, ymax=400.0, accent_hex="#dc2626"
        )
        self.assertEqual(shapes, [])

    def test_skips_when_peak_x_nan(self):
        peak = {"x": float("nan")}
        shapes = _selected_peak_area_shape(
            peak, half_width_bp=1.0, baseline_rfu=60.0, ymax=400.0, accent_hex="#dc2626"
        )
        self.assertEqual(shapes, [])

    def test_uses_correct_layer_and_xref(self):
        peak = {"x": 304.0}
        rect = _selected_peak_area_shape(
            peak, half_width_bp=2.0, baseline_rfu=55.0, ymax=200.0, accent_hex="#2563eb"
        )[0]
        self.assertEqual(rect["layer"], "above")
        self.assertEqual(rect["xref"], "x")
        self.assertEqual(rect["yref"], "y")
        self.assertEqual(rect["opacity"], 1.0)


class Flt3Npm1RenderBootstrapTests(unittest.TestCase):
    """Byte-grep the rendered HTML for the new JS symbols."""

    def _render(self) -> str:
        entry = _synth_npm1_entry()
        return build_interactive_peak_plot_for_entry(entry) or ""

    def test_html_emits_npm1_half_width_helper(self):
        html = self._render()
        self.assertIn("npm1HalfWidthBp", html)
        # Default 1.0 bp is the literal JS value the Python side feeds in.
        # Tolerate a trailing decimal or trailing zero.
        import re

        m = re.search(r"var\s+npm1HalfWidthBp\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;", html)
        self.assertIsNotNone(m, "npm1HalfWidthBp= not assigned")
        self.assertAlmostEqual(float(m.group(1)), 1.0)

    def test_html_emits_peak_ymax_constant(self):
        html = self._render()
        self.assertIn("var peakYMax", html)

    def test_html_emits_selected_area_helper(self):
        html = self._render()
        # All four JS-side helpers
        for sym in (
            "hexToRgba",
            "baselineRfuForPeak",
            "computeSelectedAreaShapes",
            "selectedAreaShapes",
        ):
            self.assertIn(sym, html, f"missing JS helper: {sym}")

    def test_html_uses_npm1_branch_in_peak_half_width(self):
        html = self._render()
        # The peakHalfWidthBp function's NPM1 branch must be present.
        self.assertTrue(
            '"NPM1"' in html and "npm1HalfWidthBp" in html,
            "NPM1 branch / half-width variable not woven into peakHalfWidthBp",
        )

    def test_relayout_concats_selected_area_shapes(self):
        html = self._render()
        # The relayout call inside redrawPeaks must concat the new shapes.
        self.assertIn("baseShapes.concat(selectedAreaShapes)", html)


if __name__ == "__main__":
    unittest.main()
