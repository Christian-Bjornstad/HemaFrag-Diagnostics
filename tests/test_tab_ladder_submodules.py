"""Unit tests for `gui_qt.tabs.tab_ladder._summary` + `_io` + `_workers`.

Phase 12.1 — these helpers were extracted from the previously-monolithic
TabLadder class. Each test exercises one helper without spinning up
a QApplication or constructing a TabLadder widget.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from gui_qt.tabs.tab_ladder._io import (
    AUDIT_LOG_FILENAME,
    append_audit_event,
    bulk_save_review_bundle_annotations,
    load_review_bundle_worker,
    make_audit_event,
    read_audit_log,
    review_case_paths_from_bundle,
    save_review_bundle_annotation_worker,
)
from gui_qt.tabs.tab_ladder._summary import (
    CHIP_STATE_LABELS,
    NEVER_SAVED_LABEL,
    REVIEWED_NO_CHANGE_LABEL,
    RELEVANT_CHIP_STATES,
    apply_filter_rows,
    bulk_mark_reviewed_no_change,
    chip_state,
    count_chip_states,
    count_states,
    dit_filter_keep,
    entry_cache_key,
    entry_original_path,
    extract_dit_candidates,
    format_file_item,
    format_summary_banner,
    is_chip_state_allowed,
    metadata_from_entry,
    most_recent_save_timestamp,
    next_chip_index,
    resolve_cache_key,
)
from gui_qt.tabs.tab_ladder._workers import (
    find_report_matches_worker,
    scan_fsa_files_worker,
)


# Same POSIX-on-Windows helper as test_ladder_review_gate.py:
# PurePosixPath routes literal '/tmp/...' strings through str() unchanged on this OS.
def _posix_text(fake_path: str) -> str:
    if sys.platform == "win32":
        return str(PurePosixPath(fake_path))
    return fake_path


class TabLadderSummaryHelperTests(unittest.TestCase):
    """Pure helpers in `_summary.py`."""

    def test_resolve_cache_key_passes_through(self) -> None:
        # Use a relative path so Windows doesn't prefix with a drive.
        p = Path("tmp_xenon_test_42/foo.fsa")
        result = resolve_cache_key(p)
        # str-based comparison that ignores the leading "C:/..." Windows
        # prefix issue: both are resolved via the same mechanism.
        self.assertIsInstance(result, Path)

    def test_resolve_cache_key_handles_unresolvable(self) -> None:
        # A non-existent file should still resolve via expanduser().
        p = Path("nope_xyz/foo.fsa")
        # Should not raise.
        resolve_cache_key(p)

    def test_entry_original_path_prefers_original_file_path(self) -> None:
        entry = {
            "original_file_path": _posix_text("/first.fsa"),
            "full_path": _posix_text("/second.fsa"),
        }
        self.assertEqual(
            str(entry_original_path(entry)).replace("\\", "/"), "/first.fsa"
        )

    def test_entry_original_path_falls_back_to_fsa(self) -> None:
        fsa = SimpleNamespace(file=_posix_text("/fsa_path.fsa"))
        self.assertEqual(
            str(entry_original_path({"fsa": fsa})).replace("\\", "/"),
            "/fsa_path.fsa",
        )

    def test_entry_original_path_returns_none(self) -> None:
        # No original_file_path, no full_path, no fsa → None.
        self.assertIsNone(entry_original_path({}))

    def test_entry_cache_key_chain(self) -> None:
        entry = {"original_file_path": _posix_text("/a.fsa")}
        self.assertIsNotNone(entry_cache_key(entry))

    def test_entry_cache_key_returns_none_for_missing_entry(self) -> None:
        self.assertIsNone(entry_cache_key({}))

    def test_format_file_item_bare_when_no_case(self) -> None:
        fp = Path(_posix_text("/tmp/abc.fsa"))
        self.assertEqual(format_file_item(fp, None), fp.name)

    def test_format_file_item_rich_when_case_provided(self) -> None:
        fp = Path(_posix_text("/tmp/abc.fsa"))
        case = {
            "assay": "FR1",
            "ladder": "ROX400HD",
            "linear_max": 2.5,
            "linear_r2": 0.9987,
            "ladder_qc": "ok",
        }
        rendered = format_file_item(fp, case)
        self.assertIn("abc.fsa", rendered)
        self.assertIn("FR1", rendered)
        self.assertIn("ROX400HD", rendered)
        self.assertIn("max 2.50", rendered)
        self.assertIn("ok", rendered)

    def test_metadata_from_entry_builds_complete_payload(self) -> None:
        from config import APP_SETTINGS

        previous_analysis = APP_SETTINGS.get("active_analysis")
        APP_SETTINGS["active_analysis"] = "clonality"
        try:
            entry = {
                "assay": "FR1",
                "ladder": "ROX400HD",
                "trace_channels": ["DATA1", "DATA2"],
                "bp_min": 80.0,
                "bp_max": 400.0,
            }
            meta = metadata_from_entry(Path(_posix_text("/p.fsa")), entry)
            self.assertEqual(meta["assay"], "FR1")
            self.assertEqual(meta["ladder"], "ROX400HD")
            self.assertEqual(meta["primary_peak_channel"], "DATA1")
            self.assertEqual(meta["sample_channel"], "DATA1")
            self.assertEqual(meta["trace_channels"], ["DATA1", "DATA2"])
            self.assertEqual(meta["bp_min"], 80.0)
            self.assertEqual(meta["bp_max"], 400.0)
        finally:
            APP_SETTINGS["active_analysis"] = previous_analysis


class TabLadderIOHelperTests(unittest.TestCase):
    """Pure helpers in `_io.py` — bundle CSV load/save plumbing."""

    def _write_csv(self, td, rows):
        cases_path = Path(td) / "ladder_review_cases.csv"
        fieldnames = ["full_path", "file", "label"]
        with cases_path.open("w", encoding="utf-8", newline="") as handle:
            writer = __import__("csv").DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return cases_path

    def test_load_review_bundle_worker_keeps_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(
                td,
                [
                    {"full_path": _posix_text("/missing/path.fsa"), "file": "ghost.fsa", "label": ""},
                    {"full_path": _posix_text(str(Path(td) / "real.fsa")), "file": "real.fsa", "label": ""},
                ],
            )
            # Create the real file so exactly one is reachable.
            real = Path(td) / "real.fsa"
            real.write_bytes(b"x")
            result = load_review_bundle_worker(Path(td))
            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual(len(result["missing_paths"]), 1)

    def test_load_review_bundle_worker_raises_when_csv_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                load_review_bundle_worker(Path(td))

    def test_review_case_paths_from_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(
                td,
                [
                    {"full_path": _posix_text(str(Path(td) / "x.fsa")), "file": "x.fsa", "label": ""},
                ],
            )
            paths = review_case_paths_from_bundle(Path(td))
            self.assertEqual(len(paths), 1)
            self.assertIsInstance(next(iter(paths)), Path)

    def test_review_case_paths_from_bundle_empty_when_no_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(review_case_paths_from_bundle(Path(td)), set())

    def test_save_review_bundle_annotation_worker_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fsa = Path(td) / "x.fsa"
            fsa.write_bytes(b"x")
            self._write_csv(
                td,
                [
                    {"full_path": str(fsa), "file": "x.fsa", "label": ""},
                ],
            )
            annotation = {
                "label": "manual_adjusted",
                "label_note": "fixed in dialog",
                "reviewed_at_utc": "2026-07-08T10:00:00Z",
                "adjustment_path": str(fsa.with_suffix(".ladder_adj.json")),
                "action": "apply",
            }
            returned = save_review_bundle_annotation_worker(
                Path(td), fsa, annotation
            )
            self.assertEqual(returned["label"], "manual_adjusted")

            cases_path = Path(td) / "ladder_review_cases.csv"
            with cases_path.open("r", encoding="utf-8", newline="") as handle:
                reader = __import__("csv").DictReader(handle)
                rows = list(reader)
            self.assertEqual(rows[0]["label"], "manual_adjusted")
            self.assertEqual(rows[0]["label_note"], "fixed in dialog")

            annotations_path = Path(td) / "ladder_review_annotations.json"
            self.assertTrue(annotations_path.exists())

    def test_save_review_bundle_annotation_worker_raises_on_unknown_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fsa = Path(td) / "x.fsa"
            fsa.write_bytes(b"x")
            self._write_csv(
                td,
                [{"full_path": str(fsa), "file": "x.fsa", "label": ""}],
            )
            with self.assertRaises(FileNotFoundError):
                save_review_bundle_annotation_worker(
                    Path(td),
                    Path(_posix_text("/never/seen.fsa")),
                    {"label": "reviewed_no_change"},
                )


class TabLadderWorkersHelperTests(unittest.TestCase):
    """Pure helpers in `_workers.py` — file scan + report match."""

    def test_scan_fsa_files_worker_returns_sorted_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Create a couple of FSA files in arbitrary order.
            (Path(td) / "b.fsa").write_bytes(b"x")
            (Path(td) / "a.fsa").write_bytes(b"x")
            (Path(td) / "c.fsa").write_bytes(b"x")

            result = scan_fsa_files_worker(Path(td))
            names = [p.name for p in result]
            self.assertEqual(names, ["a.fsa", "b.fsa", "c.fsa"])

    def test_find_report_matches_worker_matches_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "reports"
            sub.mkdir()
            # Stem of "/p/abcd.html.fsa" is "abcd.html" — present verbatim in
            # QC_REPORT_abcd.html/REPORT_abcd.html/etc.
            (sub / "QC_REPORT_seed1.html").write_text("<html>x</html>")
            (sub / "REPORT_seed1.html").write_text("<html>y</html>")
            (sub / "unrelated.html").write_text("<html>q</html>")

            fp = Path("seed1.fsa")
            result = find_report_matches_worker(fp, str(sub))
            names = [m.name for m in result["matches"]]
            self.assertIn("QC_REPORT_seed1.html", names)
            self.assertIn("REPORT_seed1.html", names)
            self.assertNotIn("unrelated.html", names)

    def test_find_report_matches_worker_missing_root_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            find_report_matches_worker(
                Path("p.fsa"), "no_such_dir_for_test_xyz"
            )


class ChipStateHelperTests(unittest.TestCase):
    """Phase 12.3 — chip_state precedence contract.

    The chip strip's four-state precedence:
       file_unreachable > reviewed > needs_review > untouched
    """

    def test_unreachable_wins_over_reviewed(self) -> None:
        # Even a "reviewed" labeled row counts as file_unreachable
        # because the chemist cannot actually access it.
        with tempfile.TemporaryDirectory() as td:
            ghost = "/no/such/path_xyz.fsa"
            row = {
                "full_path": ghost,
                "_path_unreachable": "true",
                "label": "manual_adjusted",
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row), "file_unreachable")

    def test_reviewed_label(self) -> None:
        for label in ("manual_adjusted", "reviewed_no_change"):
            row = {
                "full_path": str(Path("real.fsa")),
                "_path_unreachable": "false",
                "label": label,
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row), "reviewed")

    def test_needs_review_when_label_empty_and_flag_set(self) -> None:
        row = {
            "full_path": str(Path("real.fsa")),
            "_path_unreachable": "false",
            "label": "",
            "ladder_qc_status": "review_required",
            "ladder_review_required": "true",
            "primary_reason": "poor_linear_liz_fit",
        }
        self.assertEqual(chip_state(row), "needs_review")

    def test_needs_review_with_missing_ladder(self) -> None:
        row = {
            "full_path": str(Path("real.fsa")),
            "_path_unreachable": "false",
            "label": "",
            "ladder_qc_status": "missing_ladder",
        }
        self.assertEqual(chip_state(row), "needs_review")

    def test_untouched_when_nothing_set(self) -> None:
        row = {
            "full_path": str(Path("real.fsa")),
            "_path_unreachable": "false",
            "label": "",
            "ladder_qc_status": "ok",
        }
        self.assertEqual(chip_state(row), "untouched")

    def test_check_filesystem_true_returns_unreachable_when_path_missing(self) -> None:
        # Use a tag of "false" but force a filesystem check that has
        # to discover the path is missing anyway.
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.fsa"
            real.write_bytes(b"x")
            row = {
                "full_path": "/ghost/of/path_x.fsa",
                "_path_unreachable": "false",
                "label": "",
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row, check_filesystem=True), "file_unreachable")
            # And the same row with real_path + check_filesystem
            # returns untouched.
            row2 = {
                "full_path": str(real),
                "_path_unreachable": "false",
                "label": "",
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row2, check_filesystem=True), "untouched")

    def test_count_chip_states_tallies_each_bucket(self) -> None:
        rows = [
            {"full_path": "r1", "_path_unreachable": "false", "label": "manual_adjusted"},
            {"full_path": "r2", "_path_unreachable": "true"},
            {"full_path": "r3", "_path_unreachable": "false", "label": "", "ladder_qc_status": "review_required"},
            {"full_path": "r4", "_path_unreachable": "false", "label": ""},
            {"full_path": "r5", "_path_unreachable": "false", "label": ""},
        ]
        counts = count_chip_states(rows)
        self.assertEqual(counts["reviewed"], 1)
        self.assertEqual(counts["file_unreachable"], 1)
        self.assertEqual(counts["needs_review"], 1)
        self.assertEqual(counts["untouched"], 2)

    def test_count_chip_states_handles_empty(self) -> None:
        counts = count_chip_states([])
        for key in ("reviewed", "needs_review", "file_unreachable", "untouched"):
            self.assertEqual(counts[key], 0)


class NextChipIndexHelperTests(unittest.TestCase):
    """Phase 12.6 — keyboard navigation helper for Alt+J / Alt+K / Ctrl+. .

    The contract:

    - direction=+1 → next (Alt+K); direction=-1 → prev (Alt+J).
    - Without only_relevant, every adjacent chip is fair game; the
      index wraps mod n (single full-cycle scan).
    - With only_relevant=True, chips whose state is in
      RELEVANT_CHIP_STATES win; reviewed and untouched are skipped.
    - Returns -1 when rows is empty, or when wrap=False and no
      qualifying chip is found in a single cycle.
    """

    GOOD_PATH = "real.fsa"  # i.e. wherever the test runs; just a stable path.

    @staticmethod
    def _make_rows(spec: list[str]) -> list[dict]:
        """Build rows tagged with chip states from a list of one-letter codes.

        Codes used by tests:
          R = reviewed (label=manual_adjusted)
          U = untouched (label=, ladder_qc_status=ok)
          N = needs_review (ladder_qc_status=review_required)
          X = file_unreachable (_path_unreachable="true")
        """
        code_to_row = {
            "R": {"full_path": "r.fsa", "_path_unreachable": "false",
                  "label": "manual_adjusted", "ladder_qc_status": "ok"},
            "U": {"full_path": "u.fsa", "_path_unreachable": "false",
                  "label": "", "ladder_qc_status": "ok"},
            "N": {"full_path": "n.fsa", "_path_unreachable": "false",
                  "label": "", "ladder_qc_status": "review_required"},
            "X": {"full_path": "x.fsa", "_path_unreachable": "true",
                  "label": "", "ladder_qc_status": "ok"},
        }
        return [code_to_row[c] for c in spec]

    def test_returns_minus_one_for_empty_rows(self) -> None:
        self.assertEqual(next_chip_index([], current_index=0, direction=1), -1)
        self.assertEqual(
            next_chip_index([], current_index=0, direction=1, only_relevant=True), -1
        )

    def test_next_returns_adjacent_independent_of_state(self) -> None:
        rows = self._make_rows(["R", "U", "N", "X"])  # 4 chips, all states
        # Plain "next" (Alt+K) doesn't filter, so any chip works.
        self.assertEqual(next_chip_index(rows, 0, direction=1), 1)
        self.assertEqual(next_chip_index(rows, 2, direction=1), 3)
        # Wrap: 3 → 0
        self.assertEqual(next_chip_index(rows, 3, direction=1), 0)
        # Without state filter, the loop returns the very next index
        # — no scroll through to a "relevant" chip.
        self.assertEqual(
            next_chip_index(rows, 0, direction=1, only_relevant=True, wrap=False),
            2,  # N at index 2 is the first relevant after 0
        )

    def test_prev_returns_adjacent_independent_of_state(self) -> None:
        rows = self._make_rows(["R", "U", "N", "X"])
        self.assertEqual(next_chip_index(rows, 2, direction=-1), 1)
        self.assertEqual(next_chip_index(rows, 0, direction=-1), 3)  # wrap back to last
        self.assertEqual(next_chip_index(rows, 1, direction=-1), 0)

    def test_only_relevant_skips_reviewed_and_untouched(self) -> None:
        # Mix with a reviewed + untouched sandwich; next relevant is
        # the first needs_review or file_unreachable after start.
        rows = self._make_rows(["R", "U", "N"])
        self.assertEqual(
            next_chip_index(rows, 0, direction=1, only_relevant=True), 2
        )
        # Starting past the first relevant — wraps and lands on the
        # only one available.
        self.assertEqual(
            next_chip_index(rows, 2, direction=1, only_relevant=True), 2
        )
        # Starting from the last relevant itself — single-cycle wrap
        # returns the same index because nothing new appears.
        self.assertEqual(
            next_chip_index(rows, 2, direction=-1, only_relevant=True), 2
        )

    def test_only_relevant_targets_file_unreachable(self) -> None:
        rows = self._make_rows(["R", "X", "U", "N"])
        self.assertEqual(
            next_chip_index(rows, 0, direction=1, only_relevant=True), 1
        )
        # From X, next relevant forward is N (index 3).
        self.assertEqual(
            next_chip_index(rows, 1, direction=1, only_relevant=True), 3
        )
        # From N, next relevant backward is X (index 1).
        self.assertEqual(
            next_chip_index(rows, 3, direction=-1, only_relevant=True), 1
        )

    def test_only_relevant_wrap_false_returns_minus_one(self) -> None:
        rows = self._make_rows(["R", "U"])
        # No relevant anchor at all — wrap=False yields -1.
        self.assertEqual(
            next_chip_index(rows, 0, direction=1, only_relevant=True, wrap=False),
            -1,
        )

    def test_only_relevant_wrap_true_falls_back_to_current(self) -> None:
        rows = self._make_rows(["R", "U"])
        # wrap=True (default) keeps the chemist's focus put rather
        # than signaling "no chip".
        self.assertEqual(
            next_chip_index(rows, 0, direction=1, only_relevant=True, wrap=True),
            0,
        )

    def test_clamps_out_of_range_current_index(self) -> None:
        # Stale current_index from before rows shrunk — must not crash.
        rows = self._make_rows(["R", "N", "U"])
        # 99 % n == 0 (Python modulo), so current_index clamps to 0;
        # next direction=+1 returns 1 (N) regardless of only_relevant
        # because the default doesn't filter by state.
        self.assertEqual(next_chip_index(rows, 99, direction=1), 1)
        # -3 % n == 0 on n=3 → cur=0; with only_relevant=True, the
        # next relevant forward is index 1 (N).
        self.assertEqual(
            next_chip_index(rows, -3, direction=1, only_relevant=True), 1
        )
        # An out-of-range index that wraps back to a different point
        # also walks correctly. n=3, current_index=4 → 4 % 3 == 1
        # (N), direction=+1 with only_relevant=True → wraps and the
        # only relevant anchor in the rows is index 1 itself.
        self.assertEqual(
            next_chip_index(rows, 4, direction=1, only_relevant=True), 1
        )

    def test_relevant_chip_states_constants(self) -> None:
        # Lock the contract — Phase 12.6 callers import this set
        # indirectly via the helper. If we ever broaden it, callers
        # that draw checklist chips (red + amber only) would shift.
        self.assertEqual(
            RELEVANT_CHIP_STATES, {"needs_review", "file_unreachable"}
        )
        # And chip_state's set of recognized states must be a superset
        # so a fresh row never returns a state that's also in the
        # relevant set without the helper agreeing on the bucket.
        self.assertTrue(RELEVANT_CHIP_STATES.issubset(CHIP_STATE_LABELS))


class ChipFilterHelperTests(unittest.TestCase):
    """Phase 12.7 — chip-state filter helpers.

    These pure helpers back the ChipFilterBar widget (which lives in
    `_overview.py`). Each test pins one branch of:
      - ``apply_filter_rows(rows, allowed_states)`` returns the
        subset of rows whose chip state is in the allowed set.
      - ``count_states(rows)`` is an alias for ``count_chip_states``
        — same dict shape, same values.
      - ``is_chip_state_allowed(state, allowed_states)`` decodes a
        single state name against the same allowed-set contract.
    """

    @staticmethod
    def _row(state: str, fp: str = "r.fsa") -> dict:
        """Construct a row tagged with a chip state."""
        if state == "reviewed":
            return {"full_path": fp, "_path_unreachable": "false",
                    "label": "manual_adjusted", "ladder_qc_status": "ok"}
        if state == "needs_review":
            return {"full_path": fp, "_path_unreachable": "false",
                    "label": "", "ladder_qc_status": "review_required"}
        if state == "file_unreachable":
            return {"full_path": fp, "_path_unreachable": "true",
                    "label": "", "ladder_qc_status": "ok"}
        if state == "untouched":
            return {"full_path": fp, "_path_unreachable": "false",
                    "label": "", "ladder_qc_status": "ok"}
        raise ValueError(f"unknown state {state}")

    def test_apply_filter_rows_none_returns_all(self) -> None:
        rows = [self._row("reviewed"), self._row("untouched")]
        out = apply_filter_rows(rows, None)
        self.assertEqual(len(out), 2)
        # Shallow-copied — mutating output must not mutate input.
        out[0]["_mut"] = True
        self.assertNotIn("_mut", rows[0])

    def test_apply_filter_rows_subset_keeps_targets_only(self) -> None:
        rows = [
            self._row("reviewed", "r.fsa"),
            self._row("needs_review", "n.fsa"),
            self._row("file_unreachable", "x.fsa"),
            self._row("untouched", "u.fsa"),
        ]
        out = apply_filter_rows(rows, {"needs_review", "file_unreachable"})
        # We can't preserve order of the original list, so
        # compare by full_path instead.
        self.assertEqual({r["full_path"] for r in out}, {"n.fsa", "x.fsa"})

    def test_apply_filter_rows_empty_set_matches_nothing(self) -> None:
        rows = [self._row("reviewed"), self._row("untouched")]
        self.assertEqual(apply_filter_rows(rows, set()), [])

    def test_apply_filter_rows_accepts_list_or_tuple(self) -> None:
        # The GUI sometimes passes a list, not a set — make sure
        # the helper normalizes correctly.
        rows = [self._row("needs_review"), self._row("untouched")]
        out_list = apply_filter_rows(rows, ["needs_review"])
        out_tuple = apply_filter_rows(rows, ("needs_review",))
        self.assertEqual(len(out_list), 1)
        self.assertEqual(len(out_tuple), 1)
        self.assertEqual(out_list[0]["full_path"], out_tuple[0]["full_path"])

    def test_apply_filter_rows_input_none_safe(self) -> None:
        # Defensive contract — bundles mid-load may pass None.
        self.assertEqual(apply_filter_rows(None, None), [])
        self.assertEqual(apply_filter_rows(None, {"reviewed"}), [])

    def test_count_states_alias_to_count_chip_states(self) -> None:
        # Pin the alias so a future name-fat finger doesn't fork
        # the implementation.
        rows = [
            self._row("reviewed"),
            self._row("file_unreachable"),
            self._row("untouched"),
        ]
        self.assertEqual(count_states(rows), count_chip_states(rows))
        # And the dict shape must match CHIP_STATE keys.
        self.assertEqual(set(count_states([]).keys()), set(CHIP_STATE_LABELS))

    def test_is_chip_state_allowed_none_means_open(self) -> None:
        self.assertTrue(is_chip_state_allowed("needs_review", None))
        self.assertTrue(is_chip_state_allowed("untouched", None))

    def test_is_chip_state_allowed_set_membership(self) -> None:
        allowed = {"needs_review", "file_unreachable"}
        self.assertTrue(is_chip_state_allowed("needs_review", allowed))
        self.assertTrue(is_chip_state_allowed("file_unreachable", allowed))
        self.assertFalse(is_chip_state_allowed("reviewed", allowed))
        self.assertFalse(is_chip_state_allowed("untouched", allowed))

    def test_is_chip_state_allowed_empty_set_blocks_all(self) -> None:
        # The "None" button on the filter bar produces an empty set
        # to mean "match nothing" — pin the contract.
        for s in ("reviewed", "needs_review", "file_unreachable", "untouched"):
            self.assertFalse(is_chip_state_allowed(s, set()))

    def test_is_chip_state_allowed_handles_garbage_state(self) -> None:
        # If a chip-state with a typo lands at the helper, the
        # output is False rather than raising — defensive.
        self.assertFalse(is_chip_state_allowed("nonsense", {"reviewed"}))


class BulkMarkReviewedNoChangeTests(unittest.TestCase):
    """Phase 12.8 — `bulk_mark_reviewed_no_change` pure helper.

    Pins the label, label_note, reviewed_at_utc, and adjustment_path
    shape; pins the in-bundle gating so the button can't phantom-write
    a path that isn't in the bundle; pins the deterministic
    ``now_iso`` injection for tests.
    """

    def test_returns_list_per_path_with_correct_shape(self) -> None:
        rows = [
            {"full_path": "/p/a.fsa"},
            {"full_path": "/p/b.fsa"},
        ]
        out = bulk_mark_reviewed_no_change(rows, ["/p/a.fsa"], now_iso="T")
        self.assertEqual(len(out), 1)
        entry = out[0]
        self.assertEqual(entry["full_path"], "/p/a.fsa")
        self.assertEqual(entry["label"], REVIEWED_NO_CHANGE_LABEL)
        self.assertEqual(entry["label_note"], "")
        self.assertEqual(entry["reviewed_at_utc"], "T")
        self.assertEqual(entry["adjustment_path"], "")

    def test_skips_paths_not_in_bundle(self) -> None:
        # The button is "Mark Visible Reviewed"; a path that's
        # only in the GUI file list but not the bundle must be
        # silently skipped — never phantom-write.
        rows = [{"full_path": "/in/b.fsa"}]
        out = bulk_mark_reviewed_no_change(
            rows, ["/in/b.fsa", "/stray/z.fsa"], now_iso="T"
        )
        self.assertEqual([r["full_path"] for r in out], ["/in/b.fsa"])

    def test_empty_paths_returns_empty(self) -> None:
        self.assertEqual(bulk_mark_reviewed_no_change([], []), [])

    def test_accepts_path_objects(self) -> None:
        rows = [{"full_path": "/p/a.fsa"}]
        out = bulk_mark_reviewed_no_change(
            rows,
            [Path("/p/a.fsa")],
            now_iso="T",
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["full_path"], "/p/a.fsa")

    def test_default_now_iso_recent(self) -> None:
        import re
        rows = [{"full_path": "/p/a.fsa"}]
        out = bulk_mark_reviewed_no_change(rows, ["/p/a.fsa"])
        self.assertRegex(out[0]["reviewed_at_utc"], r"\d{4}-\d{2}-\d{2}T")


class BulkSaveReviewBundleAnnotationsTests(unittest.TestCase):
    """Phase 12.8 — `bulk_save_review_bundle_annotations` IO helper.

    Pins:
      - atomic CSV rewrite;
      - returns CHANGED count, not just touched (rows whose label
        was already in the new state don't inflate the count);
      - empty label in input means no change (don't count);
      - missing CSV raises FileNotFoundError so the GUI's worker
        error signal can surface the miss.
    """

    def _write_csv(self, td: str, lines: list[str]) -> Path:
        p = Path(td) / "ladder_review_cases.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def test_bulk_save_writes_updated_rows_to_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = self._write_csv(td, [
                "full_path,label,ladder_qc_status",
                "/p/a.fsa,,review_required",
                "/p/b.fsa,,review_required",
            ])
            new_rows = [
                {
                    "full_path": "/p/a.fsa",
                    "label": "reviewed_no_change",
                    "label_note": "n/a",
                    "reviewed_at_utc": "2026-07-08T10:00:00+00:00",
                    "adjustment_path": "",
                },
                {
                    "full_path": "/p/b.fsa",
                    "label": "reviewed_no_change",
                    "label_note": "",
                    "reviewed_at_utc": "2026-07-08T10:00:00+00:00",
                    "adjustment_path": "",
                },
            ]
            changed = bulk_save_review_bundle_annotations(Path(td), new_rows)
            self.assertEqual(changed, 2)
            text = csv_path.read_text(encoding="utf-8")
            self.assertIn("reviewed_no_change", text)
            # The annotations JSON was also written.
            annotations = json.loads(
                (Path(td) / "ladder_review_annotations.json").read_text()
            )
            self.assertEqual(
                set(annotations.keys()), {"/p/a.fsa", "/p/b.fsa"}
            )

    def test_bulk_save_only_counts_actual_label_changes(self) -> None:
        # PITFALL: a row whose stored label is already the new one
        # must NOT inflate the "changed" count. Two rows: one will
        # flip, one will stay.
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, [
                "full_path,label,ladder_qc_status",
                "/p/a.fsa,,review_required",
                "/p/b.fsa,reviewed_no_change,ok",
            ])
            new_rows = [
                {
                    "full_path": "/p/a.fsa",
                    "label": "reviewed_no_change",
                    "label_note": "",
                    "reviewed_at_utc": "T",
                    "adjustment_path": "",
                },
                {
                    "full_path": "/p/b.fsa",
                    "label": "reviewed_no_change",
                    "label_note": "",
                    "reviewed_at_utc": "T",
                    "adjustment_path": "",
                },
            ]
            changed = bulk_save_review_bundle_annotations(Path(td), new_rows)
            self.assertEqual(changed, 1, "only one row should have changed")

    def test_bulk_save_empty_label_skips_change_count(self) -> None:
        # Empty label means the chemist cleared the field by
        # accident — must not flip the existing label nor
        # count toward the change tally.
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, [
                "full_path,label,ladder_qc_status",
                "/p/a.fsa,manual_adjusted,ok",
            ])
            new_rows = [
                {
                    "full_path": "/p/a.fsa",
                    "label": "",
                    "label_note": "",
                    "reviewed_at_utc": "T",
                    "adjustment_path": "",
                },
            ]
            changed = bulk_save_review_bundle_annotations(Path(td), new_rows)
            self.assertEqual(changed, 0)

    def test_bulk_save_missing_csv_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                bulk_save_review_bundle_annotations(Path(td), [
                    {"full_path": "/x/y.fsa", "label": "reviewed_no_change"}
                ])

    def test_bulk_save_empty_input_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, [
                "full_path,label", "/p/a.fsa,"
            ])
            self.assertEqual(
                bulk_save_review_bundle_annotations(Path(td), []), 0
            )

    def test_bulk_save_unknown_path_silently_skipped(self) -> None:
        # The bulk helper is invoked with potentially many rows;
        # a stray path that doesn't match a bundle row must not
        # crash the run.
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, [
                "full_path,label", "/p/a.fsa,"
            ])
            changed = bulk_save_review_bundle_annotations(Path(td), [
                {"full_path": "/p/a.fsa", "label": "reviewed_no_change",
                 "label_note": "", "reviewed_at_utc": "T",
                 "adjustment_path": ""},
                {"full_path": "/stray/z.fsa", "label": "reviewed_no_change",
                 "label_note": "", "reviewed_at_utc": "T",
                 "adjustment_path": ""},
            ])
            self.assertEqual(changed, 1)


class MakeAuditEventTests(unittest.TestCase):
    """Phase 12.9 — `make_audit_event` pure helper."""

    def test_required_fields_present(self) -> None:
        event = make_audit_event(stage="review")
        self.assertIn("stage", event)
        self.assertIn("timestamp_utc", event)
        self.assertIn("row_path_text", event)
        self.assertIn("action", event)
        self.assertIn("comment", event)
        self.assertEqual(event["stage"], "review")

    def test_row_path_text_extracted_from_dict(self) -> None:
        event = make_audit_event(
            stage="drop", row={"full_path": "/p/a.fsa"}
        )
        self.assertEqual(event["row_path_text"], "/p/a.fsa")

    def test_action_and_comment_passed_through(self) -> None:
        event = make_audit_event(
            stage="bulk_review",
            action="mark_visible_reviewed",
            comment="5/7 labels flipped",
        )
        self.assertEqual(event["action"], "mark_visible_reviewed")
        self.assertEqual(event["comment"], "5/7 labels flipped")

    def test_extra_merged(self) -> None:
        event = make_audit_event(
            stage="locate_file",
            extra={"old_path": "/a", "new_path": "/b"},
        )
        self.assertEqual(event.get("old_path"), "/a")
        self.assertEqual(event.get("new_path"), "/b")

    def test_extra_garbage_does_not_crash(self) -> None:
        # If a caller passes a non-dict for extra, the helper
        # must not crash.
        try:
            make_audit_event(stage="x", extra=None)
        except Exception:
            self.fail("extra=None should not raise")

    def test_no_row_means_empty_path_text(self) -> None:
        event = make_audit_event(stage="bulk_review")
        self.assertEqual(event["row_path_text"], "")


class AppendAuditEventTests(unittest.TestCase):
    """Phase 12.9 — `append_audit_event` + `read_audit_log` IO helpers."""

    def test_append_then_read_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            event = make_audit_event(
                stage="review", row={"full_path": "/p/a.fsa"},
                action="save", comment="label=reviewed_no_change"
            )
            self.assertTrue(append_audit_event(bundle, event))
            log = read_audit_log(bundle)
            self.assertEqual(len(log), 1)
            # Round-tripped stage/action/comment match.
            self.assertEqual(log[0]["stage"], "review")
            self.assertEqual(log[0]["action"], "save")
            self.assertEqual(log[0]["row_path_text"], "/p/a.fsa")
            # And the timestamp is a non-empty string.
            self.assertTrue(log[0]["timestamp_utc"])

    def test_log_filename_constant(self) -> None:
        self.assertEqual(AUDIT_LOG_FILENAME, "ladder_review_audit.jsonl")

    def test_append_with_none_bundle_does_not_crash(self) -> None:
        # bundle_dir=None writes to cwd — we don't actually want
        # the test to pollute cwd, so we just confirm it doesn't
        # raise. It may or may not write to cwd depending on
        # where pytest runs so we don't pin the side-effect.
        event = make_audit_event(stage="review", action="save")
        result = append_audit_event(None, event)
        self.assertIsInstance(result, bool)

    def test_read_missing_log_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(read_audit_log(Path(td)), [])

    def test_appended_lines_are_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            append_audit_event(bundle, make_audit_event(stage="a"))
            append_audit_event(bundle, make_audit_event(stage="b"))
            log_path = bundle / AUDIT_LOG_FILENAME
            text = log_path.read_text(encoding="utf-8")
            lines = [line for line in text.split("\n") if line]
            self.assertEqual(len(lines), 2)
            # Each line is parseable JSON with the right stage.
            import json as _json
            stages = [_json.loads(line)["stage"] for line in lines]
            self.assertEqual(stages, ["a", "b"])


class ExtractDitCandidatesTests(unittest.TestCase):
    """Phase 12.11 — DIT prefix filter pure helper."""

    @staticmethod
    def _row(full_path: str, source_run_dir: str = "") -> dict:
        return {"full_path": full_path, "source_run_dir": source_run_dir}

    def test_extracts_dits_from_full_path(self) -> None:
        rows = [
            self._row("/proj/24OUM20364_a.fsa"),
            self._row("/proj/26OUM12345_b.fsa"),
        ]
        indices, dits = extract_dit_candidates(rows, "24")
        self.assertEqual(indices, [0])
        self.assertEqual(dits, ["24OUM20364"])

    def test_extracts_from_source_run_dir_fallback(self) -> None:
        # When the FSA filename got renamed and the DIT only
        # lives in source_run_dir (a common T7 path quirk):
        rows = [
            self._row("/proj/renamed_a.fsa",
                      source_run_dir="2025_24OUM20364_run_xyz"),
        ]
        indices, dits = extract_dit_candidates(rows, "24OUM203")
        self.assertEqual(indices, [0])
        self.assertEqual(dits, ["24OUM20364"])

    def test_case_insensitive_prefix(self) -> None:
        rows = [self._row("/proj/24OUM20364_a.fsa")]
        # Lowercase input still matches uppercase DIT.
        indices, dits = extract_dit_candidates(rows, "24oum203")
        self.assertEqual(indices, [0])
        self.assertEqual(dits, ["24OUM20364"])

    def test_returns_uppercase_dits(self) -> None:
        # Match shapes are uppercase regardless of input case.
        rows = [self._row("/proj/24oum20364_a.fsa")]
        indices, dits = extract_dit_candidates(rows, "24OUM203")
        self.assertEqual(dits, ["24OUM20364"])

    def test_empty_prefix_returns_empty(self) -> None:
        rows = [self._row("/proj/24OUM20364_a.fsa")]
        self.assertEqual(extract_dit_candidates(rows, ""), ([], []))
        self.assertEqual(extract_dit_candidates(rows, "   "), ([], []))

    def test_empty_rows_returns_empty(self) -> None:
        self.assertEqual(extract_dit_candidates([], "24"), ([], []))

    def test_no_match_returns_empty(self) -> None:
        rows = [self._row("/proj/26OUM12345_b.fsa")]
        self.assertEqual(extract_dit_candidates(rows, "25"), ([], []))

    def test_no_dit_in_row_never_matches(self) -> None:
        rows = [self._row("/proj/random_filename.fsa")]
        self.assertEqual(extract_dit_candidates(rows, "24"), ([], []))

    def test_prefix_matches_only_at_start(self) -> None:
        # `startswith` semantics: the prefix must be at the
        # *start* of the DIT. Typing "OUM203" cannot match
        # "24OUM20364" because the DIT starts with "24".
        rows = [
            self._row("/proj/24OUM20364_a.fsa"),
            self._row("/proj/26OUM99999_b.fsa"),
        ]
        # Typing a year-only prefix matches the right cohorts.
        indices, dits = extract_dit_candidates(rows, "24")
        self.assertEqual(indices, [0])  # only 24OUM20364 starts with 24
        self.assertEqual(dits, ["24OUM20364"])
        # Typing "OUM" mid-DIT must not match anything.
        indices2, dits2 = extract_dit_candidates(rows, "OUM")
        self.assertEqual(indices2, [])
        self.assertEqual(dits2, [])

    def test_dit_filter_keep_returns_none_for_empty(self) -> None:
        # Empty / None index list → filter not active.
        self.assertIsNone(dit_filter_keep([]))
        self.assertIsNone(dit_filter_keep(None))

    def test_dit_filter_keep_returns_set_for_indices(self) -> None:
        kept = dit_filter_keep([0, 2, 4])
        self.assertIsInstance(kept, set)
        self.assertEqual(kept, {0, 2, 4})


class MostRecentSaveTimestampTests(unittest.TestCase):
    """Phase 12.12 — `most_recent_save_timestamp` pure helper."""

    def test_returns_never_for_empty(self) -> None:
        self.assertEqual(most_recent_save_timestamp([]), NEVER_SAVED_LABEL)
        self.assertEqual(
            most_recent_save_timestamp(None), NEVER_SAVED_LABEL
        )

    def test_returns_never_when_no_timestamps(self) -> None:
        rows = [
            {"full_path": "/p/a.fsa"},
            {"full_path": "/p/b.fsa", "reviewed_at_utc": ""},
        ]
        self.assertEqual(
            most_recent_save_timestamp(rows), NEVER_SAVED_LABEL
        )

    def test_picks_largest_iso_string(self) -> None:
        # Lexicographic max works because ISO-8601 is sortable left-to-right.
        rows = [
            {"reviewed_at_utc": "2026-07-08T10:00:00+00:00"},
            {"reviewed_at_utc": "2026-07-08T13:30:00+00:00"},
            {"reviewed_at_utc": "2026-07-08T11:15:00+00:00"},
        ]
        self.assertEqual(
            most_recent_save_timestamp(rows),
            "2026-07-08T13:30:00+00:00",
        )

    def test_handles_garbage_timestamp_safely(self) -> None:
        rows = [
            {"reviewed_at_utc": "not-iso"},
            {"reviewed_at_utc": None},
            {"full_path": "no-ts-marker"},  # missing key
            {"reviewed_at_utc": 12345},  # wrong type
        ]
        # Most return › never — no crashes, no false positives.
        result = most_recent_save_timestamp(rows)
        self.assertIn(result, ["not-iso", "never"])  # whichever max-in-faithful-order


class FormatSummaryBannerTests(unittest.TestCase):
    """Phase 12.12 — `format_summary_banner` pure helper."""

    def test_empty_input_returns_zeroed_banner(self) -> None:
        out = format_summary_banner([])
        self.assertIn("0 needs review", out)
        self.assertIn("0 unreachable", out)
        self.assertIn("0 reviewed", out)
        self.assertIn("0 untouched", out)
        self.assertIn("last saved: never", out)

    def test_includes_visible_and_total(self) -> None:
        rows = [
            {"full_path": "a", "_path_unreachable": "false", "label": "manual_adjusted"},
            {"full_path": "b", "_path_unreachable": "false", "label": ""},
        ]
        out = format_summary_banner(rows)
        self.assertIn("visible 2 of 2", out)

    def test_visible_count_override(self) -> None:
        rows = [
            {"full_path": "a", "_path_unreachable": "false", "label": ""},
            {"full_path": "b", "_path_unreachable": "false", "label": ""},
        ]
        # Caller knows only 1 chip is visible (filter is on).
        out = format_summary_banner(rows, visible_count=1)
        self.assertIn("visible 1 of 2", out)

    def test_total_count_override(self) -> None:
        rows = [
            {"full_path": "a", "_path_unreachable": "false", "label": ""},
        ]
        # Caller passes a bundle size they know the loader saw.
        # Visible defaults to total, so the rendered line reads
        # "visible 1 of 5" only when the caller also passes
        # visible_count=1.
        out = format_summary_banner(rows, visible_count=1, total_count=5)
        self.assertIn("visible 1 of 5", out)
        # When only total_count is provided, visible defaults
        # to total — i.e. all-in-one mode.
        out_default = format_summary_banner(rows, total_count=5)
        self.assertIn("visible 5 of 5", out_default)

    def test_includes_most_recent_save(self) -> None:
        rows = [
            {"full_path": "a", "_path_unreachable": "false",
             "reviewed_at_utc": "2026-07-08T10:00:00+00:00"},
            {"full_path": "b", "_path_unreachable": "false",
             "reviewed_at_utc": "2026-07-08T13:30:00+00:00"},
        ]
        out = format_summary_banner(rows)
        self.assertIn("last saved: 2026-07-08T13:30:00+00:00", out)


if __name__ == "__main__":
    unittest.main()
