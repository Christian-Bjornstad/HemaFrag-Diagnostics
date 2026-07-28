from __future__ import annotations

import pandas as pd

from core.run_ledger import (
    RUN_LEDGER_SCHEMA,
    export_snapshot_workbook,
    read_snapshot,
    replace_snapshot,
    snapshot_workbook,
)


def _frames() -> dict[str, pd.DataFrame]:
    return {
        "Runs": pd.DataFrame(
            [
                {"IdentityKey": "patient-1", "QC": "PASS", "R2": 0.9999},
                {"IdentityKey": "qc-1", "QC": "PASS", "R2": 1.0},
            ]
        ),
        "PK_Peaks": pd.DataFrame(
            [{"IdentityKey": "qc-1", "Marker": "100bp", "Height": 1234}]
        ),
    }


def test_run_ledger_snapshot_is_idempotent_and_append_safe(tmp_path):
    ledger = tmp_path / "runs.sqlite"

    first = replace_snapshot(
        ledger,
        snapshot_id="run-1",
        frames=_frames(),
        metadata={"manifest": "run-1.json"},
    )
    second = replace_snapshot(
        ledger,
        snapshot_id="run-1",
        frames=_frames(),
        metadata={"manifest": "run-1.json"},
    )
    replace_snapshot(
        ledger,
        snapshot_id="run-2",
        frames={"Runs": pd.DataFrame([{"IdentityKey": "patient-2"}])},
    )

    assert first["schema_version"] == RUN_LEDGER_SCHEMA
    assert first["sheet_rows"] == second["sheet_rows"]
    loaded = read_snapshot(ledger, "run-1")
    assert loaded["Runs"].to_dict("records") == _frames()["Runs"].to_dict("records")
    assert len(read_snapshot(ledger, "run-2")["Runs"]) == 1


def test_workbook_snapshot_round_trips_row_for_row(tmp_path):
    source = tmp_path / "source.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        for name, frame in _frames().items():
            frame.to_excel(writer, sheet_name=name, index=False)

    ledger = tmp_path / "runs.sqlite"
    snapshot_workbook(
        ledger,
        snapshot_id="run-1",
        workbook_path=source,
    )
    exported = export_snapshot_workbook(
        ledger,
        snapshot_id="run-1",
        output_path=tmp_path / "exported.xlsx",
    )

    source_frames = pd.read_excel(source, sheet_name=None)
    exported_frames = pd.read_excel(exported, sheet_name=None)
    assert source_frames.keys() == exported_frames.keys()
    for name in source_frames:
        pd.testing.assert_frame_equal(source_frames[name], exported_frames[name])
