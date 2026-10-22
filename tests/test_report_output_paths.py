import pytest

from core.analyses.shared_pipeline import normalize_pipeline_paths


@pytest.mark.parametrize("folder", [None, "", "REPORTS", "ASSAY_REPORTS", " reports "])
def test_retired_report_folders_use_selected_output_root(tmp_path, folder):
    source = tmp_path / "input"
    output = tmp_path / "output"
    assert normalize_pipeline_paths(source, output, folder) == (source, output)


def test_custom_report_folder_is_preserved(tmp_path):
    assert normalize_pipeline_paths(tmp_path, tmp_path, "custom")[1] == tmp_path / "custom"


def test_chunked_runner_does_not_recreate_assay_reports(tmp_path, monkeypatch):
    from core import runner
    from unittest.mock import Mock

    source = tmp_path / "source"
    source.mkdir()
    files = [source / f"sample{i}.fsa" for i in range(2)]
    for path in files:
        path.write_bytes(b"fsa")
    monkeypatch.setattr(runner, "CHUNK_SIZE", 1)
    monkeypatch.setattr(runner, "_should_stage_explicit_files_once", lambda *a, **k: False)
    monkeypatch.setattr("core.pipeline.run_pipeline", lambda **k: [{"file_name": "sample.fsa"}])
    reports = Mock()
    monkeypatch.setattr("core.html_reports.build_dit_html_reports", reports)
    output = tmp_path / "output"
    runner.run_pipeline_job(source, output, "ASSAY_REPORTS", "all", "", files=files)
    assert reports.call_args.args[1] == output


def test_exact_folder_runner_publishes_dit_report(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from core import runner
    from core.analyses.clonality import pipeline
    from core.run_context import RunContext

    source = tmp_path / "source"
    source.mkdir()
    trace = source / "sample.fsa"
    trace.write_bytes(b"synthetic")
    output = tmp_path / "output"
    entry = {"file_name": trace.name}
    monkeypatch.setattr(pipeline, "_analyze_files", lambda *_args, **_kwargs: ([entry], 0))
    reports = Mock()
    monkeypatch.setattr("core.analyses.shared_pipeline.build_dit_html_reports", reports)

    runner.run_pipeline_job(
        source, output, "ASSAY_REPORTS", "all", "", files=[trace],
        update_tracking_workbook=False,
        run_context=RunContext.create(analysis_id="clonality", settings={}),
    )

    reports.assert_called_once_with([entry], output)


def test_unchunked_explicit_subset_excludes_unselected_source_files(tmp_path, monkeypatch):
    from core import runner

    source = tmp_path / "source"
    source.mkdir()
    selected = source / "selected.fsa"
    unselected = source / "unselected.fsa"
    for trace in (selected, unselected):
        trace.write_bytes(b"synthetic")
    seen = []

    def analyze(**kwargs):
        seen.extend(path.resolve() for path in kwargs["fsa_dir"].glob("*.fsa"))
        return []

    monkeypatch.setattr("core.pipeline.run_pipeline", analyze)
    runner.run_pipeline_job_collect(
        source, tmp_path / "output", "ASSAY_REPORTS", "all", "",
        files=[selected], chunk_files=False,
    )

    # Copies are the fallback when Windows does not permit creating symlinks.
    assert len(seen) == 1
    assert seen[0].name.endswith(selected.name)
