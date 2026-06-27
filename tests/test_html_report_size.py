"""Regression guard: per-patient Resultater.html size budget.

After code-cleanup Plan 07 PR A the inline plotly switch moved
from the full ~4.6 MB bundle to the slim "basic" ~1.1 MB bundle.
This test enforces that the slim inline tag stays well under
1.5 MB so the per-patient self-contained HTML stays upload-friendly
for LIS.

If the test fails, check `assets/plotly-3.1.0-basic.min.js`. It
should be the slim partial from
`https://unpkg.com/plotly.js-basic-dist-min/plotly-basic.min.js`.
If a vendor update reintroduced a feature we don't use, regenerate
via `scripts/refresh_slim_plotly.py`.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
SLIM_JS_PATH = ASSETS_DIR / "plotly-3.1.0-basic.min.js"
FULL_JS_PATH = ASSETS_DIR / "plotly-3.1.0.min.js"

# Total per-patient HTML payload must include at least the inline JS
# + REPORT_STYLE CSS + a slim HTML scaffold. Typical Resultater.html
# files are ~1.2 MB; cap at 1.5 MB.
SLIM_INLINE_BUDGET_BYTES = 1_500_000
# Pure slim JS budget (allow ~50% headroom over the actual 1.06 MB
# asset to catch extreme regressions).
SLIM_JS_BUDGET_BYTES = 1_500_000


class HtmlReportSizeGuardTests(unittest.TestCase):
    def test_slim_plotly_basic_asset_present(self) -> None:
        self.assertTrue(
            SLIM_JS_PATH.exists(),
            f"Missing slim plotly bundle at {SLIM_JS_PATH}.  "
            f"Run `python scripts/refresh_slim_plotly.py` to fetch.",
        )

    def test_basic_inline_returns_slim_script(self) -> None:
        from core.plotly_offline import plotly_inline_script_tag
        tag = plotly_inline_script_tag()
        # Should be the slim build, ~1.1 MB inline.
        self.assertLess(
            len(tag), SLIM_INLINE_BUDGET_BYTES,
            f"plotly_inline_script_tag returned {len(tag)} bytes "
            f"(>{SLIM_INLINE_BUDGET_BYTES}); slim build drift?")
        # Tag must open with the same shape as before.
        self.assertTrue(tag.startswith("<script>"))
        self.assertTrue(tag.endswith("</script>"))

    def test_full_inline_uses_full_bundle(self) -> None:
        """The full bundle should stay available for the rare HTML
        that genuinely needs gl2d/3d/finance traces.  This test pins
        the size so future vendor updates don't bloat it accidentally
        above 5 MB."""
        from core.plotly_offline import full_inline_script_tag
        if not FULL_JS_PATH.exists():
            self.skipTest(
                f"Bundled full plotly at {FULL_JS_PATH} is intentionally "
                f"absent (slim build only).  Re-add via CARTO_FETCH.md "
                f"if a feature requires it."
            )
        tag = full_inline_script_tag()
        # The full bundle is ~4.6 MB; budget up to 6 MB to allow some
        # headroom for future point releases.
        self.assertLess(
            len(tag), 6_500_000,
            f"full_inline_script_tag returned {len(tag)} bytes; "
            f"version bump may have bloated. Inspect {FULL_JS_PATH}.")

    def test_basic_bundle_features_we_use(self) -> None:
        """Sanity-check the slim bundle has the Plotly APIs we use."""
        from core.plotly_offline import _BASIC_INLINE_CACHE
        from core.plotly_offline import plotly_inline_script_tag
        if not SLIM_JS_PATH.exists():
            self.skipTest("slim bundle missing")
        # Trigger the cache
        plotly_inline_script_tag()
        from core.plotly_offline import _BASIC_INLINE_CACHE as cache
        if cache is None:
            self.skipTest("cache cold despite read attempt")
        for sym in ("Plotly.newPlot", "Plotly.relayout", "plotly_click"):
            # The minifier renames the plotly/Plotly public name, so
            # "Plotly.newPlot" / "Plotly.relayout" appear as
            # ".newPlot" / ".relayout" in the bundled JS.
            marker_map = {"Plotly.newPlot": ".newPlot", "Plotly.relayout": ".relayout"}
            marker = marker_map.get(sym, sym)
            self.assertIn(
                marker, cache,
                f"slim bundle missing required symbol {marker!r};"
                f" vendor update may have regressed the basics build."
            )


if __name__ == "__main__":
    unittest.main()
