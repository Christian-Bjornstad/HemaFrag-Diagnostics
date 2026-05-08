#!/usr/bin/env python3
"""Generate Plotly QC figures for FLT3 LIZ500 all-injection QC runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.analysis import compute_ladder_qc_metrics, estimate_running_baseline
from core.analyses.flt3.classification import classify_fsa, get_injection_metadata
from core.analyses.flt3.pipeline import (
    _build_entry_from_candidate,
    _calculate_ratios,
    _scan_files,
    _summarize_detected_peaks,
)


PLOTLY_ASSET = REPO_ROOT / "assets" / "plotly-3.1.0.min.js"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _fmt(value: Any, digits: int = 3) -> str:
    number = _safe_float(value)
    if not np.isfinite(number):
        return ""
    return f"{number:.{digits}f}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return slug.strip("._") or "plot"


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


def _baseline_correct_sample_trace(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    if values.size == 0:
        return values
    try:
        baseline = estimate_running_baseline(values, bin_size=200, quantile=0.10)
        corrected = values - baseline
        corrected[corrected < 0] = 0.0
        return corrected
    except Exception:
        return values


def _downsample_xy(x: np.ndarray, y: np.ndarray, max_points: int = 9000) -> tuple[np.ndarray, np.ndarray]:
    if x.size <= max_points:
        return x, y
    step = int(np.ceil(x.size / max_points))
    return x[::step], y[::step]


def _trace_at_indices(trace: np.ndarray, indices: np.ndarray) -> np.ndarray:
    indices = np.atleast_1d(np.asarray(indices, dtype=float))
    if trace.size == 0 or indices.size == 0:
        return np.asarray([], dtype=float)
    idx = np.asarray(np.rint(indices), dtype=int)
    idx = np.clip(idx, 0, trace.size - 1)
    return trace[idx]


def _entry_qc_status(entry: dict) -> tuple[str, str]:
    ladder_qc = str(entry.get("ladder_qc_status") or "")
    peak_qc = str(entry.get("peak_qc_status") or "")
    file_name = str(getattr(entry.get("fsa"), "file_name", ""))
    prefix = _control_prefix(file_name)
    rust_positive = bool(entry.get("rust_preview_positive_call", False))
    mutant_bps = list(entry.get("rust_preview_mutant_bps") or [])

    if ladder_qc not in {"ok", "manual_adjustment"}:
        return "REVIEW", ladder_qc or "ladder_qc_failed"
    if prefix == "NK":
        if peak_qc == "no_relevant_peaks" or (not rust_positive and not mutant_bps):
            return "PASS", "negative_control_no_relevant_peaks"
        return "REVIEW", "negative_control_has_relevant_peaks"
    if peak_qc == "ok":
        return "PASS", "ladder_and_peak_qc_ok"
    return "REVIEW", peak_qc or "peak_qc_failed"


def _sample_axis(entry: dict) -> tuple[np.ndarray, np.ndarray] | None:
    fsa = entry["fsa"]
    raw_df = getattr(fsa, "sample_data_with_basepairs", None)
    if raw_df is None or raw_df.empty or not {"time", "basepairs"}.issubset(raw_df.columns):
        return None
    return raw_df["time"].astype(int).to_numpy(), raw_df["basepairs"].astype(float).to_numpy()


def _sample_trace(entry: dict) -> tuple[np.ndarray, np.ndarray] | None:
    fsa = entry["fsa"]
    primary_channel = entry.get("primary_peak_channel")
    axis = _sample_axis(entry)
    if axis is None or primary_channel not in getattr(fsa, "fsa", {}):
        return None
    time_all, bp_all = axis
    raw = np.asarray(fsa.fsa[primary_channel], dtype=float)
    valid = (time_all >= 0) & (time_all < raw.size)
    if not np.any(valid):
        return None
    corrected = _baseline_correct_sample_trace(raw)
    return bp_all[valid], corrected[time_all[valid]]


def _add_ladder_subplot(fig: go.Figure, entry: dict, row: int = 1) -> None:
    fsa = entry["fsa"]
    trace = np.asarray(getattr(fsa, "size_standard", []), dtype=float)
    x = np.arange(trace.size, dtype=float)
    x_plot, y_plot = _downsample_xy(x, trace, max_points=10000)

    fig.add_trace(
        go.Scatter(
            x=x_plot,
            y=y_plot,
            mode="lines",
            name="LIZ500 DATA105 ladder trace",
            line=dict(width=1.15, color="#2563eb"),
            hovertemplate="scan=%{x:.0f}<br>RFU=%{y:.1f}<extra></extra>",
        ),
        row=row,
        col=1,
    )

    candidates = np.atleast_1d(np.asarray(getattr(fsa, "size_standard_peaks", []), dtype=float))
    if candidates.size:
        cand_y = _trace_at_indices(trace, candidates)
        fig.add_trace(
            go.Scatter(
                x=candidates,
                y=cand_y,
                mode="markers",
                name="possible ladder peaks",
                marker=dict(size=6, color="rgba(239,68,68,0.55)", line=dict(width=0)),
                hovertemplate="candidate scan=%{x:.0f}<br>RFU=%{y:.1f}<extra></extra>",
            ),
            row=row,
            col=1,
        )

    selected = np.atleast_1d(np.asarray(getattr(fsa, "best_size_standard", []), dtype=float))
    steps = np.atleast_1d(np.asarray(getattr(fsa, "ladder_steps", []), dtype=float))
    if selected.size:
        selected_y = _trace_at_indices(trace, selected)
        text = [f"{bp:g} bp" for bp in steps[: selected.size]] if steps.size else ["" for _ in selected]
        hover = [
            f"{bp:g} bp<br>scan={scan:.0f}<br>RFU={height:.1f}"
            for bp, scan, height in zip(steps[: selected.size] if steps.size else np.full(selected.size, np.nan), selected, selected_y)
        ]
        fig.add_trace(
            go.Scatter(
                x=selected,
                y=selected_y,
                mode="markers+text",
                name="selected ladder",
                marker=dict(size=10, color="#f97316", line=dict(color="#111827", width=0.8)),
                text=text,
                textposition="top center",
                textfont=dict(size=10, color="#111827"),
                hovertext=hover,
                hoverinfo="text",
            ),
            row=row,
            col=1,
        )


def _add_sample_subplot(fig: go.Figure, entry: dict, row: int = 2) -> None:
    sample = _sample_trace(entry)
    if sample is None:
        fig.add_annotation(text="No sample bp trace available", row=row, col=1, showarrow=False)
        return
    bp, y = sample
    bp_plot, y_plot = _downsample_xy(bp, y, max_points=10000)
    primary_channel = str(entry.get("primary_peak_channel") or "")

    fig.add_trace(
        go.Scatter(
            x=bp_plot,
            y=y_plot,
            mode="lines",
            name=f"{primary_channel} sample trace",
            line=dict(width=1.15, color="#059669"),
            hovertemplate="bp=%{x:.2f}<br>RFU=%{y:.1f}<extra></extra>",
        ),
        row=row,
        col=1,
    )

    peaks = entry.get("peaks_by_channel", {}).get(primary_channel, pd.DataFrame())
    if isinstance(peaks, pd.DataFrame) and not peaks.empty:
        color_by_label = {
            "WT": "#2563eb",
            "MUT": "#dc2626",
            "ITD": "#dc2626",
            "NS": "#64748b",
        }
        for label, group in peaks.groupby(peaks["label"].astype(str)):
            marker_color = color_by_label.get(label, "#7c3aed")
            hover = [
                (
                    f"{label}<br>bp={float(peak_row.basepairs):.2f}"
                    f"<br>height={float(peak_row.peaks):.1f}"
                    f"<br>area={float(peak_row.area):.1f}"
                )
                for peak_row in group.itertuples(index=False)
            ]
            fig.add_trace(
                go.Scatter(
                    x=group["basepairs"].astype(float).to_numpy(),
                    y=group["peaks"].astype(float).to_numpy(),
                    mode="markers+text",
                    name=f"{label} peaks",
                    marker=dict(size=9, color=marker_color, line=dict(color="white", width=0.8)),
                    text=[label for _ in range(len(group))],
                    textposition="top center",
                    textfont=dict(size=9),
                    hovertext=hover,
                    hoverinfo="text",
                ),
                row=row,
                col=1,
            )


def _build_figure(entry: dict) -> go.Figure:
    fsa = entry["fsa"]
    qc_status, qc_reason = _entry_qc_status(entry)
    metrics = compute_ladder_qc_metrics(fsa)
    peak_summary = _summarize_detected_peaks(entry)

    title = (
        f"{fsa.file_name} | {entry.get('injection_time')}s | "
        f"{entry.get('assay')} | {qc_status}: {qc_reason}"
    )
    subtitle = (
        f"Ladder {entry.get('ladder')} / {entry.get('sizing_method')} | "
        f"linear max {_fmt(metrics.get('linear_trend_max_abs_error_bp'))} bp, "
        f"mean {_fmt(metrics.get('linear_trend_mean_abs_error_bp'))} bp, "
        f"R2 {_fmt(metrics.get('linear_trend_r2'), 6)} | "
        f"WT {_fmt(peak_summary.get('wt_bp'), 2)} bp | "
        f"Mutants {', '.join(f'{v:.2f}' for v in peak_summary.get('mut_bps', [])) or '-'}"
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.12,
        subplot_titles=("Ladder trace by scan", "Sample trace by basepair"),
    )
    _add_ladder_subplot(fig, entry, row=1)
    _add_sample_subplot(fig, entry, row=2)

    fig.update_layout(
        title=dict(text=f"{escape(title)}<br><sup>{escape(subtitle)}</sup>", x=0.02, xanchor="left"),
        template="plotly_white",
        height=860,
        margin=dict(l=70, r=35, t=115, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
        hovermode="closest",
    )
    fig.update_xaxes(title_text="Scan index", row=1, col=1, rangeslider=dict(visible=True, thickness=0.05))
    fig.update_yaxes(title_text="RFU", row=1, col=1, rangemode="tozero")
    fig.update_xaxes(title_text="Basepairs (bp)", row=2, col=1)
    fig.update_yaxes(title_text="RFU", row=2, col=1, rangemode="tozero")

    try:
        bp_min = float(entry.get("bp_min", np.nan))
        bp_max = float(entry.get("bp_max", np.nan))
        if np.isfinite(bp_min) and np.isfinite(bp_max) and bp_max > bp_min:
            fig.update_xaxes(range=[max(0.0, bp_min - 20), bp_max + 40], row=2, col=1)
    except Exception:
        pass

    return fig


def _write_standalone_figure(fig: go.Figure, out_path: Path, *, title: str) -> None:
    fragment = fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"responsive": True, "displaylogo": False, "scrollZoom": True},
    )
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <script src="../plotly-3.1.0.min.js"></script>
  <style>
    body {{ margin: 0; padding: 18px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #0f172a; }}
    .wrap {{ max-width: 1500px; margin: 0 auto; background: white; border: 1px solid #dbeafe; border-radius: 18px; padding: 14px; box-shadow: 0 18px 55px rgba(15,23,42,0.08); }}
    a {{ color: #2563eb; text-decoration: none; font-weight: 700; }}
  </style>
</head>
<body>
  <p><a href="../FLT3_LIZ500_QC_Plotly_Index.html">Back to Plotly index</a></p>
  <div class="wrap">{fragment}</div>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def _copy_plotly_asset(outdir: Path) -> None:
    if not PLOTLY_ASSET.exists():
        raise FileNotFoundError(f"Missing bundled Plotly asset: {PLOTLY_ASSET}")
    shutil.copy2(PLOTLY_ASSET, outdir / "plotly-3.1.0.min.js")


def _write_index(outdir: Path, rows: list[dict[str, Any]]) -> None:
    status_counts = Counter(str(row.get("QCStatus") or "") for row in rows)
    injection_counts = Counter(str(row.get("InjectionTimeSeconds") or "") for row in rows)
    table_rows = []
    for row in rows:
        link = escape(str(row["Figure"]))
        table_rows.append(
            "<tr>"
            f"<td><a href='{link}'>{escape(str(row['File']))}</a></td>"
            f"<td>{escape(str(row['InjectionTimeSeconds']))}s</td>"
            f"<td>{escape(str(row['Assay']))}</td>"
            f"<td>{escape(str(row['ControlPrefix']))}</td>"
            f"<td>{escape(str(row['QCStatus']))}</td>"
            f"<td>{escape(str(row['QCReason']))}</td>"
            f"<td>{escape(str(row['LadderQC']))}</td>"
            f"<td>{escape(str(row['PeakQC']))}</td>"
            f"<td>{escape(str(row['LinearMaxBp']))}</td>"
            f"<td>{escape(str(row['LinearMeanBp']))}</td>"
            f"<td>{escape(str(row['LinearR2']))}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FLT3 LIZ500 QC Plotly figures</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; background: #f8fafc; color: #0f172a; }}
    .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 18px 0; }}
    .card {{ background: white; border: 1px solid #dbeafe; border-radius: 14px; padding: 14px 18px; min-width: 150px; box-shadow: 0 8px 28px rgba(15,23,42,0.06); }}
    .label {{ color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    .value {{ font-size: 24px; font-weight: 800; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; font-size: 13px; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 7px 8px; text-align: left; }}
    th {{ background: #e0f2fe; position: sticky; top: 0; z-index: 2; }}
    a {{ color: #2563eb; text-decoration: none; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>FLT3 LIZ500 QC Plotly figures</h1>
  <p>Interaktive ladder- og sample-traces for alle analyserte QC-kandidater. Begge injeksjonstider er inkludert.</p>
  <div class="cards">
    <div class="card"><div class="label">Figures</div><div class="value">{len(rows)}</div></div>
    <div class="card"><div class="label">PASS</div><div class="value">{status_counts.get("PASS", 0)}</div></div>
    <div class="card"><div class="label">REVIEW</div><div class="value">{status_counts.get("REVIEW", 0)}</div></div>
    <div class="card"><div class="label">5 s</div><div class="value">{injection_counts.get("5", 0)}</div></div>
    <div class="card"><div class="label">10 s</div><div class="value">{injection_counts.get("10", 0)}</div></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>File</th><th>Injection</th><th>Assay</th><th>Control</th><th>QC</th><th>Reason</th>
        <th>LadderQC</th><th>PeakQC</th><th>Linear max</th><th>Linear mean</th><th>Linear R2</th>
      </tr>
    </thead>
    <tbody>
      {''.join(table_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    (outdir / "FLT3_LIZ500_QC_Plotly_Index.html").write_text(html, encoding="utf-8")


def _metadata_row(path: Path, meta: dict, entry: dict, rel_figure: str) -> dict[str, Any]:
    fsa = entry["fsa"]
    metrics = compute_ladder_qc_metrics(fsa)
    qc_status, qc_reason = _entry_qc_status(entry)
    return {
        "File": fsa.file_name,
        "Figure": rel_figure,
        "SourceRunDir": meta.get("source_run_dir") or path.parent.name,
        "InjectionTimeSeconds": int(meta.get("injection_time", 0) or 0),
        "InjectionVoltage": meta.get("injection_voltage", ""),
        "InjectionProtocol": meta.get("injection_protocol", ""),
        "RunDate": meta.get("run_date", ""),
        "RunTime": meta.get("run_time", ""),
        "RunName": meta.get("run_name", ""),
        "Well": meta.get("well_id") or "",
        "SpecimenID": meta.get("specimen_id") or "",
        "ControlPrefix": _control_prefix(fsa.file_name),
        "Assay": entry.get("assay") or "",
        "Treatment": entry.get("analysis_type") or "",
        "QCStatus": qc_status,
        "QCReason": qc_reason,
        "LadderQC": entry.get("ladder_qc_status") or "",
        "PeakQC": entry.get("peak_qc_status") or "",
        "Ladder": entry.get("ladder") or "",
        "SizingMethod": entry.get("sizing_method") or "",
        "LinearMaxBp": _fmt(metrics.get("linear_trend_max_abs_error_bp"), 3),
        "LinearMeanBp": _fmt(metrics.get("linear_trend_mean_abs_error_bp"), 3),
        "LinearR2": _fmt(metrics.get("linear_trend_r2"), 6),
        "SelectedLadderScans": json.dumps([int(round(v)) for v in np.asarray(getattr(fsa, "best_size_standard", []), dtype=float)]),
        "SelectedLadderBPs": json.dumps([float(v) for v in np.asarray(getattr(fsa, "ladder_steps", []), dtype=float)]),
    }


def generate_figures(fsa_dir: Path, outdir: Path) -> dict[str, Any]:
    os.environ["HEMAFRAG_FLT3_LADDER"] = "LIZ500_250"
    os.environ["FRAGGLER_DISABLE_MULTIPROCESSING"] = "1"

    plotly_dir = outdir / "plotly_figures"
    figures_dir = plotly_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _copy_plotly_asset(plotly_dir)

    raw_files = _scan_files(fsa_dir, mode="all")
    classified: list[tuple[Path, dict]] = []
    for path in raw_files:
        meta = classify_fsa(path)
        if meta is not None:
            classified.append((path, meta))

    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for idx, (path, meta) in enumerate(classified, start=1):
        print(f"[{idx}/{len(classified)}] Plotly {path.name} ({meta.get('injection_time')}s)", flush=True)
        try:
            entry = _build_entry_from_candidate(path, meta)
        except Exception as exc:
            failures.append({"File": path.name, "SourceRunDir": path.parent.name, "Error": f"{type(exc).__name__}: {exc}"})
            continue
        if entry is None:
            failures.append({"File": path.name, "SourceRunDir": path.parent.name, "Error": "analysis_failed"})
            continue
        entry["selection_reason"] = "Plotly QC all-injections run; no injection selection applied"
        entry["alternate_injections"] = []
        entry["alternate_injections_summary"] = ""
        _calculate_ratios([entry])
        stem = _slug(f"{int(meta.get('injection_time', 0) or 0)}s_{path.stem}")
        file_name = f"{stem}.html"
        if file_name in used_names:
            file_name = f"{stem}_{len(used_names) + 1}.html"
        used_names.add(file_name)
        rel_figure = f"figures/{file_name}"
        try:
            fig = _build_figure(entry)
            _write_standalone_figure(fig, figures_dir / file_name, title=path.name)
            rows.append(_metadata_row(path, meta, entry, rel_figure))
        except Exception as exc:
            failures.append({"File": path.name, "SourceRunDir": path.parent.name, "Error": f"plot_write_failed: {type(exc).__name__}: {exc}"})

    rows.sort(key=lambda row: (int(row.get("InjectionTimeSeconds") or 0), str(row.get("Assay") or ""), str(row.get("File") or "")))
    pd.DataFrame(rows).to_csv(plotly_dir / "FLT3_LIZ500_QC_Plotly_Index.csv", index=False)
    if failures:
        pd.DataFrame(failures).to_csv(plotly_dir / "FLT3_LIZ500_QC_Plotly_Failures.csv", index=False)
    _write_index(plotly_dir, rows)

    raw_meta_rows = []
    for path in sorted(fsa_dir.rglob("*.fsa")):
        meta = get_injection_metadata(path)
        raw_meta_rows.append(
            {
                "SourceRunDir": path.parent.name,
                "File": path.name,
                "InjectionTimeSeconds": meta.get("injection_time", ""),
                "InjectionVoltage": meta.get("injection_voltage", ""),
                "InjectionProtocol": meta.get("injection_protocol", ""),
                "RunDate": meta.get("run_date", ""),
                "RunTime": meta.get("run_time", ""),
                "RunName": meta.get("run_name", ""),
            }
        )
    raw_counts = Counter(str(row["InjectionTimeSeconds"]) for row in raw_meta_rows)
    analyzed_counts = Counter(str(row["InjectionTimeSeconds"]) for row in rows)
    summary = {
        "input_dir": str(fsa_dir),
        "output_dir": str(plotly_dir),
        "figure_count": len(rows),
        "failure_count": len(failures),
        "raw_fsa_count": len(raw_meta_rows),
        "raw_injection_time_counts": dict(raw_counts),
        "analyzed_injection_time_counts": dict(analyzed_counts),
        "qc_status_counts": dict(Counter(str(row["QCStatus"]) for row in rows)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (plotly_dir / "FLT3_LIZ500_QC_Plotly_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Plotly ladder/sample figures for FLT3 LIZ500 QC.")
    parser.add_argument("--fsa-dir", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()

    summary = generate_figures(args.fsa_dir.expanduser(), args.outdir.expanduser())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
