from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gs500rox_start_strategy_shadow_eval import (  # noqa: E402
    GS500ROX_SIZES,
    analyze_path,
    corrected_trace,
    raw_trace,
)
from scripts.render_flt3_gs500rox_start_proposal_html import (  # noqa: E402
    DEFAULT_ANNOTATIONS,
    DEFAULT_DATA_ROOT,
    DEFAULT_PANEL_ROWS,
    DEFAULT_REVIEW_CSV,
    _load_cases,
    _resolve_case_path,
    _safe_name,
)

DEFAULT_OUT_DIR = ROOT / "local_triage" / "flt3_gs500rox_50_candidate_html"
TARGET_50_GAP_MIN = 60.0
TARGET_50_GAP_MAX = 90.0
TARGET_50_GAP_CENTER = 72.0


def _local_peaks(trace: np.ndarray, start: int, end: int) -> list[dict[str, Any]]:
    peaks: list[dict[str, Any]] = []
    for idx in range(max(2, start), min(trace.size - 3, end) + 1):
        height = float(trace[idx])
        if height < 8.0:
            continue
        if not (height >= trace[idx - 1] and height > trace[idx + 1] and height >= trace[idx - 2] and height >= trace[idx + 2]):
            continue
        left = float(np.min(trace[max(0, idx - 14) : idx + 1]))
        right = float(np.min(trace[idx : min(trace.size, idx + 15)]))
        prominence = height - max(left, right)
        if prominence < 4.0:
            continue
        peaks.append({"scan": idx, "height": height, "prominence": prominence})
    peaks.sort(key=lambda peak: -float(peak["height"]))
    kept: list[dict[str, Any]] = []
    for peak in peaks:
        if any(abs(int(peak["scan"]) - int(other["scan"])) <= 6 for other in kept):
            continue
        kept.append(peak)
    return sorted(kept, key=lambda peak: int(peak["scan"]))


def _rank_50_candidates(trace: np.ndarray, current: list[int], rust_indices: set[int]) -> list[dict[str, Any]]:
    proposed_35 = current[1]
    current_75 = current[2]
    expected = proposed_35 + TARGET_50_GAP_CENTER
    peaks = _local_peaks(trace, proposed_35 + 24, current_75 - 8)
    for peak in peaks:
        scan = int(peak["scan"])
        gap_from_35 = scan - proposed_35
        in_target_gap = TARGET_50_GAP_MIN <= gap_from_35 <= TARGET_50_GAP_MAX
        peak["is_rust_peak"] = scan in rust_indices
        peak["distance_from_expected"] = scan - expected
        peak["gap_from_35"] = gap_from_35
        peak["gap_to_75"] = current_75 - scan
        peak["in_target_gap"] = in_target_gap
        distance_penalty = abs(scan - expected) * (7.0 if in_target_gap else 16.0)
        rust_bonus = 70.0 if scan in rust_indices else 0.0
        peak["score"] = float(peak["height"]) + float(peak["prominence"]) * 0.40 + rust_bonus - distance_penalty
    peaks.sort(key=lambda peak: (not bool(peak["in_target_gap"]), -float(peak["score"]), int(peak["scan"])))
    return peaks[:6]


def _render_case(
    out_dir: Path,
    row: dict[str, Any],
    trace: np.ndarray,
    current: list[int],
    candidates: list[dict[str, Any]],
) -> str:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    ordinal = int(row.get("ordinal") or 0)
    file_name = str(row.get("File") or "")
    out = image_dir / f"{ordinal:03d}_{_safe_name(Path(file_name).stem)}_50_candidates.png"

    x_min = max(1200, current[0] - 260)
    x_max = min(trace.size - 1, current[4] + 220)
    window = trace[x_min:x_max] if x_max > x_min else trace
    y_max = max(260.0, float(np.nanpercentile(window, 99.6) * 1.22)) if window.size else 1600.0
    y_max = min(max(y_max, max([float(trace[s]) for s in current[:5] if 0 <= s < trace.size] + [0]) * 1.15 + 40.0), 7000.0)

    fig, ax = plt.subplots(figsize=(15, 5.2), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.85, label="DATA4 corrected")
    visible_current = [scan for scan in current[:7] if x_min <= scan <= x_max and 0 <= scan < trace.size]
    ax.scatter(visible_current, [trace[scan] for scan in visible_current], marker="x", s=68, linewidth=1.5, color="#dc2626", label="current")
    for idx, scan in enumerate(current[:7]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.text(scan, min(y_max * 0.90, trace[scan] + y_max * 0.035), str(GS500ROX_SIZES[idx]), ha="center", fontsize=7, color="#991b1b")

    proposed_35 = current[1]
    ax.scatter([proposed_35], [trace[proposed_35]], marker="o", s=62, facecolors="none", edgecolors="#2563eb", linewidth=1.6, label="new 35")
    ax.text(proposed_35, min(y_max * 0.98, trace[proposed_35] + y_max * 0.08), "35", ha="center", fontsize=8, color="#1d4ed8", fontweight="bold")
    letters = "ABCDEF"
    colors = ["#0891b2", "#7c3aed", "#16a34a", "#ea580c", "#be123c", "#475569"]
    for idx, candidate in enumerate(candidates):
        scan = int(candidate["scan"])
        if not (x_min <= scan <= x_max and 0 <= scan < trace.size):
            continue
        color = colors[idx % len(colors)]
        ax.scatter([scan], [trace[scan]], marker="o", s=58, facecolors="none", edgecolors=color, linewidth=1.8)
        ax.text(scan, min(y_max * 0.985, trace[scan] + y_max * 0.085), f"50{letters[idx]}", ha="center", fontsize=8, color=color, fontweight="bold")

    ax.set_title(f"{ordinal:03d} {file_name} | choose true 50 candidate", fontsize=10)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-max(35.0, y_max * 0.04), y_max)
    ax.set_xlabel("scan")
    ax.set_ylabel("RFU")
    ax.grid(alpha=0.16)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out.relative_to(out_dir).as_posix()


def _write_html(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    cards = []
    payload_rows = []
    for row in rows:
        candidates = row["candidates"]
        candidate_text = "; ".join(
            f"{chr(65+i)}={int(c['scan'])} gap={float(c['gap_from_35']):.0f} h={float(c['height']):.0f} prom={float(c['prominence']):.0f} rust={bool(c['is_rust_peak'])}"
            for i, c in enumerate(candidates)
        )
        buttons = "".join(
            f"<button type='button' data-value='50_{chr(65+i)}'>50 {chr(65+i)}</button>"
            for i in range(len(candidates))
        )
        buttons += "".join(
            [
                "<button type='button' data-value='none'>None</button>",
                "<button type='button' data-value='current_ok'>Current ok</button>",
                "<button type='button' data-value='weak_bad_ladder'>Weak/bad ladder</button>",
                "<button type='button' data-value='unclear'>Unclear</button>",
            ]
        )
        cards.append(
            f"""
<section class="case" data-key="{html.escape(row['raw_path'])}">
  <div class="head">
    <div>
      <div class="title">{int(row['ordinal']):03d}. {html.escape(str(row['File']))}</div>
      <div class="meta">current start: {html.escape(row['current_start'])}</div>
      <div class="meta">candidates: {html.escape(candidate_text)}</div>
      <div class="meta">{html.escape(str(row.get('ReviewReason') or row.get('reason') or ''))}</div>
    </div>
    <div class="buttons">{buttons}</div>
  </div>
  <img src="{html.escape(row['image'])}" alt="{html.escape(str(row['File']))}">
  <textarea placeholder="Kommentar..."></textarea>
</section>
"""
        )
        payload_rows.append(
            {
                "ordinal": int(row["ordinal"]),
                "file": str(row["File"]),
                "raw_path": row["raw_path"],
                "current_selected": row["current_selected"],
                "candidates": candidates,
            }
        )
    payload = json.dumps({"review_class": "flt3_gs500rox_50_candidate", "rows": payload_rows}).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>FLT3 GS500ROX 50 Candidates</title>
<style>
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f7f9; color:#111827; }}
header {{ position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid #d1d5db; padding:12px 18px; display:flex; justify-content:space-between; align-items:center; }}
h1 {{ margin:0; font-size:18px; }}
main {{ max-width:1500px; margin:0 auto; padding:16px; }}
.case {{ background:white; border:1px solid #d1d5db; border-radius:8px; padding:12px; margin-bottom:18px; }}
.head {{ display:flex; justify-content:space-between; gap:16px; margin-bottom:10px; }}
.title {{ font-weight:700; font-size:15px; }}
.meta {{ margin-top:4px; color:#374151; font-size:12px; }}
button {{ border:1px solid #9ca3af; background:#fff; border-radius:6px; padding:6px 9px; cursor:pointer; margin:0 0 5px 5px; }}
button.active {{ background:#111827; color:#fff; border-color:#111827; }}
#export {{ background:#111827; color:white; border-color:#111827; }}
#exportBox {{ display:none; width:100%; min-height:160px; margin:12px 0 0; box-sizing:border-box; border:1px solid #94a3b8; border-radius:6px; padding:8px; font:12px/1.35 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; }}
img {{ display:block; width:100%; height:auto; border:1px solid #e5e7eb; border-radius:4px; }}
textarea {{ width:100%; min-height:62px; margin-top:10px; box-sizing:border-box; border:1px solid #cbd5e1; border-radius:6px; padding:8px; font:14px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
</style></head><body>
<header><div><h1>FLT3 GS500ROX 50 Candidates</h1><div id="status">0 selected</div></div><button id="export" type="button">Export annotations</button></header>
<main><textarea id="exportBox" readonly></textarea>{''.join(cards)}</main>
<script>
const payload = {payload};
const storageKey = "flt3_gs500rox_50_candidate_annotations";
function loadState() {{
  try {{
    return JSON.parse(window.localStorage.getItem(storageKey) || "{{}}");
  }} catch (err) {{
    return {{}};
  }}
}}
function saveState() {{
  try {{
    window.localStorage.setItem(storageKey, JSON.stringify(state));
  }} catch (err) {{
    /* file:// pages may block localStorage; export still works from memory. */
  }}
  updateStatus();
}}
function updateStatus() {{
  const selected = Object.values(state).filter(item => item && item.label).length;
  document.getElementById("status").textContent = `${{selected}} selected`;
}}
const state = loadState();
document.querySelectorAll(".case").forEach((card, idx) => {{
  const key = payload.rows[idx].raw_path;
  const saved = state[key] || {{}};
  if (saved.label) {{
    const btn = card.querySelector(`button[data-value="${{saved.label}}"]`);
    if (btn) btn.classList.add("active");
  }}
  const textarea = card.querySelector("textarea");
  if (saved.note) textarea.value = saved.note;
  card.querySelectorAll("button[data-value]").forEach(btn => btn.addEventListener("click", () => {{
    card.querySelectorAll("button[data-value]").forEach(item => item.classList.remove("active"));
    btn.classList.add("active");
    state[key] = {{...(state[key] || {{}}), label: btn.dataset.value, note: textarea.value}};
    saveState();
  }}));
  textarea.addEventListener("input", () => {{
    state[key] = {{...(state[key] || {{}}), note: textarea.value}};
    saveState();
  }});
}});
document.getElementById("export").addEventListener("click", () => {{
  const rows = payload.rows.map(row => {{ const saved = state[row.raw_path] || {{}}; return {{...row, label:saved.label || "", note:saved.note || ""}}; }});
  const text = JSON.stringify({{exported_at:new Date().toISOString(), rows}}, null, 2);
  const exportBox = document.getElementById("exportBox");
  exportBox.value = text;
  exportBox.style.display = "block";
  exportBox.focus();
  exportBox.select();
  const blob = new Blob([text], {{type:"application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "flt3_gs500rox_50_candidate_annotations.json"; a.click(); URL.revokeObjectURL(a.href);
}});
updateStatus();
</script></body></html>"""
    (out_dir / "review_panel.html").write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--panel-rows", type=Path, default=DEFAULT_PANEL_ROWS)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--labels", default="move_both_right,move_35_right")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    labels = {part.strip() for part in args.labels.split(",") if part.strip()}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cases = _load_cases(args.review_csv, args.panel_rows, args.annotations, labels)
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        path = _resolve_case_path(case, args.data_root)
        print(f"[{idx}/{len(cases)}] {case.get('File')}", flush=True)
        analysis = analyze_path(path, args.timeout)
        if not analysis.get("ok"):
            continue
        current = [int(value) for value in analysis.get("selected") or []]
        if len(current) != len(GS500ROX_SIZES):
            continue
        trace = corrected_trace(raw_trace(path, analysis.get("channel") or "DATA4"))
        rust_indices = {
            int(round(float(peak.get("index"))))
            for peak in analysis.get("candidate_peaks") or []
            if peak.get("index") is not None
        }
        candidates = _rank_50_candidates(trace, current, rust_indices)
        image = _render_case(args.out_dir, case, trace, current, candidates)
        rows.append(
            {
                **case,
                "raw_path": str(path),
                "current_selected": json.dumps(current, separators=(",", ":")),
                "current_start": json.dumps(current[:7], separators=(",", ":")),
                "candidates": candidates,
                "image": image,
            }
        )
    with (args.out_dir / "candidate_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ordinal", "File", "raw_path", "current_start", "current_selected", "candidates", "image"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    _write_html(args.out_dir, rows)
    summary = {"rows": len(rows), "html": str(args.out_dir / "review_panel.html")}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
