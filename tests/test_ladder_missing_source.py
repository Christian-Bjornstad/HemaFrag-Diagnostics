"""Anonymous CSV rows must not trap an operator in the review gate."""
import csv
import json
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QMessageBox

from core.analyses.clonality.ladder_review_gate import (
    collect_ladder_review_cases,
    count_unresolved_review_cases,
)
from gui_qt.tabs.tab_archive_runner import TabArchiveRunner
from gui_qt.tabs.tab_batch import TabBatch
from gui_qt.tabs.tab_ladder import TabLadder, _io
from gui_qt.tabs.tab_ladder._summary import chip_state


def write_cases(bundle, rows):
    path = bundle / "ladder_review_cases.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["full_path", "file", "ladder_qc_status", "label"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_empty_csv_record_is_not_a_file_or_a_blocker(tmp_path):
    path = write_cases(tmp_path, [
        {"full_path": str(tmp_path / "real.fsa"), "file": "real.fsa", "label": "reviewed_no_change"},
        {"file": "  "},
    ])
    assert count_unresolved_review_cases(path) == 0
    result = _io.load_review_bundle_worker(tmp_path)
    assert len(result["rows"]) == 1
    assert "__missing_review" not in path.read_text()
    assert TabBatch._review_bundle_resolution_counts(tmp_path) == (1, 0)
    assert TabArchiveRunner._unresolved_review_count(tmp_path) == 0


def test_anonymous_review_evidence_is_retained_and_explicitly_excludable(tmp_path):
    path = write_cases(tmp_path, [{"ladder_qc_status": "review_required"}])
    result = _io.load_review_bundle_worker(tmp_path)
    source = tmp_path / "__missing_review_path_row_2__.fsa"
    assert result["rows"][0]["full_path"] == str(source)
    assert count_unresolved_review_cases(path) == 1
    annotation = _io.save_missing_source_exclusion_worker(
        tmp_path, source, note="Source could not be identified by operator", reviewed_at_utc="2026-10-13T12:00:00Z",
    )
    assert annotation["label"] == "excluded_missing_source"
    assert count_unresolved_review_cases(path) == 0
    assert json.loads((tmp_path / "ladder_review_annotations.json").read_text())[str(source)] == annotation
    reloaded = _io.load_review_bundle_worker(tmp_path)
    tab = SimpleNamespace(_review_bundle_cases=reloaded["rows"])
    assert TabLadder._resolved_review_bundle_files(tab) == ([], [], 0)


def test_missing_source_exclusion_rejects_existing_file(tmp_path):
    source = tmp_path / "real.fsa"
    source.write_bytes(b"fsa")
    path = write_cases(tmp_path, [{"full_path": str(source), "file": source.name}])
    before = path.read_bytes()
    with pytest.raises(ValueError, match="exists"):
        _io.save_missing_source_exclusion_worker(tmp_path, source, note="missing", reviewed_at_utc="now")
    assert path.read_bytes() == before


def test_gate_does_not_generate_anonymous_review_cases():
    with pytest.raises(ValueError, match="source identity"):
        collect_ladder_review_cases([{"ladder_review_required": True}])


def test_missing_source_action_is_available_without_metadata(qapp, tmp_path, monkeypatch):
    tab = TabLadder()
    source = tmp_path / "__missing_review_path_row_3__.fsa"
    tab._review_bundle_dir = tmp_path
    tab._review_case_by_path[source] = {"full_path": str(source), "label": ""}
    monkeypatch.setattr(tab, "_refresh_current_metadata", lambda: None)
    monkeypatch.setattr(tab, "_refresh_report_matches", lambda: None)
    tab._update_current_file(source)
    assert tab.btn_exclude_missing_ladder.isEnabled()
    assert tab.btn_exclude_missing_ladder.text() == "Exclude Missing File"
    tab.close()


def test_old_placeholder_can_be_excluded_from_ui_without_blocking_real_files(qapp, tmp_path, monkeypatch):
    tab = TabLadder()
    source = tmp_path / "__missing_review_path_row_3__.fsa"
    real = tmp_path / "reviewed.fsa"
    real.write_bytes(b"fsa")
    path = write_cases(tmp_path, [
        {"full_path": str(real), "file": real.name, "label": "reviewed_no_change"},
        {"full_path": str(source), "file": "Unknown file (CSV row 3)"},
    ])
    result = _io.load_review_bundle_worker(tmp_path)
    monkeypatch.setattr(tab, "_refresh_current_metadata", lambda: None)
    monkeypatch.setattr(tab, "_refresh_report_matches", lambda: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    workers = []
    monkeypatch.setattr(tab, "_start_registered_worker", lambda worker, **kw: workers.append(worker))
    tab._on_review_bundle_result(tab._scan_request_id, result)
    tab._select_file(source)
    assert tab._review_bundle_counts() == (1, 1)
    tab.btn_exclude_missing_ladder.click()
    assert len(workers) == 1
    workers[0].run()
    assert tab._review_bundle_counts() == (2, 0)
    assert tab._resolved_review_bundle_files() == ([real], [], 0)
    assert count_unresolved_review_cases(path) == 0
    assert "source file unavailable" in tab.status_lbl.text()
    assert chip_state(tab._review_case_by_path[source]) == "reviewed"
    tab.close()
