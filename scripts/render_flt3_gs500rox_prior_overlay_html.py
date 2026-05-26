from __future__ import annotations

import argparse
import html
import json
import math
import re
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
    linear_metrics,
    raw_trace,
)


def _safe_name(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))[:180]


def _parse_scan_list(value: object) -> list[int]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    scans: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            scans.append(int(round(float(part))))
        except ValueError:
            continue
    return scans


def _as_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _resolve_path(row: pd.Series, data_root: Path) -> Path:
    file_name = str(row.get("File") or "")
    source = str(row.get("SourceRunDir") or "")
    for year in ("2026", "2025", "2024"):
        candidate = data_root / year / source / file_name
        if candidate.exists():
            return candidate
    direct = data_root / source / file_name
    if direct.exists():
        return direct
    matches = list(data_root.rglob(file_name)) if file_name else []
    if source:
        for match in matches:
            if match.parent.name == source:
                return match
    return matches[0] if matches else direct


def _metric_text(prefix: str, scans: list[int]) -> str:
    max_bp, mean_bp, r2 = linear_metrics(scans)
    return f"{prefix} {max_bp:.3f}/{mean_bp:.3f}/{r2:.6f}"


def _render_case(row: dict[str, Any], trace: np.ndarray, current: list[int], proposal: list[int], out_dir: Path) -> str:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    ordinal = int(row["ordinal"])
    file_name = str(row["File"])
    out = image_dir / f"{ordinal:03d}_{_safe_name(Path(file_name).stem)}_{_safe_name(row.get('GS500ROXStartPriorMode'))}.png"

    focus = current[:7] + proposal[:7]
    x_min = max(1100, min(focus + [1400]) - 220)
    x_max = min(trace.size - 1, max(focus + [2400]) + 300)
    window = trace[x_min : x_max + 1] if x_max > x_min else trace
    y_max = max(260.0, float(np.nanpercentile(window, 99.6) * 1.24)) if window.size else 1500.0
    selected_heights = [float(trace[idx]) for idx in focus if 0 <= idx < trace.size]
    if selected_heights:
        y_max = max(y_max, max(selected_heights) * 1.20 + 45.0)
    y_max = min(y_max, 7200.0)

    fig, ax = plt.subplots(figsize=(15.5, 5.4), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.85, label="DATA4 corrected")

    visible_current = [scan for scan in current[:7] if x_min <= scan <= x_max and 0 <= scan < trace.size]
    visible_proposal = [scan for scan in proposal[:7] if x_min <= scan <= x_max and 0 <= scan < trace.size]
    if visible_current:
        ax.scatter(
            visible_current,
            [trace[scan] for scan in visible_current],
            marker="x",
            s=76,
            linewidth=1.6,
            color="#dc2626",
            label="current Rust",
            zorder=4,
        )
    if visible_proposal:
        ax.scatter(
            visible_proposal,
            [trace[scan] for scan in visible_proposal],
            marker="o",
            s=54,
            facecolors="none",
            edgecolors="#2563eb",
            linewidth=1.7,
            label="proposal",
            zorder=5,
        )

    for idx, scan in enumerate(current[:7]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.text(scan, min(y_max * 0.92, trace[scan] + y_max * 0.035), str(GS500ROX_SIZES[idx]), ha="center", fontsize=7, color="#991b1b")
    for idx, scan in enumerate(proposal[:7]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.text(scan, min(y_max * 0.985, trace[scan] + y_max * 0.080), str(GS500ROX_SIZES[idx]), ha="center", fontsize=8, color="#1d4ed8", fontweight="bold")

    ax.set_title(
        f"{ordinal:03d} {file_name} | {row.get('GS500ROXStartPriorMode')} | "
        f"{_metric_text('current', current)} -> {_metric_text('proposal', proposal)}",
        fontsize=9.5,
    )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-max(35.0, y_max * 0.04), y_max)
    ax.set_xlabel("scan")
    ax.set_ylabel("baseline-corrected RFU")
    ax.grid(alpha=0.16)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out.relative_to(out_dir).as_posix()


def _button(value: str, label: str) -> str:
    return f"<button type='button' data-value='{html.escape(value)}'>{html.escape(label)}</button>"


def _write_html(rows: list[dict[str, Any]], out_dir: Path) -> None:
    payload = {
        "review_class": "flt3_gs500rox_prior_overlay",
        "rows": [
            {
                "ordinal": int(row["ordinal"]),
                "file": str(row["File"]),
                "raw_path": str(row["raw_path"]),
                "proposal_strategy": str(row.get("GS500ROXStartPriorMode") or ""),
                "current_selected": str(row.get("current_selected") or ""),
                "proposed_selected": str(row.get("GS500ROXStartPriorSelected") or ""),
                "qc_status": str(row.get("QCStatus") or ""),
                "ladder_qc": str(row.get("LadderQC") or ""),
            }
            for row in rows
        ],
    }
    cards: list[str] = []
    for row in rows:
        buttons = "".join(
            [
                _button("proposal_correct", "Proposal correct"),
                _button("current_correct", "Current correct"),
                _button("proposal_close", "Close/minor"),
                _button("weak_bad_ladder", "Weak/bad ladder"),
                _button("unclear", "Unclear"),
            ]
        )
        cards.append(
            f"""
<section class="case" data-key="{html.escape(str(row['raw_path']))}">
  <div class="case-head">
    <div>
      <div class="title">{int(row['ordinal']):03d}. {html.escape(str(row['File']))}</div>
      <div class="meta">{html.escape(str(row.get('QCStatus')))} / {html.escape(str(row.get('LadderQC')))} | {html.escape(str(row.get('GS500ROXStartPriorMode')))}</div>
      <div class="anchors">current: {html.escape(str(row.get('current_selected')))}</div>
      <div class="anchors">proposal: {html.escape(str(row.get('GS500ROXStartPriorSelected')))}</div>
      <div class="reason">{html.escape(str(row.get('ReviewReason') or ''))}</div>
    </div>
    <div class="buttons">{buttons}</div>
  </div>
  <img src="{html.escape(str(row['image']))}" alt="{html.escape(str(row['File']))}">
  <textarea placeholder="Kommentar..."></textarea>
</section>
"""
        )
    payload_json = json.dumps(payload).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FLT3 GS500ROX Prior Overlay</title>
<style>
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f7f9; color:#111827; }}
header {{ position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid #d1d5db; padding:12px 18px; display:flex; justify-content:space-between; gap:16px; align-items:center; }}
h1 {{ margin:0; font-size:18px; }}
.sub {{ color:#4b5563; font-size:13px; }}
main {{ max-width:1500px; margin:0 auto; padding:16px; }}
.case {{ background:#fff; border:1px solid #d1d5db; border-radius:8px; margin:0 0 18px; padding:12px; }}
.case-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:10px; }}
.title {{ font-weight:700; font-size:15px; }}
.meta,.anchors,.reason {{ margin-top:4px; color:#374151; font-size:12px; }}
.reason {{ color:#6b7280; }}
img {{ display:block; width:100%; height:auto; border:1px solid #e5e7eb; border-radius:4px; background:white; }}
button {{ border:1px solid #9ca3af; background:#fff; border-radius:6px; padding:6px 9px; cursor:pointer; margin:0 0 5px 5px; }}
button.active {{ background:#111827; color:#fff; border-color:#111827; }}
.selected-label {{ color:#111827; font-size:12px; font-weight:700; margin-top:6px; text-align:right; }}
textarea {{ width:100%; min-height:62px; margin-top:10px; box-sizing:border-box; border:1px solid #cbd5e1; border-radius:6px; padding:8px; font:14px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
#export {{ background:#111827; color:white; border-color:#111827; }}
#export-box {{ display:none; max-width:1500px; margin:0 auto 16px; padding:0 16px; }}
#export-json {{ min-height:180px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
</style>
</head>
<body>
<header>
  <div><h1>FLT3 GS500ROX Prior Overlay</h1><div class="sub">{len(rows)} cases. Red X = current Rust, blue circle = proposal.</div></div>
  <button id="export" type="button">Export annotations</button>
</header>
<div id="export-box"><textarea id="export-json" readonly></textarea></div>
<main>
{''.join(cards)}
</main>
<script>
const payload = {payload_json};
const storageKey = "flt3_gs500rox_prior_overlay_annotations:" + location.pathname;
function storageGet() {{
  try {{ return JSON.parse(window.localStorage.getItem(storageKey) || "{{}}"); }}
  catch (err) {{ return {{}}; }}
}}
function storageSet(value) {{
  try {{ window.localStorage.setItem(storageKey, JSON.stringify(value)); }}
  catch (err) {{ /* file:// browser policy may block localStorage; keep in-memory state. */ }}
}}
const state = storageGet();
document.querySelectorAll(".case").forEach((card, idx) => {{
  const key = payload.rows[idx].raw_path;
  const saved = state[key] || {{}};
  const status = document.createElement("div");
  status.className = "selected-label";
  card.querySelector(".buttons").appendChild(status);
  const setStatus = (label) => {{
    status.textContent = label ? "Valgt: " + label : "";
  }};
  if (saved.label) {{
    const btn = card.querySelector(`button[data-value="${{saved.label}}"]`);
    if (btn) btn.classList.add("active");
    setStatus(saved.label);
  }}
  const textarea = card.querySelector("textarea");
  if (saved.note) textarea.value = saved.note;
  card.querySelectorAll("button[data-value]").forEach(btn => {{
    btn.addEventListener("click", () => {{
      card.querySelectorAll("button[data-value]").forEach(item => item.classList.remove("active"));
      btn.classList.add("active");
      state[key] = {{...(state[key] || {{}}), label: btn.dataset.value, note: textarea.value}};
      setStatus(btn.dataset.value);
      storageSet(state);
    }});
  }});
  textarea.addEventListener("input", () => {{
    state[key] = {{...(state[key] || {{}}), note: textarea.value}};
    storageSet(state);
  }});
}});
document.getElementById("export").addEventListener("click", () => {{
  const rows = payload.rows.map(row => {{
    const saved = state[row.raw_path] || {{}};
    return {{...row, label: saved.label || "", note: saved.note || ""}};
  }});
  const text = JSON.stringify({{exported_at: new Date().toISOString(), rows}}, null, 2);
  const box = document.getElementById("export-box");
  const output = document.getElementById("export-json");
  output.value = text;
  box.style.display = "block";
  output.focus();
  output.select();
  try {{
    const blob = new Blob([text], {{type:"application/json"}});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "flt3_gs500rox_prior_overlay_annotations.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }} catch (err) {{
    // The JSON is still visible in the textarea above.
  }}
}});
</script>
</body>
</html>
"""
    (out_dir / "review_panel.html").write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render current-vs-prior overlays for FLT3 GS500ROX review rows.")
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("/Volumes/T7 Shield/DATA/flt3"))
    parser.add_argument(
        "--modes",
        default="start_block_35_50_75_100_139,35_earlier,simple_shift,late_50_after_current_50,right_shifted_start_review",
    )
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    modes = {part.strip() for part in args.modes.split(",") if part.strip()}
    rows = pd.read_csv(args.review_csv).copy()
    rows = rows[rows["QCStatus"].fillna("").eq("REVIEW")].copy()
    if modes:
        rows = rows[rows["GS500ROXStartPriorMode"].fillna("").isin(modes)].copy()
    rows["mode_rank"] = rows["GS500ROXStartPriorMode"].map(
        {
            "late_50_after_current_50": 0,
            "right_shifted_start_review": 1,
            "35_earlier": 2,
            "simple_shift": 3,
            "start_block_35_50_75_100_139": 4,
        }
    ).fillna(9)
    rows = rows.sort_values(["mode_rank", "SourceRunDir", "Well", "File"], ascending=[True, True, True, True])
    if args.limit:
        rows = rows.head(args.limit).copy()
    rows = rows.reset_index(drop=True)

    rendered: list[dict[str, Any]] = []
    skipped_missing = 0
    skipped_bad_proposal = 0
    skipped_bad_analysis = 0
    for idx, row in rows.iterrows():
        ordinal = idx + 1
        path = _resolve_path(row, args.data_root)
        proposal = _parse_scan_list(row.get("GS500ROXStartPriorSelected"))
        print(f"[{ordinal}/{len(rows)}] {row.get('File')} {row.get('GS500ROXStartPriorMode')}", flush=True)
        if not path.exists():
            skipped_missing += 1
            print(f"  skip: raw file not found at {path}", flush=True)
            continue
        if len(proposal) != len(GS500ROX_SIZES):
            skipped_bad_proposal += 1
            print(f"  skip: expected {len(GS500ROX_SIZES)} proposal anchors, got {len(proposal)}", flush=True)
            continue
        analysis = analyze_path(path, args.timeout)
        current = [int(value) for value in analysis.get("selected") or []] if analysis.get("ok") else []
        if len(current) != len(GS500ROX_SIZES):
            skipped_bad_analysis += 1
            print(f"  skip: analysis did not return {len(GS500ROX_SIZES)} current anchors ({analysis.get('error') or 'no selected ladder'})", flush=True)
            continue
        trace = corrected_trace(raw_trace(path, analysis.get("channel") or "DATA4"))
        item = row.to_dict()
        item["ordinal"] = ordinal
        item["raw_path"] = str(path)
        item["current_selected"] = ", ".join(str(value) for value in current)
        current_max, current_mean, current_r2 = linear_metrics(current)
        proposal_max, proposal_mean, proposal_r2 = linear_metrics(proposal)
        item["CurrentLinearMaxBp"] = f"{current_max:.3f}"
        item["CurrentLinearMeanBp"] = f"{current_mean:.3f}"
        item["CurrentLinearR2"] = f"{current_r2:.6f}"
        item["ProposalLinearMaxBp"] = f"{proposal_max:.3f}"
        item["ProposalLinearMeanBp"] = f"{proposal_mean:.3f}"
        item["ProposalLinearR2"] = f"{proposal_r2:.6f}"
        item["image"] = _render_case(item, trace, current, proposal, out_dir)
        rendered.append(item)

    out = pd.DataFrame(rendered)
    out.to_csv(out_dir / "overlay_rows.csv", index=False)
    _write_html(rendered, out_dir)
    summary = {
        "rows": int(len(rendered)),
        "html": str(out_dir / "review_panel.html"),
        "modes": sorted(modes),
        "skipped_missing": int(skipped_missing),
        "skipped_bad_proposal": int(skipped_bad_proposal),
        "skipped_bad_analysis": int(skipped_bad_analysis),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
