"""Stored corrections must retain their integrity and precedence over sidecars."""

from contextlib import closing
import json
import sqlite3
from types import SimpleNamespace

import pytest

from core import ladder_adjustment_store as store
from core.ladder_adjustment_io import load_ladder_adjustment


@pytest.mark.parametrize("replacement", ['{"mapping": {"0": 99}}', "broken", "[]"])
def test_invalid_record_cannot_revive_sidecar(tmp_path, monkeypatch, caplog, replacement):
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"original FSA")
    database = tmp_path / "adjustments.sqlite3"
    monkeypatch.setenv(store.LADDER_ADJUSTMENT_DB_ENV, str(database))
    store.save_ladder_adjustment_record(source, {"mapping": {"0": 1}})
    sidecar = source.with_suffix(".ladder_adj.json")
    sidecar.write_text(json.dumps({"mapping": {"0": 2}}), encoding="utf-8")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE ladder_adjustments SET payload_json = ?", (replacement,))
        connection.commit()
        before = connection.execute("SELECT * FROM ladder_adjustments").fetchone()

    assert store.load_ladder_adjustment_record(source) is None
    assert "Ignoring invalid stored ladder adjustment" in caplog.text
    assert load_ladder_adjustment(SimpleNamespace(file=source)) is None
    assert sidecar.exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT * FROM ladder_adjustments").fetchone() == before


def test_checksum_failure_is_explicit_for_strict_reader(tmp_path, monkeypatch):
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"original FSA")
    database = tmp_path / "adjustments.sqlite3"
    monkeypatch.setenv(store.LADDER_ADJUSTMENT_DB_ENV, str(database))
    store.save_ladder_adjustment_record(source, {"mapping": {"0": 1}})
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE ladder_adjustments SET payload_sha256 = 'wrong'")
        connection.commit()

    assert store.load_ladder_adjustment_record(source) is None
    with pytest.raises(store.InvalidLadderAdjustmentRecord, match="checksum"):
        store.load_ladder_adjustment_record(source, raise_on_invalid=True)


def test_checksum_accepts_json_round_trip_with_numeric_mapping_keys_and_nan(tmp_path, monkeypatch):
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"original FSA")
    monkeypatch.setenv(store.LADDER_ADJUSTMENT_DB_ENV, str(tmp_path / "adjustments.sqlite3"))
    payload = {"mapping": {2: 3, 10: 11}, "review": {"before_qc": {"r2": float("nan")}}}
    store.save_ladder_adjustment_record(source, payload)

    record = store.load_ladder_adjustment_record(source)
    assert record is not None
    assert record["payload"]["mapping"] == {"2": 3, "10": 11}
