from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pandas as pd

from config import APP_SETTINGS
from fraggler.fraggler import print_green
from core.analyses.clonality.tracking_dashboard import refresh_clonality_tracking_dashboard
from core.qc.qc_markers import (
    make_run_key,
    parse_pcr_date_from_filename,
    parse_run_code_from_filename,
    parse_well_from_filename,
)


FLT3_TRACKING_FILENAME = "FLT3_Tracking.xlsx"
FLT3_NPM1_QC_TRACKER_FILENAME = FLT3_TRACKING_FILENAME
GLOBAL_FLT3_TRACKING_PATH = Path("/Volumes/T7 Shield/HemaFrag_FLT3_All_Runs.xlsx")

RUN_SHEET_COLUMNS = [
    "Month",
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
    "Ladder",
    "LadderQC",
    "LadderFitStrategy",
    "LadderEngine",
    "LadderReasonCodes",
    "SourceFsaSha256",
    "ManualAdjustmentSha256",
    "AnalysisVersion",
    "RustPreviewPositiveCall",
    "RustPreviewWTBP",
    "RustPreviewMutantBPs",
    "RustPreviewStrongestMutantRatio",
    "LadderExpectedStepCount",
    "LadderFittedStepCount",
    "LadderR2",
    "LadderMedianAnchorIntensity",
    "PullUpCandidate",
    "SaturationCandidate",
    "PeakQC",
]

PEAK_SHEET_COLUMNS = [
    "Month",
    "IdentityKey",
    "File",
    "SourceRunDir",
    "DIT",
    "Assay",
    "Control",
    "RunDate",
    "RunCode",
    "Well",
    "Batch",
    "MarkerName",
    "Kind",
    "Channel",
    "ExpectedBP",
    "WindowBP",
    "SearchMode",
    "SearchWindowBP",
    "FoundBP",
    "DeltaBP",
    "Height",
    "Area",
    "OK",
    "Reason",
    "AbsDeltaBP",
]

_excel_lock = threading.Lock()

POSITIVE_CONTROL_IDS = {"IVS-P001", "IVS-P0001"}

MARKER_DEFINITIONS = {
    ("IVS-0000", "FLT3-ITD", None): [
        {
            "name": "IVS0000_ITD_329",
            "kind": "sample",
            "channel": "primary",
            "peak_label": "WT",
            "expected_bp": 329.0,
            "window_bp": 3.0,
            "delta_threshold_bp": 1.0,
            "analysis_label": "ITD",
        },
        {
            "name": "ITD_Ladder_350",
            "kind": "ladder",
            "channel": "size_standard",
            "expected_bp": 350.0,
            "window_bp": 2.5,
            "delta_threshold_bp": 1.5,
            "analysis_label": "ITD",
        },
    ],
    ("IVS-0000", "FLT3-ITD", "ratio_quant"): [
        {
            "name": "IVS0000_RATIO_329",
            "kind": "sample",
            "channel": "primary",
            "peak_label": "WT",
            "expected_bp": 329.0,
            "window_bp": 3.0,
            "delta_threshold_bp": 1.0,
            "analysis_label": "ITD-ratio",
        },
        {
            "name": "RATIO_Ladder_350",
            "kind": "ladder",
            "channel": "size_standard",
            "expected_bp": 350.0,
            "window_bp": 2.5,
            "delta_threshold_bp": 1.5,
            "analysis_label": "ITD-ratio",
        },
    ],
    ("IVS-0000", "FLT3-D835", None): [
        {
            "name": "IVS0000_D835_80",
            "kind": "sample",
            "channel": "primary",
            "peak_label": "WT",
            "expected_bp": 80.0,
            "window_bp": 2.5,
            "delta_threshold_bp": 1.0,
            "analysis_label": "D835",
        },
        {
            "name": "D835_Ladder_139",
            "kind": "ladder",
            "channel": "size_standard",
            "expected_bp": 139.0,
            "window_bp": 2.0,
            "delta_threshold_bp": 1.5,
            "analysis_label": "D835",
        },
    ],
    ("IVS-P001", "FLT3-D835", None): [
        {
            "name": "IVSP001_D835_128_129",
            "kind": "sample",
            "channel": "primary",
            "peak_label": "MUT",
            "expected_bp": 128.5,
            "window_bp": 2.5,
            "delta_threshold_bp": 1.0,
            "analysis_label": "D835",
            "expected_range": "128-129 bp",
        },
        {
            "name": "D835_Ladder_139",
            "kind": "ladder",
            "channel": "size_standard",
            "expected_bp": 139.0,
            "window_bp": 2.0,
            "delta_threshold_bp": 1.5,
            "analysis_label": "D835",
        },
    ],
    ("IVS-0000", "NPM1", None): [
        {
            "name": "IVS0000_NPM1_299",
            "kind": "sample",
            "channel": "primary",
            "peak_label": "WT",
            "expected_bp": 299.0,
            "window_bp": 2.5,
            "delta_threshold_bp": 1.0,
            "analysis_label": "NPM1",
        },
        {
            "name": "NPM1_Ladder_350",
            "kind": "ladder",
            "channel": "size_standard",
            "expected_bp": 350.0,
            "window_bp": 2.5,
            "delta_threshold_bp": 1.5,
            "analysis_label": "NPM1",
        },
    ],
}

def normalize_specimen_id(value: str | None) -> str:
    specimen = str(value or "").strip().upper()
    if specimen in POSITIVE_CONTROL_IDS:
        return "IVS-P001"
    return specimen


def control_code_for_entry(entry: dict) -> str:
    specimen = normalize_specimen_id(entry.get("specimen_id"))
    group = str(entry.get("group") or "")
    if specimen == "IVS-0000":
        return "RK"
    if specimen == "IVS-P001":
        return "PK"
    if group == "negative_control" or specimen == "NTC":
        return "NK"
    return ""


def is_tracking_control_entry(entry: dict) -> bool:
    return control_code_for_entry(entry) in {"RK", "PK", "NK"}


def marker_specs_for_entry(entry: dict) -> list[dict]:
    specimen = normalize_specimen_id(entry.get("specimen_id"))
    assay = str(entry.get("assay") or "")
    analysis_type = str(entry.get("analysis_type") or "")
    specs = MARKER_DEFINITIONS.get((specimen, assay, analysis_type))
    if specs is None:
        specs = MARKER_DEFINITIONS.get((specimen, assay, None), [])
    return [dict(spec) for spec in specs]


def build_tracking_base_row(entry: dict) -> dict:
    from core.qc.trend_monitor import build_entry_qc_trend_evidence

    file_name = resolve_entry_file_name(entry)
    if not file_name:
        return {}

    control = control_code_for_entry(entry)
    sample_kind = "control" if control else "patient"
    source_run_dir = str(entry.get("source_run_dir") or "").strip()
    run_date = str(entry.get("run_date") or "").strip() or parse_pcr_date_from_filename(file_name) or ""
    run_code = parse_run_code_from_filename(file_name) or ""
    well = str(entry.get("well_id") or "").strip() or parse_well_from_filename(file_name) or ""
    identity_key = f"{source_run_dir}::{file_name}" if control else f"{source_run_dir}::{make_run_key(file_name)}::{well or file_name}"
    ladder_r2 = entry.get("ladder_r2")
    rust_preview_wt_bp = entry.get("rust_preview_wt_bp")
    if rust_preview_wt_bp is None or not np.isfinite(rust_preview_wt_bp):
        rust_preview_wt_bp = ""
    rust_preview_ratio = entry.get("rust_preview_strongest_mutant_ratio")
    if rust_preview_ratio is None or not np.isfinite(rust_preview_ratio):
        rust_preview_ratio = ""
    provenance = (
        entry.get("analysis_provenance")
        if isinstance(entry.get("analysis_provenance"), dict)
        else {}
    )
    trend_evidence = build_entry_qc_trend_evidence(entry)

    return {
        "Month": _month_bucket(run_date),
        "IdentityKey": identity_key,
        "File": file_name,
        "SourceRunDir": source_run_dir,
        "DIT": str(entry.get("dit") or ""),
        "Assay": str(entry.get("assay") or ""),
        "SampleKind": sample_kind,
        "Group": str(entry.get("group") or ""),
        "Control": control,
        "RunDate": run_date,
        "RunCode": run_code,
        "Well": well,
        "Batch": "",
        "Ladder": str(entry.get("ladder") or ""),
        "LadderQC": str(entry.get("ladder_qc_status") or ""),
        "LadderFitStrategy": str(entry.get("ladder_fit_strategy") or ""),
        "LadderEngine": str(provenance.get("ladder_engine") or ""),
        "LadderReasonCodes": ";".join(
            str(value) for value in provenance.get("ladder_reason_codes") or []
        ),
        "SourceFsaSha256": str(provenance.get("source_sha256") or ""),
        "ManualAdjustmentSha256": str(
            provenance.get("manual_adjustment_sha256") or ""
        ),
        "AnalysisVersion": str(provenance.get("app_version") or ""),
        "RustPreviewPositiveCall": bool(entry.get("rust_preview_positive_call", False)),
        "RustPreviewWTBP": rust_preview_wt_bp,
        "RustPreviewMutantBPs": ", ".join(f"{float(v):.2f}" for v in list(entry.get("rust_preview_mutant_bps") or [])),
        "RustPreviewStrongestMutantRatio": rust_preview_ratio,
        "LadderExpectedStepCount": int(entry.get("ladder_expected_step_count", 0) or 0),
        "LadderFittedStepCount": int(entry.get("ladder_fitted_step_count", 0) or 0),
        "LadderR2": ladder_r2 if ladder_r2 is not None else "",
        **trend_evidence,
    }


def resolve_entry_file_name(entry: dict) -> str:
    fsa = entry.get("fsa")
    return str(getattr(fsa, "file_name", "") or entry.get("file_name") or "").strip()


def update_flt3_npm1_qc_tracker(
    excel_path: Path,
    runs_df: pd.DataFrame,
    peaks_df: pd.DataFrame,
) -> None:
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    runs_df = _reindex_columns(runs_df, RUN_SHEET_COLUMNS)
    peaks_df = _reindex_columns(peaks_df, PEAK_SHEET_COLUMNS)

    with _excel_lock:
        if excel_path.exists():
            try:
                with pd.ExcelFile(excel_path, engine="openpyxl") as xls:
                    old_runs = pd.read_excel(excel_path, sheet_name="Runs", engine="openpyxl") if "Runs" in xls.sheet_names else pd.DataFrame(columns=RUN_SHEET_COLUMNS)
                    old_peaks = pd.read_excel(excel_path, sheet_name="PK_Peaks", engine="openpyxl") if "PK_Peaks" in xls.sheet_names else pd.DataFrame(columns=PEAK_SHEET_COLUMNS)
            except Exception:
                old_runs = pd.DataFrame(columns=RUN_SHEET_COLUMNS)
                old_peaks = pd.DataFrame(columns=PEAK_SHEET_COLUMNS)
        else:
            old_runs = pd.DataFrame(columns=RUN_SHEET_COLUMNS)
            old_peaks = pd.DataFrame(columns=PEAK_SHEET_COLUMNS)

        if not runs_df.empty:
            old_runs = old_runs[~old_runs["IdentityKey"].isin(runs_df["IdentityKey"])]
        if not peaks_df.empty and not old_peaks.empty:
            new_keys = peaks_df[["IdentityKey", "MarkerName"]].astype(str).agg("::".join, axis=1)
            old_keys = old_peaks[["IdentityKey", "MarkerName"]].astype(str).agg("::".join, axis=1)
            old_peaks = old_peaks[~old_keys.isin(set(new_keys.tolist()))]

        all_runs = _concat_frames(old_runs, runs_df).drop_duplicates(subset=["IdentityKey"], keep="last")
        all_peaks = _concat_frames(old_peaks, peaks_df).drop_duplicates(subset=["IdentityKey", "MarkerName"], keep="last")

        patient_runs, control_runs = _split_run_frames(all_runs)

        writer_kwargs: dict[str, object] = {"engine": "openpyxl"}
        if excel_path.exists():
            writer_kwargs.update({"mode": "a", "if_sheet_exists": "replace"})
        with pd.ExcelWriter(excel_path, **writer_kwargs) as writer:
            all_runs.to_excel(writer, sheet_name="Runs", index=False)
            patient_runs.to_excel(writer, sheet_name="Patient_Runs", index=False)
            control_runs.to_excel(writer, sheet_name="Control_Runs", index=False)
            all_peaks.to_excel(writer, sheet_name="PK_Peaks", index=False)

        refresh_clonality_tracking_dashboard(
            excel_path,
            dashboard_title="HemaFrag FLT3/NPM1 Tracking Dashboard",
        )

    print_green(f"FLT3/NPM1 QC tracker updated in {excel_path}")


def update_flt3_npm1_qc_tracker_workbook(
    excel_path: Path,
    entries: list[dict],
) -> None:
    runs_df, peaks_df = build_flt3_npm1_tracker_frames(entries)
    update_flt3_npm1_qc_tracker(excel_path, runs_df, peaks_df)


def resolve_global_flt3_tracking_path() -> Path:
    batch_settings = APP_SETTINGS.get("analyses", {}).get("flt3", {}).get("batch", {})
    configured = str(batch_settings.get("global_tracking_excel_path") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return GLOBAL_FLT3_TRACKING_PATH


def update_global_flt3_tracking_workbook(entries: list[dict]) -> Path | None:
    if not entries:
        return None
    path = resolve_global_flt3_tracking_path()
    update_flt3_npm1_qc_tracker_workbook(path, entries)
    return path


def build_flt3_npm1_tracker_frames(entries: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    from core.analyses.flt3.pipeline import _build_flt3_npm1_tracker_frames

    return _build_flt3_npm1_tracker_frames(entries)


def _split_run_frames(runs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    runs = _reindex_columns(runs, RUN_SHEET_COLUMNS)
    if runs.empty:
        return (
            pd.DataFrame(columns=RUN_SHEET_COLUMNS),
            pd.DataFrame(columns=RUN_SHEET_COLUMNS),
        )

    sample_kind = runs.get("SampleKind", pd.Series("", index=runs.index)).fillna("").astype(str).str.lower()
    control = runs.get("Control", pd.Series("", index=runs.index)).fillna("").astype(str)
    is_control = sample_kind.eq("control") | control.ne("")
    patient_runs = _reindex_columns(runs.loc[~is_control].copy(), RUN_SHEET_COLUMNS)
    control_runs = _reindex_columns(runs.loc[is_control].copy(), RUN_SHEET_COLUMNS)
    return patient_runs, control_runs


def _reindex_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    result = df.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result[columns]


def _concat_frames(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    old = old if old is not None else pd.DataFrame()
    new = new if new is not None else pd.DataFrame()
    if old.empty:
        return new.copy()
    if new.empty:
        return old.copy()
    all_columns = list(dict.fromkeys([*old.columns.tolist(), *new.columns.tolist()]))
    return pd.concat([old.reindex(columns=all_columns), new.reindex(columns=all_columns)], ignore_index=True)


def _month_bucket(run_date: str) -> str:
    value = str(run_date or "").strip()
    if len(value) >= 7 and value[4:5] == "-" and value[7:8] == "-":
        return value[:7].replace("-", "_")
    return ""
