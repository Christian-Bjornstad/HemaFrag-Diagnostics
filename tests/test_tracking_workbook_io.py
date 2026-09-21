from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from core.tracking_workbook_io import (
    publish_workbook_contents,
    upsert_frame,
    write_tracking_frames,
)


@pytest.mark.parametrize("missing_value", [None, float("nan"), pd.NA])
def test_upsert_clears_missing_generated_values_without_touching_falsy_values_or_user_formulas(
    missing_value,
):
    workbook = Workbook()
    upsert_frame(
        workbook,
        "Runs",
        pd.DataFrame([{"ID": "A", "Value": 42, "Zero": 1, "Flag": True}]),
        key_columns=["ID"],
    )
    sheet = workbook["Runs"]
    sheet["E1"] = "UserFormula"
    sheet["E2"] = "=B2+C2"

    upsert_frame(
        workbook,
        "Runs",
        pd.DataFrame(
            [{"ID": "A", "Value": missing_value, "Zero": 0, "Flag": False}]
        ),
        key_columns=["ID"],
    )

    assert sheet["B2"].value is None
    assert sheet["C2"].value == 0
    assert sheet["D2"].value is False
    assert sheet["E2"].value == "=B2+C2"


def test_tracking_rows_upsert_and_extend_user_formula_columns(tmp_path):
    path = tmp_path / "tracking.xlsx"
    first = pd.DataFrame(
        [{"IdentityKey": "one", "Value": 2}]
    )
    write_tracking_frames(path, (("Runs", first, ("IdentityKey",)),))

    workbook = load_workbook(path)
    sheet = workbook["Runs"]
    sheet.cell(1, 3, "DoubleValue")
    sheet.cell(2, 3, "=B2*2")
    workbook.save(path)
    workbook.close()

    updated = pd.DataFrame(
        [
            {"IdentityKey": "one", "Value": 3},
            {"IdentityKey": "two", "Value": 5},
        ]
    )
    write_tracking_frames(path, (("Runs", updated, ("IdentityKey",)),))

    workbook = load_workbook(path, data_only=False)
    sheet = workbook["Runs"]
    assert sheet["B2"].value == 3
    assert sheet["C2"].value == "=B2*2"
    assert sheet["B3"].value == 5
    assert sheet["C3"].value == "=B3*2"
    assert list(sheet.tables.values())[0].ref == "A1:C3"
    workbook.close()


def test_publishing_existing_workbook_keeps_destination_entry(tmp_path, monkeypatch):
    destination = tmp_path / "tracking.xlsx"
    destination.write_bytes(b"old")
    staged = tmp_path / "staged.xlsx"
    staged.write_bytes(b"new workbook bytes")

    monkeypatch.setattr(
        "core.tracking_workbook_io.os.replace",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not replace")),
    )

    publish_workbook_contents(staged, destination)

    assert destination.read_bytes() == b"new workbook bytes"
    assert not staged.exists()
