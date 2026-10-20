"""Cleanup errors must not misreport an already committed bundle revision."""

import json
import logging
from pathlib import Path

import pytest

from core import ladder_review_bundle_store as store


def test_locked_backup_after_commit_preserves_success(tmp_path, monkeypatch, caplog):
    cases = tmp_path / "ladder_review_cases.csv"
    summary = tmp_path / "ladder_review_summary.json"
    cases.write_text("name\nold\n", encoding="utf-8")
    summary.write_text('{"revision": "old"}', encoding="utf-8")
    real_unlink = store._safe_unlink
    blocked = []

    def reject_backups(path, purpose):
        if path.suffix == ".backup":
            blocked.append(path)
            raise PermissionError("Backup is temporarily locked")
        return real_unlink(path, purpose)

    monkeypatch.setattr(store, "_safe_unlink", reject_backups)
    with caplog.at_level(logging.WARNING):
        store.save_review_bundle(
            cases, [{"name": "new"}], ["name"], summary, {"revision": "new"}
        )

    assert "new" in cases.read_text(encoding="utf-8")
    assert json.loads(summary.read_text(encoding="utf-8")) == {"revision": "new"}
    assert len(blocked) == 2
    assert all(path.exists() for path in blocked)
    assert not store._journal_path(cases).exists()
    assert "Backup is temporarily locked" in caplog.text
    with store.review_bundle_transaction(cases) as recovered:
        assert recovered is False


def test_backup_failure_during_rollback_still_raises(tmp_path, monkeypatch):
    cases = tmp_path / "ladder_review_cases.csv"
    summary = tmp_path / "ladder_review_summary.json"
    cases.write_text("name\nold\n", encoding="utf-8")
    summary.write_text('{"revision": "old"}', encoding="utf-8")
    real_replace = store.os.replace

    def reject_publication_and_rollback(source, destination):
        source = Path(source)
        if source.suffix == ".backup":
            raise PermissionError("Rollback backup is locked")
        if source.suffix == ".staged" and Path(destination).name == summary.name:
            raise OSError("Publication failed")
        return real_replace(source, destination)

    monkeypatch.setattr(store.os, "replace", reject_publication_and_rollback)
    with pytest.raises(RuntimeError, match="rollback could not complete"):
        store.save_review_bundle(
            cases, [{"name": "new"}], ["name"], summary, {"revision": "new"}
        )
    assert store._journal_path(cases).exists()
    assert len(list(tmp_path.glob("*.backup"))) == 2
