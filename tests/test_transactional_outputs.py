from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def test_atomic_html_write_replaces_complete_file(tmp_path):
    from core.html_reports._legacy import _atomic_write_html

    path = tmp_path / "report.html"
    path.write_text("old", encoding="utf-8")

    _atomic_write_html(path, "new")

    assert path.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".report.html.*.tmp")) == []


def test_atomic_html_write_preserves_previous_file_on_replace_failure(
    tmp_path,
    monkeypatch,
):
    from core.html_reports import _legacy as reports

    path = tmp_path / "report.html"
    path.write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        reports.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        reports._atomic_write_html(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".report.html.*.tmp")) == []


def test_tracking_workbook_failure_preserves_previous_file(tmp_path, monkeypatch):
    from core.analyses.clonality import tracking_excel

    path = tmp_path / "tracking.xlsx"
    first = {
        "fsa": None,
        "file_name": "26OUM00001_FR1__220526_A01_H9TEST01.fsa",
        "original_file_path": str(tmp_path / "first.fsa"),
        "source_run_dir": "run_a",
        "assay": "FR1",
        "dit": "26OUM00001",
        "group": "B",
        "ladder": "ROX400HD",
        "ladder_qc_status": "ok",
    }
    tracking_excel.update_clonality_tracking_workbook(
        path,
        [first],
        refresh_dashboard=False,
    )
    original_bytes = path.read_bytes()
    second = {
        **first,
        "file_name": "26OUM00002_FR1__220526_A02_H9TEST01.fsa",
        "original_file_path": str(tmp_path / "second.fsa"),
        "dit": "26OUM00002",
    }
    monkeypatch.setattr(
        tracking_excel,
        "refresh_clonality_tracking_dashboard",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dashboard failed")),
    )

    with pytest.raises(RuntimeError, match="dashboard failed"):
        tracking_excel.update_clonality_tracking_workbook(path, [second])

    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(".tracking.*.tmp.xlsx")) == []


def test_tracking_workbook_rerun_is_idempotent(tmp_path):
    from core.analyses.clonality.tracking_excel import (
        update_clonality_tracking_workbook,
    )

    path = tmp_path / "tracking.xlsx"
    entry = {
        "fsa": None,
        "file_name": "26OUM00001_FR1__220526_A01_H9TEST01.fsa",
        "original_file_path": str(tmp_path / "first.fsa"),
        "source_run_dir": "run_a",
        "assay": "FR1",
        "dit": "26OUM00001",
        "group": "B",
        "ladder": "ROX400HD",
        "ladder_qc_status": "ok",
    }

    update_clonality_tracking_workbook(path, [entry], refresh_dashboard=False)
    update_clonality_tracking_workbook(path, [entry], refresh_dashboard=False)

    runs = pd.read_excel(path, sheet_name="Runs", engine="openpyxl")
    assert len(runs) == 1


def test_flt3_tracking_failure_preserves_previous_file(tmp_path, monkeypatch):
    from core.analyses.flt3 import qc_tracker

    path = tmp_path / "FLT3_Tracking.xlsx"
    first = {
        "fsa": None,
        "file_name": "26OUM00001_ITD__220526_A01_H9TEST01.fsa",
        "source_run_dir": "run_a",
        "assay": "FLT3-ITD",
        "dit": "26OUM00001",
        "specimen_id": "26OUM00001",
        "group": "sample",
        "ladder": "GS500ROX",
        "ladder_qc_status": "ok",
        "peak_qc_status": "ok",
        "primary_peak_channel": "DATA1",
        "peaks_by_channel": {"DATA1": pd.DataFrame()},
    }
    qc_tracker.update_flt3_npm1_qc_tracker_workbook(path, [first])
    original_bytes = path.read_bytes()
    second = {
        **first,
        "file_name": "26OUM00002_ITD__220526_A02_H9TEST01.fsa",
        "dit": "26OUM00002",
        "specimen_id": "26OUM00002",
    }
    monkeypatch.setattr(
        qc_tracker,
        "refresh_flt3_tracking_dashboard",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("dashboard failed")
        ),
    )

    with pytest.raises(RuntimeError, match="dashboard failed"):
        qc_tracker.update_flt3_npm1_qc_tracker_workbook(path, [second])

    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(".FLT3_Tracking.*.tmp.xlsx")) == []
