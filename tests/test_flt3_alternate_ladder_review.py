from __future__ import annotations

from pathlib import Path

from core.analyses.clonality.ladder_review_gate import collect_ladder_review_cases
from core.analyses.flt3.pipeline import _legacy as flt3


def _candidate(path: Path, *, review: bool) -> dict:
    return {
        "original_file_path": str(path),
        "file_name": path.name,
        "source_run_dir": path.parent.name,
        "assay": "FLT3-ITD",
        "ladder": "GS500ROX",
        "ladder_qc_status": "review_required" if review else "ok",
        "ladder_review_required": review,
        "ladder_review_reason": "GS500ROX anchors mostly outside expected time window" if review else "",
        "ladder_review_reason_codes": ["rust_ladder_fit_rejected"] if review else [],
        "ladder_review_summary": "Unsafe fit" if review else "",
        "ladder_fit_strategy": "rust_rejected_review" if review else "auto_full",
        "ladder_expected_step_count": 16,
        "ladder_fitted_step_count": 0 if review else 16,
        "peak_qc_pass": not review,
        "selected_injection": "10s",
        "injection_time": 10,
        "fsa": type("Fsa", (), {"file_name": path.name})(),
    }


def test_rejected_alternate_is_reviewed_even_when_good_candidate_selected(monkeypatch, tmp_path):
    rejected = tmp_path / "00001_12345678_26OUM00000_ITD_A05.fsa"
    good = tmp_path / "00002_12345678_26OUM00000_ITD_B05.fsa"
    by_path = {rejected: _candidate(rejected, review=True), good: _candidate(good, review=False)}
    monkeypatch.setattr(flt3, "_build_entry_from_candidate", lambda path, _meta: by_path[path])
    monkeypatch.setattr(flt3, "_preferred_injection_time", lambda _meta: 10)
    monkeypatch.setattr(flt3, "_candidate_sort_key", lambda item, _preferred: str(item[0]))
    monkeypatch.setattr(flt3, "_entry_ranking_key", lambda entry, _preferred: entry["file_name"])
    monkeypatch.setattr(flt3, "_fallback_entry_ranking_key", lambda entry, _preferred: entry["file_name"])

    selected = flt3._select_best_entry([(rejected, {"injection_time": 10}), (good, {"injection_time": 10})])

    assert selected is by_path[good]
    assert [row["full_path"] for row in collect_ladder_review_cases([selected])] == [str(rejected)]


def test_review_case_deduplicates_selected_candidate(monkeypatch, tmp_path):
    rejected = tmp_path / "00001_12345678_26OUM00000_ITD_A05.fsa"
    other = tmp_path / "00002_12345678_26OUM00000_ITD_B05.fsa"
    by_path = {rejected: _candidate(rejected, review=True), other: _candidate(other, review=True)}
    monkeypatch.setattr(flt3, "_build_entry_from_candidate", lambda path, _meta: by_path[path])
    monkeypatch.setattr(flt3, "_preferred_injection_time", lambda _meta: 10)
    monkeypatch.setattr(flt3, "_candidate_sort_key", lambda item, _preferred: str(item[0]))
    monkeypatch.setattr(flt3, "_fallback_entry_ranking_key", lambda entry, _preferred: entry["file_name"])

    selected = flt3._select_best_entry([(rejected, {"injection_time": 10}), (other, {"injection_time": 10})])

    paths = [row["full_path"] for row in collect_ladder_review_cases([selected])]
    assert paths == [str(rejected), str(other)]
    assert len(paths) == len(set(paths))


def test_rejected_nonpreferred_injection_is_reviewed_without_changing_selected_result(monkeypatch, tmp_path):
    good = tmp_path / "00001_12345678_26OUM00000_ITD_10s.fsa"
    rejected = tmp_path / "00002_12345678_26OUM00000_ITD_25s.fsa"
    healthy = tmp_path / "00003_12345678_26OUM00000_ITD_30s.fsa"
    by_path = {
        good: _candidate(good, review=False),
        rejected: _candidate(rejected, review=True),
        healthy: _candidate(healthy, review=False),
    }
    monkeypatch.setattr(flt3, "_build_entry_from_candidate", lambda path, _meta: by_path[path])
    monkeypatch.setattr(flt3, "_preferred_injection_time", lambda _meta: 10)
    monkeypatch.setattr(flt3, "_candidate_sort_key", lambda item, _preferred: str(item[0]))
    monkeypatch.setattr(flt3, "_entry_ranking_key", lambda entry, _preferred: entry["file_name"])

    selected = flt3._select_best_entry(
        [(good, {"injection_time": 10}), (rejected, {"injection_time": 25}), (healthy, {"injection_time": 30})]
    )

    assert selected is by_path[good]
    assert [row["full_path"] for row in collect_ladder_review_cases([selected])] == [str(rejected)]


def test_rejected_nonpreferred_injection_remains_visible_if_preferred_fails(
    monkeypatch, tmp_path
):
    failed = tmp_path / "00001_12345678_26OUM00000_ITD_10s.fsa"
    rejected = tmp_path / "00002_12345678_26OUM00000_ITD_25s.fsa"
    review_entry = _candidate(rejected, review=True)
    monkeypatch.setattr(
        flt3,
        "_build_entry_from_candidate",
        lambda path, _meta: None if path == failed else review_entry,
    )
    monkeypatch.setattr(flt3, "_preferred_injection_time", lambda _meta: 10)
    monkeypatch.setattr(flt3, "_candidate_sort_key", lambda item, _preferred: str(item[0]))
    monkeypatch.setattr(flt3, "_fallback_entry_ranking_key", lambda entry, _preferred: entry["file_name"])

    selected = flt3._select_best_entry(
        [(failed, {"injection_time": 10}), (rejected, {"injection_time": 25})]
    )

    assert selected is review_entry
    assert [row["full_path"] for row in collect_ladder_review_cases([selected])] == [str(rejected)]
