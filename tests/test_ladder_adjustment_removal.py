from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.ladder_adjustment_io import deactivate_ladder_adjustment, load_ladder_adjustment
from core.ladder_adjustment_store import load_ladder_adjustment_record, save_ladder_adjustment_record


@pytest.fixture
def source(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(tmp_path / "adjustments.sqlite3"))
    path = tmp_path / "sample.fsa"
    path.write_bytes(b"synthetic FSA fixture")
    return path


def _fsa(path: Path, ladder="LIZ", channel="Orange"):
    return SimpleNamespace(file=path, ladder=ladder, size_standard_channel=channel)


def test_deactivation_is_exact_and_shared_by_identical_source_copies(source, tmp_path):
    copy = tmp_path / "copy.fsa"
    copy.write_bytes(source.read_bytes())
    payload = {"mapping": {"0": 1}}
    save_ladder_adjustment_record(source, payload, ladder="LIZ", size_standard_channel="Orange")
    save_ladder_adjustment_record(source, payload, ladder="ROX", size_standard_channel="Orange")
    save_ladder_adjustment_record(source, payload, ladder="LIZ", size_standard_channel="Red")

    deactivate_ladder_adjustment(_fsa(source))

    assert load_ladder_adjustment(_fsa(source)) is None
    assert load_ladder_adjustment(SimpleNamespace(file=source)) is not None
    assert load_ladder_adjustment(_fsa(copy)) is None
    assert load_ladder_adjustment_record(source, ladder="ROX", size_standard_channel="Orange")
    assert load_ladder_adjustment_record(source, ladder="LIZ", size_standard_channel="Red")
    save_ladder_adjustment_record(source, payload, ladder="LIZ", size_standard_channel="Orange")
    assert load_ladder_adjustment(_fsa(copy)) is not None


@pytest.mark.parametrize("sqlite_record", [False, True])
def test_deactivation_prevents_sidecar_reimport(source, sqlite_record):
    sidecar = source.with_suffix(".ladder_adj.json")
    sidecar.write_text(json.dumps({"mapping": {"0": 1}}), encoding="utf-8")
    if sqlite_record:
        save_ladder_adjustment_record(source, {"mapping": {"0": 1}}, ladder="LIZ", size_standard_channel="Orange")

    deactivate_ladder_adjustment(_fsa(source))

    assert load_ladder_adjustment(_fsa(source)) is None
    assert load_ladder_adjustment(SimpleNamespace(file=source)) is None
    assert sidecar.exists()
    assert load_ladder_adjustment_record(source, ladder="LIZ", size_standard_channel="Orange") is None


def test_failed_deactivation_preserves_adjustment(source, monkeypatch):
    payload = {"mapping": {"0": 1}}
    save_ladder_adjustment_record(source, payload, ladder="LIZ", size_standard_channel="Orange")
    import core.ladder_adjustment_store as store

    with monkeypatch.context() as patch:
        patch.setattr(store, "_connect", lambda path: (_ for _ in ()).throw(OSError("locked")))
        with pytest.raises(OSError, match="locked"):
            deactivate_ladder_adjustment(_fsa(source))
    assert load_ladder_adjustment(_fsa(source)) is not None
