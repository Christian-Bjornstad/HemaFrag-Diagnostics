from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import APP_SETTINGS
from core.analyses.clonality.interpretation import (
    ANNOTATION_CLASSES,
    ANNOTATION_SCHEMA_VERSION,
    CONTROL_FLAGS,
    DEFAULT_SAMPLE_QUOTAS,
    assay_interpretation_range,
    assay_interpretation_ranges,
    features_from_entry,
    interpret_entry,
    sample_annotation_files,
    utc_now_iso,
    write_rows_csv,
)
from core.analyses.clonality.pipeline import _analyze_single_file
from core.batch import generate_jobs
from core.plotting_mpl import draw_multi_channel_zoom_on_ax


def collect_candidate_files(input_root: Path, *, run_date_filter: str = "latest") -> tuple[list[Path], dict[str, Any]]:
    previous_active = APP_SETTINGS.get("active_analysis", "clonality")
    APP_SETTINGS["active_analysis"] = "clonality"
    try:
        jobs = generate_jobs([input_root], aggregate_patients=True, run_date_filter=run_date_filter)
    finally:
        APP_SETTINGS["active_analysis"] = previous_active

    files: list[Path] = []
    scan_summary: dict[str, Any] = {}
    for job in jobs:
        files.extend(Path(path) for path in job.get("files", []) or [])
        if not scan_summary and isinstance(job.get("_scan_summary"), dict):
            scan_summary = dict(job["_scan_summary"])
    return sorted(set(files)), scan_summary


def render_annotation_panel(
    *,
    input_root: Path,
    out_dir: Path,
    limit: int = 500,
    sample_offset: int = 0,
    run_date_filter: str = "latest",
    annotator: str = "",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    candidates, scan_summary = collect_candidate_files(input_root, run_date_filter=run_date_filter)
    sample_offset = max(0, int(sample_offset or 0))
    base_quotas = _scaled_sample_quotas(DEFAULT_SAMPLE_QUOTAS, limit)
    selected_pool, sample_summary = sample_annotation_files(
        candidates,
        limit=limit + sample_offset,
        quotas=_offset_quotas(base_quotas, sample_offset),
    )
    selected_files = selected_pool[sample_offset : sample_offset + limit]
    sample_summary["sample_offset"] = sample_offset
    sample_summary["selected_total_after_offset"] = len(selected_files)

    rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for ordinal, raw_path in enumerate(selected_files, start=1):
        entry = _analyze_single_file(raw_path)
        if not isinstance(entry, dict):
            skipped.append({"raw_path": str(raw_path), "reason": "analysis_skipped"})
            continue
        features = features_from_entry(entry)
        interpretation = interpret_entry(entry)
        image_path = _plot_entry(entry, image_dir=image_dir, ordinal=ordinal)
        row = {
            "ordinal": len(rows) + 1,
            "raw_path": str(raw_path),
            "file": raw_path.name,
            "assay": features.get("assay", ""),
            "ladder": features.get("ladder", ""),
            "sample_kind": features.get("sample_kind", ""),
            "control": features.get("control", ""),
            "run_date": features.get("run_date", ""),
            "patient_id": _patient_id_from_file(raw_path.name),
            "primary_peak_channel": features.get("primary_peak_channel", ""),
            "ladder_qc_status": features.get("ladder_qc_status", ""),
            "ladder_fit_strategy": entry.get("ladder_fit_strategy", ""),
            "ladder_linear_mean_residual_bp": features.get("ladder_linear_mean_residual_bp", 0.0),
            "ladder_linear_max_residual_bp": features.get("ladder_linear_max_residual_bp", 0.0),
            "raw_peak_count": features.get("raw_peak_count", 0),
            "peak_count": features.get("peak_count", 0),
            "peak_count_in_interpretation_range": features.get("peak_count_in_interpretation_range", 0),
            "peak_count_outside_interpretation_range": features.get("peak_count_outside_interpretation_range", 0),
            "nonspecific_peak_count": features.get("nonspecific_peak_count", 0),
            "nonspecific_peak_basepairs": features.get("nonspecific_peak_basepairs", ""),
            "nonspecific_height_share": features.get("nonspecific_height_share", 0.0),
            "dominant_peak_basepairs": features.get("dominant_peak_basepairs", 0.0),
            "dominant_peak_in_interpretation_range": features.get("dominant_peak_in_interpretation_range", False),
            "dominant_peak_is_nonspecific": features.get("dominant_peak_is_nonspecific", False),
            "outside_interpretation_height_share": features.get("outside_interpretation_height_share", 0.0),
            "interpretation_range_min_bp": features.get("interpretation_range_min_bp", 0.0),
            "interpretation_range_max_bp": features.get("interpretation_range_max_bp", 0.0),
            "interpretation_ranges_bp": features.get("interpretation_ranges_bp", ""),
            "dominant_peak_height": features.get("dominant_peak_height", 0.0),
            "dominant_to_second_ratio": features.get("dominant_to_second_ratio", 0.0),
            "dominant_height_share": features.get("dominant_height_share", 0.0),
            "sl_100_percent": features.get("sl_100_percent", 0.0),
            "sl_200_percent": features.get("sl_200_percent", 0.0),
            "sl_300_percent": features.get("sl_300_percent", 0.0),
            "sl_400_percent": features.get("sl_400_percent", 0.0),
            "sl_600_percent": features.get("sl_600_percent", 0.0),
            "sl_fragmented_percent": features.get("sl_fragmented_percent", 0.0),
            "sl_quality_class": features.get("sl_quality_class", ""),
            "sl_quality_phrase": features.get("sl_quality_phrase", ""),
            "suggestion": interpretation.get("ClonalitySuggestion", ""),
            "confidence": interpretation.get("ClonalityConfidence", ""),
            "review_needed": interpretation.get("ClonalityReviewNeeded", ""),
            "evidence": interpretation.get("ClonalityEvidence", ""),
            "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
            "image": _relative_or_uri(image_path, out_dir) if image_path else "",
        }
        rows.append(row)
        feature_rows.append({**features, "ordinal": row["ordinal"]})
        if ordinal % 25 == 0 or ordinal == len(selected_files):
            print(f"rendered {ordinal}/{len(selected_files)}", flush=True)

    annotation_csv = write_rows_csv(rows, out_dir / "annotation_rows.csv")
    feature_csv = write_rows_csv(feature_rows, out_dir / "feature_rows.csv")
    html_path = out_dir / "review_panel.html"
    html_path.write_text(
        build_html(rows, title="HemaFrag clonality interpretation annotation", annotator=annotator),
        encoding="utf-8",
    )
    summary = {
        "generated_at_utc": utc_now_iso(),
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "input_root": str(input_root),
        "out_dir": str(out_dir),
        "html": str(html_path),
        "annotation_rows_csv": str(annotation_csv),
        "feature_rows_csv": str(feature_csv),
        "limit": int(limit),
        "sample_offset": sample_offset,
        "run_date_filter": run_date_filter,
        "scan_summary": scan_summary,
        "sample_summary": sample_summary,
        "rendered_rows": len(rows),
        "skipped_rows": len(skipped),
        "skipped": skipped[:200],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def build_html(rows: Sequence[dict[str, Any]], *, title: str, annotator: str = "") -> str:
    enriched_rows = _attach_parallel_context(list(rows))
    rows_json = json.dumps(enriched_rows, ensure_ascii=True).replace("</", "<\\/")
    class_buttons = "".join(_button(value, value.replace("_", " ")) for value in ANNOTATION_CLASSES)
    flag_buttons = "".join(_flag_button(value, value.replace("_", " ")) for value in CONTROL_FLAGS)
    cards = []
    for row in enriched_rows:
        ident = f"case-{int(row.get('ordinal', 0)):04d}"
        image = str(row.get("image") or "")
        control = str(row.get("control") or "")
        control_block = f"<span class='bar-label'>Flags:</span>{flag_buttons}" if control else ""
        cards.append(
            f"""
<section class="case" id="{ident}" data-raw-path="{html.escape(str(row.get('raw_path') or ''))}">
  <div class="case-head">
    <div>
      <div class="case-title">{int(row.get('ordinal', 0)):03d}. {html.escape(str(row.get('file') or ''))}</div>
      <div class="meta">
        {html.escape(str(row.get('assay') or 'UNKNOWN'))} | {html.escape(str(row.get('ladder') or ''))}
        | {html.escape(str(row.get('sample_kind') or ''))}{' / ' + html.escape(control) if control else ''}
        | QC {html.escape(str(row.get('ladder_qc_status') or ''))}
        | fit {html.escape(str(row.get('ladder_fit_strategy') or ''))}
      </div>
      <div class="meta">
        Raw peaks={html.escape(str(row.get('raw_peak_count', row.get('peak_count'))))}
        | interpreted={html.escape(str(row.get('peak_count')))}
        | in-range={html.escape(str(row.get('peak_count_in_interpretation_range')))}
        | outside={html.escape(str(row.get('peak_count_outside_interpretation_range')))}
        | uspesifikke={html.escape(str(row.get('nonspecific_peak_count') or 0))}
        | dominant-bp={_fmt(row.get('dominant_peak_basepairs'))}
        | top={_fmt(row.get('dominant_peak_height'))}
        | ratio={_fmt(row.get('dominant_to_second_ratio'))}
        | share={_fmt(row.get('dominant_height_share'))}
      </div>
      <div class="meta">
        Range={_range_text(row)}
        | outside-share={_fmt(row.get('outside_interpretation_height_share'))}
        | uspesifikk-share={_fmt(row.get('nonspecific_height_share'))}
        | uspesifikke-bp={html.escape(str(row.get('nonspecific_peak_basepairs') or ''))}
        | linear residual mean/max={_fmt(row.get('ladder_linear_mean_residual_bp'))}/{_fmt(row.get('ladder_linear_max_residual_bp'))} bp
      </div>
      <div class="suggestion">
        Suggestion: <strong>{html.escape(str(row.get('suggestion') or ''))}</strong>
        ({html.escape(str(row.get('confidence') or ''))})
        {' review needed' if row.get('review_needed') else ''}
        <span>{html.escape(str(row.get('evidence') or ''))}</span>
      </div>
      {_sl_quality_html(row)}
      {_parallel_html(row)}
      <details class="path"><summary>File path</summary>{html.escape(str(row.get('raw_path') or ''))}</details>
    </div>
  </div>
  <div class="annotate-bar"><span class="bar-label">Class:</span>{class_buttons}{control_block}</div>
  <div class="plot-scroll">{'<img src="' + html.escape(image) + '" alt="' + html.escape(str(row.get('file') or '')) + '">' if image else '<div class="missing">Image unavailable</div>'}</div>
  <div class="note-row"><textarea placeholder="Note"></textarea></div>
</section>
"""
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #111827; }}
header {{ position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #d1d5db; padding: 12px 18px; display: flex; gap: 16px; justify-content: space-between; align-items: center; }}
h1 {{ margin: 0; font-size: 18px; }}
.sub {{ color: #475569; font-size: 13px; }}
main {{ max-width: 1280px; margin: 0 auto; padding: 16px; }}
.case {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 18px; padding: 0; overflow: hidden; }}
.case-head {{ padding: 10px 14px; border-bottom: 1px solid #f1f5f9; }}
.plot-scroll {{ overflow-x: auto; }}
.case-title {{ font-weight: 700; font-size: 14px; }}
.meta, .path, .suggestion, .sl-quality, .parallel {{ margin-top: 4px; font-size: 12px; color: #374151; }}
.path {{ color: #64748b; font-size: 11px; word-break: break-all; }}
.path summary {{ cursor: pointer; color: #94a3b8; }}
.suggestion span {{ color: #64748b; margin-left: 8px; }}
.sl-quality span {{ color: #64748b; margin-left: 8px; }}
.parallel a {{ color: #0f766e; text-decoration: none; margin-right: 8px; }}
.annotate-bar {{ position: sticky; top: 52px; z-index: 5; background: #f8fafc; padding: 6px 14px; border-bottom: 1px solid #e2e8f0; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }}
.annotate-bar .bar-label {{ font-size: 11px; color: #64748b; margin-right: 4px; font-weight: 600; }}
.note-row {{ padding: 8px 14px; }}
button {{ border: 1px solid #94a3b8; background: #fff; border-radius: 6px; padding: 6px 9px; cursor: pointer; font-size: 12px; }}
button.active {{ background: #111827; color: #fff; border-color: #111827; }}
button.flag.active {{ background: #0f766e; border-color: #0f766e; }}
#export {{ background: #0f766e; color: #fff; border-color: #0f766e; }}
#status {{ font-size: 12px; color: #166534; margin-left: 8px; }}
img {{ width: 100%; max-width: 880px; height: auto; display: block; border: 1px solid #e5e7eb; border-radius: 4px; background: #fff; }}
textarea {{ width: 100%; min-height: 72px; box-sizing: border-box; font: 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; }}
#export-box {{ display: none; margin: 16px; padding: 12px; background: #ecfeff; border: 1px solid #67e8f9; border-radius: 8px; }}
#export-box textarea {{ min-height: 260px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; }}
.missing {{ padding: 40px; text-align: center; color: #64748b; border: 1px dashed #cbd5e1; border-radius: 4px; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>{html.escape(title)}</h1>
    <div class="sub">{len(rows)} cases. Pick one class per file; control flags are optional.</div>
  </div>
  <div>
    <input id="annotator" placeholder="Annotator" value="{html.escape(annotator)}">
    <button id="export" type="button">Export annotations</button>
    <span id="status">Loading controls...</span>
  </div>
</header>
<section id="export-box">
  <strong>Export JSON</strong>
  <div class="sub">If download is blocked, copy this text. CSV is downloaded at the same time when possible.</div>
  <textarea id="export-text" spellcheck="false"></textarea>
</section>
<main>
{''.join(cards)}
</main>
<script id="row-data" type="application/json">{rows_json}</script>
<script>
const schemaVersion = {json.dumps(ANNOTATION_SCHEMA_VERSION)};
const storageKey = "hemafrag_clonality_interpretation:" + location.pathname;
const rows = JSON.parse(document.getElementById("row-data").textContent);
let state = {{}};
try {{ state = JSON.parse(window.localStorage.getItem(storageKey) || "{{}}"); }} catch (error) {{ state = {{}}; }}
function save() {{
  try {{ window.localStorage.setItem(storageKey, JSON.stringify(state)); }} catch (error) {{}}
}}
function csvEscape(value) {{
  const text = String(value ?? "");
  return /[",\\n]/.test(text) ? '"' + text.replaceAll('"', '""') + '"' : text;
}}
for (const card of document.querySelectorAll(".case")) {{
  const key = card.dataset.rawPath;
  state[key] = state[key] || {{}};
  const note = card.querySelector("textarea");
  note.value = state[key].note || "";
  note.addEventListener("input", () => {{ state[key].note = note.value; save(); }});
  for (const button of card.querySelectorAll("button[data-class]")) {{
    if (state[key].label === button.dataset.class) button.classList.add("active");
  }}
  for (const button of card.querySelectorAll("button[data-flag]")) {{
    const flags = state[key].control_flags || [];
    if (flags.includes(button.dataset.flag)) button.classList.add("active");
  }}
}}
document.addEventListener("click", event => {{
  const classButton = event.target.closest("button[data-class]");
  if (classButton) {{
    const card = classButton.closest(".case");
    const key = card.dataset.rawPath;
    state[key] = state[key] || {{}};
    state[key].label = classButton.dataset.class;
    for (const peer of card.querySelectorAll("button[data-class]")) peer.classList.remove("active");
    classButton.classList.add("active");
    save();
    return;
  }}
  const flagButton = event.target.closest("button[data-flag]");
  if (flagButton) {{
    const card = flagButton.closest(".case");
    const key = card.dataset.rawPath;
    state[key] = state[key] || {{}};
    const flags = new Set(state[key].control_flags || []);
    if (flags.has(flagButton.dataset.flag)) {{
      flags.delete(flagButton.dataset.flag);
      flagButton.classList.remove("active");
    }} else {{
      flags.add(flagButton.dataset.flag);
      flagButton.classList.add("active");
    }}
    state[key].control_flags = Array.from(flags);
    save();
  }}
}});
function download(name, text, type) {{
  const blob = new Blob([text], {{type}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}}
document.getElementById("export").addEventListener("click", () => {{
  const annotator = document.getElementById("annotator").value || "";
  const exportedAt = new Date().toISOString();
  const exportRows = rows.map(row => {{
    const item = state[row.raw_path] || {{}};
    return {{
      ...row,
      label: item.label || "",
      control_flags: item.control_flags || [],
      note: item.note || "",
      annotator,
      exported_at: exportedAt,
      annotation_schema_version: schemaVersion,
    }};
  }});
  const payload = {{annotation_schema_version: schemaVersion, exported_at: exportedAt, annotator, rows: exportRows}};
  const text = JSON.stringify(payload, null, 2);
  document.getElementById("export-box").style.display = "block";
  document.getElementById("export-text").value = text;
  const columns = [
    "raw_path","file","assay","ladder","sample_kind","control","run_date","patient_id",
    "raw_peak_count","peak_count","peak_count_in_interpretation_range","peak_count_outside_interpretation_range",
    "nonspecific_peak_count","nonspecific_peak_basepairs","nonspecific_height_share",
    "dominant_peak_basepairs","dominant_peak_height","dominant_to_second_ratio","dominant_height_share",
    "dominant_peak_is_nonspecific","outside_interpretation_height_share",
    "interpretation_range_min_bp","interpretation_range_max_bp","interpretation_ranges_bp",
    "sl_100_percent","sl_200_percent","sl_300_percent","sl_400_percent","sl_600_percent",
    "sl_fragmented_percent","sl_quality_class","sl_quality_phrase",
    "label","control_flags","note","annotator","exported_at","annotation_schema_version"
  ];
  const csv = [columns.join(",")].concat(exportRows.map(row => columns.map(col => csvEscape(Array.isArray(row[col]) ? row[col].join(";") : row[col])).join(","))).join("\\n");
  try {{
    download("clonality_interpretation_annotations.json", text, "application/json");
    download("clonality_interpretation_annotations.csv", csv, "text/csv");
  }} catch (error) {{
    console.warn("Download failed; JSON remains visible in export box.", error);
  }}
}});
document.getElementById("status").textContent = "Controls ready";
</script>
</body>
</html>
"""


def _plot_entry(entry: dict[str, Any], *, image_dir: Path, ordinal: int) -> Path | None:
    fsa = entry.get("fsa")
    if fsa is None:
        return None
    fig, ax = plt.subplots(figsize=(14.0, 5.0), dpi=140)
    try:
        draw_multi_channel_zoom_on_ax(
            ax,
            fsa,
            entry.get("peaks_by_channel") or {},
            entry.get("trace_channels") or [],
            str(entry.get("primary_peak_channel") or ""),
            float(entry.get("bp_min") or 0.0),
            float(entry.get("bp_max") or 500.0),
            assay_name=str(entry.get("assay") or ""),
        )
        x_min, x_max = _plot_zoom_range(entry)
        if x_min < x_max:
            ax.set_xlim(x_min, x_max)
        for start_bp, end_bp in assay_interpretation_ranges(str(entry.get("assay") or "")):
            ax.axvspan(float(start_bp), float(end_bp), color="#c7d2fe", alpha=0.16, zorder=0)
        ax.axhline(0, color="#475569", linewidth=0.7, alpha=0.55)
        ymax = float(entry.get("ymax") or 0.0)
        if np.isfinite(ymax) and ymax > 0:
            ax.set_ylim(bottom=min(0.0, ax.get_ylim()[0]), top=max(ymax * 1.18, ax.get_ylim()[1]))
        # Subtitle: assay + sample_kind + channel info for context
        subtitle = f"assay={entry.get('assay','')}  kind={entry.get('sample_kind','')}  ch={entry.get('primary_peak_channel','')}"
        ax.set_xlabel(subtitle, fontsize=8, color="#475569")
        fig.tight_layout()
        out = image_dir / f"{ordinal:04d}_{_safe_name(str(entry.get('file_name') or 'case'))}.png"
        fig.savefig(out)
        return out
    except Exception as exc:
        ax.clear()
        ax.text(0.5, 0.5, f"Plot failed: {exc}", ha="center", va="center", transform=ax.transAxes)
        fig.tight_layout()
        out = image_dir / f"{ordinal:04d}_{_safe_name(str(entry.get('file_name') or 'case'))}_plot_failed.png"
        fig.savefig(out)
        return out
    finally:
        plt.close(fig)


def _button(value: str, label: str) -> str:
    return f"<button type='button' data-class='{html.escape(value)}'>{html.escape(label)}</button>"


def _flag_button(value: str, label: str) -> str:
    return f"<button class='flag' type='button' data-flag='{html.escape(value)}'>{html.escape(label)}</button>"


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _range_text(row: dict[str, Any]) -> str:
    ranges_text = str(row.get("interpretation_ranges_bp") or "")
    if ranges_text:
        return f"{ranges_text} bp"
    lo = _fmt(row.get("interpretation_range_min_bp"))
    hi = _fmt(row.get("interpretation_range_max_bp"))
    if not lo or not hi or (lo == "0.00" and hi == "0.00"):
        return "not set"
    return f"{lo}-{hi} bp"


def _parallel_html(row: dict[str, Any]) -> str:
    links = row.get("parallel_links") or []
    if not links:
        return ""
    rendered = " ".join(
        f"<a href='#{html.escape(str(item.get('id') or ''))}'>{html.escape(str(item.get('label') or ''))}</a>"
        for item in links
    )
    return f"<div class='parallel'>Paralleller: {rendered}</div>"


def _sl_quality_html(row: dict[str, Any]) -> str:
    if str(row.get("assay") or "").upper() != "SL":
        return ""
    return (
        "<div class='sl-quality'>"
        f"SL quality: <strong>{html.escape(str(row.get('sl_quality_class') or ''))}</strong>"
        f" | fragmented={_fmt(row.get('sl_fragmented_percent'))}%"
        f" | 100/200/300/400/600={_fmt(row.get('sl_100_percent'))}/"
        f"{_fmt(row.get('sl_200_percent'))}/{_fmt(row.get('sl_300_percent'))}/"
        f"{_fmt(row.get('sl_400_percent'))}/{_fmt(row.get('sl_600_percent'))}%"
        f"<span>{html.escape(str(row.get('sl_quality_phrase') or ''))}</span>"
        "</div>"
    )


def _attach_parallel_context(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_patient: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        patient_id = str(row.get("patient_id") or "")
        if patient_id:
            by_patient.setdefault(patient_id, []).append(row)
    for row in rows:
        patient_rows = by_patient.get(str(row.get("patient_id") or ""), [])
        links = []
        for peer in patient_rows:
            if peer is row:
                continue
            ordinal = int(peer.get("ordinal", 0) or 0)
            links.append(
                {
                    "id": f"case-{ordinal:04d}",
                    "label": f"{ordinal:03d} {peer.get('assay') or ''}",
                }
            )
        row["parallel_links"] = links
    return rows


def _plot_zoom_range(entry: dict[str, Any]) -> tuple[float, float]:
    assay = str(entry.get("assay") or "")
    assay_ranges = assay_interpretation_ranges(assay)
    assay_range = assay_interpretation_range(assay)
    peaks = []
    peaks_by_channel = entry.get("peaks_by_channel") or {}
    primary = str(entry.get("primary_peak_channel") or "")
    frames = []
    if isinstance(peaks_by_channel, dict):
        if primary in peaks_by_channel:
            frames.append(peaks_by_channel[primary])
        frames.extend(frame for channel, frame in peaks_by_channel.items() if channel != primary)
    for frame in frames:
        if not isinstance(frame, pd.DataFrame) or frame.empty or "basepairs" not in frame.columns:
            continue
        series = pd.to_numeric(frame["basepairs"], errors="coerce")
        peaks.extend(float(value) for value in series.to_numpy() if np.isfinite(value))

    if assay_range is None and not peaks:
        return float(entry.get("bp_min") or 0.0), float(entry.get("bp_max") or 500.0)

    candidates: list[float] = []
    if assay_ranges:
        for start_bp, end_bp in assay_ranges:
            candidates.extend([float(start_bp), float(end_bp)])
    if peaks:
        if assay_range is None:
            candidates.extend(peaks)
        else:
            for start_bp, end_bp in assay_ranges:
                span = float(end_bp) - float(start_bp)
                margin = max(18.0, span * 0.24)
                candidates.extend([value for value in peaks if start_bp - margin <= value <= end_bp + margin])
    if not candidates:
        return float(entry.get("bp_min") or 0.0), float(entry.get("bp_max") or 500.0)

    lo = min(candidates)
    hi = max(candidates)
    min_span = 120.0 if str(entry.get("assay") or "").upper() != "DHJH_E" else 90.0
    if hi - lo < min_span:
        center = (lo + hi) / 2.0
        lo = center - min_span / 2.0
        hi = center + min_span / 2.0
    margin = max(18.0, (hi - lo) * 0.12)
    fallback_min = float(entry.get("bp_min") or 0.0)
    fallback_max = float(entry.get("bp_max") or 500.0)
    return max(fallback_min, lo - margin), min(fallback_max, hi + margin)


def _patient_id_from_file(file_name: str) -> str:
    import re

    match = re.search(r"\d{2}OUM\d{5}", str(file_name or ""))
    return match.group(0) if match else ""


def _offset_quotas(quotas: dict[str, int], sample_offset: int) -> dict[str, int]:
    if sample_offset <= 0:
        return dict(quotas)
    expanded = dict(quotas)
    expanded["patient"] = int(expanded.get("patient", 0)) + sample_offset
    return expanded


def _scaled_sample_quotas(quotas: dict[str, int], limit: int) -> dict[str, int]:
    limit = max(0, int(limit or 0))
    total = sum(max(0, int(value or 0)) for value in quotas.values())
    if limit <= 0 or total <= 0 or limit >= total:
        return dict(quotas)
    scaled: dict[str, int] = {}
    assigned = 0
    for key, value in quotas.items():
        scaled_value = int(max(0, value) * limit / total)
        if value > 0 and scaled_value == 0:
            scaled_value = 1
        scaled[key] = scaled_value
        assigned += scaled_value
    remainder = limit - assigned
    order = sorted(quotas, key=lambda key: quotas[key], reverse=True)
    idx = 0
    while remainder != 0 and order:
        key = order[idx % len(order)]
        if remainder > 0:
            scaled[key] += 1
            remainder -= 1
        elif scaled[key] > 0:
            scaled[key] -= 1
            remainder += 1
        idx += 1
    return scaled


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)[:180]


def _relative_or_uri(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_uri()


def default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return ROOT / "local_triage" / f"clonality_interpretation_annotation_{stamp}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render HemaFrag clonality interpretation annotation HTML.")
    parser.add_argument("--input-root", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--sample-offset", type=int, default=0)
    parser.add_argument("--run-date-filter", choices=["latest", "all"], default="latest")
    parser.add_argument("--annotator", default="")
    args = parser.parse_args()

    input_root = args.input_root
    if input_root is None:
        input_root = Path(
            APP_SETTINGS.get("analyses", {})
            .get("clonality", {})
            .get("batch", {})
            .get("base_input_dir")
            or Path.home()
        )
    out_dir = args.out_dir or default_out_dir()
    summary = render_annotation_panel(
        input_root=input_root.expanduser(),
        out_dir=out_dir.expanduser(),
        limit=args.limit,
        sample_offset=args.sample_offset,
        run_date_filter=args.run_date_filter,
        annotator=args.annotator,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
