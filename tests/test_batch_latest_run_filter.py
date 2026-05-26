from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.batch import extract_run_date_from_folder_name, generate_jobs


def _write_fsa(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"dummy-fsa")


class BatchLatestRunFilterTests(unittest.TestCase):
    def test_extract_run_date_from_folder_name(self) -> None:
        self.assertEqual(
            extract_run_date_from_folder_name("2026_05_22_b_sl_fr123_dhjh_pr_H9H1DHU4_2026-05-22_0805").isoformat(),
            "2026-05-22",
        )
        self.assertEqual(
            extract_run_date_from_folder_name("run_export_2026-05-23_0806").isoformat(),
            "2026-05-23",
        )
        self.assertIsNone(extract_run_date_from_folder_name("reports_2026_05"))
        self.assertIsNone(extract_run_date_from_folder_name("not_a_run_folder"))

    def test_latest_run_filter_keeps_only_latest_patient_and_qc_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "2026"
            old_run = root / "2026_05_21_tcrg_igkkde_pr_OLD_2026-05-21_0801"
            latest_a = root / "2026_05_22_tcrg_igkkde_pr_NEW1_2026-05-22_0804"
            latest_b = root / "2026_05_22_b_sl_fr123_dhjh_pr_NEW2_2026-05-22_0805"
            _write_fsa(old_run / "26OUM00001_tcrgA__210526_A01_OLD.fsa")
            _write_fsa(old_run / "PK_tcrgA__210526_E01_OLD.fsa")
            _write_fsa(latest_a / "26OUM00002_tcrgA__220526_A01_NEW1.fsa")
            _write_fsa(latest_a / "PK_tcrgA__220526_E01_NEW1.fsa")
            _write_fsa(latest_b / "26OUM00003_FR1__220526_A02_NEW2.fsa")
            _write_fsa(latest_b / "NK_FR1__220526_F01_NEW2.fsa")

            jobs = generate_jobs([root], aggregate_patients=True, run_date_filter="latest")

            all_files = {file.name for job in jobs for file in job.get("files", [])}
            self.assertIn("26OUM00002_tcrgA__220526_A01_NEW1.fsa", all_files)
            self.assertIn("26OUM00003_FR1__220526_A02_NEW2.fsa", all_files)
            self.assertIn("PK_tcrgA__220526_E01_NEW1.fsa", all_files)
            self.assertIn("NK_FR1__220526_F01_NEW2.fsa", all_files)
            self.assertNotIn("26OUM00001_tcrgA__210526_A01_OLD.fsa", all_files)
            self.assertNotIn("PK_tcrgA__210526_E01_OLD.fsa", all_files)

            qc_jobs = [job for job in jobs if job["type"] == "qc"]
            self.assertEqual(len(qc_jobs), 1)
            self.assertEqual({file.name for file in qc_jobs[0]["files"]}, {"PK_tcrgA__220526_E01_NEW1.fsa", "NK_FR1__220526_F01_NEW2.fsa"})
            self.assertEqual(jobs[0]["_scan_summary"]["selected_run_date"], "2026-05-22")
            self.assertEqual(jobs[0]["_scan_summary"]["selected_folder_count"], 2)

    def test_latest_run_filter_preserves_single_day_folder_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "22_05"
            run_a = root / "2026_05_22_tcrg_igkkde_pr_NEW1_2026-05-22_0804"
            run_b = root / "2026_05_22_b_sl_fr123_dhjh_pr_NEW2_2026-05-22_0805"
            _write_fsa(run_a / "26OUM00002_tcrgA__220526_A01_NEW1.fsa")
            _write_fsa(run_a / "PK_tcrgA__220526_E01_NEW1.fsa")
            _write_fsa(run_b / "26OUM00003_FR1__220526_A02_NEW2.fsa")
            _write_fsa(run_b / "NK_FR1__220526_F01_NEW2.fsa")

            all_jobs = generate_jobs([root], aggregate_patients=True, run_date_filter="all")
            latest_jobs = generate_jobs([root], aggregate_patients=True, run_date_filter="latest")

            all_files = {file.name for job in all_jobs for file in job.get("files", [])}
            latest_files = {file.name for job in latest_jobs for file in job.get("files", [])}
            self.assertEqual(latest_files, all_files)
            self.assertEqual(latest_jobs[0]["_scan_summary"]["selected_run_date"], "2026-05-22")


if __name__ == "__main__":
    unittest.main()
