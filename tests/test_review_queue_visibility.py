"""Every file counted by the review gate must remain accessible to the operator."""
import csv
from types import SimpleNamespace
from pathlib import Path

from core.batch import find_all_fsa_files, KNOWN_CLONALITY_BACKFILL_SKIP_FILES
from core.analyses.clonality.ladder_review_gate import (
    collect_ladder_review_cases,
    count_unresolved_review_cases,
    relocate_review_case,
)
from gui_qt.tabs.tab_ladder._io import load_review_bundle_worker, save_review_bundle_annotation_worker


def test_historical_hang_files_are_included_in_normal_scan(tmp_path):
    files = [tmp_path / name for name in KNOWN_CLONALITY_BACKFILL_SKIP_FILES]
    for path in files:
        path.write_bytes(b"fsa")
    assert set(find_all_fsa_files([tmp_path])) == set(files)


def test_review_entry_without_fsa_retains_filename():
    rows = collect_ladder_review_cases([
        {"file_name": "rejected.fsa", "ladder_qc_status": "missing_ladder"}
    ])
    assert rows[0]["full_path"] == "rejected.fsa"


def _write_cases(tmp_path, rows):
    path = tmp_path / "ladder_review_cases.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["full_path", "file", "label"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_legacy_blank_path_remains_visible_and_can_be_reviewed(tmp_path):
    path = _write_cases(tmp_path, [
        {"full_path": "", "file": "hidden.fsa", "label": ""},
        {"full_path": str(tmp_path / "visible.fsa"), "file": "visible.fsa", "label": ""},
    ])
    result = load_review_bundle_worker(tmp_path)
    assert len(result["rows"]) == 2
    hidden = result["rows"][0]
    assert hidden["_path_unreachable"] == "true"
    assert hidden["full_path"] in result["missing_paths"]
    source = tmp_path / "source" / "hidden.fsa"
    source.parent.mkdir()
    source.write_bytes(b"fsa")
    relocate_review_case(tmp_path, Path(hidden["full_path"]), source)
    reloaded = load_review_bundle_worker(tmp_path)
    assert reloaded["rows"][0]["_path_unreachable"] == "false"
    save_review_bundle_annotation_worker(tmp_path, source, {"label": "reviewed_no_change"})
    with path.open(encoding="utf-8", newline="") as handle:
        persisted = list(csv.DictReader(handle))
    assert persisted[0]["label"] == "reviewed_no_change"
    assert count_unresolved_review_cases(path) == 1


def test_unidentifiable_row_does_not_block_valid_files(tmp_path):
    source = tmp_path / "valid.fsa"
    source.write_bytes(b"fsa")
    _write_cases(tmp_path, [
        {"full_path": "", "file": "", "label": ""},
        {"full_path": str(source), "file": source.name, "label": ""},
    ])
    result = load_review_bundle_worker(tmp_path)
    assert len(result["rows"]) == 2
    assert result["rows"][1]["full_path"] == str(source)
    assert result["rows"][1]["_path_unreachable"] == "false"
    assert result["rows"][0]["_path_unreachable"] == "true"
    assert "row 2" in " ".join(result["warnings"])


def test_repair_write_failure_does_not_block_valid_files(tmp_path, monkeypatch):
    source = tmp_path / "valid.fsa"
    source.write_bytes(b"fsa")
    cases = _write_cases(tmp_path, [
        {"full_path": "", "file": "hidden.fsa", "label": ""},
        {"full_path": str(source), "file": source.name, "label": ""},
    ])
    original = cases.read_bytes()
    def locked(*args, **kwargs):
        raise PermissionError("CSV is locked")
    monkeypatch.setattr("gui_qt.tabs.tab_ladder._io.save_review_bundle", locked)
    result = load_review_bundle_worker(tmp_path)
    assert len(result["rows"]) == 2
    assert result["rows"][1]["full_path"] == str(source)
    assert "CSV is locked" in " ".join(result["warnings"])
    assert cases.read_bytes() == original


def test_windows_bom_does_not_hide_original_path(tmp_path):
    source = tmp_path / "source" / "valid.fsa"
    source.parent.mkdir()
    source.write_bytes(b"fsa")
    cases = _write_cases(tmp_path, [{"full_path": str(source), "file": source.name, "label": ""}])
    cases.write_bytes(b"\xef\xbb\xbf" + cases.read_bytes())
    original = cases.read_bytes()
    result = load_review_bundle_worker(tmp_path)
    assert result["rows"][0]["full_path"] == str(source)
    assert result["rows"][0]["_path_unreachable"] == "false"
    assert cases.read_bytes() == original
    save_review_bundle_annotation_worker(tmp_path, source, {"label": "reviewed_no_change"})
    assert count_unresolved_review_cases(cases) == 0


def test_batch_keeps_file_identity_before_releasing_fsa(tmp_path, monkeypatch):
    from config import APP_SETTINGS
    import core.batch as batch
    import copy

    settings = copy.deepcopy(APP_SETTINGS)
    settings["active_analysis"] = "clonality"
    monkeypatch.setattr("config.APP_SETTINGS", settings)
    source = tmp_path / "26OUM00001_FR1.fsa"
    source.write_bytes(b"fsa")
    entry = {
        "fsa": SimpleNamespace(file=source, file_name=source.name),
        "ladder_qc_status": "review_required", "assay": "FR1", "dit": "26OUM00001",
    }
    monkeypatch.setattr(batch, "run_pipeline_job_collect", lambda **kwargs: [entry])
    result = batch.run_batch_jobs(
        jobs=[{"name": "sample", "type": "pipeline", "path": None, "files": [source]}],
        output_base=tmp_path / "output", out_folder_tmpl="",
        outfile_html_tmpl="qc.html", excel_name_tmpl="qc.xlsx",
        pipeline_scope="all", assay_filter="", aggregate_dit_reports=True,
        continue_on_error=False, defer_dit_html_reports=True,
        defer_tracking_workbook_refresh=True, preserve_deferred_entries=False,
    )
    assert entry["fsa"] is None
    rows = collect_ladder_review_cases(result["dit_report_entries"])
    assert rows[0]["full_path"] == str(source)
    assert rows[0]["file"] == source.name
