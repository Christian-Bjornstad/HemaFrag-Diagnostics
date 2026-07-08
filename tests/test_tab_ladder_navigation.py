"""Wiring sanity check: TabLadder has 3 navigation QShortcut objects."""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from gui_qt.tabs.tab_ladder._legacy import TabLadder


class TabLadderNavigationWiringTests(unittest.TestCase):
    def test_three_shortcuts_installed(self) -> None:
        tab = TabLadder(parent=None)
        # 3 shortcuts: Alt+J (prev), Alt+K (next), Ctrl+. (next relevant)
        self.assertTrue(hasattr(tab, "_nav_shortcuts"))
        self.assertEqual(len(tab._nav_shortcuts), 3)

    def test_nav_move_silent_without_bundle(self) -> None:
        # No bundle loaded → the slot just returns, doesn't crash.
        tab = TabLadder(parent=None)
        tab._nav_move_chip(direction=+1)  # must not raise
        tab._nav_move_chip(direction=-1)
        tab._nav_jump_next_relevant()

    def test_current_chip_index_returns_minus_one_empty(self) -> None:
        tab = TabLadder(parent=None)
        self.assertEqual(tab._current_chip_index(), -1)

    def test_current_chip_index_finds_path_in_bundle(self) -> None:
        from pathlib import Path
        from gui_qt.tabs.tab_ladder._legacy import TabLadder
        tab = TabLadder(parent=None)
        fake_a = Path("/tmp/x_a.fsa")
        fake_b = Path("/tmp/x_b.fsa")
        tab._review_bundle_cases = [
            {"full_path": str(fake_a)},
            {"full_path": str(fake_b)},
        ]
        # No current file → -1
        self.assertEqual(tab._current_chip_index(), -1)
        tab._current_file = fake_a
        self.assertEqual(tab._current_chip_index(), 0)
        tab._current_file = fake_b
        self.assertEqual(tab._current_chip_index(), 1)
        # Unrelated current_file → -1
        tab._current_file = Path("/tmp/zz.fsa")
        self.assertEqual(tab._current_chip_index(), -1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
