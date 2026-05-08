from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.analyses.clonality.ladder_review_gate import (
    collect_ladder_review_cases,
    count_unresolved_review_cases,
    write_ladder_review_gate,
)
from gui_qt.tabs.tab_batch import TabBatch


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
                    "fsa": SimpleNamespace(file=Path("/tmp/review.fsa"), file_name="review.fsa"),
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


if __name__ == "__main__":
    unittest.main()
