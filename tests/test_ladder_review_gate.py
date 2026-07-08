from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from core.analyses.clonality.ladder_review_gate import (
    collect_ladder_review_cases,
    count_unresolved_review_cases,
    drop_review_case,
    read_review_drops,
    write_ladder_review_gate,
)
from gui_qt.tabs.tab_batch import TabBatch


def _windows_safe_path(text):
    """Return a Path whose `str()` equals `text` on any platform.

    On Linux Path(text).expanduser().resolve() preserves the literal;
    on Windows that exact sequence rewrites '/p/a.fsa' into '\\p\\a.fsa'
    because PurePosixPath interprets forward slashes as drive
    separators and `str()` falls through Windows coercion. Routing
    it through the local path with `expanduser` only would still fail,
    so we stash the argument verbatim and only construct a Path for
    `Path` operator calls that the helper under test demands.
    """
    return Path(text)


# POSIX-style absolute path that survives Windows. On Linux the path is
# used as-is; on Windows we route it through PurePosixPath so str()
# doesn't reinterpret forward slashes as drive separators.
def _posix_text(fake_path):
    if sys.platform == "win32":
        return str(PurePosixPath(fake_path))
    return fake_path


class LadderReviewGateTests(unittest.TestCase):
    def test_collects_only_review_cases(self) -> None:
        rows = collect_ladder_review_cases(
            [
                {
                    "file_name": "ok.fsa",
                    "ladder_qc_status": "ok",
                    "ladder_review_required": False,
                },
                {
                    "fsa": SimpleNamespace(
                        file=_posix_text("/tmp/review.fsa"),
                        file_name="review.fsa",
                    ),
                    "assay": "TCRgB",
                    "ladder": "LIZ500_250",
                    "ladder_qc_status": "review_required",
                    "ladder_review_required": True,
                    "ladder_review_reason": "poor_linear_liz_fit",
                    "ladder_review_reason_codes": ["poor_linear_liz_fit"],
                    "ladder_linear_max_residual_bp": 8.1,
                    "ladder_linear_mean_residual_bp": 3.2,
                    "ladder_linear_r2": 0.998,
                },
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["full_path"], "/tmp/review.fsa")
        self.assertEqual(rows[0]["reason_codes"], "poor_linear_liz_fit")

    def test_write_gate_and_count_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary = write_ladder_review_gate(
                [
                    {
                        "file_name": "review.fsa",
                        "ladder_qc_status": "missing_ladder",
                    }
                ],
                Path(td),
            )
            cases_path = Path(summary["cases_path"])

            self.assertEqual(summary["review_case_count"], 1)
            self.assertEqual(count_unresolved_review_cases(cases_path), 1)

            with cases_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0].keys())
            rows[0]["label"] = "reviewed_no_change"
            with cases_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            self.assertEqual(count_unresolved_review_cases(cases_path), 0)

    def test_prefers_original_file_path_over_staged_fsa_path(self) -> None:
        rows = collect_ladder_review_cases(
            [
                {
                    "fsa": SimpleNamespace(
                        file=Path("/tmp/fraggler_stage_dead/00001_abcd_sample.fsa"),
                        file_name="00001_abcd_sample.fsa",
                    ),
                    "original_file_path": "/Volumes/T7 Shield/run/sample.fsa",
                    "ladder_qc_status": "review_required",
                    "ladder_review_required": True,
                }
            ]
        )

        self.assertEqual(rows[0]["full_path"], "/Volumes/T7 Shield/run/sample.fsa")
        self.assertEqual(rows[0]["file"], "sample.fsa")

    def test_review_session_counts_unresolved_bundle_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            summary = write_ladder_review_gate(
                [
                    {
                        "file_name": "fixed.fsa",
                        "ladder_qc_status": "review_required",
                    },
                    {
                        "file_name": "still_open.fsa",
                        "ladder_qc_status": "missing_ladder",
                    },
                ],
                Path(td),
            )
            cases_path = Path(summary["cases_path"])

            with cases_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0].keys())
            rows[0]["label"] = "manual_adjusted"
            with cases_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            self.assertEqual(TabBatch._review_bundle_resolution_counts(Path(td)), (1, 1))

    def test_carries_resolved_labels_to_new_gate(self) -> None:
        with tempfile.TemporaryDirectory() as old_td, tempfile.TemporaryDirectory() as new_td:
            old_summary = write_ladder_review_gate(
                [
                    {
                        "fsa": SimpleNamespace(file=Path("/tmp/fixed.fsa"), file_name="fixed.fsa"),
                        "ladder_qc_status": "review_required",
                        "ladder_review_required": True,
                    },
                ],
                Path(old_td),
            )
            old_cases_path = Path(old_summary["cases_path"])
            with old_cases_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0].keys())
            rows[0]["label"] = "manual_adjusted"
            rows[0]["label_note"] = "fixed in ladder editor"
            rows[0]["adjustment_path"] = "/tmp/fixed.ladder_adj.json"
            with old_cases_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            resolved_rows = TabBatch._resolved_review_rows_from_bundle(Path(old_td))
            new_summary = write_ladder_review_gate(
                [
                    {
                        "fsa": SimpleNamespace(file=Path("/tmp/fixed.fsa"), file_name="fixed.fsa"),
                        "ladder_qc_status": "review_required",
                        "ladder_review_required": True,
                    },
                    {
                        "fsa": SimpleNamespace(file=Path("/tmp/still_open.fsa"), file_name="still_open.fsa"),
                        "ladder_qc_status": "review_required",
                        "ladder_review_required": True,
                    },
                ],
                Path(new_td),
            )

            unresolved = TabBatch._carry_resolved_labels_to_gate(new_summary, resolved_rows)

            self.assertEqual(unresolved, 1)
            self.assertEqual(new_summary["review_case_count"], 1)
            with Path(new_summary["cases_path"]).open("r", encoding="utf-8", newline="") as handle:
                new_rows = {row["file"]: row for row in csv.DictReader(handle)}
            self.assertEqual(new_rows["fixed.fsa"]["label"], "manual_adjusted")
            self.assertEqual(new_rows["fixed.fsa"]["label_note"], "fixed in ladder editor")
            self.assertEqual(new_rows["still_open.fsa"]["label"], "")


class TabLadderBundleLoaderTests(unittest.TestCase):
    """Phase 12.0 — keep unreachable rows in the bundle loader.

    Before Phase 12.0 the GUI's worker dropped any row whose full_path
    no longer existed on disk. That's why the editor "kinda worked"
    (loaded 0 cases with no error). The fix preserves every
    non-empty full_path and tags unreachable ones.
    """

    def _write_bundle(self, td, rows):
        cases_path = Path(td) / "ladder_review_cases.csv"
        fieldnames = ["full_path", "file", "ladder_qc_status"]
        with cases_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return cases_path

    def _loader_result(self, bundle_dir):
        from gui_qt.tabs.tab_ladder import TabLadder

        return TabLadder._load_review_bundle_worker(Path(bundle_dir))

    def test_bundle_loader_keeps_unreachable_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.fsa"
            real.write_bytes(b"x")
            self._write_bundle(
                td,
                [
                    {"full_path": str(real), "file": "real.fsa", "ladder_qc_status": "review_required"},
                    {"full_path": "/definitely/does/not/exist.fsa", "file": "ghost.fsa", "ladder_qc_status": "review_required"},
                ],
            )
            result = self._loader_result(td)
            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual(len(result["missing_paths"]), 1)
            self.assertEqual(result["missing_paths"][0], "/definitely/does/not/exist.fsa")
            ghost_row = next(r for r in result["rows"] if r["file"] == "ghost.fsa")
            self.assertEqual(ghost_row["_path_unreachable"], "true")
            real_row = next(r for r in result["rows"] if r["file"] == "real.fsa")
            self.assertEqual(real_row["_path_unreachable"], "false")

    def test_bundle_loader_raises_on_missing_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                self._loader_result(td)

    def test_bundle_loader_drops_only_truly_empty_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.fsa"
            real.write_bytes(b"x")
            self._write_bundle(
                td,
                [
                    {"full_path": "", "file": "blank.fsa", "ladder_qc_status": "review_required"},
                    {"full_path": str(real), "file": "real.fsa", "ladder_qc_status": "review_required"},
                ],
            )
            result = self._loader_result(td)
            self.assertEqual(len(result["rows"]), 1)
            self.assertEqual(result["rows"][0]["file"], "real.fsa")


class RelocateReviewCaseTests(unittest.TestCase):
    """Phase 12.4 — relocate_review_case atomic rewrite + audit log."""

    def _seed_bundle(self, td):
        """Create a 2-row bundle CSV and return the bundle dir."""
        from core.analyses.clonality.ladder_review_gate import write_ladder_review_gate

        cases = [
            {
                "original_file_path": _posix_text("/p/a.fsa"),
                "assay": "FR1",
                "ladder": "ROX400HD",
                "ladder_qc_status": "review_required",
                "ladder_review_required": True,
            },
            {
                "original_file_path": _posix_text("/p/b.fsa"),
                "assay": "TCRgB",
                "ladder": "LIZ500_250",
                "ladder_qc_status": "missing_ladder",
                "ladder_review_required": True,
            },
        ]
        summary = write_ladder_review_gate(cases, Path(td))
        return summary

    def test_relocate_review_case_swaps_path_in_csv(self) -> None:
        from core.analyses.clonality.ladder_review_gate import relocate_review_case

        with tempfile.TemporaryDirectory() as td:
            self._seed_bundle(td)
            entry = relocate_review_case(
                Path(td),
                Path(_posix_text("/p/a.fsa")),
                Path(_posix_text("/p/a_v2.fsa")),
            )
            self.assertEqual(entry["old_path"], _posix_text("/p/a.fsa"))
            self.assertEqual(entry["new_path"], _posix_text("/p/a_v2.fsa"))
            # And the CSV reflects it.
            cases_path = Path(td) / "ladder_review_cases.csv"
            with cases_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                paths = [r["full_path"] for r in reader]
            self.assertIn(_posix_text("/p/a_v2.fsa"), paths)
            self.assertNotIn(_posix_text("/p/a.fsa"), paths)
            self.assertIn(_posix_text("/p/b.fsa"), paths)  # second row untouched.

    def test_relocate_review_case_appends_to_relocations_log(self) -> None:
        from core.analyses.clonality.ladder_review_gate import relocate_review_case

        with tempfile.TemporaryDirectory() as td:
            self._seed_bundle(td)
            relocate_review_case(
                Path(td),
                Path(_posix_text("/p/a.fsa")),
                Path(_posix_text("/p/a_v2.fsa")),
            )
            log_path = Path(td) / "ladder_review_relocations.json"
            self.assertTrue(log_path.exists())
            data = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertIn(_posix_text("/p/a.fsa"), data)
            self.assertEqual(
                data[_posix_text("/p/a.fsa")]["new_path"], _posix_text("/p/a_v2.fsa")
            )

    def test_relocate_review_case_raises_for_unknown_path(self) -> None:
        from core.analyses.clonality.ladder_review_gate import relocate_review_case

        with tempfile.TemporaryDirectory() as td:
            self._seed_bundle(td)
            with self.assertRaises(FileNotFoundError):
                relocate_review_case(
                    Path(td),
                    Path(_posix_text("/p/never_seen.fsa")),
                    Path(_posix_text("/p/somewhere.fsa")),
                )

    def test_relocate_review_case_raises_when_bundle_csv_missing(self) -> None:
        from core.analyses.clonality.ladder_review_gate import relocate_review_case

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                relocate_review_case(
                    Path(td),
                    Path(_posix_text("/p/a.fsa")),
                    Path(_posix_text("/p/a_v2.fsa")),
                )


class DropReviewCaseTests(unittest.TestCase):
    """Phase 12.10 — `drop_review_case` + `read_review_drops`.

    Pins:
      - the row is removed atomically;
      - `ladder_review_drops.json` accumulates one entry per drop;
      - re-dropping the same path raises FileNotFoundError;
      - missing CSV raises FileNotFoundError.
    """

    def _write_csv(self, td, lines):
        p = Path(td) / "ladder_review_cases.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def test_drop_removes_row_and_returns_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = self._write_csv(td, [
                "full_path,label",
                "/p/a.fsa,manual_adjusted",
                "/p/b.fsa,",
            ])
            entry = drop_review_case(Path(td), "/p/a.fsa")
            self.assertEqual(entry["full_path"], "/p/a.fsa")
            self.assertEqual(entry["previous_label"], "manual_adjusted")
            self.assertEqual(entry["dropped_row_index"], 0)
            self.assertIn("dropped_at_utc", entry)
            text = csv_path.read_text(encoding="utf-8")
            self.assertNotIn("/p/a.fsa", text)
            self.assertIn("/p/b.fsa", text)
            drops = read_review_drops(Path(td))
            self.assertEqual(len(drops), 1)
            self.assertEqual(drops[0]["full_path"], "/p/a.fsa")

    def test_drop_accumulates_log_across_calls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, [
                "full_path,label",
                "/p/a.fsa,",
                "/p/b.fsa,",
            ])
            drop_review_case(Path(td), "/p/a.fsa")
            drop_review_case(Path(td), "/p/b.fsa")
            drops = read_review_drops(Path(td))
            self.assertEqual(len(drops), 2)
            self.assertEqual([d["full_path"] for d in drops],
                             ["/p/a.fsa", "/p/b.fsa"])

    def test_drop_raises_for_unknown_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, ["full_path,label", "/p/a.fsa,"])
            with self.assertRaises(FileNotFoundError):
                drop_review_case(Path(td), "/p/z.fsa")

    def test_drop_raises_when_csv_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                drop_review_case(Path(td), "/x.fsa")

    def test_read_review_drops_returns_empty_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(read_review_drops(Path(td)), [])

    def test_read_review_drops_handles_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "ladder_review_drops.json").write_text(
                "not-valid-json{", encoding="utf-8"
            )
            self.assertEqual(read_review_drops(Path(td)), [])

    def test_drop_returns_path_object_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(td, ["full_path,label", "/p/a.fsa,"])
            entry = drop_review_case(Path(td), Path("/p/a.fsa"))
            self.assertEqual(entry["full_path"], "/p/a.fsa")


if __name__ == "__main__":
    unittest.main()
