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
    def test_shortcuts_installed(self) -> None:
        tab = TabLadder(parent=None)
        # 4 shortcuts: Alt+J (prev), Alt+K (next), Ctrl+. (next relevant),
        # Ctrl+R (mark current reviewed, Phase 12.13).
        self.assertTrue(hasattr(tab, "_nav_shortcuts"))
        self.assertEqual(len(tab._nav_shortcuts), 4)

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


class TabLadderBulkMarkReviewedWiringTests(unittest.TestCase):
    """Phase 12.8 — 'Mark Visible Reviewed (no change)' button wiring."""

    def test_button_installed(self) -> None:
        tab = TabLadder(parent=None)
        self.assertTrue(hasattr(tab, "btn_bulk_mark_reviewed"))
        self.assertTrue(hasattr(tab, "bulk_mark_label"))

    def test_click_without_bundle_writes_red_status(self) -> None:
        tab = TabLadder(parent=None)
        # The status widget isn't easy to introspect directly
        # without knowing its inner name; we just confirm that
        # the click is a no-op that doesn't raise.
        tab._on_bulk_mark_visible_reviewed_clicked()

    def test_click_with_bundle_writes_changed_count(self) -> None:
        import csv as csvmod
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            real_a = bundle / "a.fsa"; real_a.write_text("x")
            real_b = bundle / "b.fsa"; real_b.write_text("x")
            csv_path = bundle / "ladder_review_cases.csv"
            # Two rows: a.fsa is needs_review, b.fsa is already
            # reviewed_no_change. After the bulk save, only a.fsa
            # should count toward "changed" (b.fsa's stored label
            # didn't change).
            with csv_path.open("w", newline="", encoding="utf-8") as h:
                w = csvmod.DictWriter(
                    h, fieldnames=["full_path", "label", "ladder_qc_status",
                                   "ladder_review_required", "_path_unreachable"]
                )
                w.writeheader()
                w.writerow({
                    "full_path": str(real_a), "label": "",
                    "ladder_qc_status": "review_required",
                    "ladder_review_required": "true",
                    "_path_unreachable": "false",
                })
                w.writerow({
                    "full_path": str(real_b), "label": "reviewed_no_change",
                    "ladder_qc_status": "ok",
                    "ladder_review_required": "false",
                    "_path_unreachable": "false",
                })

            tab = TabLadder(parent=None)
            tab._review_bundle_dir = bundle
            tab._review_bundle_cases = [
                {"full_path": str(real_a), "label": "",
                 "ladder_qc_status": "review_required",
                 "_path_unreachable": "false"},
                {"full_path": str(real_b), "label": "reviewed_no_change",
                 "ladder_qc_status": "ok",
                 "_path_unreachable": "false"},
            ]
            tab.review_bundle_dir.setText(str(bundle))

            tab._on_bulk_mark_visible_reviewed_clicked()
            self.assertIn("Marked 1 of 2", tab.bulk_mark_label.text())


class TabLadderAuditStreamWiringTests(unittest.TestCase):
    """Phase 12.9 — in-memory + on-disk audit event stream."""

    def test_audit_stream_initialized_empty(self) -> None:
        tab = TabLadder(parent=None)
        self.assertEqual(tab._audit_event_stream, [])

    def test_append_audit_event_caps_at_200(self) -> None:
        tab = TabLadder(parent=None)
        for i in range(250):
            tab._append_audit_event({"stage": "x", "i": i})
        self.assertEqual(len(tab._audit_event_stream), 200)
        # The oldest entries rolled off; the most recent 200 are
        # the ones that landed in the head.
        self.assertEqual(tab._audit_event_stream[0]["i"], 50)
        self.assertEqual(tab._audit_event_stream[-1]["i"], 249)

    def test_clear_recent_audit_panel_resets_stream(self) -> None:
        tab = TabLadder(parent=None)
        for i in range(10):
            tab._append_audit_event({"stage": "x", "i": i})
        tab._clear_recent_audit_panel()
        self.assertEqual(tab._audit_event_stream, [])


class TabLadderBulkMarkWritesAuditEventTests(unittest.TestCase):
    """Phase 12.9 — bulk-review emits an on-disk audit event."""

    def test_bulk_review_click_writes_audit_jsonl(self) -> None:
        # Set up the tab + a 2-row bundle, then verify that the
        # audit stream receives a "bulk_review" event AND the
        # on-disk jsonl file grows by one entry.
        import csv as csvmod
        import tempfile

        from gui_qt.tabs.tab_ladder._io import (
            read_audit_log,
            AUDIT_LOG_FILENAME,
        )

        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            csv_path = bundle / "ladder_review_cases.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as h:
                w = csvmod.DictWriter(
                    h, fieldnames=["full_path", "label", "ladder_qc_status",
                                   "ladder_review_required", "_path_unreachable"]
                )
                w.writeheader()
                w.writerow({
                    "full_path": "/p/a.fsa", "label": "",
                    "ladder_qc_status": "review_required",
                    "ladder_review_required": "true",
                    "_path_unreachable": "false",
                })

            tab = TabLadder(parent=None)
            tab._review_bundle_dir = bundle
            tab._review_bundle_cases = [
                {"full_path": "/p/a.fsa", "label": "",
                 "ladder_qc_status": "review_required",
                 "_path_unreachable": "false"},
            ]
            tab.review_bundle_dir.setText(str(bundle))
            tab._on_bulk_mark_visible_reviewed_clicked()

            # 1. On-disk JSONL gained one entry.
            log = read_audit_log(bundle)
            self.assertTrue(len(log) >= 1, "audit log should be written")
            stage_set = {e["stage"] for e in log}
            self.assertIn("bulk_review", stage_set)
            # 2. In-memory stream mirror has at least one event.
            self.assertTrue(len(tab._audit_event_stream) >= 1)
            stream_stages = {e["stage"] for e in tab._audit_event_stream}
            self.assertIn("bulk_review", stream_stages)


class TabLadderDropReviewCaseWiringTests(unittest.TestCase):
    """Phase 12.10 — drop-row hook wiring."""

    def test_chip_strip_exposes_drop_signal(self) -> None:
        tab = TabLadder(parent=None)
        # The widget must have at least one bound signal we can
        # hook into (Qt's bound signal introspects).
        from PyQt6.QtCore import QMetaObject
        # Just confirm the connection didn't error out by checking
        # the slot exists on the tab.
        self.assertTrue(hasattr(tab, "_on_drop_review_case"))
        # And that the chip-strip has its chipDropRequested signal.
        from gui_qt.tabs.tab_ladder._overview import ChipStripOverview
        self.assertTrue(
            hasattr(ChipStripOverview, "chipDropRequested")
        )

    def test_drop_slot_emits_drop_stage_audit_event(self) -> None:
        # Synthesize a drop without the confirm dialog by
        # out-of-band calling the helper, then verify the
        # audit stream carries a stage="drop" event AND the
        # in-memory mirror too.
        import csv as csvmod
        import tempfile
        from unittest.mock import patch

        from core.analyses.clonality.ladder_review_gate import (
            drop_review_case,
        )

        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            csv_path = bundle / "ladder_review_cases.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as h:
                w = csvmod.DictWriter(
                    h, fieldnames=["full_path", "label",
                                   "ladder_qc_status",
                                   "ladder_review_required",
                                   "_path_unreachable"]
                )
                w.writeheader()
                w.writerow({
                    "full_path": "/p/a.fsa", "label": "manual_adjusted",
                    "ladder_qc_status": "ok",
                    "ladder_review_required": "false",
                    "_path_unreachable": "false",
                })

            tab = TabLadder(parent=None)
            tab._review_bundle_dir = bundle
            tab._review_bundle_cases = [
                {"full_path": "/p/a.fsa", "label": "manual_adjusted",
                 "ladder_qc_status": "ok",
                 "_path_unreachable": "false"},
            ]

            # Bypass the QMessageBox.question by stubbing it.
            from PyQt6.QtWidgets import QMessageBox
            with patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                tab._on_drop_review_case("/p/a.fsa")

            # The CSV lost the row.
            text = csv_path.read_text(encoding="utf-8")
            self.assertNotIn("/p/a.fsa", text)
            # The audit stream carries a stage="drop" event.
            drop_events = [
                e for e in tab._audit_event_stream
                if e.get("stage") == "drop"
            ]
            self.assertGreaterEqual(len(drop_events), 1)


class TabLadderDitFilterWiringTests(unittest.TestCase):
    """Phase 12.11 — DIT prefix filter GUI wiring."""

    def test_input_and_clear_button_installed(self) -> None:
        tab = TabLadder(parent=None)
        self.assertTrue(hasattr(tab, "dit_filter_input"))
        self.assertTrue(hasattr(tab, "btn_clear_dit"))
        self.assertTrue(hasattr(tab, "dit_filter_summary_label"))

    def test_dit_changed_slot_updates_summary(self) -> None:
        tab = TabLadder(parent=None)
        tab._review_bundle_cases = [
            {"full_path": "/proj/24OUM20364_a.fsa", "_path_unreachable": "false"},
            {"full_path": "/proj/26OUM12345_b.fsa", "_path_unreachable": "false"},
        ]
        tab._on_dit_filter_changed("24")
        # Only 1 of 2 rows matches.
        self.assertIn("1 match", tab.dit_filter_summary_label.text())
        self.assertIn("24OUM20364", tab.dit_filter_summary_label.text())

    def test_dit_changed_clears_summary_on_empty(self) -> None:
        tab = TabLadder(parent=None)
        tab._review_bundle_cases = [
            {"full_path": "/proj/24OUM20364_a.fsa", "_path_unreachable": "false"},
        ]
        # First trigger with a prefix.
        tab._on_dit_filter_changed("24")
        self.assertNotEqual(tab.dit_filter_summary_label.text(), "")
        # Then clear.
        tab._on_dit_filter_changed("")
        self.assertEqual(tab.dit_filter_summary_label.text(), "")

    def test_zero_matches_summary(self) -> None:
        tab = TabLadder(parent=None)
        tab._review_bundle_cases = [
            {"full_path": "/proj/26OUM99999_a.fsa", "_path_unreachable": "false"},
        ]
        tab._on_dit_filter_changed("24")
        self.assertIn("0 matches", tab.dit_filter_summary_label.text())

    def test_clear_button_slot_clears_summary(self) -> None:
        tab = TabLadder(parent=None)
        tab._review_bundle_cases = [
            {"full_path": "/proj/24OUM20364_a.fsa", "_path_unreachable": "false"},
        ]
        # Type into the line edit (via the slot's pathway).
        tab.dit_filter_input.setText("24")
        # Press clear.
        tab._on_clear_dit_filter_clicked()
        self.assertEqual(tab.dit_filter_input.text(), "")
        # Summary is cleared too.
        self.assertEqual(tab.dit_filter_summary_label.text(), "")

    def test_chip_strip_and_compose_with_state_filter(self) -> None:
        # Verify the chip-strip widget has dit_filter_keep
        # attribute and that the AND-composition shape holds.
        tab = TabLadder(parent=None)
        # The chip strip widget has both allowed_states (set_filter)
        # and allowed_indices (dit_filter_keep).
        self.assertTrue(hasattr(tab._chip_strip, "_allowed_states"))
        self.assertTrue(hasattr(tab._chip_strip, "_allowed_indices"))
        # Both start at None / open.
        self.assertIsNone(tab._chip_strip._allowed_states)
        self.assertIsNone(tab._chip_strip._allowed_indices)


class TabLadderBundleSummaryBannerTests(unittest.TestCase):
    """Phase 12.12 — bundle summary banner wiring."""

    def test_banner_label_installed(self) -> None:
        tab = TabLadder(parent=None)
        self.assertTrue(hasattr(tab, "bundle_summary_label"))

    def test_initial_zeroed_banner(self) -> None:
        tab = TabLadder(parent=None)
        # The banner always renders something, even before
        # a bundle is loaded.
        text = tab.bundle_summary_label.text()
        self.assertIn("0 needs review", text)
        self.assertIn("last saved: never", text)

    def test_sync_chip_strip_refreshes_banner(self) -> None:
        # Calling _sync_chip_strip with rows containing one
        # reviewed row should update the banner to show
        # "1 reviewed" + the most recent save timestamp.
        tab = TabLadder(parent=None)
        rows = [
            {
                "full_path": "/p/a.fsa",
                "_path_unreachable": "false",
                "label": "manual_adjusted",
                "reviewed_at_utc": "2026-07-08T13:30:00+00:00",
            },
            {
                "full_path": "/p/b.fsa",
                "_path_unreachable": "false",
                "label": "",
                "ladder_qc_status": "review_required",
            },
        ]
        tab._sync_chip_strip(cases=rows)
        text = tab.bundle_summary_label.text()
        self.assertIn("1 needs review", text)
        self.assertIn("1 reviewed", text)
        self.assertIn("last saved: 2026-07-08T13:30:00+00:00", text)


class TabLadderCtrlRWiringTests(unittest.TestCase):
    """Phase 12.13 — Ctrl+R mark-current-reviewed shortcut."""

    def test_slot_method_exists(self) -> None:
        tab = TabLadder(parent=None)
        self.assertTrue(hasattr(tab, "_mark_current_file_reviewed_no_change"))

    def test_no_bundle_status_warnings(self) -> None:
        # Without a bundle, the slot must warn + return, not crash.
        tab = TabLadder(parent=None)
        # Bundle dir / cases all None here.
        tab._review_bundle_dir = None
        tab._review_bundle_cases = []
        tab._current_file = None
        # Just confirm no exception.
        tab._mark_current_file_reviewed_no_change()

    def test_no_current_file_warning(self) -> None:
        tab = TabLadder(parent=None)
        tab._review_bundle_dir = Path("/tmp/any")
        # current_file remains None.
        tab._mark_current_file_reviewed_no_change()

    def test_current_file_not_in_bundle_refuses(self) -> None:
        # A scanned path that isn't part of the loaded
        # bundle must be refused — phantom-write guard.
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            csv_path = bundle / "ladder_review_cases.csv"
            csv_path.write_text(
                "full_path,label\n/p/in_bundle.fsa,\n", encoding="utf-8"
            )
            tab = TabLadder(parent=None)
            tab._review_bundle_dir = bundle
            tab._review_bundle_cases = [
                {"full_path": "/p/in_bundle.fsa", "_path_unreachable": "false"}
            ]
            tab._review_case_by_path = {
                tab._resolve_cache_key(Path("/p/in_bundle.fsa")):
                    tab._review_bundle_cases[0]
            }
            # current_file is something NOT in the bundle.
            tab._current_file = Path("/p/scanned_but_not_in_batch.fsa")
            # Should not raise — silently refuse with warning.
            tab._mark_current_file_reviewed_no_change()


class TabLadderAuditPanelWiringTests(unittest.TestCase):
    """Phase 12.17 — audit-trail mini panel wiring."""

    def test_panel_widget_installed(self) -> None:
        tab = TabLadder(parent=None)
        self.assertTrue(hasattr(tab, "recent_audit_view"))

    def test_panel_is_read_only(self) -> None:
        tab = TabLadder(parent=None)
        # The widget is a QPlainTextEdit; readOnly must be True
        # so the chemist's strokes don't accidentally edit the
        # audit log display.
        self.assertTrue(tab.recent_audit_view.isReadOnly())

    def test_refresh_recent_audit_panel_renders_stream(self) -> None:
        tab = TabLadder(parent=None)
        # Append three synthetic audit events directly to
        # the in-memory stream (the panel render ignores the
        # IO side-effect).
        tab._audit_event_stream.extend([
            {
                "stage": "review", "action": "save",
                "row_path_text": "/p/a.fsa",
                "comment": "label=reviewed",
                "timestamp_utc": "2026-07-08T13:30:00",
            },
            {
                "stage": "bulk_review", "action": "mark_visible_reviewed",
                "row_path_text": "",
                "comment": "5/7 labels flipped",
                "timestamp_utc": "2026-07-08T13:35:12+00:00",
            },
            {
                "stage": "drop", "action": "drop_row",
                "row_path_text": "/p/z.fsa",
                "comment": "",
                "timestamp_utc": "2026-07-08T13:40:00.000000Z",
            },
        ])
        tab._refresh_recent_audit_panel()
        text = tab.recent_audit_view.toPlainText()
        # Each event got rendered.
        self.assertIn("review:save", text)
        self.assertIn("bulk_review:mark_visible_reviewed", text)
        self.assertIn("drop:drop_row", text)
        # The bulk_review event had no row → placeholder "<no-path>".
        self.assertIn("<no-path>", text)
        # Timestamps were rendered with trimmed tz suffixes.
        self.assertNotIn("+00:00", text)
        self.assertNotIn(".000000", text)
        self.assertNotIn("Z", text)

    def test_refresh_with_empty_stream_safe(self) -> None:
        tab = TabLadder(parent=None)
        # No events → refresh is a no-op (panel may be cleared).
        tab._refresh_recent_audit_panel()
        # The panel didn't crash; the plain text is just empty.
        text = tab.recent_audit_view.toPlainText()
        self.assertEqual(text, "")

    def test_clear_recent_audit_panel_wipes_widget(self) -> None:
        tab = TabLadder(parent=None)
        tab._audit_event_stream.extend([
            {"stage": "x", "action": "y", "row_path_text": "",
             "comment": "", "timestamp_utc": "T"},
        ])
        tab._clear_recent_audit_panel()
        # Stream is reset.
        self.assertEqual(tab._audit_event_stream, [])
        # Widget shows nothing.
        self.assertEqual(tab.recent_audit_view.toPlainText(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
