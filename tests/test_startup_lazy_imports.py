"""Startup performance guardrails.

The Qt window must appear WITHOUT pulling the heavy scientific stack
(scipy / sklearn / pandas / matplotlib / Biopython / core.analysis). Those
modules cost ~2 s of import time and are only needed once a batch run,
ladder review dialog, or archive job actually starts.

Regression: tab_ladder -> gui_qt.ladder_utils -> core.analysis dragged
scipy+sklearn+Bio into every startup; tab_archive_runner dragged pandas in;
tab_ladder's eager LadderAdjustmentDialog import dragged matplotlib in.
"""
from __future__ import annotations

import importlib
import sys
import unittest


HEAVY_MODULES = (
    "core.analysis._legacy",
    "scipy.signal",
    "sklearn",
    "matplotlib.pyplot",
    "pandas",
    "Bio",
)


def _assert_light(self, *module_names: str) -> None:
    for target in module_names:
        before = set(sys.modules)
        importlib.import_module(target)
        added_heavy = [heavy for heavy in HEAVY_MODULES if heavy in sys.modules and heavy not in before]
        self.assertEqual(
            added_heavy,
            [],
            f"importing {target} must stay lightweight, but it pulled in {added_heavy}",
        )


class StartupImportLightnessTests(unittest.TestCase):
    def test_main_window_does_not_import_scientific_stack(self) -> None:
        _assert_light(self, "gui_qt.main_window")

    def test_tab_ladder_does_not_import_core_analysis_or_matplotlib(self) -> None:
        _assert_light(self, "gui_qt.tabs.tab_ladder")

    def test_ladder_dialog_only_loaded_on_demand(self) -> None:
        # The ladder adjustment dialog is a heavy interactive editor
        # (matplotlib canvas). Importing gui_qt.tabs.tab_ladder itself must
        # not pull it in; only opening the dialog may. Delta-based so other
        # tests in the same process having loaded it don't false-positive.
        import sys

        import gui_qt.tabs.tab_ladder  # noqa: F401

        before = set(sys.modules)
        importlib.reload(sys.modules["gui_qt.tabs.tab_ladder"])
        added = set(sys.modules) - before
        self.assertNotIn("gui_qt.dialogs.ladder_dialog", added)

    def test_archive_runner_defers_pandas_until_used(self) -> None:
        _assert_light(self, "gui_qt.tabs.tab_archive_runner")

    def test_ladder_utils_stays_light_but_keeps_runtime_helpers(self) -> None:
        _assert_light(self, "gui_qt.ladder_utils")

        import gui_qt.ladder_utils as lu

        # Config-only helpers must keep working without core.analysis loaded.
        self.assertEqual(lu._resolve_exact_ladder_name("clonality", "LIZ"), "LIZ500_250")
        self.assertEqual(lu._resolve_exact_ladder_name("general", "ROX"), lu.GENERAL_DEFAULT_LADDER)

    def test_archive_support_still_available_after_lazy_load(self) -> None:
        import gui_qt.tabs.tab_archive_runner as ar

        runners = ar._ensure_archive_modules()
        self.assertTrue(ar._ARCHIVE_SUPPORT_AVAILABLE)
        self.assertIn("clonality", runners)
        self.assertIn("flt3", ar._COMBINERS)
        self.assertTrue(callable(ar._RUNNERS["clonality"]))
        self.assertTrue(callable(ar._COMBINERS["flt3"]))

    def test_ladder_adjustment_functions_still_reachable(self) -> None:
        # The persistence API moves to a light module; both import paths must work.
        from core.ladder_adjustment_io import load_ladder_adjustment, save_ladder_adjustment

        self.assertTrue(callable(load_ladder_adjustment))
        self.assertTrue(callable(save_ladder_adjustment))


if __name__ == "__main__":
    unittest.main()
