from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTextBrowser

from core.tracking_workbook_io import write_tracking_frames
from scripts.combine_clonality_yearly_overview import combine_run_root
from scripts.run_clonality_yearly import (
    discover_month_folders,
    normalize_month_keys,
    run_yearly_validation,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _tracking_workbook(path: Path, runs: list[dict]) -> None:
    run_frame = pd.DataFrame(runs)
    patients = run_frame.loc[
        run_frame["SampleKind"].eq("patient")
    ].copy()
    controls = run_frame.loc[
        run_frame["SampleKind"].eq("control")
    ].copy()
    peaks = pd.DataFrame(
        columns=["IdentityKey", "MarkerName", "Control", "Assay", "Kind"]
    )
    write_tracking_frames(
        path,
        (
            ("Runs", run_frame, ("IdentityKey",)),
            ("Patient_Runs", patients, None),
            ("Control_Runs", controls, None),
            ("PK_Peaks", peaks, ("IdentityKey", "MarkerName")),
        ),
    )


def test_month_discovery_and_normalization(tmp_path):
    january = tmp_path / "2026_01_run_a"
    february = tmp_path / "2026-02-run-b"
    other = tmp_path / "2025_01_old"
    for folder in (january, february, other):
        folder.mkdir()

    discovered = discover_month_folders(tmp_path, "2026")

    assert discovered["2026_01"] == [january]
    assert discovered["2026_02"] == [february]
    assert normalize_month_keys(
        "2026",
        ["1", "2026-02", "2026_02", "wrong"],
    ) == ["2026_01", "2026_02"]


def test_combined_workbook_keeps_latest_identity_and_all_patients(tmp_path):
    run_root = tmp_path / "archive"
    first_path = run_root / "month_runs" / "2026_01" / "track-clonality.xlsx"
    first_path.parent.mkdir(parents=True)
    _tracking_workbook(
        first_path,
        [
            {
                "IdentityKey": "same",
                "DIT": "26OUM00001",
                "SampleKind": "patient",
                "Control": "",
                "LadderQC": "review_required",
            }
        ],
    )
    corrected_path = (
        run_root
        / "month_runs"
        / "2026_01"
        / "reports_backfill"
        / "Clonality_Tracking.xlsx"
    )
    corrected_path.parent.mkdir(parents=True)
    _tracking_workbook(
        corrected_path,
        [
            {
                "IdentityKey": "same",
                "DIT": "26OUM00001",
                "SampleKind": "patient",
                "Control": "",
                "LadderQC": "manual_adjustment",
            },
            {
                "IdentityKey": "new",
                "DIT": "26OUM00002",
                "SampleKind": "patient",
                "Control": "",
                "LadderQC": "ok",
            },
        ],
    )

    output = combine_run_root(
        run_root,
        run_root / "track-clonality-2026-overview.xlsx",
        year_label="2026",
    )

    runs = pd.read_excel(output, sheet_name="Runs", engine="openpyxl")
    patients = pd.read_excel(
        output,
        sheet_name="Patient_Runs",
        engine="openpyxl",
    )
    assert len(runs) == 2
    assert len(patients) == 2
    assert (
        runs.loc[runs["IdentityKey"].eq("same"), "LadderQC"].iloc[0]
        == "manual_adjustment"
    )


def test_yearly_orchestration_writes_resumable_manifest(
    tmp_path,
    monkeypatch,
):
    input_root = tmp_path / "input"
    (input_root / "2026_01_run").mkdir(parents=True)
    output_root = tmp_path / "output"
    events: list[dict] = []
    calls: list[str] = []

    def fake_backfill(**kwargs):
        month = kwargs["month"]
        calls.append(month)
        return {
            "folders": {
                f"{month}_run": {
                    "month": month,
                    "status": "done",
                }
            }
        }

    def fake_combine(_run_root, output_path, **_kwargs):
        output_path.write_bytes(b"xlsx")
        return output_path

    monkeypatch.setattr(
        "scripts.run_clonality_yearly.run_clonality_backfill",
        fake_backfill,
    )
    monkeypatch.setattr(
        "scripts.run_clonality_yearly.combine_run_root",
        fake_combine,
    )

    result = run_yearly_validation(
        year_label="2026",
        input_root=input_root,
        output_root=output_root,
        run_name="validation",
        months=["2026_01", "2026_02"],
        progress_callback=events.append,
    )

    manifest_path = Path(result["run_dir"]) / "full_2026_run_manifest.json"
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calls == ["2026_01"]
    assert persisted["months"]["2026_01"]["status"] == "done"
    assert persisted["months"]["2026_02"]["status"] == "skipped_empty"
    assert persisted["status"] == "completed"
    assert events[0]["event"] == "run_started"
    assert events[-1]["event"] == "run_finished"


def test_archive_runner_support_modules_are_available():
    from gui_qt.tabs import tab_archive_runner

    assert tab_archive_runner._ARCHIVE_SUPPORT_AVAILABLE is True
    assert tab_archive_runner.run_yearly_validation is not None
    assert tab_archive_runner.combine_run_root is not None


def test_archive_tab_opens_discovered_ladder_review_bundle(
    tmp_path,
    qapp,
):
    from gui_qt.tabs.tab_archive_runner import TabArchiveRunner

    bundle = tmp_path / "month_runs" / "2026_01" / "ladder_review_gate"
    bundle.mkdir(parents=True)
    (bundle / "ladder_review_cases.csv").write_text(
        "full_path,label\nsample.fsa,\n",
        encoding="utf-8",
    )
    tab = TabArchiveRunner()
    tab.set_analysis("clonality")
    tab._current_run_root = tmp_path
    emitted: list[tuple[str, str]] = []
    tab.ladderReviewRequested.connect(
        lambda analysis, path: emitted.append((analysis, path))
    )

    tab.on_review_failed_ladders()

    assert emitted == [("clonality", str(bundle))]
    tab.close()


def test_about_text_browsers_have_explicit_readable_contrast(qapp):
    from gui_qt.styles import VIBRANT_PRO_QSS
    from gui_qt.tabs.tab_about import TabAbout

    tab = TabAbout()
    browsers = tab.findChildren(QTextBrowser, "AboutTextBrowser")

    assert browsers
    assert all(browser.styleSheet() == "" for browser in browsers)
    assert all(
        "a { color: #2563EB; }" in browser.document().defaultStyleSheet()
        for browser in browsers
    )
    assert "QTextBrowser#AboutTextBrowser" in VIBRANT_PRO_QSS
    assert "color: #102235" in VIBRANT_PRO_QSS
    tab.close()
