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
