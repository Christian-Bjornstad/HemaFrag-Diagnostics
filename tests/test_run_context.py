from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from config import APP_SETTINGS
from core.run_context import RunContext, settings_fingerprint


def _manifest_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_create_captures_an_immutable_deep_settings_snapshot(monkeypatch):
    source = {
        "active_analysis": "clonality",
        "engine": {"use_rust": True},
        "paths": [Path("input"), Path("output")],
    }
    expected = copy.deepcopy(source)

    context = RunContext.create(
        analysis_id="clonality",
        settings=source,
        run_id="run-1",
        created_at_utc="2026-09-23T10:00:00+00:00",
    )
    original_fingerprint = context.settings_fingerprint

    source["engine"]["use_rust"] = False
    source["paths"].append(Path("later"))
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "flt3")

    assert dict(context.settings_snapshot["engine"]) == expected["engine"]
    assert context.settings_snapshot["paths"] == tuple(expected["paths"])
    assert context.settings_fingerprint == original_fingerprint
    assert context.settings_fingerprint == _manifest_fingerprint(expected)
    assert settings_fingerprint(context.settings_snapshot) == original_fingerprint
    with pytest.raises(TypeError):
        context.settings_snapshot["engine"]["use_rust"] = False


def test_create_without_settings_freezes_app_settings_at_capture_time(monkeypatch):
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "clonality")
    original_use_rust = APP_SETTINGS["engine"]["use_rust"]
    context = RunContext.create(
        analysis_id="clonality",
        run_id="run-2",
        created_at_utc="2026-09-23T10:00:00Z",
    )

    captured_fingerprint = context.settings_fingerprint
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "general")
    monkeypatch.setitem(APP_SETTINGS["engine"], "use_rust", not original_use_rust)

    assert context.settings_snapshot["active_analysis"] == "clonality"
    assert context.settings_snapshot["engine"]["use_rust"] is original_use_rust
    assert context.settings_fingerprint == captured_fingerprint


def test_explicit_empty_settings_are_not_replaced_by_app_settings():
    context = RunContext.create(
        analysis_id="general",
        settings={},
        run_id="run-empty",
        created_at_utc="2026-09-23T10:00:00+00:00",
    )

    assert dict(context.settings_snapshot) == {}
    assert context.settings_fingerprint == _manifest_fingerprint({})


@pytest.mark.parametrize("analysis_id", ["", "unknown", " clonality "])
def test_create_rejects_invalid_analysis_ids(analysis_id):
    with pytest.raises(ValueError, match="analysis_id"):
        RunContext.create(analysis_id=analysis_id, settings={})


def test_create_rejects_a_run_as_its_own_parent():
    with pytest.raises(ValueError, match="parent_run_id"):
        RunContext.create(
            analysis_id="clonality",
            settings={},
            run_id="same-run",
            parent_run_id="same-run",
        )


@pytest.mark.parametrize("run_id", ["../escape", "folder\\escape", "run:name", "..", "bad id"])
def test_context_rejects_run_ids_that_are_unsafe_as_manifest_names(run_id):
    with pytest.raises(ValueError, match="run_id"):
        RunContext.create(analysis_id="clonality", settings={}, run_id=run_id)


def test_create_rejects_a_snapshot_for_a_different_analysis():
    with pytest.raises(ValueError, match="active_analysis"):
        RunContext.create(
            analysis_id="clonality",
            settings={"active_analysis": "flt3"},
        )


def test_create_rejects_invalid_settings_shapes():
    with pytest.raises(TypeError, match="mapping"):
        RunContext.create(analysis_id="clonality", settings=[])

    with pytest.raises(TypeError, match="string keys"):
        RunContext.create(analysis_id="clonality", settings={1: "invalid"})


def test_context_fields_cannot_be_reassigned():
    context = RunContext.create(analysis_id="flt3", settings={})

    with pytest.raises((AttributeError, TypeError)):
        context.analysis_id = "clonality"


def test_settings_copy_is_mutable_without_changing_snapshot_or_fingerprint():
    context = RunContext.create(
        analysis_id="clonality",
        settings={"active_analysis": "clonality", "analyses": {"clonality": {"batch": {"max_workers": 2}}}},
    )
    original_fingerprint = context.settings_fingerprint

    copied = context.settings_copy()
    copied["analyses"]["clonality"]["batch"]["max_workers"] = 8

    assert context.settings_snapshot["analyses"]["clonality"]["batch"]["max_workers"] == 2
    assert context.settings_fingerprint == original_fingerprint
