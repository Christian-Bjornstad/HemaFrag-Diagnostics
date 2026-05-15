from __future__ import annotations

import argparse
import ast
import csv
import html
import json
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

from scripts.gs500rox_start_strategy_shadow_eval import GS500ROX_SIZES, analyze_path, corrected_trace, raw_trace  # noqa: E402
from scripts.render_flt3_gs500rox_50_candidate_html import _local_peaks  # noqa: E402
from scripts.render_flt3_gs500rox_start_proposal_html import _resolve_case_path, _safe_name  # noqa: E402

DEFAULT_CANDIDATE_ROWS = ROOT / "local_triage" / "flt3_gs500rox_50_gapprior_candidate_html" / "candidate_rows.csv"
DEFAULT_ANNOTATIONS = ROOT / "local_triage" / "flt3_gs500rox_50_gapprior_candidate_html" / "annotations_imported.csv"
DEFAULT_OUT_DIR = ROOT / "local_triage" / "flt3_gs500rox_35_earlier_candidate_html"
DEFAULT_DATA_ROOT = Path("/Volumes/T7 Shield/DATA/flt3")


def _choose_annotated_50(row: dict[str, Any]) -> int:
    label = str(row.get("label") or "")
    current = json.loads(str(row["current_selected"]))
    if label == "none":
        return int(current[1])
    if label.startswith("50_") and len(label) == 4:
        candidates = ast.literal_eval(str(row["candidates"]))
        idx = ord(label[-1]) - ord("A")
        if 0 <= idx < len(candidates):
            return int(candidates[idx]["scan"])
    return int(current[1])


def _rank_35_candidates(trace: np.ndarray, true_50: int, current: list[int], rust_indices: set[int]) -> list[dict[str, Any]]:
    expected = true_50 - 72
    start = max(1200, true_50 - 135)
    end = true_50 - 18
    peaks = _local_peaks(trace, start, end)
    anchors = {int(current[0]), int(current[1])}
    for peak in peaks:
        scan = int(peak["scan"])
        gap_to_50 = true_50 - scan
        peak["is_rust_peak"] = scan in rust_indices
        peak["is_current_anchor"] = scan in anchors
        peak["gap_to_50"] = gap_to_50
        peak["distance_from_expected"] = scan - expected
        peak["in_target_gap"] = 55 <= gap_to_50 <= 95
        distance_penalty = abs(scan - expected) * (6.0 if peak["in_target_gap"] else 13.0)
        rust_bonus = 60.0 if scan in rust_indices else 0.0
        anchor_bonus = 30.0 if scan in anchors else 0.0
        peak["score"] = float(peak["height"]) + 0.35 * float(peak["prominence"]) + rust_bonus + anchor_bonus - distance_penalty
    peaks.sort(key=lambda peak: (not bool(peak["in_target_gap"]), -float(peak["score"]), int(peak["scan"])))
    return peaks[:6]


def _render_case(out_dir: Path, row: dict[str, Any], trace: np.ndarray, current: list[int], true_50: int, candidates: list[dict[str, Any]]) -> str:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    ordinal = int(row["ordinal"])
    out = image_dir / f"{ordinal:03d}_{_safe_name(Path(str(row['File'])).stem)}_35_candidates.png"

    focus = current[:4] + [true_50] + [int(c["scan"]) for c in candidates]
    x_min = max(1150, min(focus) - 180)
    x_max = min(trace.size - 1, max(focus) + 230)
    window = trace[x_min:x_max]
    y_max = max(260.0, float(np.nanpercentile(window, 99.6) * 1.22)) if window.size else 1500.0
    y_max = min(max(y_max, max(float(trace[idx]) for idx in focus if 0 <= idx < trace.size) * 1.15 + 40.0), 7000.0)

    fig, ax = plt.subplots(figsize=(15, 5.2), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.85, label="DATA4 corrected")
    visible_current = [scan for scan in current[:7] if x_min <= scan <= x_max and 0 <= scan < trace.size]
    ax.scatter(visible_current, [trace[scan] for scan in visible_current], marker="x", s=68, linewidth=1.5, color="#dc2626", label="current")
    for idx, scan in enumerate(current[:7]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.text(scan, min(y_max * 0.90, trace[scan] + y_max * 0.035), str(GS500ROX_SIZES[idx]), ha="center", fontsize=7, color="#991b1b")

    ax.scatter([true_50], [trace[true_50]], marker="o", s=72, facecolors="none", edgecolors="#2563eb", linewidth=1.8, label="annotated 50")
    ax.text(true_50, min(y_max * 0.98, trace[true_50] + y_max * 0.08), "50", ha="center", fontsize=8, color="#1d4ed8", fontweight="bold")

    letters = "ABCDEF"
    colors = ["#0891b2", "#7c3aed", "#16a34a", "#ea580c", "#be123c", "#475569"]
    for idx, candidate in enumerate(candidates):
        scan = int(candidate["scan"])
        if not (x_min <= scan <= x_max and 0 <= scan < trace.size):
            continue
        color = colors[idx % len(colors)]
        ax.scatter([scan], [trace[scan]], marker="o", s=58, facecolors="none", edgecolors=color, linewidth=1.8)
        ax.text(scan, min(y_max * 0.985, trace[scan] + y_max * 0.085), f"35{letters[idx]}", ha="center", fontsize=8, color=color, fontweight="bold")

    ax.set_title(f"{ordinal:03d} {row['File']} | choose true 35 before annotated 50", fontsize=10)
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
    cards: list[str] = []
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        candidates = row["candidates_35"]
        candidate_text = "; ".join(
            f"{chr(65+i)}={int(c['scan'])} gap={float(c['gap_to_50']):.0f} h={float(c['height']):.0f} rust={bool(c['is_rust_peak'])}"
            for i, c in enumerate(candidates)
        )
        buttons = "".join(f"<button type='button' data-value='35_{chr(65+i)}'>35 {chr(65+i)}</button>" for i in range(len(candidates)))
        buttons += "<button type='button' data-value='none'>None</button><button type='button' data-value='current_ok'>Current ok</button><button type='button' data-value='unclear'>Unclear</button>"
        cards.append(
            f"""
<section class="case" data-key="{html.escape(row['raw_path'])}">
  <div class="head">
    <div>
      <div class="title">{int(row['ordinal']):03d}. {html.escape(str(row['File']))}</div>
      <div class="meta">annotated 50: {int(row['annotated_50'])} | previous label: {html.escape(str(row['label']))} | note: {html.escape(str(row['note']))}</div>
      <div class="meta">35 candidates: {html.escape(candidate_text)}</div>
      <div class="meta">current start: {html.escape(str(row['current_start']))}</div>
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
                "annotated_50": int(row["annotated_50"]),
                "previous_label": row["label"],
                "previous_note": row["note"],
                "candidates_35": candidates,
            }
        )
    payload = json.dumps({"review_class": "flt3_gs500rox_35_earlier_candidate", "rows": payload_rows}).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>FLT3 GS500ROX 35 Candidates</title>
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
<header><div><h1>FLT3 GS500ROX 35 Candidates</h1><div id="status">0 selected</div></div><button id="export" type="button">Export annotations</button></header>
<main><textarea id="exportBox" readonly></textarea>{''.join(cards)}</main>
<script>
const payload = {payload};
const storageKey = "flt3_gs500rox_35_earlier_candidate_annotations";
let memoryState = {{}};
function loadState() {{ try {{ return JSON.parse(window.localStorage.getItem(storageKey) || "{{}}"); }} catch (err) {{ return memoryState; }} }}
function saveState() {{ try {{ window.localStorage.setItem(storageKey, JSON.stringify(state)); }} catch (err) {{ memoryState = state; }} updateStatus(); }}
function updateStatus() {{ document.getElementById("status").textContent = `${{Object.values(state).filter(item => item && item.label).length}} selected`; }}
const state = loadState();
document.querySelectorAll(".case").forEach((card, idx) => {{
  const key = payload.rows[idx].raw_path;
  const saved = state[key] || {{}};
  if (saved.label) {{ const btn = card.querySelector(`button[data-value="${{saved.label}}"]`); if (btn) btn.classList.add("active"); }}
  const textarea = card.querySelector("textarea");
  if (saved.note) textarea.value = saved.note;
  card.querySelectorAll("button[data-value]").forEach(btn => btn.addEventListener("click", () => {{
    card.querySelectorAll("button[data-value]").forEach(item => item.classList.remove("active"));
    btn.classList.add("active");
    state[key] = {{...(state[key] || {{}}), label: btn.dataset.value, note: textarea.value}};
    saveState();
  }}));
  textarea.addEventListener("input", () => {{ state[key] = {{...(state[key] || {{}}), note: textarea.value}}; saveState(); }});
}});
document.getElementById("export").addEventListener("click", () => {{
  const rows = payload.rows.map(row => {{ const saved = state[row.raw_path] || {{}}; return {{...row, label:saved.label || "", note:saved.note || ""}}; }});
  const text = JSON.stringify({{exported_at:new Date().toISOString(), rows}}, null, 2);
  const exportBox = document.getElementById("exportBox");
  exportBox.value = text; exportBox.style.display = "block"; exportBox.focus(); exportBox.select();
  const blob = new Blob([text], {{type:"application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "flt3_gs500rox_35_earlier_candidate_annotations.json"; a.click(); URL.revokeObjectURL(a.href);
}});
updateStatus();
</script></body></html>"""
    (out_dir / "review_panel.html").write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-rows", type=Path, default=DEFAULT_CANDIDATE_ROWS)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    candidate_rows = pd.read_csv(args.candidate_rows)
    annotations = pd.read_csv(args.annotations).fillna("")
    merged = candidate_rows.merge(annotations, on="ordinal", how="inner")
    selected = merged[merged["note"].str.contains("tidligere", case=False, na=False)].copy()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(selected.sort_values("ordinal").to_dict("records"), start=1):
        path = Path(str(item["raw_path"]))
        if not path.exists():
            path = _resolve_case_path(item, args.data_root)
        print(f"[{idx}/{len(selected)}] {item['File']}", flush=True)
        analysis = analyze_path(path, args.timeout)
        if not analysis.get("ok"):
            continue
        current = [int(value) for value in analysis.get("selected") or []]
        trace = corrected_trace(raw_trace(path, analysis.get("channel") or "DATA4"))
        rust_indices = {
            int(round(float(peak.get("index"))))
            for peak in analysis.get("candidate_peaks") or []
            if peak.get("index") is not None
        }
        annotated_50 = _choose_annotated_50(item)
        candidates = _rank_35_candidates(trace, annotated_50, current, rust_indices)
        image = _render_case(args.out_dir, item, trace, current, annotated_50, candidates)
        rows.append(
            {
                **item,
                "raw_path": str(path),
                "annotated_50": annotated_50,
                "candidates_35": candidates,
                "image": image,
            }
        )

    with (args.out_dir / "candidate_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=["ordinal", "File", "raw_path", "current_start", "current_selected", "label", "note", "annotated_50", "candidates_35", "image"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    _write_html(args.out_dir, rows)
    summary = {"rows": len(rows), "html": str(args.out_dir / "review_panel.html")}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
