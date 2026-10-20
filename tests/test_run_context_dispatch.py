"""Explicit run contexts keep dispatch independent of mutable global settings."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from config import APP_SETTINGS
from core.run_context import RunContext


def _context(analysis_id: str) -> RunContext:
    return RunContext.create(
        analysis_id=analysis_id,
        settings={"active_analysis": analysis_id, "marker": analysis_id},
    )


def test_explicit_registry_lookup_never_falls_back_to_clonality(monkeypatch):
    from core.analyses import registry

    paths = []

    def import_module(path):
        paths.append(path)
        if path == "core.analyses.unknown.pipeline":
            raise ModuleNotFoundError("missing", name=path)
        return SimpleNamespace(name=path)

    monkeypatch.setattr(registry.importlib, "import_module", import_module)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")

    with pytest.raises(ModuleNotFoundError):
        registry.get_analysis_module("pipeline", analysis_id="unknown")
    assert paths == ["core.analyses.unknown.pipeline"]


def test_parallel_contexts_dispatch_despite_global_mutation(monkeypatch, tmp_path):
    from core import pipeline

    contexts = [_context("clonality"), _context("general")]
    barrier = Barrier(2)
    seen = []

    def module_for(submodule, *, analysis_id=None):
        assert submodule == "pipeline"

        def run_pipeline(**kwargs):
            barrier.wait(timeout=5)
            seen.append((analysis_id, APP_SETTINGS["active_analysis"]))
            return [analysis_id]

        return SimpleNamespace(run_pipeline=run_pipeline)

    monkeypatch.setattr(pipeline, "get_analysis_module", module_for)
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "flt3")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(pipeline.run_pipeline, tmp_path, run_context=context)
            for context in contexts
        ]
        assert [future.result(timeout=5) for future in futures] == [
            ["clonality"], ["general"]
        ]

    assert {analysis for analysis, _ in seen} == {"clonality", "general"}
    assert {global_analysis for _, global_analysis in seen} == {"flt3"}


@pytest.mark.parametrize("analysis_id", ["general", "clonality"])
def test_pipeline_forwards_context_to_context_aware_analysis(monkeypatch, tmp_path, analysis_id):
    from core import pipeline

    received = []

    def analysis_pipeline(*, fsa_dir, base_outdir, assay_folder_name,
                        return_entries, make_dit_reports, mode,
                        tracking_excel_path, update_tracking_workbook,
                        progress_callback, run_context):
        received.append((fsa_dir, run_context))
        return []

    monkeypatch.setattr(
        pipeline, "get_analysis_module",
        lambda submodule, *, analysis_id=None: SimpleNamespace(run_pipeline=analysis_pipeline),
    )
    context = _context(analysis_id)
    assert pipeline.run_pipeline(tmp_path, run_context=context) == []
    assert received == [(tmp_path, context)]


@pytest.mark.parametrize("collect", [False, True])
def test_runner_forwards_context_to_pipeline(monkeypatch, tmp_path, collect):
    from core import pipeline, runner

    context = _context("general")
    seen = []

    def fake_pipeline(**kwargs):
        seen.append(kwargs)
        return []

    monkeypatch.setattr(pipeline, "run_pipeline", fake_pipeline)
    if collect:
        from core import batch
        monkeypatch.setattr(batch, "_scan_folder_fsa_files", lambda *_: [tmp_path / "x.fsa"])
        runner.run_pipeline_job_collect(
            tmp_path, tmp_path, "out", "all", "", run_context=context,
        )
    else:
        runner.run_pipeline_job(
            tmp_path, tmp_path, "out", "all", "", run_context=context,
        )
    assert seen[0]["run_context"] is context


def test_general_runner_branch_uses_context_analysis(monkeypatch, tmp_path):
    from core import pipeline, runner

    context = _context("general")
    source = tmp_path / "x.fsa"
    source.write_bytes(b"synthetic")
    seen = []
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    monkeypatch.setattr(runner, "stage_files", lambda files: tmp_path)
    monkeypatch.setattr(runner, "cleanup_temp", lambda path: None)
    monkeypatch.setattr(pipeline, "run_pipeline", lambda **kwargs: seen.append(kwargs))

    runner.run_pipeline_job(
        tmp_path, tmp_path, "out", "all", "", files=[source],
        run_context=context,
    )

    assert seen[0]["run_context"] is context
    assert seen[0].get("return_entries") is None


def test_runner_legacy_call_does_not_add_context_keyword(monkeypatch, tmp_path):
    from core import pipeline, runner

    seen = []
    monkeypatch.setattr(pipeline, "run_pipeline", lambda **kwargs: seen.append(kwargs))
    runner.run_pipeline_job(tmp_path, tmp_path, "out", "all", "")
    assert "run_context" not in seen[0]


def test_dit_job_forwards_context(monkeypatch, tmp_path):
    from core import pipeline, runner

    context = _context("general")
    seen = []
    monkeypatch.setattr(pipeline, "run_pipeline", lambda **kwargs: seen.append(kwargs))
    runner.run_dit_job(tmp_path, tmp_path, "out", "all", "", run_context=context)
    assert seen[0]["run_context"] is context


def test_qc_job_forwards_context(monkeypatch, tmp_path):
    from core import pipeline, runner

    context = _context("clonality")
    seen = []
    monkeypatch.setattr(
        pipeline, "run_pipeline", lambda **kwargs: seen.append(kwargs) or [{"file_name": "x.fsa"}],
    )
    runner.run_qc_job(
        tmp_path, tmp_path, "qc.html", "trends.xlsx", rules=None,
        skip_html_reports=True, update_qc_trends=False, run_context=context,
    )
    assert seen[0]["run_context"] is context
