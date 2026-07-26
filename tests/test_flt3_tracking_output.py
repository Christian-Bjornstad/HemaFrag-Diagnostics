from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from config import APP_SETTINGS
from core.analyses.flt3.qc_tracker import update_flt3_npm1_qc_tracker_workbook
from scripts.run_flt3_liz500_qc_all_injections import (
    QC_OUTPUT_COLUMNS,
    RAW_METADATA_COLUMNS,
    _update_global_rox500_workbook,
)


def _entry(file_name: str, *, specimen_id: str = "26OUM00001", assay: str = "FLT3-ITD") -> dict:
    return {
        "fsa": None,
        "file_name": file_name,
        "source_run_dir": "flt3_run",
        "dit": "26OUM00001" if specimen_id.startswith("26OUM") else "",
        "assay": assay,
        "specimen_id": specimen_id,
        "analysis_type": "",
        "group": "sample",
        "run_date": "2026-05-26",
        "well_id": "A01",
        "ladder": "GS500ROX",
        "ladder_qc_status": "ok",
        "ladder_fit_strategy": "linear",
        "ladder_expected_step_count": 16,
        "ladder_fitted_step_count": 16,
        "ladder_r2": 0.9999,
        "peak_qc_status": "ok",
        "primary_peak_channel": "DATA1",
        "peaks_by_channel": {
            "DATA1": pd.DataFrame(
                [
                    {"label": "WT", "basepairs": 329.0, "peaks": 1200.0, "area": 5000.0, "keep": True},
                    {"label": "MUT", "basepairs": 360.0, "peaks": 200.0, "area": 300.0, "keep": True},
                ]
            )
        },
        "ratio": 0.0,
    }


class Flt3TrackingOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._settings = copy.deepcopy(APP_SETTINGS)

    def tearDown(self) -> None:
        APP_SETTINGS.clear()
        APP_SETTINGS.update(self._settings)

    def test_flt3_tracking_workbook_writes_split_dashboard_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "FLT3_Tracking.xlsx"
            update_flt3_npm1_qc_tracker_workbook(
                workbook,
                [
                    _entry("26OUM00001_ITD__260526_A01_H9TEST01.fsa"),
                    _entry("IVS-0000_ITD__260526_B01_H9TEST01.fsa", specimen_id="IVS-0000"),
                    _entry("IVS-P001_ITD__260526_C01_H9TEST01.fsa", specimen_id="IVS-P001"),
                ],
            )

            with pd.ExcelFile(workbook, engine="openpyxl") as xls:
                sheets = xls.sheet_names
            self.assertIn("Runs", sheets)
            self.assertIn("Patient_Runs", sheets)
            self.assertIn("Control_Runs", sheets)
            self.assertIn("PK_Peaks", sheets)
            self.assertIn("Dashboard", sheets)

            patients = pd.read_excel(workbook, sheet_name="Patient_Runs", engine="openpyxl")
            controls = pd.read_excel(workbook, sheet_name="Control_Runs", engine="openpyxl")
            peaks = pd.read_excel(workbook, sheet_name="PK_Peaks", engine="openpyxl")
            self.assertEqual(len(patients), 1)
            self.assertEqual(len(controls), 2)
            self.assertEqual(set(controls["Control"]), {"RK", "PK"})
            self.assertGreaterEqual(len(peaks), 2)

    def test_flt3_tracking_preserves_rox500_qc_sheets_in_shared_global_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "HemaFrag_FLT3_All_Runs.xlsx"
            row = {column: "" for column in QC_OUTPUT_COLUMNS}
            row.update(
                {
                    "File": "IVS-0000_ITD__260526_B01_H9TEST01.fsa",
                    "SourceRunDir": "flt3_run",
                    "InjectionTimeSeconds": 5,
                    "QCStatus": "PASS",
                    "LadderQC": "ok",
                    "PeakQC": "not_evaluated",
                }
            )
            raw_row = {column: "" for column in RAW_METADATA_COLUMNS}
            raw_row.update({"File": row["File"], "RunName": "flt3_run", "InjectionTimeSeconds": 5})
            _update_global_rox500_workbook(
                workbook,
                qc_df=pd.DataFrame([row], columns=QC_OUTPUT_COLUMNS),
                raw_meta_df=pd.DataFrame([raw_row], columns=RAW_METADATA_COLUMNS),
                skipped=[],
            )

            update_flt3_npm1_qc_tracker_workbook(
                workbook,
                [_entry("26OUM00001_ITD__260526_A01_H9TEST01.fsa")],
            )

            with pd.ExcelFile(workbook, engine="openpyxl") as xls:
                sheets = xls.sheet_names
            self.assertIn("Runs", sheets)
            self.assertIn("All_Analyzed_QC", sheets)
            self.assertIn("Raw_Metadata_All_FSA", sheets)

    def test_rox500_global_workbook_appends_and_dedupes_qc_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "HemaFrag_FLT3_All_Runs.xlsx"
            row = {column: "" for column in QC_OUTPUT_COLUMNS}
            row.update(
                {
                    "File": "IVS-0000_ITD__260526_B01_H9TEST01.fsa",
                    "SourceRunDir": "flt3_run",
                    "Assay": "FLT3-ITD",
                    "ControlPrefix": "IVS-0000",
                    "InjectionTimeSeconds": 5,
                    "QCStatus": "PASS",
                    "LadderQC": "ok",
                    "PeakQC": "not_evaluated",
                }
            )
            raw_row = {column: "" for column in RAW_METADATA_COLUMNS}
            raw_row.update(
                {
                    "File": row["File"],
                    "RunName": "flt3_run",
                    "InjectionTimeSeconds": 5,
                }
            )
            qc_df = pd.DataFrame([row], columns=QC_OUTPUT_COLUMNS)
            raw_df = pd.DataFrame([raw_row], columns=RAW_METADATA_COLUMNS)

            _update_global_rox500_workbook(workbook, qc_df=qc_df, raw_meta_df=raw_df, skipped=[])
            _update_global_rox500_workbook(workbook, qc_df=qc_df, raw_meta_df=raw_df, skipped=[])

            all_qc = pd.read_excel(workbook, sheet_name="All_Analyzed_QC", engine="openpyxl")
            summary = pd.read_excel(workbook, sheet_name="Summary_By_Injection", engine="openpyxl")
            self.assertEqual(len(all_qc), 1)
            self.assertEqual(int(summary.iloc[0]["Count"]), 1)


if __name__ == "__main__":
    unittest.main()
