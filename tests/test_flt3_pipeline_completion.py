"""Exercise the FLT3 completion path used by both patient and QC jobs."""
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("mode", ["all", "controls"])
def test_flt3_pipeline_completes_after_selection(monkeypatch, tmp_path, mode):
    from core.analyses.flt3.pipeline import _legacy as pipeline

    entry = {"file_name": "synthetic.fsa", "ladder_qc_status": "ok"}
    monkeypatch.setattr(pipeline, "_scan_files", lambda *a, **kw: [tmp_path / "synthetic.fsa"])
    monkeypatch.setattr(pipeline, "_should_use_multiprocessing", lambda: False)
    monkeypatch.setattr(pipeline, "classify_fsa", lambda p: {"selection_key": "synthetic"})
    monkeypatch.setattr(pipeline, "_select_best_entry", lambda candidates: entry)
    monkeypatch.setattr(pipeline, "_calculate_ratios", lambda entries: None)
    writer = Mock()
    monkeypatch.setattr(pipeline, "update_flt3_npm1_qc_tracker_workbook", writer)

    assert pipeline.run_pipeline(
        tmp_path, tmp_path / "output", return_entries=True,
        make_dit_reports=False, mode=mode,
    ) == [entry]
    assert writer.call_args.args[1] == [entry]


def test_flt3_completion_uses_captured_settings(monkeypatch, tmp_path):
    from config import APP_SETTINGS
    from core.analyses.flt3.pipeline import _legacy as pipeline
    from core.run_context import RunContext

    selected = tmp_path / "captured.xlsx"
    context = RunContext.create(analysis_id="flt3", settings={
        "general": {"author": "Captured operator"},
        "engine": {"export_diagnostic_csv": True},
        "analyses": {"flt3": {"batch": {"tracking_excel_path": str(selected)}}},
    })
    monkeypatch.setitem(APP_SETTINGS, "engine", {"export_diagnostic_csv": False})
    entry = {"file_name": "synthetic.fsa", "ladder_qc_status": "ok"}
    monkeypatch.setattr(pipeline, "_scan_files", lambda *a, **kw: [tmp_path / "synthetic.fsa"])
    monkeypatch.setattr(pipeline, "_should_use_multiprocessing", lambda: False)
    monkeypatch.setattr(pipeline, "classify_fsa", lambda p: {"selection_key": "synthetic"})
    monkeypatch.setattr(pipeline, "_select_best_entry", lambda candidates: entry)
    monkeypatch.setattr(pipeline, "_calculate_ratios", lambda entries: None)
    writer = Mock()
    export = Mock()
    monkeypatch.setattr(pipeline, "update_flt3_npm1_qc_tracker_workbook", writer)
    monkeypatch.setattr(pipeline, "generate_flt3_peak_report", export)
    monkeypatch.setattr(pipeline, "generate_flt3_bp_validation_report", Mock())
    pipeline.run_pipeline(tmp_path, make_dit_reports=False, run_context=context)
    assert writer.call_args.args[0] == selected
    assert entry["operator"] == "Captured operator"
    export.assert_called_once()
