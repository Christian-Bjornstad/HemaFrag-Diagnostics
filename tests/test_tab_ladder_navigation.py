"""Wiring sanity check: TabLadder has 3 navigation QShortcut objects."""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from gui_qt.tabs.tab_ladder._legacy import TabLadder
from gui_qt.tabs.tab_ladder._overview import ChipFilterBar, ChipStripOverview
from gui_qt.tabs.tab_ladder._summary import CHIP_STATE_LABELS


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


class ChipFilterBarWiringTests(unittest.TestCase):
    """Phase 12.7 — chip-state filter bar wiring."""

    def test_filter_bar_installed_on_tab(self) -> None:
        tab = TabLadder(parent=None)
        # _build_source_card must have built the bar.
        self.assertTrue(hasattr(tab, "_chip_filter_bar"))
        self.assertIsInstance(tab._chip_filter_bar, ChipFilterBar)

    def test_chip_strip_already_installed(self) -> None:
        bar, strip = self._build_pair()
        self.assertIsInstance(bar, ChipFilterBar)
        self.assertIsInstance(strip, ChipStripOverview)

    def test_initial_state_allows_every_chip_state(self) -> None:
        # Right after construction, the bar defaults to allowing
        # every chip state — PhiFlag(None) signals "no filter"
        # back to ChipStripOverview.
        bar = ChipFilterBar()
        self.assertEqual(bar.allowedStates(), None)
        self.assertEqual(bar._allowed_states, set(CHIP_STATE_LABELS))

    def test_select_all_resets(self) -> None:
        bar = ChipFilterBar()
        bar._select_none()
        self.assertEqual(bar.allowedStates(), set())
        bar._select_all()
        self.assertEqual(bar.allowedStates(), None)

    def test_select_none_blocks_all(self) -> None:
        bar = ChipFilterBar()
        bar._select_none()
        # After "None", allowed_states is empty set — pin so a
        # future refactor doesn't accidentally revert to None.
        self.assertEqual(bar._allowed_states, set())
        self.assertEqual(bar.allowedStates(), set())
        for s in ("reviewed", "needs_review", "file_unreachable", "untouched"):
            self.assertFalse(bar.isStateAllowed(s))

    def test_set_rows_updates_counts_label(self) -> None:
        bar = ChipFilterBar()
        rows = [
            {"full_path": "a", "_path_unreachable": "false", "label": "manual_adjusted", "ladder_qc_status": "ok"},
            {"full_path": "b", "_path_unreachable": "true"},
            {"full_path": "c", "_path_unreachable": "false"},
        ]
        bar.setRows(rows)
        # Default state (all allowed) → "3 / 3".
        self.assertEqual(bar.counts_label.text(), "3 / 3")
        bar._select_none()
        # With empty allowed-set, the visible count drops to 0.
        self.assertTrue(bar.counts_label.text().startswith("visible 0 / 3"))

    def test_set_rows_empty_clears_label(self) -> None:
        bar = ChipFilterBar()
        bar.setRows([{"full_path": "a", "_path_unreachable": "false",
                      "label": "", "ladder_qc_status": "ok"}])
        bar.setRows([])
        self.assertEqual(bar.counts_label.text(), "")

    def _build_pair(self):
        """Return (filter bar, chip strip) from a freshly built tab."""
        tab = TabLadder(parent=None)
        return tab._chip_filter_bar, tab._chip_strip


class TabLadderChipFilterForwardingTests(unittest.TestCase):
    """Phase 12.7 — filter-bar selection flows into the chip strip."""

    def test_filter_changed_forwards_to_strip(self) -> None:
        # Construct a tab and emit a synthetic filterChanged.
        tab = TabLadder(parent=None)
        bar = tab._chip_filter_bar
        strip = tab._chip_strip
        # Default state is no filter — allowedStates() is None.
        self.assertIsNone(bar.allowedStates())

        # Synthesize toggling "Reviewed" off via the helper.
        bar._on_toggle("reviewed", False)
        # After blocking one state, the allowed set is the rest.
        # Allow-states shape should be a 3-element set (not None).
        self.assertIsNotNone(bar.allowedStates())
        self.assertNotIn("reviewed", bar.allowedStates())

        # And the chip strip's set_filter pathway was driven.
        self.assertEqual(strip._allowed_states, bar._allowed_states)


if __name__ == "__main__":
    unittest.main(verbosity=2)
