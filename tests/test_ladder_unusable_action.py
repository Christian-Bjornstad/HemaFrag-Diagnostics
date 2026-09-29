"""Operator exclusion of a ladder that has signal but cannot be fitted."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QDialog, QMessageBox

from core.analyses.clonality.ladder_review_labels import (
    is_review_fitting_eligible,
    is_review_ml_eligible,
    is_review_rerunnable,
    is_review_resolved,
)
from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog
from gui_qt.tabs.tab_ladder import TabLadder
from gui_qt.tabs.tab_ladder._io import (
    load_review_bundle_worker,
    save_unusable_ladder_exclusion_worker,
)
from gui_qt.tabs.tab_ladder._summary import review_progress_text


def _write_case(bundle: Path, fsa: Path) -> None:
    with (bundle / "ladder_review_cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["full_path", "file", "label"])
        writer.writeheader()
        writer.writerow({"full_path": str(fsa), "file": fsa.name, "label": ""})


def _fake_fsa(path: Path):
    steps = np.array([35.0, 50.0, 75.0, 100.0], dtype=float)
    return SimpleNamespace(
        file=str(path),
        file_name=path.name,
        ladder="GS500ROX",
        analysis_id="flt3",
        ladder_steps=steps,
        expected_ladder_steps=steps,
        size_standard=np.zeros(1200, dtype=float),
        best_size_standard=np.array([], dtype=float),
    )


def test_unusable_ladder_policy_is_resolved_and_never_rerunnable():
    label = "excluded_unusable_ladder"
    assert is_review_resolved(label)
    assert not is_review_rerunnable(label)
    assert not is_review_fitting_eligible(label)
    assert not is_review_ml_eligible(label)
    assert review_progress_text([{"label": label}]) == "Reviewed 1 / 1 — Remaining 0"


def test_unusable_ladder_exclusion_persists_without_adjustment(tmp_path):
    fsa = tmp_path / "unusable.fsa"
    fsa.write_bytes(b"fsa")
    _write_case(tmp_path, fsa)

    annotation = save_unusable_ladder_exclusion_worker(
        tmp_path,
        fsa,
        note="GS500ROX peaks cannot be fitted safely",
        reviewed_at_utc="2026-09-29T10:00:00+00:00",
    )

    assert annotation["label"] == "excluded_unusable_ladder"
    assert annotation["adjustment_path"] == ""
    reloaded = load_review_bundle_worker(tmp_path)["rows"][0]
    assert reloaded["label"] == "excluded_unusable_ladder"
    assert reloaded["label_note"] == "GS500ROX peaks cannot be fitted safely"
    assert not fsa.with_suffix(".ladder_adj.json").exists()
    saved_annotations = json.loads((tmp_path / "ladder_review_annotations.json").read_text(encoding="utf-8"))
    assert saved_annotations[str(fsa)]["label"] == "excluded_unusable_ladder"

    with pytest.raises(ValueError, match="unresolved row"):
        save_unusable_ladder_exclusion_worker(
            tmp_path,
            fsa,
            note="duplicate decision",
            reviewed_at_utc="2026-09-29T10:01:00+00:00",
        )


def test_unusable_ladder_exclusion_rejects_an_existing_adjustment(tmp_path):
    fsa = tmp_path / "adjusted.fsa"
    fsa.write_bytes(b"fsa")
    _write_case(tmp_path, fsa)
    fsa.with_suffix(".ladder_adj.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="existing adjustment"):
        save_unusable_ladder_exclusion_worker(
            tmp_path,
            fsa,
            note="must not replace a saved fit",
            reviewed_at_utc="2026-09-29T10:00:00+00:00",
        )
    assert load_review_bundle_worker(tmp_path)["rows"][0]["label"] == ""


def test_editor_action_requires_explicit_confirmation(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(LadderAdjustmentDialog, "_get_candidates", lambda self: pd.DataFrame())
    monkeypatch.setattr(LadderAdjustmentDialog, "_suggest_auto", lambda self, store_initial: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_preview_state", lambda self, show_errors: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_refresh_all", lambda self: None)
    monkeypatch.setattr(LadderAdjustmentDialog, "_focus_initial_step", lambda self: None)
    dialog = LadderAdjustmentDialog(
        _fake_fsa(tmp_path / "unusable.fsa"),
        review_context={"full_path": str(tmp_path / "unusable.fsa"), "label": "", "assay": "FLT3"},
    )
    assert dialog.btn_mark_unusable.text() == "Ladder Does Not Fit"
    assert dialog.btn_mark_unusable.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    dialog.btn_mark_unusable.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.review_comment_edit.setPlainText("Machine trace looks wrong")
    dialog.btn_mark_unusable.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.get_review_payload()["action"] == "exclude_unusable_ladder"
    assert dialog.get_review_payload()["comment"] == "Machine trace looks wrong"
    dialog.close()


def test_editor_exclusion_never_saves_ladder_mapping(qapp, monkeypatch, tmp_path):
    fsa = tmp_path / "unusable.fsa"
    fsa.write_bytes(b"fsa")
    _write_case(tmp_path, fsa)
    tab = TabLadder()
    tab._current_file = fsa
    tab._current_meta = {"ladder": "GS500ROX"}
    tab._current_fsa = _fake_fsa(fsa)
    tab._review_bundle_dir = tmp_path
    tab._review_case_by_path = {fsa.resolve(): {"full_path": str(fsa), "label": ""}}
    tab._review_bundle_cases = [{"full_path": str(fsa), "label": ""}]
    monkeypatch.setattr("gui_qt.tabs.tab_ladder._legacy.load_ladder_adjustment", lambda *_: None)
    monkeypatch.setattr("gui_qt.tabs.tab_ladder._legacy.save_ladder_adjustment", lambda *_args, **_kw: pytest.fail("must not save adjustment"))
    monkeypatch.setattr(tab, "_refresh_current_metadata", lambda: None)
    monkeypatch.setattr(tab, "_on_missing_ladder_exclusion_saved", lambda key, annotation: None)

    class AcceptedDialog:
        def exec(self):
            return True

        def get_review_payload(self):
            return {"action": "exclude_unusable_ladder", "comment": "peaks inconsistent"}

        def get_adjustment_payload(self):
            pytest.fail("must not construct an adjustment")

    monkeypatch.setattr("gui_qt.tabs.tab_ladder._legacy._open_ladder_adjustment_dialog", lambda *_args, **_kw: AcceptedDialog())
    tab._open_ladder_editor()
    assert load_review_bundle_worker(tmp_path)["rows"][0]["label"] == "excluded_unusable_ladder"
    tab.close()


def test_editor_exclusion_save_failure_keeps_review_unresolved(qapp, monkeypatch, tmp_path):
    fsa = tmp_path / "unusable.fsa"
    fsa.write_bytes(b"fsa")
    _write_case(tmp_path, fsa)
    tab = TabLadder()
    tab._current_file = fsa
    tab._current_meta = {"ladder": "GS500ROX"}
    tab._current_fsa = _fake_fsa(fsa)
    tab._review_bundle_dir = tmp_path
    tab._review_case_by_path = {fsa.resolve(): {"full_path": str(fsa), "label": ""}}
    tab._review_bundle_cases = [{"full_path": str(fsa), "label": ""}]
    monkeypatch.setattr("gui_qt.tabs.tab_ladder._legacy.load_ladder_adjustment", lambda *_: None)
    monkeypatch.setattr(tab, "_refresh_current_metadata", lambda: None)
    monkeypatch.setattr(
        "gui_qt.tabs.tab_ladder._io.save_unusable_ladder_exclusion_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("network denied")),
    )
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _self, title, message: messages.append((title, message)))

    class AcceptedDialog:
        def exec(self):
            return True

        def get_review_payload(self):
            return {"action": "exclude_unusable_ladder", "comment": "peaks inconsistent"}

    monkeypatch.setattr("gui_qt.tabs.tab_ladder._legacy._open_ladder_adjustment_dialog", lambda *_args, **_kw: AcceptedDialog())
    tab._open_ladder_editor()
    assert load_review_bundle_worker(tmp_path)["rows"][0]["label"] == ""
    assert tab._review_case_by_path[fsa.resolve()]["label"] == ""
    assert "remains unresolved" in messages[0][1]
    assert "network denied" in tab.status_lbl.text()
    tab.close()
