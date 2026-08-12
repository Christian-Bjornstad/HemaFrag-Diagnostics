from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.tracking_workbook_io import write_tracking_frames
from scripts.combine_flt3_yearly_overview import combine_run_root
from scripts.run_flt3_yearly import run_yearly_validation


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _tracking_workbook(path: Path, runs: list[dict]) -> None:
    frame = pd.DataFrame(runs)
    patients = frame.loc[frame["SampleKind"].eq("patient")].copy()
    controls = frame.loc[frame["SampleKind"].eq("control")].copy()
    peaks = pd.DataFrame(
        columns=["IdentityKey", "MarkerName", "Control", "Assay", "Kind"]
    )
    write_tracking_frames(
        path,
        (
            ("Runs", frame, ("IdentityKey",)),
            ("Patient_Runs", patients, ("IdentityKey",), True),
            ("Control_Runs", controls, ("IdentityKey",), True),
            ("PK_Peaks", peaks, ("IdentityKey", "MarkerName")),
        ),
    )


def test_flt3_combined_workbook_prefers_corrected_identity(tmp_path):
    run_root = tmp_path / "archive"
    first = run_root / "month_runs" / "2026_01" / "FLT3_Tracking.xlsx"
    first.parent.mkdir(parents=True)
    _tracking_workbook(
        first,
        [
            {
                "IdentityKey": "same",
                "DIT": "26OUM00001",
                "SampleKind": "patient",
                "Control": "",
                "Assay": "FLT3-ITD",
                "LadderQC": "review_required",
            }
        ],
    )
    corrected = (
        run_root
        / "month_runs"
        / "2026_01"
        / "ASSAY_REPORTS"
        / "FLT3_Tracking.xlsx"
    )
    corrected.parent.mkdir(parents=True)
    _tracking_workbook(
        corrected,
        [
            {
                "IdentityKey": "same",
                "DIT": "26OUM00001",
                "SampleKind": "patient",
                "Control": "",
                "Assay": "FLT3-ITD",
                "LadderQC": "manual_adjustment",
            }
        ],
    )

    output = combine_run_root(
        run_root,
        run_root / "track-flt3-2026-overview.xlsx",
        year_label="2026",
    )

    runs = pd.read_excel(output, sheet_name="Runs", engine="openpyxl")
    assert len(runs) == 1
    assert runs.loc[0, "LadderQC"] == "manual_adjustment"


def test_flt3_yearly_runner_writes_review_bundle_and_manifest(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "input"
    (source / "2026_01_run").mkdir(parents=True)
    output = tmp_path / "output"
    sample = source / "2026_01_run" / "sample.fsa"
    sample.write_bytes(b"fsa")
    captured = {}

    monkeypatch.setattr(
        "scripts.run_flt3_yearly.generate_jobs",
        lambda *_args, **_kwargs: [
            {
                "name": "patient",
                "type": "pipeline",
                "path": sample.parent,
                "files": [sample],
            }
        ],
    )

    def fake_batch(**kwargs):
        captured.update(kwargs)
        batch_manifest = kwargs["output_base"] / "reports_archive" / "run.json"
        batch_manifest.parent.mkdir(parents=True, exist_ok=True)
        batch_manifest.write_text("{}", encoding="utf-8")
        return {
            "failed_jobs": [],
            "dit_report_entries": [
                {
                    "original_file_path": str(sample),
                    "file_name": sample.name,
                    "source_run_dir": sample.parent.name,
                    "assay": "FLT3-ITD",
                    "ladder": "GS500ROX",
                    "ladder_qc_status": "review_required",
                    "ladder_review_required": True,
                }
            ],
            "run_manifest_path": batch_manifest,
        }

    monkeypatch.setattr(
        "scripts.run_flt3_yearly.run_batch_jobs",
        fake_batch,
    )

    def fake_combine(_run_root, output_path, **_kwargs):
        output_path.write_bytes(b"xlsx")
        return output_path

    monkeypatch.setattr(
        "scripts.run_flt3_yearly.combine_run_root",
        fake_combine,
    )

    result = run_yearly_validation(
        year_label="2026",
        input_root=source,
        output_root=output,
        run_name="flt3-test",
        months=["2026_01"],
    )

    run_root = Path(result["run_dir"])
    cases = (
        run_root
        / "month_runs"
        / "2026_01"
        / "reports_archive"
        / "ladder_review_gate"
        / "ladder_review_cases.csv"
    )
    summary = json.loads(
        cases.with_name("ladder_review_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "completed"
    assert result["analysis"] == "flt3"
    assert cases.is_file()
    assert summary["review_case_count"] == 1
    assert summary["run_manifest_path"].endswith("run.json")
    assert captured["tracking_excel_path"].name == "FLT3_Tracking.xlsx"


def test_archive_tab_switches_to_flt3_runner(qapp):
    from gui_qt.tabs.tab_archive_runner import TabArchiveRunner

    tab = TabArchiveRunner()
    tab.set_analysis("flt3")

    assert tab.isEnabled()
    assert tab._runner() is not None
    assert tab._combiner() is not None
    assert tab.title.text() == "FLT3 Archive Runner"
    assert tab.chk_include_sl.isHidden()
    assert not tab.folder_workers.isEnabled()
    tab.close()
