#!/usr/bin/env python3
"""Combine archive-run tracking workbooks into one stable yearly workbook."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from core.analyses.clonality.tracking_dashboard import (
    refresh_clonality_tracking_dashboard,
)
from core.tracking_workbook_io import write_tracking_frames


TRACKING_SHEETS = ("Runs", "Patient_Runs", "Control_Runs", "PK_Peaks")


def discover_tracking_workbooks(
    run_root: Path,
    *,
    exclude: Path | None = None,
) -> list[Path]:
    root = Path(run_root).expanduser()
    excluded = exclude.resolve() if exclude is not None and exclude.exists() else exclude
    candidates: list[Path] = []
    for path in root.rglob("*.xlsx"):
        if path.name.startswith("~$"):
            continue
        if excluded is not None:
            try:
                if path.resolve() == excluded:
                    continue
            except OSError:
                pass
        if "overview" in path.stem.lower():
            continue
        try:
            with pd.ExcelFile(path, engine="openpyxl") as workbook:
                if "Runs" in workbook.sheet_names:
                    candidates.append(path)
        except Exception:
            continue
    return sorted(
        candidates,
        key=lambda path: (path.stat().st_mtime_ns, str(path).lower()),
    )


def _union_columns(frames: Iterable[pd.DataFrame]) -> list[str]:
    columns: list[str] = []
    for frame in frames:
        for column in frame.columns:
            name = str(column)
            if name not in columns:
                columns.append(name)
    return columns


def _combined_sheet(workbooks: list[Path], sheet_name: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for workbook in workbooks:
        try:
            with pd.ExcelFile(workbook, engine="openpyxl") as xls:
                if sheet_name not in xls.sheet_names:
                    continue
                frames.append(pd.read_excel(xls, sheet_name=sheet_name))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    columns = _union_columns(frames)
    combined = pd.concat(
        [frame.reindex(columns=columns) for frame in frames],
        ignore_index=True,
    )
    keys = (
        ["IdentityKey", "MarkerName"]
        if sheet_name == "PK_Peaks"
        else ["IdentityKey"]
    )
    if all(column in combined.columns for column in keys):
        valid = (
            combined[keys]
            .fillna("")
            .astype(str)
            .apply(lambda column: column.str.strip())
            .ne("")
            .all(axis=1)
        )
        keyed = combined.loc[valid].drop_duplicates(subset=keys, keep="last")
        unkeyed = combined.loc[~valid]
        combined = pd.concat([keyed, unkeyed], ignore_index=True)
    return combined


def combine_run_root(
    run_root: Path,
    output_path: Path,
    *,
    year_label: str | None = None,
    include_sl: bool = False,
) -> Path:
    del year_label
    root = Path(run_root).expanduser()
    output = Path(output_path).expanduser()
    workbooks = discover_tracking_workbooks(root, exclude=output)
    if not workbooks:
        raise FileNotFoundError(
            f"No clonality tracking workbooks were found below {root}."
        )

    frames = {
        sheet_name: _combined_sheet(workbooks, sheet_name)
        for sheet_name in TRACKING_SHEETS
    }
    if not include_sl:
        for sheet_name in ("Runs", "Control_Runs"):
            frame = frames[sheet_name]
            if "Control" in frame.columns:
                frames[sheet_name] = frame.loc[
                    ~frame["Control"].fillna("").astype(str).str.upper().eq("SL")
                ].copy()

    output.parent.mkdir(parents=True, exist_ok=True)
    write_tracking_frames(
        output,
        (
            ("Runs", frames["Runs"], ("IdentityKey",)),
            ("Patient_Runs", frames["Patient_Runs"], ("IdentityKey",), True),
            ("Control_Runs", frames["Control_Runs"], ("IdentityKey",), True),
            ("PK_Peaks", frames["PK_Peaks"], ("IdentityKey", "MarkerName")),
        ),
    )
    refresh_clonality_tracking_dashboard(output)
    return output


__all__ = ["combine_run_root", "discover_tracking_workbooks"]
