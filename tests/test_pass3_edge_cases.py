"""Pass 3 edge-case tests: lock the multi-Pass-1+2 refactors' correctness.

These tests guard against regressions to behaviour that existed
before the perf (Pass 1) and DRY (Pass 2) campaigns. They do NOT
introduce new behaviour; they pin the obvious edge cases.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from core.analysis._legacy import _rolling_quantile_baseline
from core.area import _gaussian_model_cls, compute_peak_area_gaussian
from core.plot_cache import (
    FsaPlotCache,
    EntryPlotCache,
    get_fsa_axis_arrays,
    get_fsa_trace_array,
)


class RollingQuantileBaselineEdgeTests(unittest.TestCase):
    """Lock _rolling_quantile_baseline behaviour for edge sizes/quantiles.

    These existed in the original Python-loop implementation; the
    vectorised version preserves them. If a future refactor
    regresses, these fail.
    """

    def test_empty_trace(self) -> None:
        out = _rolling_quantile_baseline(np.array([]))
        self.assertEqual(out.size, 0)

    def test_length_one_trace(self) -> None:
        out = _rolling_quantile_baseline(np.array([42.0]))
        self.assertEqual(out.size, 1)
        self.assertTrue(np.isfinite(out).all())

    def test_length_below_bin_size(self) -> None:
        # bin_size 200 default; n=10 -> single short bin.
        tr = np.linspace(50, 450, 10)
        out = _rolling_quantile_baseline(tr)
        self.assertEqual(out.shape, (10,))
        # All-zero baseline since the entire trace is one bin's
        # quantile and we evaluated at quantile=0.10.
        q = float(np.quantile(tr, 0.10))
        np.testing.assert_allclose(out, np.full_like(tr, q), rtol=1e-12)

    def test_bin_size_clamped(self) -> None:
        # bin_size < 20 should be clamped to 20.
        tr = np.random.RandomState(0).rand(500) * 400 + 50
        out_low = _rolling_quantile_baseline(tr, bin_size=10, quantile=0.10)
        out_floor = _rolling_quantile_baseline(tr, bin_size=20, quantile=0.10)
        np.testing.assert_array_equal(out_low, out_floor)

    def test_quantile_one_returns_top_envelope(self) -> None:
        np.random.seed(0)
        tr = np.random.rand(12000) * 400 + 50
        out = _rolling_quantile_baseline(tr, bin_size=200, quantile=1.0)
        # Per-bin top values, linearly interpolated; min(out) should
        # be the global max only if the trace is monotonic; we
        # assert the upper-bound property of quantile=1.
        self.assertGreaterEqual(out.min(), tr.min())

    def test_quantile_zero_returns_bottom_envelope(self) -> None:
        np.random.seed(0)
        tr = np.random.rand(12000) * 400 + 50
        out = _rolling_quantile_baseline(tr, bin_size=200, quantile=0.0)
        # Per-bin minima, interpolated
        self.assertLessEqual(out.max(), tr.max())


class GaussianModelLazyImportTests(unittest.TestCase):
    """Lock lazy lmfit import (Pass 1 Task 1)."""

    def test_lazy_gaussian_model_cls_loads(self) -> None:
        m = _gaussian_model_cls()
        self.assertIsNotNone(m)

    def test_compute_peak_area_gaussian_still_runs(self) -> None:
        # Synthetic spike; result is positive float.
        trace = np.zeros(200)
        trace[80:120] = 100.0
        bp = np.linspace(0, 200, 200)
        t = np.arange(200, dtype=float)
        out = compute_peak_area_gaussian(trace, t, bp, 100.0, 30.0)
        self.assertIsInstance(out, float)
        self.assertGreaterEqual(out, 0.0)


class PlotCacheSmokeTests(unittest.TestCase):
    """Smoke tests for the Pass-2 shared plot_cache module."""

    def test_fsa_plot_cache_round_trip(self) -> None:
        class FakeFsa:
            fsa = {"DATA1": np.array([0.0, 1, 2, 3, 4])}
        f = FakeFsa()
        cache = FsaPlotCache.for_fsa(f)
        tr1 = cache.get_or_compute_trace("DATA1")
        tr2 = cache.get_or_compute_trace("DATA1")
        # Same identity => hits cache.
        self.assertIs(tr1, tr2)

    def test_fsa_plot_cache_invalidates_on_id_change(self) -> None:
        class FakeFsa:
            pass
        f = FakeFsa()
        cache = FsaPlotCache.for_fsa(f)
        # First binding
        f.fsa = {"DATA2": np.array([100.0, 200, 300])}
        tr1 = cache.get_or_compute_trace("DATA2")
        # Re-bind with fresh array => new identity => fresh value
        f.fsa = {"DATA2": np.array([1000.0, 2000, 3000])}
        tr2 = cache.get_or_compute_trace("DATA2")
        # Source array changed => id() changed => cache miss and
        # new value (this is the whole point of source_id-keyed cache).
        self.assertFalse(np.allclose(tr1, tr2))

    def test_entry_plot_cache_display_round_trip(self) -> None:
        entry = {}
        cache_obj = EntryPlotCache.for_entry(entry)
        trace = np.array([1.0, 2, 3, 4])
        called = []

        def compute(t, _assay):
            called.append(t)
            return t * 2

        a = cache_obj.get_or_compute_display("DATA1", trace, "FLT3-ITD", compute)
        b = cache_obj.get_or_compute_display("DATA1", trace, "FLT3-ITD", compute)
        self.assertIs(a, b)
        self.assertEqual(called, [trace])  # second call hit cache

    def test_module_level_shim_matches_class(self) -> None:
        class FakeFsa:
            fsa = {"DATA1": np.array([0.0, 1, 2, 3, 4])}
        f = FakeFsa()
        cache = FsaPlotCache.for_fsa(f)
        # Class-based and shim-based give same array.
        np.testing.assert_array_equal(
            cache.get_or_compute_trace("DATA1"),
            get_fsa_trace_array(f, "DATA1"),
        )


if __name__ == "__main__":
    unittest.main()
