#!/usr/bin/env python3
"""Run FLT3 ROX500 QC for every injection candidate, without DIT reports.

ROX500 is the user-facing FLT3 size-standard mode. Internally it uses the
GS500ROX ladder contract, which has the same size steps as LIZ500_250.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import io
import json
import os
import sys
import time
import warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
from Bio import SeqIO

from core.analysis import compute_ladder_qc_metrics
from core.analyses.flt3.classification import classify_fsa, get_injection_metadata
from core.analyses.flt3.pipeline import (
    FLT3_LADDER_ONLY_PEAK_QC_STATUS,
    _build_entry_from_candidate,
    _calculate_ratios,
    _reportable_itd_mut_rows,
    _scan_files,
    _summarize_detected_peaks,
    flt3_size_standard_mode,
)
from core.analyses.flt3.rox500_exclusions import (
    FLT3_ROX500_REVIEW_EXCLUSIONS,
    FLT3_ROX500_USER_GOOD_OVERRIDES,
    FLT3_ROX500_USER_REVIEW_OVERRIDES,
)
from core.utils import is_water_file


ROX500_QC_PREFIX = "FLT3_ROX500_QC"
QC_OUTPUT_COLUMNS = [
    "File",
    "SourceRunDir",
    "Well",
    "SpecimenID",
    "ControlPrefix",
    "Assay",
    "Treatment",
    "InjectionTimeSeconds",
    "InjectionVoltage",
    "InjectionProtocol",
    "RunDate",
    "RunTime",
    "RunName",
    "QCStatus",
    "QCReason",
    "SizeStandard",
    "InternalLadder",
    "Ladder",
    "SizeStandardChannel",
    "SizingMethod",
    "LadderQC",
    "LadderFitStrategy",
    "LadderR2",
    "LadderLinearMaxBp",
    "LadderLinearMeanBp",
    "LadderLinearR2",
    "LadderExpectedSteps",
    "LadderFittedSteps",
    "GS500ROXStartPriorMode",
    "GS500ROXStartPriorReviewBand",
    "GS500ROXStartPriorCurvedReviewBand",
    "GS500ROXStartPriorLearnedApplyBand",
    "GS500ROXStartPriorQuadraticMaxBp",
    "GS500ROXStartPriorQuadraticMeanBp",
    "GS500ROXStartPriorQuadraticR2",
    "GS500ROXStartPriorSelected",
    "GS500ROXStartPriorSummary",
    "PeakQC",
    "RustPositiveCall",
    "RustWTBP",
    "RustMutantBPs",
    "RustStrongestMutantRatio",
    "DetectedWTBPs",
    "DetectedMutantBPs",
    "DetectedPeakCount",
    "WT_bp",
    "WT_Area",
    "Mutant_bp_List",
    "Mutant_Area_Total",
    "Ratio",
    "ReviewReason",
]
RAW_METADATA_COLUMNS = [
    "SourceRunDir",
    "File",
    "Well",
    "ControlPrefix",
    "InjectionTimeSeconds",
    "InjectionVoltage",
    "InjectionProtocol",
    "RunName",
    "RunDate",
    "RunTime",
    "IncludedInAnalysis",
]
SUMMARY_COLUMNS = ["InjectionTimeSeconds", "Assay", "ControlPrefix", "QCStatus", "LadderQC", "PeakQC", "Count"]


@contextlib.contextmanager
def _temporary_rox500_env():
    old_ladder = os.environ.get("HEMAFRAG_FLT3_LADDER")
    old_size_standard = os.environ.get("HEMAFRAG_FLT3_SIZE_STANDARD")
    old_multiprocessing = os.environ.get("FRAGGLER_DISABLE_MULTIPROCESSING")
    old_skip_deep_search = os.environ.get("HEMAFRAG_SKIP_DEEP_SEARCH")
    old_skip_template_rescue = os.environ.get("HEMAFRAG_FLT3_SKIP_TEMPLATE_RESCUE")
    old_ladder_only_qc = os.environ.get("HEMAFRAG_FLT3_LADDER_ONLY_QC")
    os.environ["HEMAFRAG_FLT3_LADDER"] = "ROX500"
    os.environ["FRAGGLER_DISABLE_MULTIPROCESSING"] = "1"
    os.environ["HEMAFRAG_SKIP_DEEP_SEARCH"] = "True"
    os.environ["HEMAFRAG_FLT3_SKIP_TEMPLATE_RESCUE"] = "True"
    os.environ["HEMAFRAG_FLT3_LADDER_ONLY_QC"] = "True"
    try:
        yield
    finally:
        if old_ladder is None:
            os.environ.pop("HEMAFRAG_FLT3_LADDER", None)
        else:
            os.environ["HEMAFRAG_FLT3_LADDER"] = old_ladder
        if old_size_standard is None:
            os.environ.pop("HEMAFRAG_FLT3_SIZE_STANDARD", None)
        else:
            os.environ["HEMAFRAG_FLT3_SIZE_STANDARD"] = old_size_standard
        if old_multiprocessing is None:
            os.environ.pop("FRAGGLER_DISABLE_MULTIPROCESSING", None)
        else:
            os.environ["FRAGGLER_DISABLE_MULTIPROCESSING"] = old_multiprocessing
        if old_skip_deep_search is None:
            os.environ.pop("HEMAFRAG_SKIP_DEEP_SEARCH", None)
        else:
            os.environ["HEMAFRAG_SKIP_DEEP_SEARCH"] = old_skip_deep_search
        if old_skip_template_rescue is None:
            os.environ.pop("HEMAFRAG_FLT3_SKIP_TEMPLATE_RESCUE", None)
        else:
            os.environ["HEMAFRAG_FLT3_SKIP_TEMPLATE_RESCUE"] = old_skip_template_rescue
        if old_ladder_only_qc is None:
            os.environ.pop("HEMAFRAG_FLT3_LADDER_ONLY_QC", None)
        else:
            os.environ["HEMAFRAG_FLT3_LADDER_ONLY_QC"] = old_ladder_only_qc


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _fmt_float(value: Any, digits: int = 4) -> str:
    number = _safe_float(value)
    if not np.isfinite(number):
        return ""
    return f"{number:.{digits}f}"


def _fmt_list(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, str):
        return values
    try:
        return ", ".join(str(v) for v in values)
    except TypeError:
        return str(values)


def _detected_candidate_peak_lists(entry: dict, detected_peaks: pd.DataFrame) -> tuple[list[str], list[str], int]:
    if not isinstance(detected_peaks, pd.DataFrame) or detected_peaks.empty:
        return [], [], 0

    labels = detected_peaks["label"].astype(str)
    wt_rows = detected_peaks[labels == "WT"].copy()
    mut_rows = detected_peaks[labels.isin(["MUT", "ITD"])].copy()
    if entry.get("assay") == "FLT3-ITD":
        mut_rows = _reportable_itd_mut_rows(entry, detected_peaks, wt_rows=wt_rows, mut_rows=mut_rows)

    if entry.get("group") == "negative_control":
        mut_rows = mut_rows.iloc[0:0].copy()

    min_area = 50.0
    if not wt_rows.empty and "area" in wt_rows.columns:
        wt_area = float(wt_rows["area"].astype(float).max())
        if np.isfinite(wt_area) and wt_area > 0.0:
            min_area = max(min_area, wt_area * 0.0002)
    if not mut_rows.empty and "area" in mut_rows.columns:
        mut_rows = mut_rows[mut_rows["area"].astype(float) >= min_area].copy()

    detected_wt_bps = [f"{float(bp):.2f}" for bp in wt_rows["basepairs"].astype(float).tolist()]
    detected_mut_bps = [f"{float(bp):.2f}" for bp in mut_rows["basepairs"].astype(float).tolist()]
    return detected_wt_bps, detected_mut_bps, int(len(detected_peaks))


def _control_prefix(file_name: str) -> str:
    if is_water_file(file_name):
        return "V"
    upper = file_name.upper()
    for prefix in ("NK", "PK", "RK"):
        if upper.startswith(prefix + "_") or upper == prefix:
            return prefix
    if upper.startswith("V_") or upper.startswith("V__") or upper == "V":
        return "V"
    if "NTC" in upper:
        return "NK"
    if "IVS-P" in upper:
        return "PK"
    if "IVS-0000" in upper:
        return "RK"
    return ""


def _qc_status(entry: dict | None, reason: str = "") -> tuple[str, str]:
    if entry is None:
        return "FAIL", reason or "analysis_failed"

    ladder_qc = str(entry.get("ladder_qc_status") or "")
    peak_qc = str(entry.get("peak_qc_status") or "")
    prefix = _control_prefix(getattr(entry.get("fsa"), "file_name", ""))
    rust_positive = bool(entry.get("rust_preview_positive_call", False))
    mutant_bps = list(entry.get("rust_preview_mutant_bps") or [])

    if ladder_qc not in {"ok", "manual_adjustment"}:
        return "REVIEW", ladder_qc or "ladder_qc_failed"

    if peak_qc == FLT3_LADDER_ONLY_PEAK_QC_STATUS:
        return "PASS", "ladder_qc_ok"

    if prefix == "NK":
        if peak_qc == "no_relevant_peaks" or (not rust_positive and not mutant_bps):
            return "PASS", "negative_control_no_relevant_peaks"
        return "REVIEW", "negative_control_has_relevant_peaks"

    if prefix == "V":
        if peak_qc == "no_relevant_peaks":
            return "PASS", "blank_no_relevant_peaks"
        return "REVIEW", "blank_has_relevant_peaks"

    if peak_qc == "ok":
        return "PASS", "ladder_and_peak_qc_ok"

    return "REVIEW", peak_qc or "peak_qc_failed"


def _size_standard_channel_for_path(path: Path, *, fallback: str) -> str:
    try:
        tags = SeqIO.read(str(path), "abi").annotations.get("abif_raw", {})
        channels = {str(key) for key in tags.keys() if str(key).startswith("DATA")}
    except Exception:
        return str(fallback)
    preferred = str(fallback or "").strip()
    if preferred and preferred in channels:
        return preferred
    if preferred == "DATA4" and "DATA4" in channels:
        return "DATA4"
    if preferred == "DATA105" and "DATA105" in channels:
        return "DATA105"
    if "DATA4" in channels:
        return "DATA4"
    if "DATA105" in channels:
        return "DATA105"
    return str(fallback)


def _entry_row(path: Path, meta: dict, entry: dict | None, error: str = "") -> dict[str, Any]:
    mode = flt3_size_standard_mode()
    if entry is None:
        status, status_reason = _qc_status(None, error)
        size_standard_channel = _size_standard_channel_for_path(
            path,
            fallback=str(mode["size_standard_channel"]),
        )
        return {
            "File": path.name,
            "SourceRunDir": meta.get("source_run_dir", path.parent.name),
            "Well": meta.get("well_id") or "",
            "SpecimenID": meta.get("specimen_id") or "",
            "ControlPrefix": _control_prefix(path.name),
            "Assay": meta.get("assay") or "",
            "Treatment": meta.get("analysis_type") or "",
            "InjectionTimeSeconds": meta.get("injection_time", ""),
            "InjectionVoltage": meta.get("injection_voltage", ""),
            "InjectionProtocol": meta.get("injection_protocol", ""),
            "RunDate": meta.get("run_date", ""),
            "RunTime": meta.get("run_time", ""),
            "RunName": meta.get("run_name", ""),
            "QCStatus": status,
            "QCReason": status_reason,
            "SizeStandard": str(mode["size_standard"]),
            "InternalLadder": str(mode["internal_ladder"]),
            "Ladder": str(mode["internal_ladder"]),
            "SizeStandardChannel": size_standard_channel,
            "SizingMethod": "",
            "LadderQC": "analysis_failed",
            "LadderFitStrategy": "",
            "LadderR2": "",
            "LadderLinearMaxBp": "",
            "LadderLinearMeanBp": "",
            "LadderLinearR2": "",
            "LadderExpectedSteps": "",
            "LadderFittedSteps": "",
            "GS500ROXStartPriorMode": "",
            "GS500ROXStartPriorReviewBand": "",
            "GS500ROXStartPriorCurvedReviewBand": "",
            "GS500ROXStartPriorLearnedApplyBand": "",
            "GS500ROXStartPriorQuadraticMaxBp": "",
            "GS500ROXStartPriorQuadraticMeanBp": "",
            "GS500ROXStartPriorQuadraticR2": "",
            "GS500ROXStartPriorSelected": "",
            "GS500ROXStartPriorSummary": "",
            "PeakQC": "",
            "RustPositiveCall": "",
            "RustWTBP": "",
            "RustMutantBPs": "",
            "RustStrongestMutantRatio": "",
            "DetectedWTBPs": "",
            "DetectedMutantBPs": "",
            "DetectedPeakCount": "",
            "WT_bp": "",
            "WT_Area": "",
            "Mutant_bp_List": "",
            "Mutant_Area_Total": "",
            "Ratio": "",
            "ReviewReason": error,
        }

    fsa = entry["fsa"]
    metrics = compute_ladder_qc_metrics(fsa)
    ladder_only_qc = entry.get("peak_qc_status") == FLT3_LADDER_ONLY_PEAK_QC_STATUS
    peak_summary = {} if ladder_only_qc else _summarize_detected_peaks(entry)
    detected_peaks = entry.get("peaks_by_channel", {}).get(entry.get("primary_peak_channel"), pd.DataFrame())
    if ladder_only_qc:
        detected_wt_bps, detected_mut_bps, detected_peak_count = [], [], ""
    else:
        detected_wt_bps, detected_mut_bps, detected_peak_count = _detected_candidate_peak_lists(
            entry,
            detected_peaks,
        )
    status, status_reason = _qc_status(entry)

    return {
        "File": fsa.file_name,
        "SourceRunDir": entry.get("source_run_dir") or meta.get("source_run_dir", path.parent.name),
        "Well": entry.get("well_id") or meta.get("well_id") or "",
        "SpecimenID": entry.get("specimen_id") or meta.get("specimen_id") or "",
        "ControlPrefix": _control_prefix(fsa.file_name),
        "Assay": entry.get("assay") or "",
        "Treatment": entry.get("analysis_type") or "",
        "InjectionTimeSeconds": entry.get("injection_time", meta.get("injection_time", "")),
        "InjectionVoltage": meta.get("injection_voltage", ""),
        "InjectionProtocol": entry.get("injection_protocol") or meta.get("injection_protocol", ""),
        "RunDate": entry.get("run_date") or meta.get("run_date", ""),
        "RunTime": entry.get("run_time") or meta.get("run_time", ""),
        "RunName": entry.get("run_name") or meta.get("run_name", ""),
        "QCStatus": status,
        "QCReason": status_reason,
        "SizeStandard": entry.get("size_standard") or str(mode["size_standard"]),
        "InternalLadder": entry.get("internal_ladder") or str(mode["internal_ladder"]),
        "Ladder": entry.get("ladder") or str(mode["internal_ladder"]),
        "SizeStandardChannel": entry.get("size_standard_channel") or str(mode["size_standard_channel"]),
        "SizingMethod": entry.get("sizing_method") or "",
        "LadderQC": entry.get("ladder_qc_status") or "",
        "LadderFitStrategy": entry.get("ladder_fit_strategy") or "",
        "LadderR2": _fmt_float(entry.get("ladder_r2"), 6),
        "LadderLinearMaxBp": _fmt_float(metrics.get("linear_trend_max_abs_error_bp"), 3),
        "LadderLinearMeanBp": _fmt_float(metrics.get("linear_trend_mean_abs_error_bp"), 3),
        "LadderLinearR2": _fmt_float(metrics.get("linear_trend_r2"), 6),
        "LadderExpectedSteps": entry.get("ladder_expected_step_count") or "",
        "LadderFittedSteps": entry.get("ladder_fitted_step_count") or "",
        "GS500ROXStartPriorMode": entry.get("gs500rox_start_prior_mode") or "",
        "GS500ROXStartPriorReviewBand": (
            "" if not entry.get("gs500rox_start_prior_mode") else bool(entry.get("gs500rox_start_prior_review_band", False))
        ),
        "GS500ROXStartPriorCurvedReviewBand": (
            ""
            if not entry.get("gs500rox_start_prior_mode")
            else bool(entry.get("gs500rox_start_prior_curved_review_band", False))
        ),
        "GS500ROXStartPriorLearnedApplyBand": (
            ""
            if not entry.get("gs500rox_start_prior_mode")
            else bool(entry.get("gs500rox_start_prior_learned_apply_band", False))
        ),
        "GS500ROXStartPriorQuadraticMaxBp": _fmt_float(
            entry.get("gs500rox_start_prior_quadratic_max_bp"),
            3,
        ),
        "GS500ROXStartPriorQuadraticMeanBp": _fmt_float(
            entry.get("gs500rox_start_prior_quadratic_mean_bp"),
            3,
        ),
        "GS500ROXStartPriorQuadraticR2": _fmt_float(
            entry.get("gs500rox_start_prior_quadratic_r2"),
            6,
        ),
        "GS500ROXStartPriorSelected": _fmt_list(entry.get("gs500rox_start_prior_selected") or []),
        "GS500ROXStartPriorSummary": entry.get("gs500rox_start_prior_summary") or "",
        "PeakQC": entry.get("peak_qc_status") or "",
        "RustPositiveCall": "" if ladder_only_qc else bool(entry.get("rust_preview_positive_call", False)),
        "RustWTBP": "" if ladder_only_qc else _fmt_float(entry.get("rust_preview_wt_bp"), 2),
        "RustMutantBPs": "" if ladder_only_qc else _fmt_list(entry.get("rust_preview_mutant_bps") or []),
        "RustStrongestMutantRatio": ""
        if ladder_only_qc
        else _fmt_float(entry.get("rust_preview_strongest_mutant_ratio"), 6),
        "DetectedWTBPs": _fmt_list(detected_wt_bps),
        "DetectedMutantBPs": _fmt_list(detected_mut_bps),
        "DetectedPeakCount": detected_peak_count,
        "WT_bp": "" if ladder_only_qc else _fmt_float(peak_summary.get("wt_bp"), 2),
        "WT_Area": "" if ladder_only_qc else _fmt_float(peak_summary.get("wt_area"), 2),
        "Mutant_bp_List": ""
        if ladder_only_qc
        else _fmt_list(f"{bp:.2f}" for bp in peak_summary.get("mut_bps", [])),
        "Mutant_Area_Total": "" if ladder_only_qc else _fmt_float(peak_summary.get("mut_area_total"), 2),
        "Ratio": "" if ladder_only_qc else _fmt_float(entry.get("ratio"), 6),
        "ReviewReason": entry.get("ladder_review_reason") or entry.get("ladder_review_summary") or "",
    }


def _raw_metadata_rows(
    root: Path,
    *,
    years: list[str] | None = None,
    require_run_name_contains: str = "",
    exclude_run_name_contains: str = "",
    limit: int = 0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = _filter_candidate_files(
        sorted(root.rglob("*.fsa")),
        root,
        years=years,
        require_run_name_contains=require_run_name_contains,
        exclude_run_name_contains=exclude_run_name_contains,
        limit=limit,
    )
    for path in paths:
        meta = get_injection_metadata(path)
        rows.append(
            {
                "SourceRunDir": path.parent.name,
                "File": path.name,
                "Well": meta.get("well_id") or "",
                "ControlPrefix": _control_prefix(path.name),
                "InjectionTimeSeconds": meta.get("injection_time", ""),
                "InjectionVoltage": meta.get("injection_voltage", ""),
                "InjectionProtocol": meta.get("injection_protocol", ""),
                "RunName": meta.get("run_name", ""),
                "RunDate": meta.get("run_date", ""),
                "RunTime": meta.get("run_time", ""),
                "IncludedInAnalysis": not is_water_file(path.name),
            }
        )
    return rows


def _path_matches_years(path: Path, root: Path, years: set[str]) -> bool:
    if not years:
        return True
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(str(part).startswith(tuple(years)) or any(year in str(part) for year in years) for part in parts)


def _path_matches_run_filter(path: Path, required_text: str) -> bool:
    token = required_text.strip().lower()
    if not token:
        return True
    if any(token in str(part).lower() for part in path.parts):
        return True
    try:
        tags = SeqIO.read(str(path), "abi").annotations.get("abif_raw", {})
    except Exception:
        return False
    for key in ("RunN1", "MCHN1", "HCFG3", "MODL1", "RPrN1"):
        value = tags.get(key, "")
        text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else str(value)
        if token in text.lower():
            return True
    return False


def _run_filter_tokens(text: str) -> list[str]:
    return [token.strip() for token in str(text or "").replace(";", ",").split(",") if token.strip()]


def _matches_review_exclusion(path: Path) -> bool:
    source_run_dir = path.parent.name
    file_name = path.name
    for run_pattern, file_pattern, _reason in FLT3_ROX500_REVIEW_EXCLUSIONS:
        run_pattern = str(run_pattern or "*")
        file_pattern = str(file_pattern or "*")
        if fnmatch.fnmatchcase(source_run_dir, run_pattern) and fnmatch.fnmatchcase(file_name, file_pattern):
            return True
    return False


def _matches_user_good_override(path: Path) -> str:
    source_run_dir = path.parent.name
    file_name = path.name
    for run_pattern, file_pattern, reason in FLT3_ROX500_USER_GOOD_OVERRIDES:
        run_pattern = str(run_pattern or "*")
        file_pattern = str(file_pattern or "*")
        if fnmatch.fnmatchcase(source_run_dir, run_pattern) and fnmatch.fnmatchcase(file_name, file_pattern):
            return str(reason or "user_good_review")
    return ""


def _matches_user_review_override(path: Path) -> str:
    source_run_dir = path.parent.name
    file_name = path.name
    for run_pattern, file_pattern, reason in FLT3_ROX500_USER_REVIEW_OVERRIDES:
        run_pattern = str(run_pattern or "*")
        file_pattern = str(file_pattern or "*")
        if fnmatch.fnmatchcase(source_run_dir, run_pattern) and fnmatch.fnmatchcase(file_name, file_pattern):
            return str(reason or "user_minor_review")
    return ""


def _apply_user_good_override(row: dict[str, Any], reason: str) -> dict[str, Any]:
    if not reason:
        return row
    row = dict(row)
    row["QCStatus"] = "PASS"
    row["QCReason"] = reason
    if row.get("LadderQC") in {"", "analysis_failed", "review_required"}:
        row["LadderQC"] = "ok"
    row["ReviewReason"] = ""
    return row


def _apply_user_review_override(row: dict[str, Any], reason: str) -> dict[str, Any]:
    if not reason:
        return row
    row = dict(row)
    row["QCStatus"] = "REVIEW"
    row["QCReason"] = reason
    if row.get("LadderQC") in {"", "analysis_failed"}:
        row["LadderQC"] = "review_required"
    row["ReviewReason"] = reason
    return row


def _is_operator_error_flt3_file(path: Path) -> bool:
    if _matches_review_exclusion(path):
        return True
    # User-reviewed FLT3 FAIL panel showed MP1_* rows are human/operator plate
    # errors, not ladder fitting cases. Exclude these before QC so they do not
    # inflate future REVIEW/FAIL validation workbooks.
    if path.name.upper().startswith("MP1_"):
        return True
    # User-confirmed 2026-05-18 FLT3 ROX500 FAIL panels: these have missing or
    # too-short ladders and should be skipped rather than counted as pipeline
    # validation failures.
    known_missing_ladder = {
        "25OUM04778_p1_RATIO__250324_A04_H9C0VADZ.fsa",
        "25OUM04778_p2_RATIO__250324_F04_H9C0VADZ.fsa",
        "25OUM04792_p1_RATIO__250324_B04_H9C0VADZ.fsa",
        "25OUM04792_p2_RATIO__250324_G04_H9C0VADZ.fsa",
        "25OUM04888_p1_RATIO__250324_C04_H9C0VADZ.fsa",
        "25OUM04888_p2_RATIO__250324_H04_H9C0VADZ.fsa",
        "NTC_RATIO__250324_E04_H9C0VADZ.fsa",
        "IVS-0000_RATIO__250324_D04_H9C0VADZ.fsa",
        "IVS-0000_ITD__0300725_C01_H9C0ZJ88.fsa",
        "25OUM11534_p2_TKD-kutting__240725_B05_H9C0VC6E.fsa",
    }
    return path.name in known_missing_ladder


def _filter_candidate_files(
    paths: list[Path],
    root: Path,
    *,
    years: list[str] | None = None,
    require_run_name_contains: str = "",
    exclude_run_name_contains: str = "",
    limit: int = 0,
) -> list[Path]:
    year_set = {str(year).strip() for year in (years or []) if str(year).strip()}
    max_rows = int(limit or 0)
    filtered: list[Path] = []
    for path in paths:
        if _is_operator_error_flt3_file(path):
            continue
        if not _path_matches_years(path, root, year_set):
            continue
        if not _path_matches_run_filter(path, require_run_name_contains):
            continue
        if any(_path_matches_run_filter(path, token) for token in _run_filter_tokens(exclude_run_name_contains)):
            continue
        filtered.append(path)
        if max_rows > 0 and len(filtered) >= max_rows:
            break
    return filtered


def _write_html(out_path: Path, summary: dict[str, Any], qc_df: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    if "QCStatus" in qc_df.columns:
        issue_df = qc_df[qc_df["QCStatus"] != "PASS"].copy()
    else:
        issue_df = pd.DataFrame()
    issue_html = issue_df.to_html(index=False, escape=True) if not issue_df.empty else "<p>No QC issues.</p>"
    by_injection_html = summary_df.to_html(index=False, escape=True)
    top_rows = qc_df.head(96).to_html(index=False, escape=True)
    status_counts = Counter(qc_df["QCStatus"].astype(str)) if "QCStatus" in qc_df.columns else Counter()
    injection_counts = (
        Counter(qc_df["InjectionTimeSeconds"].astype(str))
        if "InjectionTimeSeconds" in qc_df.columns
        else Counter()
    )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FLT3 ROX500 QC all injections</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; color: #0f172a; background: #f8fafc; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 18px 0; }}
    .card {{ background: white; border: 1px solid #dbeafe; border-radius: 14px; padding: 14px 18px; min-width: 180px; box-shadow: 0 8px 28px rgba(15,23,42,0.06); }}
    .label {{ color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    .value {{ font-size: 26px; font-weight: 800; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; margin: 16px 0 28px; font-size: 12px; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #e0f2fe; color: #0f172a; position: sticky; top: 0; }}
    .pass {{ color: #047857; }}
    .review {{ color: #b45309; }}
  </style>
</head>
<body>
  <h1>FLT3 ROX500 QC - all injections</h1>
  <p>QC-only ladder-fit run. No DIT reports generated. ROX500 uses the GS500ROX ladder contract internally; sample peak detection and ratio calculation are intentionally not evaluated here.</p>
  <div class="cards">
    <div class="card"><div class="label">Analyzed FSA</div><div class="value">{summary["analyzed_fsa_count"]}</div></div>
    <div class="card"><div class="label">PASS</div><div class="value pass">{status_counts.get("PASS", 0)}</div></div>
    <div class="card"><div class="label">REVIEW</div><div class="value review">{status_counts.get("REVIEW", 0)}</div></div>
    <div class="card"><div class="label">5 s</div><div class="value">{injection_counts.get("5", 0)}</div></div>
    <div class="card"><div class="label">10 s</div><div class="value">{injection_counts.get("10", 0)}</div></div>
  </div>
  <h2>Summary by injection</h2>
  {by_injection_html}
  <h2>Rows needing review</h2>
  {issue_html}
  <h2>All QC rows preview</h2>
  {top_rows}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def _analyze_qc_file_worker(payload: tuple[int, int, str, dict[str, Any], bool]) -> dict[str, Any]:
    idx, total, path_text, meta, quiet = payload
    path = Path(path_text)
    started = time.monotonic()
    stdout_cm = contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext()
    stderr_cm = contextlib.redirect_stderr(io.StringIO()) if quiet else contextlib.nullcontext()
    with _temporary_rox500_env():
        with stdout_cm, stderr_cm:
            try:
                entry = _build_entry_from_candidate(path, meta)
            except Exception as exc:
                elapsed = time.monotonic() - started
                row = _entry_row(path, meta, None, f"{type(exc).__name__}: {exc}")
                row = _apply_user_review_override(row, _matches_user_review_override(path))
                row = _apply_user_good_override(row, _matches_user_good_override(path))
                return {
                    "idx": idx,
                    "total": total,
                    "file": path.name,
                    "row": row,
                    "elapsed": elapsed,
                    "kind": "ERROR",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "status": row.get("QCStatus", "FAIL"),
                    "status_reason": row.get("QCReason", ""),
                    "ladder_qc": row.get("LadderQC", ""),
                    "peak_qc": row.get("PeakQC", ""),
                }

            if entry is None:
                elapsed = time.monotonic() - started
                row = _entry_row(path, meta, None, "analysis_failed")
                row = _apply_user_review_override(row, _matches_user_review_override(path))
                row = _apply_user_good_override(row, _matches_user_good_override(path))
                return {
                    "idx": idx,
                    "total": total,
                    "file": path.name,
                    "row": row,
                    "elapsed": elapsed,
                    "kind": "FAIL",
                    "detail": "analysis_failed",
                    "status": row.get("QCStatus", "FAIL"),
                    "status_reason": row.get("QCReason", ""),
                    "ladder_qc": row.get("LadderQC", ""),
                    "peak_qc": row.get("PeakQC", ""),
                }

            entry["selection_reason"] = "QC-only all-injections run; no injection selection applied"
            entry["alternate_injections"] = []
            entry["alternate_injections_summary"] = ""
            if entry.get("peak_qc_status") != FLT3_LADDER_ONLY_PEAK_QC_STATUS:
                _calculate_ratios([entry])
            row = _entry_row(path, meta, entry)
            row = _apply_user_review_override(row, _matches_user_review_override(path))
            row = _apply_user_good_override(row, _matches_user_good_override(path))
        elapsed = time.monotonic() - started
        status = row.get("QCStatus", "")
        status_reason = row.get("QCReason", "")
        return {
            "idx": idx,
            "total": total,
            "file": path.name,
            "row": row,
            "elapsed": elapsed,
            "kind": "DONE",
            "detail": "",
            "status": status,
            "status_reason": status_reason,
            "ladder_qc": row.get("LadderQC", ""),
            "peak_qc": row.get("PeakQC", ""),
        }


def _print_qc_result(result: dict[str, Any]) -> None:
    idx = int(result.get("idx", 0))
    total = int(result.get("total", 0))
    file_name = str(result.get("file", ""))
    elapsed = float(result.get("elapsed", 0.0))
    kind = str(result.get("kind", "DONE"))
    if kind == "DONE":
        print(
            f"[{idx}/{total}] DONE {file_name} in {elapsed:.1f}s: "
            f"{result.get('status')} ({result.get('status_reason')}); "
            f"ladder={result.get('ladder_qc')}; peak={result.get('peak_qc')}",
            flush=True,
        )
    else:
        print(
            f"[{idx}/{total}] {kind} {file_name} in {elapsed:.1f}s: {result.get('detail')}",
            flush=True,
        )


def run_qc(
    fsa_dir: Path,
    outdir: Path,
    *,
    years: list[str] | None = None,
    require_run_name_contains: str = "",
    exclude_run_name_contains: str = "",
    limit: int = 0,
    workers: int = 1,
    progress_callback=None,
    progress_max_callback=None,
    status_callback=None,
) -> dict[str, Any]:
    with _temporary_rox500_env():
        return _run_qc_impl(
            fsa_dir,
            outdir,
            years=years,
            require_run_name_contains=require_run_name_contains,
            exclude_run_name_contains=exclude_run_name_contains,
            limit=limit,
            workers=workers,
            progress_callback=progress_callback,
            progress_max_callback=progress_max_callback,
            status_callback=status_callback,
        )


def _run_qc_impl(
    fsa_dir: Path,
    outdir: Path,
    *,
    years: list[str] | None = None,
    require_run_name_contains: str = "",
    exclude_run_name_contains: str = "",
    limit: int = 0,
    workers: int = 1,
    progress_callback=None,
    progress_max_callback=None,
    status_callback=None,
) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    raw_files = _filter_candidate_files(
        _scan_files(fsa_dir, mode="all"),
        fsa_dir,
        years=years,
        require_run_name_contains=require_run_name_contains,
        exclude_run_name_contains=exclude_run_name_contains,
        limit=limit,
    )
    classified: list[tuple[Path, dict]] = []
    skipped: list[dict[str, Any]] = []
    for path in raw_files:
        meta = classify_fsa(path)
        if meta is None:
            skipped.append({"File": path.name, "SourceRunDir": path.parent.name, "Reason": "not_classified"})
            continue
        classified.append((path, meta))

    rows: list[dict[str, Any]] = []
    total = len(classified)
    if progress_max_callback is not None:
        progress_max_callback(total)
    worker_count = max(1, min(int(workers or 1), total or 1))
    parallel = worker_count > 1
    payloads = [
        (idx, total, str(path), meta, parallel)
        for idx, (path, meta) in enumerate(classified, start=1)
    ]

    if parallel:
        print(f"[INFO] FLT3 ROX500 QC running with {worker_count} parallel workers.", flush=True)
        try:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                future_to_job = {}
                for payload, (path, meta) in zip(payloads, classified, strict=False):
                    idx = payload[0]
                    message = f"[{idx}/{total}] ROX500 QC queued {path.name} ({meta.get('injection_time')}s)"
                    print(message, flush=True)
                    if status_callback is not None:
                        status_callback(message)
                    future_to_job[executor.submit(_analyze_qc_file_worker, payload)] = (idx, path, meta)

                completed = 0
                for future in as_completed(future_to_job):
                    idx, path, meta = future_to_job[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        row = _entry_row(path, meta, None, f"parallel_worker_failed: {type(exc).__name__}: {exc}")
                        result = {
                            "idx": idx,
                            "total": total,
                            "file": path.name,
                            "row": row,
                            "elapsed": 0.0,
                            "kind": "ERROR",
                            "detail": f"parallel_worker_failed: {type(exc).__name__}: {exc}",
                            "status": row.get("QCStatus", "FAIL"),
                            "status_reason": row.get("QCReason", ""),
                            "ladder_qc": row.get("LadderQC", ""),
                            "peak_qc": row.get("PeakQC", ""),
                        }
                    rows.append(result["row"])
                    completed += 1
                    _print_qc_result(result)
                    if status_callback is not None:
                        status_callback(
                            f"[{completed}/{total}] Completed {result.get('file')} "
                            f"{result.get('status')} ({result.get('status_reason')})"
                        )
                    if progress_callback is not None:
                        progress_callback(completed)
        except (OSError, PermissionError) as exc:
            print(
                f"[WARN] Parallel workers unavailable ({type(exc).__name__}: {exc}); "
                "falling back to sequential ROX500 QC.",
                flush=True,
            )
            for idx, (path, meta) in enumerate(classified, start=1):
                payload = (idx, total, str(path), meta, False)
                message = f"[{idx}/{total}] ROX500 QC {path.name} ({meta.get('injection_time')}s)"
                print(message, flush=True)
                if status_callback is not None:
                    status_callback(message)
                result = _analyze_qc_file_worker(payload)
                rows.append(result["row"])
                _print_qc_result(result)
                if progress_callback is not None:
                    progress_callback(idx)
    else:
        for payload, (path, meta) in zip(payloads, classified, strict=False):
            idx = payload[0]
            message = f"[{idx}/{total}] ROX500 QC {path.name} ({meta.get('injection_time')}s)"
            print(message, flush=True)
            if status_callback is not None:
                status_callback(message)
            result = _analyze_qc_file_worker(payload)
            rows.append(result["row"])
            _print_qc_result(result)
            if progress_callback is not None:
                progress_callback(idx)

    qc_df = pd.DataFrame(rows, columns=QC_OUTPUT_COLUMNS)
    if not qc_df.empty:
        qc_df = qc_df.sort_values(["InjectionTimeSeconds", "Assay", "ControlPrefix", "File"], kind="stable")

    raw_meta_df = pd.DataFrame(
        _raw_metadata_rows(
            fsa_dir,
            years=years,
            require_run_name_contains=require_run_name_contains,
            exclude_run_name_contains=exclude_run_name_contains,
            limit=limit,
        )
        ,
        columns=RAW_METADATA_COLUMNS,
    )
    summary_df = (
        qc_df.groupby(["InjectionTimeSeconds", "Assay", "ControlPrefix", "QCStatus", "LadderQC", "PeakQC"], dropna=False)
        .size()
        .reset_index(name="Count")
        if not qc_df.empty
        else pd.DataFrame(columns=SUMMARY_COLUMNS)
    )
    review_df = (
        qc_df[qc_df["QCStatus"].astype(str) != "PASS"].copy()
        if "QCStatus" in qc_df.columns
        else pd.DataFrame(columns=QC_COLUMNS)
    )

    qc_csv = outdir / f"{ROX500_QC_PREFIX}_All_Injections.csv"
    review_csv = outdir / f"{ROX500_QC_PREFIX}_Review_Rows.csv"
    summary_csv = outdir / f"{ROX500_QC_PREFIX}_Summary_By_Injection.csv"
    raw_csv = outdir / f"{ROX500_QC_PREFIX}_Raw_Metadata_All_FSA.csv"
    xlsx_path = outdir / f"{ROX500_QC_PREFIX}_All_Injections.xlsx"
    html_path = outdir / f"{ROX500_QC_PREFIX}_All_Injections.html"
    json_path = outdir / f"{ROX500_QC_PREFIX}_summary.json"

    qc_df.to_csv(qc_csv, index=False)
    review_df.to_csv(review_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)
    raw_meta_df.to_csv(raw_csv, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        qc_df.to_excel(writer, sheet_name="All_Analyzed_QC", index=False)
        review_df.to_excel(writer, sheet_name="Review_Rows", index=False)
        summary_df.to_excel(writer, sheet_name="Summary_By_Injection", index=False)
        raw_meta_df.to_excel(writer, sheet_name="Raw_Metadata_All_FSA", index=False)
        if skipped:
            pd.DataFrame(skipped).to_excel(writer, sheet_name="Skipped", index=False)

    summary = {
        "input_dir": str(fsa_dir),
        "output_dir": str(outdir),
        "size_standard": "ROX500",
        "internal_ladder": "GS500ROX",
        "preferred_size_standard_channel": str(flt3_size_standard_mode()["size_standard_channel"]),
        "size_standard_channel": (
            ";".join(
                f"{channel}:{count}"
                for channel, count in sorted(Counter(qc_df["SizeStandardChannel"].astype(str)).items())
                if channel
            )
            if "SizeStandardChannel" in qc_df.columns and not qc_df.empty
            else ""
        ),
        "size_standard_channel_counts": dict(Counter(qc_df["SizeStandardChannel"].astype(str)))
        if "SizeStandardChannel" in qc_df.columns and not qc_df.empty
        else {},
        "years": list(years or []),
        "require_run_name_contains": require_run_name_contains,
        "exclude_run_name_contains": exclude_run_name_contains,
        "limit": int(limit or 0),
        "raw_fsa_count": int(len(raw_meta_df)),
        "analyzed_fsa_count": int(len(qc_df)),
        "review_row_count": int(len(review_df)),
        "skipped_count": int(len(skipped)),
        "raw_injection_time_counts": dict(Counter(raw_meta_df["InjectionTimeSeconds"].astype(str)))
        if "InjectionTimeSeconds" in raw_meta_df.columns
        else {},
        "analyzed_injection_time_counts": dict(Counter(qc_df["InjectionTimeSeconds"].astype(str)))
        if "InjectionTimeSeconds" in qc_df.columns
        else {},
        "qc_status_counts": dict(Counter(qc_df["QCStatus"].astype(str))) if "QCStatus" in qc_df.columns else {},
        "ladder_qc_counts": dict(Counter(qc_df["LadderQC"].astype(str))) if "LadderQC" in qc_df.columns else {},
        "peak_qc_counts": dict(Counter(qc_df["PeakQC"].astype(str))) if "PeakQC" in qc_df.columns else {},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_html(html_path, summary, qc_df, summary_df)

    return {
        "run_dir": str(outdir),
        "summary_json": str(json_path),
        "workbook_path": str(xlsx_path),
        "qc_csv": str(qc_csv),
        "review_csv": str(review_csv),
        "summary": summary,
        "validator_summary": {
            "status_counts": summary["qc_status_counts"],
            "ladder_qc_counts": summary["ladder_qc_counts"],
            "peak_qc_counts": summary["peak_qc_counts"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FLT3 ROX500 QC for all injection candidates.")
    parser.add_argument("--fsa-dir", "--data-root", dest="fsa_dir", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--year", dest="years", action="append", default=[])
    parser.add_argument("--require-run-name-contains", default="")
    parser.add_argument("--exclude-run-name-contains", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    payload = run_qc(
        args.fsa_dir.expanduser(),
        args.outdir.expanduser(),
        years=args.years,
        require_run_name_contains=args.require_run_name_contains,
        exclude_run_name_contains=args.exclude_run_name_contains,
        limit=args.limit,
        workers=args.workers,
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
