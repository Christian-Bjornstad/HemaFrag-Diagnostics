from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from config import APP_SETTINGS
from fraggler.fraggler import print_green, print_warning
from core.analyses.flt3.tracking_dashboard import refresh_flt3_tracking_dashboard
from core.html_reports import extract_dit_from_name
from core.qc.qc_markers import (
    make_run_key,
    parse_batch_from_filename,
    parse_pcr_date_from_filename,
    parse_run_code_from_filename,
    parse_well_from_filename,
)
from core.tracking_workbook_io import (
    publish_workbook_contents,
    write_tracking_frames,
)


FLT3_TRACKING_FILENAME = "FLT3_Tracking.xlsx"
FLT3_NPM1_QC_TRACKER_FILENAME = FLT3_TRACKING_FILENAME

RUN_SHEET_COLUMNS = [
    "Month",
    "RunDate",
    "DIT",
    "SpecimenID",
    "Assay",
    "AnalysisType",
    "SampleKind",
    "Group",
    "Control",
    "File",
    "SourceRunDir",
    "IdentityKey",
    "RunCode",
    "Well",
    "Batch",
    "SelectedInjection",
    "PreferredInjection",
    "InjectionTimeSeconds",
    "SelectionReason",
    "ResultStatus",
    "Interpretation",
    "PositiveCall",
    "Ratio",
    "MutantFraction",
    "RatioMode",
    "ManualSelectionValid",
    "ManualSelectionReason",
    "WT_BP",
    "WT_Area",
    "MutantBPs",
    "MutantAreas",
    "MutantAreaTotal",
    "MutantMain_BP",
    "MutantMain_Area",
    "RatioNumeratorArea",
    "RatioDenominatorArea",
    "PeakQCPass",
    "PeakQC",
    "ReviewStatus",
    "TrackingNote",
    "Ladder",
    "SizeStandardChannel",
    "PrimaryPeakChannel",
    "LadderQC",
    "LadderFitStrategy",
    "ManualAdjustmentUsed",
    "RustPreviewPositiveCall",
    "RustPreviewWTBP",
    "RustPreviewMutantBPs",
    "RustPreviewStrongestMutantRatio",
    "LadderExpectedStepCount",
    "LadderFittedStepCount",
    "LadderR2",
    "LadderLinearR2",
    "LadderLinearMeanResidualBp",
    "LadderLinearMaxResidualBp",
    "LadderCurvature",
    "LadderMedianAnchorIntensity",
]

PEAK_SHEET_COLUMNS = [
    "Month",
    "IdentityKey",
    "File",
    "SourceRunDir",
    "DIT",
    "Assay",
    "AnalysisType",
    "SpecimenID",
    "Control",
    "RunDate",
    "RunCode",
    "Well",
    "Batch",
    "InjectionTimeSeconds",
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

POSITIVE_CONTROL_IDS = {
    "IVS-P001",
    "IVS-P0001",
    "PK",
    "PK-D835",
    "PK-ITD",
    "PKD835",
    "PKITD",
}
USER_RUN_COLUMNS = ("ReviewStatus", "TrackingNote")

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
    if specimen.startswith("PK-"):
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
    source_run_dir = str(entry.get("source_run_dir") or "").strip()
    run_date = str(entry.get("run_date") or "").strip() or parse_pcr_date_from_filename(file_name) or ""
    run_code = parse_run_code_from_filename(file_name) or ""
    well = str(entry.get("well_id") or "").strip() or parse_well_from_filename(file_name) or ""
    identity_key = f"{source_run_dir}::{file_name}" if control else f"{source_run_dir}::{make_run_key(file_name)}::{well or file_name}"
    dit = str(entry.get("dit") or extract_dit_from_name(file_name) or "").strip().upper()
    specimen_id = normalize_specimen_id(entry.get("specimen_id")) or dit
    sample_kind = "control" if control else ("patient" if dit else "unassigned")
    ladder_r2 = entry.get("ladder_r2")
    rust_preview_wt_bp = entry.get("rust_preview_wt_bp")
    if rust_preview_wt_bp is None or not np.isfinite(rust_preview_wt_bp):
        rust_preview_wt_bp = ""
    rust_preview_ratio = entry.get("rust_preview_strongest_mutant_ratio")
    if rust_preview_ratio is None or not np.isfinite(rust_preview_ratio):
        rust_preview_ratio = ""
    trend_evidence = build_entry_qc_trend_evidence(entry)
    preferred_injection = _format_injection_seconds(
        entry.get("preferred_injection_time")
    )

    return {
        "Month": _month_bucket(run_date),
        "IdentityKey": identity_key,
        "File": file_name,
        "SourceRunDir": source_run_dir,
        "DIT": dit,
        "Assay": str(entry.get("assay") or ""),
        "AnalysisType": str(entry.get("analysis_type") or ""),
        "SpecimenID": specimen_id,
        "SampleKind": sample_kind,
        "Group": str(entry.get("group") or ""),
        "Control": control,
        "RunDate": run_date,
        "RunCode": run_code,
        "Well": well,
        "Batch": parse_batch_from_filename(file_name) or "",
        "SelectedInjection": str(entry.get("selected_injection") or ""),
        "PreferredInjection": preferred_injection,
        "InjectionTimeSeconds": entry.get(
            "selected_injection_time",
            entry.get("injection_time", ""),
        ),
        "SelectionReason": str(entry.get("selection_reason") or ""),
        "Ladder": str(entry.get("ladder") or ""),
        "SizeStandardChannel": str(entry.get("size_standard_channel") or ""),
        "PrimaryPeakChannel": str(entry.get("primary_peak_channel") or ""),
        "LadderQC": str(entry.get("ladder_qc_status") or ""),
        "LadderFitStrategy": str(entry.get("ladder_fit_strategy") or ""),
        "ManualAdjustmentUsed": (
            str(entry.get("ladder_fit_strategy") or "") == "manual_adjustment"
        ),
        "RustPreviewPositiveCall": bool(entry.get("rust_preview_positive_call", False)),
        "RustPreviewWTBP": rust_preview_wt_bp,
        "RustPreviewMutantBPs": ", ".join(f"{float(v):.2f}" for v in list(entry.get("rust_preview_mutant_bps") or [])),
        "RustPreviewStrongestMutantRatio": rust_preview_ratio,
        "LadderExpectedStepCount": int(entry.get("ladder_expected_step_count", 0) or 0),
        "LadderFittedStepCount": int(entry.get("ladder_fitted_step_count", 0) or 0),
        "LadderR2": ladder_r2 if ladder_r2 is not None else "",
        "LadderLinearR2": entry.get("ladder_linear_r2", ""),
        "LadderLinearMeanResidualBp": entry.get(
            "ladder_linear_mean_residual_bp",
            "",
        ),
        "LadderLinearMaxResidualBp": entry.get(
            "ladder_linear_max_residual_bp",
            "",
        ),
        "LadderCurvature": entry.get("ladder_max_curvature", ""),
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
                    legacy_qc = (
                        pd.read_excel(
                            excel_path,
                            sheet_name="All_Analyzed_QC",
                            engine="openpyxl",
                        )
                        if "All_Analyzed_QC" in xls.sheet_names
                        else pd.DataFrame()
                    )
                    annotation_frames = [
                        pd.read_excel(
                            excel_path,
                            sheet_name=sheet_name,
                            engine="openpyxl",
                        )
                        for sheet_name in ("Patient_Runs", "Control_Runs")
                        if sheet_name in xls.sheet_names
                    ]
            except Exception:
                old_runs = pd.DataFrame(columns=RUN_SHEET_COLUMNS)
                old_peaks = pd.DataFrame(columns=PEAK_SHEET_COLUMNS)
                legacy_qc = pd.DataFrame()
                annotation_frames = []
        else:
            old_runs = pd.DataFrame(columns=RUN_SHEET_COLUMNS)
            old_peaks = pd.DataFrame(columns=PEAK_SHEET_COLUMNS)
            legacy_qc = pd.DataFrame()
            annotation_frames = []

        old_runs = _reindex_columns(old_runs, RUN_SHEET_COLUMNS)
        old_runs = _normalize_legacy_run_classification(old_runs)
        migrated_patients = _legacy_qc_patient_runs(legacy_qc)
        if not migrated_patients.empty:
            migrated_patients = migrated_patients.loc[
                ~migrated_patients["IdentityKey"].isin(
                    set(old_runs["IdentityKey"].astype(str))
                )
            ]
            old_runs = _concat_frames(old_runs, migrated_patients)
        old_peaks = _reindex_columns(old_peaks, PEAK_SHEET_COLUMNS)
        old_runs = _merge_user_columns_into_runs(old_runs, annotation_frames)
        runs_df = _carry_forward_user_columns(old_runs, runs_df)

        if not runs_df.empty:
            old_runs = old_runs[~old_runs["IdentityKey"].isin(runs_df["IdentityKey"])]
        if not peaks_df.empty:
            new_keys = peaks_df[["IdentityKey", "MarkerName"]].astype(str).agg("::".join, axis=1)
            old_keys = old_peaks[["IdentityKey", "MarkerName"]].astype(str).agg("::".join, axis=1)
            old_peaks = old_peaks[~old_keys.isin(set(new_keys.tolist()))]

        all_runs = _concat_frames(old_runs, runs_df).drop_duplicates(subset=["IdentityKey"], keep="last")
        all_peaks = _concat_frames(old_peaks, peaks_df).drop_duplicates(subset=["IdentityKey", "MarkerName"], keep="last")
        if not all_peaks.empty:
            all_peaks = all_peaks.loc[
                all_peaks["Control"].fillna("").astype(str).str.upper().eq("PK")
                & all_peaks["Assay"].fillna("").astype(str).eq("FLT3-D835")
                & all_peaks["Kind"].fillna("").astype(str).str.lower().eq("sample")
                & all_peaks["MarkerName"]
                .fillna("")
                .astype(str)
                .eq("IVSP001_D835_128_129")
            ].copy()
        all_runs = _sort_tracking_rows(
            _reindex_columns(all_runs, RUN_SHEET_COLUMNS),
            ["RunDate", "SourceRunDir", "Assay", "File"],
        )
        all_peaks = _sort_tracking_rows(
            _reindex_columns(all_peaks, PEAK_SHEET_COLUMNS),
            ["RunDate", "SourceRunDir", "Assay", "File", "MarkerName"],
        )

        patient_runs, control_runs = _split_run_frames(all_runs)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=excel_path.parent,
                prefix=f".{excel_path.stem}.",
                suffix=".tmp.xlsx",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
            if excel_path.exists():
                shutil.copy2(excel_path, temporary_path)
            else:
                temporary_path.unlink(missing_ok=True)
            write_tracking_frames(
                temporary_path,
                (
                    ("Runs", all_runs, ("IdentityKey",)),
                    ("Patient_Runs", patient_runs, ("IdentityKey",), True),
                    ("Control_Runs", control_runs, ("IdentityKey",), True),
                    ("PK_Peaks", all_peaks, ("IdentityKey", "MarkerName")),
                ),
            )

            refresh_flt3_tracking_dashboard(temporary_path)
            publish_workbook_contents(temporary_path, excel_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    print_green(f"FLT3/NPM1 QC tracker updated in {excel_path}")


def update_flt3_npm1_qc_tracker_workbook(
    excel_path: Path,
    entries: list[dict],
) -> None:
    runs_df, peaks_df = build_flt3_npm1_tracker_frames(entries)
    update_flt3_npm1_qc_tracker(excel_path, runs_df, peaks_df)


def resolve_global_flt3_tracking_path() -> Path | None:
    batch_settings = APP_SETTINGS.get("analyses", {}).get("flt3", {}).get("batch", {})
    configured = str(batch_settings.get("global_tracking_excel_path") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return None


def update_global_flt3_tracking_workbook(entries: list[dict]) -> Path | None:
    if not entries:
        return None
    path = resolve_global_flt3_tracking_path()
    if path is None:
        print_warning(
            "[TRACKING] FLT3 master workbook is disabled. Set 'Master Tracking Excel File' in FLT3 Settings to enable it."
        )
        return None
    try:
        update_flt3_npm1_qc_tracker_workbook(path, entries)
    except Exception as exc:
        print_warning(
            f"[TRACKING] Could not update optional FLT3 master workbook {path}: {exc}. "
            "The local run workbook and reports were kept."
        )
        return None
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
    is_patient = sample_kind.eq("patient") & ~is_control
    patient_runs = _reindex_columns(runs.loc[is_patient].copy(), RUN_SHEET_COLUMNS)
    control_runs = _reindex_columns(runs.loc[is_control].copy(), RUN_SHEET_COLUMNS)
    return patient_runs, control_runs


def _normalize_legacy_run_classification(runs: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return runs
    normalized = runs.copy()
    for column in ("Control", "DIT", "SpecimenID", "SampleKind"):
        normalized[column] = normalized[column].astype(object)
    for index, row in normalized.iterrows():
        from core.utils import strip_stage_prefix

        def clean(value: object) -> str:
            return "" if value is None or pd.isna(value) else str(value).strip()

        file_name = clean(row.get("File"))
        clean_file_name = strip_stage_prefix(file_name)
        specimen_id = clean(row.get("SpecimenID"))
        upper_name = Path(clean_file_name).stem.upper()
        if not specimen_id:
            if upper_name.startswith("IVS-0000"):
                specimen_id = "IVS-0000"
            elif upper_name.startswith("IVS-P001") or upper_name.startswith("PK-"):
                specimen_id = "IVS-P001"
            elif upper_name.startswith("NTC"):
                specimen_id = "NTC"
        control = control_code_for_entry(
            {
                "specimen_id": specimen_id,
            }
        )
        dit = str(
            clean(row.get("DIT"))
            or extract_dit_from_name(clean_file_name)
            or ""
        ).strip().upper()
        normalized.at[index, "Control"] = control
        normalized.at[index, "DIT"] = dit
        normalized.at[index, "SpecimenID"] = (
            normalize_specimen_id(specimen_id) or dit
        )
        normalized.at[index, "SampleKind"] = (
            "control" if control else ("patient" if dit else "unassigned")
        )
    return normalized


def _legacy_qc_patient_runs(qc_rows: pd.DataFrame) -> pd.DataFrame:
    if qc_rows is None or qc_rows.empty or "File" not in qc_rows.columns:
        return pd.DataFrame(columns=RUN_SHEET_COLUMNS)

    def clean(value: object) -> str:
        return "" if value is None or pd.isna(value) else str(value).strip()

    def clean_number(value: object, default: float = 0.0) -> float:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return default if pd.isna(numeric) else float(numeric)

    migrated: list[dict] = []
    for _, raw in qc_rows.iterrows():
        file_name = clean(raw.get("File"))
        dit = clean(raw.get("SpecimenID")).upper()
        if not extract_dit_from_name(dit):
            dit = extract_dit_from_name(file_name) or ""
        if not dit:
            continue
        entry = {
            "file_name": file_name,
            "source_run_dir": clean(raw.get("SourceRunDir")),
            "dit": dit,
            "specimen_id": dit,
            "assay": clean(raw.get("Assay")),
            "analysis_type": clean(raw.get("Treatment")),
            "group": "sample",
            "run_date": clean(raw.get("RunDate")),
            "well_id": clean(raw.get("Well")),
            "ladder": clean(raw.get("InternalLadder") or raw.get("Ladder")),
            "size_standard_channel": clean(raw.get("SizeStandardChannel")),
            "ladder_qc_status": clean(raw.get("LadderQC")),
            "ladder_fit_strategy": clean(raw.get("LadderFitStrategy")),
            "ladder_r2": clean_number(raw.get("LadderR2")),
            "ladder_expected_step_count": int(
                clean_number(raw.get("LadderExpectedSteps"))
            ),
            "ladder_fitted_step_count": int(
                clean_number(raw.get("LadderFittedSteps"))
            ),
            "selected_injection": _format_injection_seconds(
                clean_number(raw.get("InjectionTimeSeconds"))
            ),
            "selected_injection_time": clean_number(
                raw.get("InjectionTimeSeconds")
            ),
        }
        base = build_tracking_base_row(entry)
        if not base:
            continue
        ratio = pd.to_numeric(
            pd.Series([raw.get("Ratio")]),
            errors="coerce",
        ).iloc[0]
        positive = str(raw.get("RustPositiveCall") or "").strip().lower() in {
            "true",
            "1",
            "yes",
        }
        base.update(
            {
                "ResultStatus": "qc_only",
                "Interpretation": "",
                "PositiveCall": positive,
                "Ratio": "" if pd.isna(ratio) else float(ratio),
                "WT_BP": raw.get("WT_bp", ""),
                "WT_Area": raw.get("WT_Area", ""),
                "MutantBPs": clean(raw.get("Mutant_bp_List")),
                "MutantAreaTotal": raw.get("Mutant_Area_Total", ""),
                "PeakQC": clean(raw.get("PeakQC")),
                "PeakQCPass": clean(raw.get("PeakQC")).lower() in {
                    "ok",
                    "not_evaluated_ladder_only",
                },
            }
        )
        migrated.append(
            {column: base.get(column, "") for column in RUN_SHEET_COLUMNS}
        )
    return pd.DataFrame(migrated, columns=RUN_SHEET_COLUMNS)


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


def _format_injection_seconds(value: object) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if text.lower().endswith("s"):
        return text
    try:
        return f"{int(float(text))}s"
    except (TypeError, ValueError):
        return text


def _merge_user_columns_into_runs(
    runs: pd.DataFrame,
    annotation_frames: list[pd.DataFrame],
) -> pd.DataFrame:
    if runs.empty or "IdentityKey" not in runs.columns:
        return runs
    annotations = [
        frame
        for frame in annotation_frames
        if not frame.empty and "IdentityKey" in frame.columns
    ]
    if not annotations:
        return runs
    combined = pd.concat(annotations, ignore_index=True)
    merged = runs.copy()
    for column in USER_RUN_COLUMNS:
        if column not in combined.columns:
            continue
        values = combined[["IdentityKey", column]].copy()
        values["IdentityKey"] = values["IdentityKey"].fillna("").astype(str)
        values = (
            values.loc[values["IdentityKey"].str.strip().ne("")]
            .drop_duplicates(subset=["IdentityKey"], keep="last")
            .set_index("IdentityKey")[column]
        )
        current = merged[column].fillna("").astype(str)
        inherited = (
            merged["IdentityKey"].fillna("").astype(str).map(values).fillna("")
        )
        merged[column] = current.where(current.str.strip().ne(""), inherited)
    return merged


def _carry_forward_user_columns(
    old_runs: pd.DataFrame,
    new_runs: pd.DataFrame,
) -> pd.DataFrame:
    if (
        old_runs.empty
        or new_runs.empty
        or "IdentityKey" not in old_runs.columns
        or "IdentityKey" not in new_runs.columns
    ):
        return new_runs

    carried = new_runs.copy()
    old = old_runs.copy()
    old["IdentityKey"] = old["IdentityKey"].fillna("").astype(str)
    for column in USER_RUN_COLUMNS:
        if column not in old.columns:
            continue
        values = (
            old.loc[old["IdentityKey"].str.strip().ne(""), ["IdentityKey", column]]
            .drop_duplicates(subset=["IdentityKey"], keep="last")
            .set_index("IdentityKey")[column]
        )
        current = carried[column].fillna("").astype(str)
        inherited = (
            carried["IdentityKey"].fillna("").astype(str).map(values).fillna("")
        )
        carried[column] = current.where(current.str.strip().ne(""), inherited)
    return carried


def _sort_tracking_rows(
    frame: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    usable = [column for column in columns if column in frame.columns]
    if frame.empty or not usable:
        return frame
    return frame.sort_values(usable, kind="stable", ignore_index=True)


def _month_bucket(run_date: str) -> str:
    value = str(run_date or "").strip()
    if len(value) >= 7 and value[4:5] == "-" and value[7:8] == "-":
        return value[:7].replace("-", "_")
    return ""
