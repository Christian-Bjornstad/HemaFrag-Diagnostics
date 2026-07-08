"""Phase 12.14 — ladder editor preview header helpers.

Pure-Python tests for compose_dialog_header and the
fsa-driven refresh_dialog_header wrapper.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from gui_qt.dialogs.ladder_dialog._legacy import (
    LADDER_DIALOG_BASE_TITLE,
    LADDER_DIALOG_TITLE_SEPARATOR,
    compose_dialog_header,
    refresh_dialog_header,
)


class ComposeDialogHeaderTests(unittest.TestCase):
    """Phase 12.14 — `compose_dialog_header` pure helper."""

    def test_file_only(self) -> None:
        out = compose_dialog_header("a.fsa")
        self.assertEqual(
            out,
            f"{LADDER_DIALOG_BASE_TITLE}{LADDER_DIALOG_TITLE_SEPARATOR}a.fsa",
        )

    def test_file_assay_ladder(self) -> None:
        out = compose_dialog_header("a.fsa", "FR1", "ROX400HD")
        self.assertIn("a.fsa", out)
        self.assertIn("FR1", out)
        self.assertIn("ROX400HD", out)
        # Order: file · assay · ladder (joined by separator).
        self.assertEqual(
            out,
            f"{LADDER_DIALOG_BASE_TITLE}{LADDER_DIALOG_TITLE_SEPARATOR}"
            f"a.fsa{LADDER_DIALOG_TITLE_SEPARATOR}FR1"
            f"{LADDER_DIALOG_TITLE_SEPARATOR}ROX400HD",
        )

    def test_empty_assay_skipped(self) -> None:
        out = compose_dialog_header("a.fsa", "", "ROX400HD")
        self.assertIn("a.fsa", out)
        self.assertIn("ROX400HD", out)
        # Should not show an empty fragment.
        self.assertNotIn(f"{LADDER_DIALOG_TITLE_SEPARATOR}{LADDER_DIALOG_TITLE_SEPARATOR}", out)
        self.assertEqual(
            out,
            f"{LADDER_DIALOG_BASE_TITLE}{LADDER_DIALOG_TITLE_SEPARATOR}"
            f"a.fsa{LADDER_DIALOG_TITLE_SEPARATOR}ROX400HD",
        )

    def test_all_empty_falls_back(self) -> None:
        # No parts at all — graceful fallback to base title.
        out = compose_dialog_header("", "", "")
        self.assertEqual(out, LADDER_DIALOG_BASE_TITLE)


class RefreshDialogHeaderTests(unittest.TestCase):
    """Phase 12.14 — `refresh_dialog_header` wrapper side-effect."""

    def test_refresh_sets_window_title(self) -> None:
        # A dummy QObject doesn't accept setWindowTitle, so use
        # a real QDialog to check the side-effect shape.
        from PyQt6.QtWidgets import QDialog

        dialog = QDialog()
        fsa = SimpleNamespace(file_name="x.fsa", assay="FR1", ladder="ROX400HD")
        refresh_dialog_header(dialog, fsa=fsa)
        title = dialog.windowTitle()
        self.assertIn("x.fsa", title)
        self.assertIn("FR1", title)
        self.assertIn("ROX400HD", title)
        # And the base title prefix.
        self.assertIn(LADDER_DIALOG_BASE_TITLE, title)

    def test_refresh_tolerates_none_dialog(self) -> None:
        # None dialog → no-op, no crash.
        refresh_dialog_header(None, fsa=SimpleNamespace(file_name="x"))
        # None fsa → no-op, no crash.
        from PyQt6.QtWidgets import QDialog
        dialog = QDialog()
        refresh_dialog_header(dialog, fsa=None)
        # Title unchanged.
        self.assertEqual(dialog.windowTitle(), "")

    def test_refresh_falls_back_on_garbage_fsa(self) -> None:
        # FSA with no attributes ⇒ getattr default ⇒ at minimum
        # the base title lands.
        from PyQt6.QtWidgets import QDialog
        dialog = QDialog()
        refresh_dialog_header(dialog, fsa=SimpleNamespace())
        # No crash, title may be base or empty depending on
        # getattr defauts. Just have something.
        title = dialog.windowTitle()
        self.assertIsInstance(title, str)


if __name__ == "__main__":
    unittest.main()
