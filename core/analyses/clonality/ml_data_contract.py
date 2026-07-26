"""Shared data contract for real-data clonality ML workflows.

The tracking workbook is the index for local FSA files and chemist labels.
This module keeps workbook sheet selection and column normalization identical
for audit, labeling, and training code.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


CHEMIST_LABEL_COLUMN = "ClonalityChemistLabel"
RULE_LABEL_COLUMN = "ClonalitySuggestion"

RUN_SHEET_PRIORITY = ("Runs", "Run")
FALLBACK_RUN_SHEETS = ("Patient_Runs", "Control_Runs")

CANONICAL_RUN_COLUMNS = (
    "IdentityKey",
    "File",
    "SourceRunDir",
    "DIT",
    "Assay",
    "SampleKind",
    "Group",
    "Control",
    "RunDate",
    "RunCode",
    "Well",
    CHEMIST_LABEL_COLUMN,
    RULE_LABEL_COLUMN,
)

TRACE_FEATURE_PREFIXES = (
    "raw_peak_",
    "peak_count",
    "dominant_",
    "second_peak_",
    "total_peak_",
    "nonspecific_",
    "outside_interpretation_",
    "interpretation_range_",
    "peak_variance_per_channel",
    "mad_per_channel",
    "dome_",
    "trace_",
    "ref_window_",
    "in_reference_window",
    "dom_distance_",
)


@dataclass(frozen=True)
class TrackingRunTable:
    frame: pd.DataFrame
    primary_sheet: str
    source_sheets: tuple[str, ...]
    available_sheets: tuple[str, ...]


def load_tracking_run_table(
    workbook_path: Path | str,
    *,
    include_controls: bool = False,
) -> TrackingRunTable:
    """Load one canonical row per tracked FSA injection.

    Current workbooks use ``Runs``. ``Run`` remains supported for older
    labeling workbooks, and split patient/control sheets are a final fallback.
    """
    workbook = Path(workbook_path).expanduser()
    with pd.ExcelFile(workbook, engine="openpyxl") as xls:
        available = tuple(xls.sheet_names)
        primary = next((name for name in RUN_SHEET_PRIORITY if name in available), "")

        if primary:
            frame = xls.parse(primary)
            frame["_TrackingSheet"] = primary
            frame["_TrackingRowNumber"] = frame.index + 2
            source_sheets = (primary,)
        else:
            source_sheets = tuple(name for name in FALLBACK_RUN_SHEETS if name in available)
            if not source_sheets:
                expected = ", ".join((*RUN_SHEET_PRIORITY, *FALLBACK_RUN_SHEETS))
                raise ValueError(
                    f"Excel '{workbook}' has no tracking run sheet. "
                    f"Expected one of: {expected}. Found: {list(available)}"
                )
            pieces = []
            for sheet_name in source_sheets:
                piece = xls.parse(sheet_name)
                piece["_TrackingSheet"] = sheet_name
                piece["_TrackingRowNumber"] = piece.index + 2
                pieces.append(piece)
            frame = pd.concat(pieces, ignore_index=True, sort=False)
            primary = source_sheets[0]

    frame = _normalize_run_columns(frame)
    frame = frame.reset_index(drop=True)
    if "_TrackingRowNumber" not in frame.columns:
        frame["_TrackingRowNumber"] = frame.index + 2
    if "_TrackingSheet" not in frame.columns:
        frame["_TrackingSheet"] = primary

    if not include_controls:
        frame = frame.loc[~_control_mask(frame)].reset_index(drop=True)

    return TrackingRunTable(
        frame=frame,
        primary_sheet=primary,
        source_sheets=source_sheets,
        available_sheets=available,
    )


def missing_required_columns(
    frame: pd.DataFrame,
    required: Iterable[str],
) -> list[str]:
    return [column for column in required if column not in frame.columns]


def is_trace_feature(column: object) -> bool:
    name = str(column).strip().lower()
    return any(name.startswith(prefix) for prefix in TRACE_FEATURE_PREFIXES)


def _normalize_run_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    lower_to_actual = {str(column).strip().lower(): column for column in normalized.columns}
    renames: dict[object, str] = {}
    for canonical in CANONICAL_RUN_COLUMNS:
        if canonical in normalized.columns:
            continue
        actual = lower_to_actual.get(canonical.lower())
        if actual is not None:
            renames[actual] = canonical
    if renames:
        normalized = normalized.rename(columns=renames)

    for column in normalized.columns:
        if pd.api.types.is_object_dtype(normalized[column]):
            normalized[column] = normalized[column].where(
                pd.notna(normalized[column]), ""
            )
    return normalized


def _control_mask(frame: pd.DataFrame) -> pd.Series:
    sample_kind = frame.get("SampleKind", pd.Series("", index=frame.index))
    control = frame.get("Control", pd.Series("", index=frame.index))
    return (
        sample_kind.fillna("").astype(str).str.strip().str.lower().eq("control")
        | control.fillna("").astype(str).str.strip().ne("")
    )


__all__ = [
    "CANONICAL_RUN_COLUMNS",
    "CHEMIST_LABEL_COLUMN",
    "FALLBACK_RUN_SHEETS",
    "RULE_LABEL_COLUMN",
    "RUN_SHEET_PRIORITY",
    "TrackingRunTable",
    "TRACE_FEATURE_PREFIXES",
    "is_trace_feature",
    "load_tracking_run_table",
    "missing_required_columns",
]
