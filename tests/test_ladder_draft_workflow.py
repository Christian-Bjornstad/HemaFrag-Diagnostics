from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gui_qt.tabs.tab_ladder import TabLadder
from gui_qt.tabs.tab_ladder import _legacy as ladder_tab


class _DraftDialog:
    _preview_fsa = None

    def exec(self):
        return 1

    def get_review_payload(self):
        return {
            "action": "save_draft",
            "comment": "continue later",
            "after_qc": {},
            "partial_mapping": True,
            "partial_approved": False,
        }

    def get_adjustment_payload(self):
        return {
            "mapping": {0: 0, 2: 1},
            "mapping_times": {0: 100.0, 2: 300.0},
            "partial_mapping": True,
        }


def test_open_editor_persists_short_draft_without_approving_or_offering_rerun(
    monkeypatch,
):
    captured = {}
    statuses = []
    fsa = SimpleNamespace(file="sample.fsa", file_name="sample.fsa")
    tab = SimpleNamespace(
        _current_file=Path("sample.fsa"),
        _metadata_loading=False,
        _current_meta={},
        _current_fsa=fsa,
        _review_case_by_path={},
        _review_bundle_dir=None,
        _review_runtime_cache={},
        _resolve_cache_key=lambda path: Path(path),
        _refresh_current_metadata=lambda: None,
        _set_status=lambda text, error=False: statuses.append((text, error)),
        _is_run_tab_owned_review=lambda: False,
    )

    monkeypatch.setattr(ladder_tab, "_open_ladder_adjustment_dialog", lambda *args, **kwargs: _DraftDialog())

    def save(_fsa, _adjustment, **kwargs):
        captured.update(kwargs)
        return Path("ladder_adjustments.sqlite3")

    monkeypatch.setattr(ladder_tab, "save_ladder_adjustment", save)
    monkeypatch.setattr(ladder_tab, "load_ladder_adjustment", lambda _fsa: {"review": {"partial_approved": False}})

    TabLadder._open_ladder_editor(tab)

    assert captured["partial_approved"] is False
    assert statuses[-1] == (
        "Saved ladder draft for sample.fsa. Add at least 3 anchors before rerunning.",
        False,
    )


def test_review_bundle_keeps_short_draft_unresolved():
    saved_annotations = []
    unregistered = []
    current = Path("sample.fsa")
    review_case = {"full_path": str(current), "label": ""}
    run_tab = SimpleNamespace(
        unregister_ladder_review_update=lambda path: unregistered.append(path)
    )
    tab = SimpleNamespace(
        _review_bundle_dir=Path("review-bundle"),
        _current_file=current,
        _review_case_by_path={current: review_case},
        _review_bundle_cases=[review_case],
        _recent_reviewed_files={current},
        _resolve_cache_key=lambda path: Path(path),
        _save_review_bundle_annotation_worker=lambda bundle, path, annotation: saved_annotations.append(annotation),
        _sync_chip_strip=lambda: None,
        _run_tab_for_review=lambda: run_tab,
        _rebuild_file_list=lambda: None,
        _select_file=lambda path: None,
        _refresh_review_bundle_run_button=lambda: None,
    )

    TabLadder._save_review_bundle_annotation(
        tab,
        review_case,
        {
            "action": "save_draft",
            "comment": "continue later",
            "partial_mapping": True,
            "partial_approved": False,
            "adjustment_path": "ladder_adjustments.sqlite3",
        },
    )

    assert saved_annotations[0]["label"] == "manual_partial_draft"
    assert saved_annotations[0]["adjustment_path"] == "ladder_adjustments.sqlite3"
    assert tab._recent_reviewed_files == set()
    assert unregistered == [current]


def test_remove_adjustment_failure_keeps_review_and_cache(monkeypatch):
    statuses = []
    source = Path("sample.fsa")
    fsa = SimpleNamespace(file=source, ladder="LIZ", size_standard_channel="Orange")
    tab = SimpleNamespace(
        _current_file=source, _current_fsa=fsa, _metadata_loading=False,
        is_operation_active=lambda: False,
        _review_runtime_cache={source: {"old": True}},
        _review_case_by_path={source: {"label": "manual_adjusted"}},
        _resolve_cache_key=lambda path: Path(path),
        _set_status=lambda text, error=False: statuses.append((text, error)),
    )
    monkeypatch.setattr(ladder_tab, "load_ladder_adjustment", lambda _fsa: {"mapping": {0: 1}})
    monkeypatch.setattr(ladder_tab.QMessageBox, "question", lambda *args: ladder_tab.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ladder_tab.QMessageBox, "critical", lambda *args: None)
    monkeypatch.setattr(ladder_tab, "deactivate_ladder_adjustment", lambda _fsa: (_ for _ in ()).throw(OSError("locked")))

    TabLadder._remove_saved_adjustment(tab)

    assert statuses[-1][1] is True
    assert "locked" in statuses[-1][0]
    assert tab._review_runtime_cache[source] == {"old": True}
    assert tab._review_case_by_path[source]["label"] == "manual_adjusted"


def test_remove_adjustment_clears_cache_review_and_run_state(monkeypatch):
    statuses = []
    unregistered = []
    source = Path("sample.fsa")
    fsa = SimpleNamespace(file=source, ladder="LIZ", size_standard_channel="Orange")
    review_case = {
        "full_path": str(source), "label": "manual_adjusted",
        "label_note": "ok", "adjustment_path": "db", "rerun_status": "consumed",
    }
    tab = SimpleNamespace(
        _current_file=source, _current_fsa=fsa, _metadata_loading=False,
        is_operation_active=lambda: False,
        _review_runtime_cache={source: {"old": True}},
        _manual_rerun_consumption_by_path={source: {"consumed": True}},
        _recent_reviewed_files={source},
        _review_session_entries_by_path={source: {"old": True}},
        _review_case_by_path={source: review_case},
        _review_bundle_cases=[review_case], _review_bundle_dir=Path("bundle"),
        _resolve_cache_key=lambda path: Path(path),
        _save_review_bundle_annotation_worker=lambda *args: {},
        _run_tab_for_review=lambda: SimpleNamespace(
            unregister_ladder_review_update=lambda path: unregistered.append(path)
        ),
        _sync_chip_strip=lambda: None, _rebuild_file_list=lambda: None,
        _refresh_review_bundle_run_button=lambda: None,
        _refresh_current_metadata=lambda: None,
        _set_status=lambda text, error=False: statuses.append((text, error)),
    )
    monkeypatch.setattr(ladder_tab, "load_ladder_adjustment", lambda _fsa: {"mapping": {0: 1}})
    monkeypatch.setattr(ladder_tab.QMessageBox, "question", lambda *args: ladder_tab.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ladder_tab, "deactivate_ladder_adjustment", lambda _fsa: None)

    TabLadder._remove_saved_adjustment(tab)

    assert source not in tab._review_runtime_cache
    assert source not in tab._manual_rerun_consumption_by_path
    assert source not in tab._recent_reviewed_files
    assert source not in tab._review_session_entries_by_path
    assert review_case["label"] == review_case["adjustment_path"] == review_case["rerun_status"] == ""
    assert unregistered == [source]
    assert statuses[-1] == ("Removed saved ladder adjustment for sample.fsa.", False)


def test_annotation_failure_still_invalidates_run_state(monkeypatch):
    statuses = []
    unregistered = []
    source = Path("sample.fsa")
    fsa = SimpleNamespace(file=source, ladder="LIZ", size_standard_channel="Orange")
    review_case = {"full_path": str(source), "label": "manual_adjusted"}
    tab = SimpleNamespace(
        _current_file=source, _current_fsa=fsa, _metadata_loading=False,
        is_operation_active=lambda: False,
        _review_runtime_cache={source: {}}, _manual_rerun_consumption_by_path={},
        _recent_reviewed_files={source}, _review_session_entries_by_path={},
        _review_case_by_path={source: review_case}, _review_bundle_cases=[review_case],
        _review_bundle_dir=Path("bundle"), _resolve_cache_key=lambda path: Path(path),
        _save_review_bundle_annotation_worker=lambda *args: (_ for _ in ()).throw(OSError("readonly")),
        _run_tab_for_review=lambda: SimpleNamespace(
            unregister_ladder_review_update=lambda path: unregistered.append(path)
        ),
        _sync_chip_strip=lambda: None, _rebuild_file_list=lambda: None,
        _refresh_review_bundle_run_button=lambda: None, _refresh_current_metadata=lambda: None,
        _set_status=lambda text, error=False: statuses.append((text, error)),
    )
    monkeypatch.setattr(ladder_tab, "load_ladder_adjustment", lambda _fsa: {"mapping": {0: 1}})
    monkeypatch.setattr(ladder_tab.QMessageBox, "question", lambda *args: ladder_tab.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ladder_tab, "deactivate_ladder_adjustment", lambda _fsa: None)

    TabLadder._remove_saved_adjustment(tab)

    assert unregistered == [source]
    assert source not in tab._recent_reviewed_files
    assert statuses[-1][1] is True
    assert "readonly" in statuses[-1][0]
