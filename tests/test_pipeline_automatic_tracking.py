"""Both patient and control completion create the owning analysis's workbook."""
import pytest
from openpyxl import load_workbook


@pytest.mark.parametrize("analysis", ["clonality", "flt3"])
@pytest.mark.parametrize("mode", ["all", "controls"])
def test_pipeline_publishes_automatic_tracking_with_snapshot(monkeypatch, tmp_path, analysis, mode):
    from core.pipeline import run_pipeline
    from core.run_context import RunContext
    from config import APP_SETTINGS, resolve_analysis_excel_output_path

    context = RunContext.create(analysis_id=analysis, settings={
        "general": {"author": "Queued operator"},
        "analyses": {analysis: {"batch": {"output_base": str(tmp_path / "shared")}}},
    })
    if analysis == "clonality":
        from core.analyses.clonality import pipeline
        from test_clonality_tracking_output import _entry
        specimen = "PK" if mode == "controls" else "26OUM00001"
        entry = _entry(f"{specimen}_FR1__260526_A01_TEST.fsa", dit=specimen if mode == "all" else "")
        monkeypatch.setattr(pipeline, "_analyze_files", lambda *args, **kwargs: ([entry], 0))
    else:
        from core.analyses.flt3.pipeline import _legacy as pipeline
        from test_flt3_tracking_output import _entry
        specimen = "IVS-P001" if mode == "controls" else "26OUM00001"
        entry = _entry(f"{specimen}_ITD__260526_A01_TEST.fsa", specimen_id=specimen)
        monkeypatch.setattr(pipeline, "_should_use_multiprocessing", lambda: False)
        monkeypatch.setattr(pipeline, "classify_fsa", lambda path: {"selection_key": "test"})
        monkeypatch.setattr(pipeline, "_select_best_entry", lambda files: entry)
    monkeypatch.setattr(pipeline, "_scan_files", lambda *args, **kwargs: [tmp_path / entry["file_name"]])
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "general")
    path = resolve_analysis_excel_output_path(analysis, tmp_path, "ignored.xlsx", context.settings_snapshot)
    for _ in range(2):
        assert run_pipeline(
            tmp_path, tmp_path / "run-output", return_entries=True,
            make_dit_reports=False, mode=mode, run_context=context,
        ) == [entry]
    assert list((tmp_path / "shared" / "Tracking").glob("*.xlsx")) == [path]
    book = load_workbook(path)
    headers = {c.value: c.column for c in book["Runs"][1]}
    assert book["Runs"].max_row == 2
    assert book["Runs"].cell(2, headers["Operator"]).value == "Queued operator"
    assert book["Runs"].cell(2, headers["SampleKind"]).value == ("control" if mode == "controls" else "patient")
    assert book["Dashboard"]["A6" if analysis == "flt3" else "A5"].data_type == "f"
    book.close()
