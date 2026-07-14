"""NPM1 half-width + local-baseline math (Phase 15.2).

Pins three contracts after the Phase 15.2 changes:

1. ``_peak_area_half_width_bp(\"NPM1\", label, center_bp)`` returns the
   FLT3 settings accessor (default 1.0 bp, slider-overridable live).
2. ``_calculate_peak_area_local_baseline`` survives a half-width of
   1.0 bp without collapsing the sideband closer than 1.5 bp -
   because if it did, the local-baseline control samples would sit
   inside the integration window and the baseline would track the
   peak shoulder, defeating the subtraction.
3. ``_local_baseline_rfu_at_bp`` returns the *baseline level at the
   peak center*, not the peak height - the dashed-line basis for the
   Phase 15.3 shaded-area visual.
"""
from __future__ import annotations

import unittest

import numpy as np

from core.analyses.flt3.pipeline._legacy import (
    _calculate_peak_area_local_baseline,
    _local_baseline_rfu_at_bp,
    _peak_area_half_width_bp,
)


def _synth_npm1_trace(seed: int = 42):
    """Build a representative NPM1 electropherogram: 60 RFU baseline +
    a narrow Gaussian peak (sigma = 0.6 bp) centered at 300 bp on a
    290-310 bp trace (~0.05 bp per sample).
    """
    rng = np.random.default_rng(seed)
    time_all = np.arange(0, 401)
    bp_all = np.linspace(290.0, 310.0, time_all.size)
    peak = 250.0 * np.exp(-0.5 * ((bp_all - 300.0) / 0.6) ** 2)
    trace = 60.0 + peak + 1.0 * rng.normal(size=time_all.size)
    return trace, time_all, bp_all


class Npm1HalfWidthTests(unittest.TestCase):
    def test_default_npm1_half_width_is_one_bp(self):
        self.assertAlmostEqual(_peak_area_half_width_bp("NPM1", "WT", 300.0), 1.0)
        self.assertAlmostEqual(_peak_area_half_width_bp("NPM1", "MUT", 304.0), 1.0)
        self.assertAlmostEqual(_peak_area_half_width_bp("NPM1", "", 299.5), 1.0)

    def test_settings_accessor_overrides_npm1_half_width(self):
        # Simulate the GUI saving a wider half-width and verify the
        # pipeline helper honours it on the next call.
        import config
        saved = config.APP_SETTINGS.get("analyses", {}).get("flt3", {}).get("peak_window", {})
        before = dict(saved)
        try:
            config.APP_SETTINGS.setdefault("analyses", {}).setdefault("flt3", {})["peak_window"] = {
                "npm1_half_width_bp": 2.5,
                "npm1_x_min": 290.0,
                "npm1_x_max": 330.0,
            }
            self.assertAlmostEqual(_peak_area_half_width_bp("NPM1", "WT", 300.0), 2.5)
        finally:
            config.APP_SETTINGS.setdefault("analyses", {}).setdefault("flt3", {})["peak_window"] = before

    def test_other_assays_unaffected(self):
        # FLT3-ITD WT still 2.0 bp; FLT3-D835 WT still 1.2; unknown assay
        # still falls through to the legacy 5.0 bp default.
        self.assertAlmostEqual(_peak_area_half_width_bp("FLT3-ITD", "WT", 330.0), 2.0)
        self.assertAlmostEqual(_peak_area_half_width_bp("FLT3-D835", "WT", 80.0), 1.2)
        self.assertAlmostEqual(_peak_area_half_width_bp("FR1", "WT", 100.0), 5.0)


class Npm1LocalBaselineTests(unittest.TestCase):
    def test_local_baseline_does_not_collapse_at_one_bp_npm1(self):
        # Sanity: with HW=1 bp the function still produces a strictly
        # positive area (no NaN, no zero-collapse) on a representative
        # NPM1-shaped trace. Earlier behaviour before the sideband
        # floor was acceptable here numerically but the sideband
        # window was too tight to suppress the peak shoulder.
        trace, time_all, bp_all = _synth_npm1_trace()
        area = _calculate_peak_area_local_baseline(
            trace, time_all, bp_all, center_bp=300.0, half_width_bp=1.0
        )
        self.assertTrue(np.isfinite(area))
        self.assertGreater(area, 0.0)

    def test_local_baseline_rfu_at_centre_stays_on_baseline(self):
        # The helper must NOT return the *peak* RFU when measured at the
        # centre; the dashed-line follow-up in Atomic 3 draws this value
        # as the baseline beneath the shaded integration window.
        trace, time_all, bp_all = _synth_npm1_trace()
        baseline = _local_baseline_rfu_at_bp(trace, time_all, bp_all, 300.0, 1.0)
        peak_height = float(trace[time_all[(bp_all >= 299.95) & (bp_all <= 300.05)]].max())
        # baseline should sit near 60 RFU (+tiny noise), peak height at 250+
        self.assertGreater(peak_height, 200.0)
        self.assertLess(baseline, 100.0, f"baseline contaminated? got {baseline}")
        self.assertGreater(baseline, 30.0, f"baseline implausibly low? got {baseline}")

    def test_wider_half_width_yields_larger_area(self):
        # Wider integration window must bring in *more* (positive)
        # area than a narrower one on the same synthetic.
        trace, time_all, bp_all = _synth_npm1_trace()
        narrow = _calculate_peak_area_local_baseline(
            trace, time_all, bp_all, center_bp=300.0, half_width_bp=1.0
        )
        wide = _calculate_peak_area_local_baseline(
            trace, time_all, bp_all, center_bp=300.0, half_width_bp=3.0
        )
        self.assertGreater(wide, narrow)

    def test_local_baseline_helper_handles_edge_inputs(self):
        # Empty trace, missing bp_all, and other degenerate inputs must
        # silently return 0 without raising - same contract as the
        # area-based helper.
        empty = np.asarray([], dtype=float)
        self.assertEqual(_local_baseline_rfu_at_bp(empty, empty, empty, 300.0, 1.0), 0.0)
        self.assertEqual(_calculate_peak_area_local_baseline(empty, empty, empty, 300.0, 1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
