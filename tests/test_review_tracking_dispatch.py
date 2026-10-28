"""Review finalization writes the owning assay's captured tracking outputs."""
from pathlib import Path

import pytest

from config import APP_SETTINGS
from core.run_context import RunContext


@pytest.mark.parametrize("analysis_id", ["clonality", "flt3"])
def test_review_finalize_updates_only_owning_assay_tracking(tmp_path, monkeypatch, analysis_id):
    from core import html_reports
    from core.analyses.clonality import tracking_excel
    from core.analyses.flt3 import qc_tracker
    from gui_qt.tabs.tab_batch import TabBatch

    patient = {"original_file_path": str(tmp_path / "patient.fsa")}
    local_path = tmp_path / "captured_local.xlsx"
    master_path = tmp_path / "captured_master.xlsx"
    context = RunContext.create(analysis_id=analysis_id, settings={
        "active_analysis": analysis_id,
        "analyses": {analysis_id: {"batch": {
            "global_tracking_excel_path": str(master_path), "tracking_excel_path": str(local_path),
        }}},
    })
    # An unrelated current profile must not redirect the queued master write.
    monkeypatch.setitem(APP_SETTINGS, "analyses", {
        "clonality": {"batch": {"global_tracking_excel_path": str(tmp_path / "wrong_clonality.xlsx")}},
        "flt3": {"batch": {"global_tracking_excel_path": str(tmp_path / "wrong_flt3.xlsx")}},
    })
    writes = []

    def record(assay):
        def update(path, entries, **kwargs):
            writes.append((assay, Path(path), entries, kwargs))
        return update

    monkeypatch.setattr(tracking_excel, "update_clonality_tracking_workbook", record("clonality"))
    monkeypatch.setattr(qc_tracker, "update_flt3_npm1_qc_tracker_workbook", record("flt3"))
    monkeypatch.setattr(html_reports, "build_dit_html_reports", lambda *_: None)
    payload = TabBatch._review_finalize_worker(
        jobs_to_run=[], corrected_paths=[], session_entries=[patient], resolved_review_rows={},
        output_root=tmp_path, analysis_id=analysis_id, pipeline_scope="all", assay_filter="",
        aggregate_dit_reports=True, aggregate_outdir_name="reports", run_context=context,
    )

    assert payload["final_reports_built"] is True
    assert [(assay, path) for assay, path, _entries, _kwargs in writes] == [
        (analysis_id, local_path),
    ]
    assert all(entries == [patient] for _assay, _path, entries, _kwargs in writes)
    if analysis_id == "clonality":
        assert all(kwargs["settings"] is context.settings_snapshot for *_rest, kwargs in writes)
