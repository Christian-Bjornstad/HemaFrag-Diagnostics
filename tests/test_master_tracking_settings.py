from __future__ import annotations

from pathlib import Path


def _set_master_path(monkeypatch, analysis: str, value: str) -> None:
    from config import APP_SETTINGS

    profile = APP_SETTINGS.setdefault("analyses", {}).setdefault(analysis, {})
    batch = profile.setdefault("batch", {})
    monkeypatch.setitem(batch, "global_tracking_excel_path", value)


def test_master_workbooks_are_disabled_by_default():
    from config import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["analyses"]["clonality"]["batch"]["global_tracking_excel_path"] == ""
    assert DEFAULT_SETTINGS["analyses"]["flt3"]["batch"]["global_tracking_excel_path"] == ""


def test_clonality_master_path_is_configurable_and_optional(tmp_path, monkeypatch):
    from core.analyses.clonality import tracking_excel

    _set_master_path(monkeypatch, "clonality", "")
    assert tracking_excel.resolve_global_clonality_tracking_path() is None

    selected = tmp_path / "Clonality_Master.xlsx"
    _set_master_path(monkeypatch, "clonality", str(selected))
    assert tracking_excel.resolve_global_clonality_tracking_path() == selected


def test_flt3_master_path_is_configurable_and_optional(tmp_path, monkeypatch):
    from core.analyses.flt3 import qc_tracker

    _set_master_path(monkeypatch, "flt3", "")
    assert qc_tracker.resolve_global_flt3_tracking_path() is None

    selected = tmp_path / "FLT3_Master.xlsx"
    _set_master_path(monkeypatch, "flt3", str(selected))
    assert qc_tracker.resolve_global_flt3_tracking_path() == selected


def test_unavailable_optional_master_does_not_fail_patient_run(tmp_path, monkeypatch):
    from core.analyses.clonality import tracking_excel
    from core.analyses.flt3 import qc_tracker

    clonality_path = tmp_path / "unavailable" / "Clonality.xlsx"
    flt3_path = tmp_path / "unavailable" / "FLT3.xlsx"
    _set_master_path(monkeypatch, "clonality", str(clonality_path))
    _set_master_path(monkeypatch, "flt3", str(flt3_path))

    def denied(*_args, **_kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(tracking_excel, "update_clonality_tracking_workbook", denied)
    monkeypatch.setattr(qc_tracker, "update_flt3_npm1_qc_tracker_workbook", denied)

    assert tracking_excel.update_global_clonality_tracking_workbook([{}]) is None
    assert qc_tracker.update_global_flt3_tracking_workbook([{}]) is None

