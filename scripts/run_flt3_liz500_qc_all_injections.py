#!/usr/bin/env python3
"""Run FLT3 LIZ500 QC for every injection candidate, without DIT reports."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from core.analysis import compute_ladder_qc_metrics
from core.analyses.flt3.classification import classify_fsa, get_injection_metadata
from core.analyses.flt3.pipeline import (
    _build_entry_from_candidate,
    _calculate_ratios,
    _scan_files,
    _summarize_detected_peaks,
)


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


def _control_prefix(file_name: str) -> str:
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


def _entry_row(path: Path, meta: dict, entry: dict | None, error: str = "") -> dict[str, Any]:
    if entry is None:
        status, status_reason = _qc_status(None, error)
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
            "Ladder": "LIZ500_250",
            "SizeStandardChannel": "DATA105",
            "SizingMethod": "",
            "LadderQC": "analysis_failed",
            "LadderFitStrategy": "",
            "LadderR2": "",
            "LadderLinearMaxBp": "",
            "LadderLinearMeanBp": "",
            "LadderLinearR2": "",
            "LadderExpectedSteps": "",
            "LadderFittedSteps": "",
            "PeakQC": "",
            "RustPositiveCall": "",
            "RustWTBP": "",
            "RustMutantBPs": "",
            "RustStrongestMutantRatio": "",
            "WT_bp": "",
            "WT_Area": "",
            "Mutant_bp_List": "",
            "Mutant_Area_Total": "",
            "Ratio": "",
            "ReviewReason": error,
        }

    fsa = entry["fsa"]
    metrics = compute_ladder_qc_metrics(fsa)
    peak_summary = _summarize_detected_peaks(entry)
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
        "Ladder": entry.get("ladder") or "LIZ500_250",
        "SizeStandardChannel": "DATA105",
        "SizingMethod": entry.get("sizing_method") or "",
        "LadderQC": entry.get("ladder_qc_status") or "",
        "LadderFitStrategy": entry.get("ladder_fit_strategy") or "",
        "LadderR2": _fmt_float(entry.get("ladder_r2"), 6),
        "LadderLinearMaxBp": _fmt_float(metrics.get("linear_trend_max_abs_error_bp"), 3),
        "LadderLinearMeanBp": _fmt_float(metrics.get("linear_trend_mean_abs_error_bp"), 3),
        "LadderLinearR2": _fmt_float(metrics.get("linear_trend_r2"), 6),
        "LadderExpectedSteps": entry.get("ladder_expected_step_count") or "",
        "LadderFittedSteps": entry.get("ladder_fitted_step_count") or "",
        "PeakQC": entry.get("peak_qc_status") or "",
        "RustPositiveCall": bool(entry.get("rust_preview_positive_call", False)),
        "RustWTBP": _fmt_float(entry.get("rust_preview_wt_bp"), 2),
        "RustMutantBPs": _fmt_list(entry.get("rust_preview_mutant_bps") or []),
        "RustStrongestMutantRatio": _fmt_float(entry.get("rust_preview_strongest_mutant_ratio"), 6),
        "WT_bp": _fmt_float(peak_summary.get("wt_bp"), 2),
        "WT_Area": _fmt_float(peak_summary.get("wt_area"), 2),
        "Mutant_bp_List": _fmt_list(f"{bp:.2f}" for bp in peak_summary.get("mut_bps", [])),
        "Mutant_Area_Total": _fmt_float(peak_summary.get("mut_area_total"), 2),
        "Ratio": _fmt_float(entry.get("ratio"), 6),
        "ReviewReason": entry.get("ladder_review_reason") or entry.get("ladder_review_summary") or "",
    }


def _raw_metadata_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.fsa")):
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
                "IncludedInAnalysis": not path.name.lower().startswith("v_"),
            }
        )
    return rows


def _write_html(out_path: Path, summary: dict[str, Any], qc_df: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    issue_df = qc_df[qc_df["QCStatus"] != "PASS"].copy()
    issue_html = issue_df.to_html(index=False, escape=True) if not issue_df.empty else "<p>No QC issues.</p>"
    by_injection_html = summary_df.to_html(index=False, escape=True)
    top_rows = qc_df.head(96).to_html(index=False, escape=True)
    status_counts = Counter(qc_df["QCStatus"].astype(str))
    injection_counts = Counter(qc_df["InjectionTimeSeconds"].astype(str))

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FLT3 LIZ500 QC all injections</title>
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
  <h1>FLT3 LIZ500 QC - all injections</h1>
  <p>QC-only run. No DIT reports generated. Both 5 s and 10 s injections are included.</p>
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


def run_qc(fsa_dir: Path, outdir: Path) -> dict[str, Any]:
    os.environ["HEMAFRAG_FLT3_LADDER"] = "LIZ500_250"
    os.environ["FRAGGLER_DISABLE_MULTIPROCESSING"] = "1"

    outdir.mkdir(parents=True, exist_ok=True)
    raw_files = _scan_files(fsa_dir, mode="all")
    classified: list[tuple[Path, dict]] = []
    skipped: list[dict[str, Any]] = []
    for path in raw_files:
        meta = classify_fsa(path)
        if meta is None:
            skipped.append({"File": path.name, "SourceRunDir": path.parent.name, "Reason": "not_classified"})
            continue
        classified.append((path, meta))

    entries: list[dict] = []
    entry_records: list[tuple[Path, dict, dict]] = []
    rows: list[dict[str, Any]] = []
    for idx, (path, meta) in enumerate(classified, start=1):
        print(f"[{idx}/{len(classified)}] QC {path.name} ({meta.get('injection_time')}s)")
        try:
            entry = _build_entry_from_candidate(path, meta)
        except Exception as exc:
            rows.append(_entry_row(path, meta, None, f"{type(exc).__name__}: {exc}"))
            continue
        if entry is None:
            rows.append(_entry_row(path, meta, None, "analysis_failed"))
            continue
        entry["selection_reason"] = "QC-only all-injections run; no injection selection applied"
        entry["alternate_injections"] = []
        entry["alternate_injections_summary"] = ""
        entries.append(entry)
        entry_records.append((path, meta, entry))
        rows.append(_entry_row(path, meta, entry))

    if entries:
        _calculate_ratios(entries)
        failure_rows = [row for row in rows if row.get("LadderQC") == "analysis_failed"]
        rows = [_entry_row(path, meta, entry) for path, meta, entry in entry_records] + failure_rows

    qc_df = pd.DataFrame(rows)
    if not qc_df.empty:
        qc_df = qc_df.sort_values(["InjectionTimeSeconds", "Assay", "ControlPrefix", "File"], kind="stable")

    raw_meta_df = pd.DataFrame(_raw_metadata_rows(fsa_dir))
    summary_df = (
        qc_df.groupby(["InjectionTimeSeconds", "Assay", "ControlPrefix", "QCStatus", "LadderQC", "PeakQC"], dropna=False)
        .size()
        .reset_index(name="Count")
        if not qc_df.empty
        else pd.DataFrame()
    )

    qc_csv = outdir / "FLT3_LIZ500_QC_All_Injections.csv"
    summary_csv = outdir / "FLT3_LIZ500_QC_Summary_By_Injection.csv"
    raw_csv = outdir / "FLT3_LIZ500_Raw_Metadata_All_FSA.csv"
    xlsx_path = outdir / "FLT3_LIZ500_QC_All_Injections.xlsx"
    html_path = outdir / "FLT3_LIZ500_QC_All_Injections.html"
    json_path = outdir / "FLT3_LIZ500_QC_summary.json"

    qc_df.to_csv(qc_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)
    raw_meta_df.to_csv(raw_csv, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        qc_df.to_excel(writer, sheet_name="All_Analyzed_QC", index=False)
        summary_df.to_excel(writer, sheet_name="Summary_By_Injection", index=False)
        raw_meta_df.to_excel(writer, sheet_name="Raw_Metadata_All_FSA", index=False)
        if skipped:
            pd.DataFrame(skipped).to_excel(writer, sheet_name="Skipped", index=False)

    summary = {
        "input_dir": str(fsa_dir),
        "output_dir": str(outdir),
        "raw_fsa_count": int(len(raw_meta_df)),
        "analyzed_fsa_count": int(len(qc_df)),
        "skipped_count": int(len(skipped)),
        "raw_injection_time_counts": dict(Counter(raw_meta_df["InjectionTimeSeconds"].astype(str))) if not raw_meta_df.empty else {},
        "analyzed_injection_time_counts": dict(Counter(qc_df["InjectionTimeSeconds"].astype(str))) if not qc_df.empty else {},
        "qc_status_counts": dict(Counter(qc_df["QCStatus"].astype(str))) if not qc_df.empty else {},
        "ladder_qc_counts": dict(Counter(qc_df["LadderQC"].astype(str))) if not qc_df.empty else {},
        "peak_qc_counts": dict(Counter(qc_df["PeakQC"].astype(str))) if not qc_df.empty else {},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_html(html_path, summary, qc_df, summary_df)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FLT3 LIZ500 QC for all 5s/10s injection candidates.")
    parser.add_argument("--fsa-dir", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()

    summary = run_qc(args.fsa_dir.expanduser(), args.outdir.expanduser())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
