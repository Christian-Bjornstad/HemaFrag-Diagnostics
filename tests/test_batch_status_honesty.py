"""Regression tests for honest batch status reporting (no premature success/complete).

Root cause: in aggregated mode the per-job "success" callback fired when a job's
collection finished, while final DIT report building / tracking workbook refresh
still ran afterwards. The GUI showed green "Completed" during that window.

Fix contract:
- per-job terminal state is now "collected" while aggregation is still pending
- only after all post-processing does the callback emit ("Done", "done")
- failure paths must never emit success
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import APP_SETTINGS


def _entry(file_name: str, *, assay: str = "FR1", dit: str = "") -> dict:
    return {
        "fsa": None,
        "file_name": file_name,
        "assay": assay,
        "dit": dit,
        "group": "B",
        "ladder": "ROX400HD",
        "ladder_qc_status": "ok",
        "ladder_fit_strategy": "linear",
        "ladder_expected_step_count": 16,
        "ladder_fitted_step_count": 16,
        "ladder_r2": 0.9999,
        "ladder_linear_r2": 0.9999,
        "ladder_linear_mean_residual_bp": 0.2,
        "ladder_linear_max_residual_bp": 0.7,
        "ladder_max_curvature": 0.0,
    }


class BatchStatusHonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._settings = copy.deepcopy(APP_SETTINGS)

    def tearDown(self) -> None:
        APP_SETTINGS.clear()
        APP_SETTINGS.update(self._settings)

    def _run_aggregated_batch(self, update_callback, build_side_effect=None) -> dict:
        import core.batch as batch

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "run"
            APP_SETTINGS["active_analysis"] = "clonality"
            APP_SETTINGS.setdefault("analyses", {}).setdefault("clonality", {}).setdefault("batch", {})
            APP_SETTINGS["analyses"]["clonality"]["batch"].update(
                {
                    "ladder_review_gate": {"enabled": False},
                }
            )

            patient_entry = _entry("26OUM00001_FR1__220526_A01_H9TEST01.fsa", dit="26OUM00001")
            qc_entry = _entry("PK_FR1__220526_E08_H9TEST01.fsa")
            jobs = [
                {"name": "26OUM00001", "type": "pipeline", "path": None, "files": [Path("patient.fsa")]},
                {"name": "QC", "type": "qc", "path": None, "files": [Path("pk.fsa")]},
            ]

            if build_side_effect is not None:
                build_patch = patch(
                    "core.html_reports.build_dit_html_reports",
                    side_effect=build_side_effect,
                )
            else:
                build_patch = patch(
                    "core.html_reports.build_dit_html_reports",
                    return_value=None,
                )

            with (
                patch.object(batch, "run_pipeline_job_collect", return_value=[patient_entry]),
                patch.object(batch, "run_qc_job", return_value=(None, [qc_entry])),
                build_patch,
            ):
                return batch.run_batch_jobs(
                    jobs=jobs,
                    output_base=output_root,
                    out_folder_tmpl="ASSAY_REPORTS",
                    outfile_html_tmpl="QC_REPORT_{name}.html",
                    excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
                    pipeline_scope="all",
                    assay_filter="",
                    aggregate_dit_reports=True,
                    continue_on_error=False,
                    aggregate_outdir_name="reports_test",
                    update_callback=update_callback,
                )

    def test_job_success_is_not_emitted_before_aggregation(self) -> None:
        """Per-job completion in aggregate mode must NOT emit 'success'."""
        events: list[tuple[int, int, str, str]] = []

        # Simulate the GUI race: build_dit_html_reports observes callbacks while
        # aggregation is still running.
        def fake_build(entries, outdir):
            for _, _, _, state in events:
                if state == "success":
                    raise AssertionError(
                        "'success' was emitted before build_dit_html_reports ran"
                    )
            return None

        with patch("core.html_reports.build_dit_html_reports", side_effect=fake_build):
            self._run_aggregated_batch(lambda i, t, n, s: events.append((i, t, n, s)))

        job_terminal_states = [
            state for (_, total, name, state) in events if name not in {"DIT aggregation"}
        ]
        self.assertNotIn(
            "success",
            [s.split(":", 1)[0] for s in job_terminal_states[:-1]],
            "individual job completions must use 'collected', not 'success'",
        )
        # Final event is the global Done
        self.assertEqual(events[-1][3], "done")
        self.assertEqual(events[-1][2], "Done")

    def test_final_done_event_fires_after_all_jobs_and_aggregation(self) -> None:
        events: list[tuple[int, int, str, str]] = []

        order: list[str] = []

        def fake_build(entries, outdir):
            order.append("build_report")

        def track(i, t, n, s):
            events.append((i, t, n, s))
            order.append(f"cb:{n}:{s}")

        with patch("core.html_reports.build_dit_html_reports", side_effect=fake_build):
            self._run_aggregated_batch(track, build_side_effect=fake_build)

        self.assertIn("build_report", order)
        # Aggregation must complete BEFORE the final Done callback fires.
        self.assertLess(order.index("build_report"), order.index("cb:Done:done"))
        done_events = [e for e in events if e[3] == "done" and e[2] == "Done"]
        self.assertEqual(len(done_events), 1)
        self.assertEqual(done_events[0][0], done_events[0][1])

    def test_failed_job_never_emits_success(self) -> None:
        import core.batch as batch

        events: list[tuple[int, int, str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "run"
            APP_SETTINGS["active_analysis"] = "clonality"
            APP_SETTINGS.setdefault("analyses", {}).setdefault("clonality", {}).setdefault("batch", {})
            APP_SETTINGS["analyses"]["clonality"]["batch"].update(
                {
                    "ladder_review_gate": {"enabled": False},
                }
            )
            jobs = [
                {"name": "BAD", "type": "pipeline", "path": None, "files": [Path("bad.fsa")]}
            ]
            with (
                patch.object(batch, "run_pipeline_job_collect", side_effect=RuntimeError("boom")),
                patch("core.html_reports.build_dit_html_reports", return_value=None),
            ):
                batch.run_batch_jobs(
                    jobs=jobs,
                    output_base=output_root,
                    out_folder_tmpl="ASSAY_REPORTS",
                    outfile_html_tmpl="QC_REPORT_{name}.html",
                    excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
                    pipeline_scope="all",
                    assay_filter="",
                    aggregate_dit_reports=True,
                    continue_on_error=True,
                    aggregate_outdir_name="reports_test",
                    update_callback=lambda i, t, n, s: events.append((i, t, n, s)),
                )

        states = [s for (_, _, _, s) in events]
        self.assertTrue(any(s.startswith("error") for s in states))
        self.assertFalse(
            any(s == "success" or s.startswith("success") for s in states),
            f"no success may be emitted on failed run, got {states}",
        )


if __name__ == "__main__":
    unittest.main()
