from __future__ import annotations

import json

from config import APP_SETTINGS
from core.batch import generate_jobs, run_batch_jobs
from core.run_context import RunContext


def _run_empty_batch(tmp_path, *, context):
    return run_batch_jobs(
        jobs=[],
        output_base=tmp_path / context.run_id,
        out_folder_tmpl="reports_{name}",
        outfile_html_tmpl="qc_{name}.html",
        excel_name_tmpl="qc.xlsx",
        pipeline_scope="all",
        assay_filter="",
        aggregate_dit_reports=True,
        continue_on_error=True,
        run_context=context,
    )


def test_two_contexts_keep_distinct_analysis_qc_and_manifest_provenance(tmp_path, monkeypatch):
    import core.qc.qc_rules as qc_rules_module

    captured_rules = []
    original_rules = qc_rules_module.QCRules

    def capture_rules(**kwargs):
        captured_rules.append(kwargs)
        return original_rules(**kwargs)

    monkeypatch.setattr(qc_rules_module, "QCRules", capture_rules)
    first = RunContext.create(
        analysis_id="clonality",
        settings={"qc": {"min_r2_ok": 0.91}},
        run_id="batch-context-one",
        created_at_utc="2026-09-23T10:00:00+00:00",
    )
    second = RunContext.create(
        analysis_id="general",
        settings={"qc": {"min_r2_ok": 0.97}},
        run_id="batch-context-two",
        parent_run_id=first.run_id,
        created_at_utc="2026-09-23T11:00:00+00:00",
    )
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "flt3")
    monkeypatch.setitem(APP_SETTINGS, "qc", {"min_r2_ok": 0.5})

    first_result = _run_empty_batch(tmp_path, context=first)
    second_result = _run_empty_batch(tmp_path, context=second)

    first_manifest = json.loads(first_result["run_manifest_path"].read_text())
    second_manifest = json.loads(second_result["run_manifest_path"].read_text())
    assert [rules["min_r2_ok"] for rules in captured_rules] == [0.91, 0.97]
    assert first_manifest["analysis"] == "clonality"
    assert second_manifest["analysis"] == "general"
    assert first_manifest["run_id"] == first.run_id
    assert second_manifest["run_id"] == second.run_id
    assert second_manifest["parent_run_id"] == first.run_id
    assert second_manifest["created_at_utc"] == second.created_at_utc
    assert first_manifest["settings_fingerprint"] == first.settings_fingerprint
    assert second_manifest["settings_fingerprint"] == second.settings_fingerprint
    assert first_manifest["execution"]["aggregate_dit_reports"] is True
    assert second_manifest["execution"]["aggregate_dit_reports"] is False


def test_explicit_empty_context_settings_do_not_fall_back_to_globals(tmp_path, monkeypatch):
    trace = tmp_path / "alias.fsa"
    trace.write_bytes(b"synthetic")
    context = RunContext.create(
        analysis_id="general",
        settings={},
        run_id="empty-settings-context",
    )
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")

    jobs = generate_jobs([trace], run_context=context)
    result = _run_empty_batch(tmp_path, context=context)
    manifest = json.loads(result["run_manifest_path"].read_text())

    assert len(jobs) == 1
    assert jobs[0]["name"] == "GENERAL"
    assert manifest["analysis"] == "general"
    assert manifest["settings_fingerprint"] == context.settings_fingerprint


def test_context_reaches_pipeline_runner_without_changing_legacy_calls(tmp_path, monkeypatch):
    import core.batch as batch

    calls = []
    monkeypatch.setattr(batch, "run_pipeline_job", lambda **kwargs: calls.append(kwargs))
    job = {"name": "sample", "type": "pipeline", "path": None, "files": []}
    context = RunContext.create(analysis_id="general", settings={})
    common = dict(
        jobs=[job],
        output_base=tmp_path,
        out_folder_tmpl="reports_{name}",
        outfile_html_tmpl="qc_{name}.html",
        excel_name_tmpl="qc.xlsx",
        pipeline_scope="all",
        assay_filter="",
        aggregate_dit_reports=False,
        continue_on_error=False,
    )

    run_batch_jobs(**common, run_context=context)
    run_batch_jobs(**common)

    assert calls[0]["run_context"] is context
    assert "run_context" not in calls[1]


def test_context_selects_clonality_tracking_path_without_global_settings(tmp_path, monkeypatch):
    import core.batch as batch
    import core.analyses.clonality.tracking_excel as tracking_excel

    selected = tmp_path / "snapshot-tracking.xlsx"
    snapshot_global = tmp_path / "snapshot-master.xlsx"
    global_path = tmp_path / "global-tracking.xlsx"
    context = RunContext.create(
        analysis_id="clonality",
        settings={
            "qc": {"sample_peak_window_bp": 9.0},
            "analyses": {
                "clonality": {
                    "batch": {
                        "tracking_excel_path": str(selected),
                        "global_tracking_excel_path": str(snapshot_global),
                        "ladder_review_gate": {"enabled": False},
                    }
                }
            }
        },
    )
    monkeypatch.setitem(
        APP_SETTINGS["analyses"]["clonality"]["batch"],
        "tracking_excel_path",
        str(global_path),
    )
    monkeypatch.setitem(
        APP_SETTINGS["analyses"]["clonality"]["batch"],
        "global_tracking_excel_path",
        str(global_path),
    )
    monkeypatch.setattr(batch, "run_qc_job", lambda **_kwargs: (None, [{"File": "qc.fsa"}]))
    paths = []
    monkeypatch.setattr(
        tracking_excel,
        "update_clonality_tracking_workbook",
        lambda path, _entries, *, settings=None: paths.append((path, settings)),
    )

    run_batch_jobs(
        jobs=[{"name": "QC", "type": "qc", "path": None, "files": []}],
        output_base=tmp_path / "output",
        out_folder_tmpl="reports_{name}",
        outfile_html_tmpl="qc_{name}.html",
        excel_name_tmpl="qc.xlsx",
        pipeline_scope="all",
        assay_filter="",
        aggregate_dit_reports=True,
        continue_on_error=False,
        run_context=context,
    )

    assert paths == [
        (selected, context.settings_snapshot),
        (snapshot_global, context.settings_snapshot),
    ]
