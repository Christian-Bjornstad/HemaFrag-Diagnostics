from __future__ import annotations

import html
import json
import math
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker


LADDER_SIZES = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


def safe_name(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))[:180]


def linear_metrics(scans: list[int], bps: list[int]) -> tuple[float, float, float]:
    if len(scans) != len(bps) or not scans:
        return (float("nan"), float("nan"), float("nan"))
    x = np.asarray(scans, dtype=float)
    y = np.asarray(bps, dtype=float)
    slope, intercept = np.linalg.lstsq(np.vstack([x, np.ones_like(x)]).T, y, rcond=None)[0]
    pred = slope * x + intercept
    resid = y - pred
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return (
        float(np.max(np.abs(resid))),
        float(np.mean(np.abs(resid))),
        float(1.0 - ss_res / ss_tot) if ss_tot else 1.0,
    )


def propose_local_clean_apex(scans: list[int], peaks: list[dict], ladder: str) -> tuple[list[int], list[dict]]:
    out = list(scans)
    changes: list[dict] = []
    for step, scan in enumerate(scans):
        current = next((peak for peak in peaks if int(peak.get("index", -1)) == int(scan)), None)
        if not current:
            continue
        height = max(float(current.get("height", 0.0)), 1.0)
        prominence = float(current.get("prominence", 0.0))
        baseline_ratio = max(float(current.get("local_baseline", 0.0)), 0.0) / height
        purity = prominence / height

        choices: list[tuple[float, dict]] = []
        for candidate in peaks:
            idx = int(candidate.get("index", -1))
            if idx == scan or abs(idx - scan) > 28:
                continue
            if step > 0 and idx <= out[step - 1]:
                continue
            if step + 1 < len(out) and idx >= out[step + 1]:
                continue
            cand_height = max(float(candidate.get("height", 0.0)), 1.0)
            cand_prom = float(candidate.get("prominence", 0.0))
            cand_baseline_ratio = max(float(candidate.get("local_baseline", 0.0)), 0.0) / cand_height
            cand_purity = cand_prom / cand_height
            cleaner = cand_purity >= 0.75 and cand_baseline_ratio <= 0.25
            stronger = cand_prom >= prominence * 1.5 or cand_height >= height * 1.5
            current_suspect = baseline_ratio >= 0.30 or purity <= 0.70
            if cleaner and (stronger or current_suspect):
                score = cand_prom + cand_height * 0.15 - abs(idx - scan) * 4.0
                choices.append((score, candidate))
        if not choices:
            continue
        choices.sort(key=lambda item: item[0], reverse=True)
        candidate = choices[0][1]
        idx = int(candidate["index"])
        out[step] = idx
        changes.append(
            {
                "step": step,
                "from": int(scan),
                "to": idx,
                "bp": LADDER_SIZES.get(ladder, [])[step] if step < len(LADDER_SIZES.get(ladder, [])) else step + 1,
                "from_baseline_ratio": round(baseline_ratio, 3),
                "from_purity": round(purity, 3),
            }
        )
    return out, changes


def analyze(worker, raw_path: Path) -> dict:
    analysis = live_eval.analyze_path(worker, raw_path)
    if str(analysis.get("error", "")).startswith("worker timeout"):
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is None:
            raise RuntimeError("Rust worker unavailable")
        analysis = live_eval.analyze_path(worker, raw_path)
    return analysis


def render_case(row: pd.Series, analysis: dict, out_dir: Path, image_dir: Path, ordinal: int) -> dict:
    result = analysis.get("result") or {}
    ladder = str(analysis.get("ladder") or row.get("ladder") or "")
    raw_path = Path(str(row["raw_path"]))
    channel = str(analysis.get("channel") or result.get("size_standard_channel_guess") or "")
    raw = live_eval.raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return {"image": "", "render_ok": False, "render_error": "missing trace"}
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)
    preview = result.get("ladder_fit_preview") or {}
    selected = live_eval.selected_scans(preview)
    peaks = result.get("ladder_peak_preview") or []
    candidates = [int(peak["index"]) for peak in peaks if peak.get("index") is not None]
    proposed, changes = propose_local_clean_apex(selected, peaks, ladder)
    sizes = LADDER_SIZES.get(ladder, [])
    old_metrics = linear_metrics(selected, sizes)
    new_metrics = linear_metrics(proposed, sizes)

    focus = [idx for idx in selected + proposed + candidates if 0 <= idx < trace.size]
    x_min = max(0, min(focus) - 320) if focus else 1100
    x_max = min(trace.size - 1, max(focus) + 420) if focus else min(trace.size - 1, 5000)
    x_min = min(x_min, 1150 if ladder == "LIZ500_250" else 1250)
    x_max = max(x_max, min(trace.size - 1, 4500 if ladder == "LIZ500_250" else 4100))
    window = trace[x_min : x_max + 1]
    ymax = float(max(260.0, np.nanpercentile(window, 99.7) * 1.18)) if window.size else 800.0
    visible = [idx for idx in selected + proposed + candidates if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if visible:
        ymax = max(ymax, np.nanpercentile([trace[idx] for idx in visible], 98.0) * 1.15 + 35.0)
    ymax = min(max(ymax, 260.0), 6500.0)

    fig, ax = plt.subplots(figsize=(15.5, 5.8), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.8, label=trace_label)
    visible_candidates = [idx for idx in candidates if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(visible_candidates, [trace[idx] for idx in visible_candidates], s=12, color="#9ca3af", alpha=0.38, label="candidate")
    visible_selected = [idx for idx in selected if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(visible_selected, [trace[idx] for idx in visible_selected], s=46, color="#dc2626", edgecolor="white", linewidth=0.45, zorder=4, label="current Rust")
    visible_proposed = [idx for idx in proposed if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(visible_proposed, [trace[idx] for idx in visible_proposed], s=44, color="#2563eb", marker="D", edgecolor="white", linewidth=0.45, zorder=5, label="shadow snap")
    for step, scan in enumerate(selected):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            bp = str(sizes[step]) if step < len(sizes) else str(step + 1)
            ax.text(scan, min(float(trace[scan]) + ymax * 0.035, ymax * 0.96), bp, fontsize=7, ha="center", color="#991b1b")
    for step, scan in enumerate(proposed):
        if scan != selected[step] and x_min <= scan <= x_max and 0 <= scan < trace.size:
            bp = str(sizes[step]) if step < len(sizes) else str(step + 1)
            ax.text(scan, min(float(trace[scan]) + ymax * 0.08, ymax * 0.97), bp, fontsize=7, ha="center", color="#1d4ed8")
    ax.set_title(
        f"{ordinal:03d} | {raw_path.name} | {ladder} | current {old_metrics[0]:.2f}/{old_metrics[1]:.2f} -> shadow {new_metrics[0]:.2f}/{new_metrics[1]:.2f}",
        fontsize=10,
    )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-max(20.0, ymax * 0.035), ymax)
    ax.set_xlabel("scan")
    ax.set_ylabel("baseline-corrected RFU")
    ax.grid(alpha=0.16)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    image_dir.mkdir(parents=True, exist_ok=True)
    image = image_dir / f"{ordinal:03d}_{safe_name(raw_path.stem)}.png"
    fig.savefig(image)
    plt.close(fig)
    return {
        "image": str(image),
        "render_ok": True,
        "render_error": "",
        "selected": json.dumps(selected),
        "linear_max": old_metrics[0],
        "linear_mean": old_metrics[1],
        "linear_r2": old_metrics[2],
        "shadow_selected": json.dumps(proposed),
        "shadow_changes": json.dumps(changes, ensure_ascii=False),
        "shadow_change_count": len(changes),
        "shadow_linear_max": new_metrics[0],
        "shadow_linear_mean": new_metrics[1],
        "shadow_linear_r2": new_metrics[2],
    }


def html_doc(rows: pd.DataFrame, out_dir: Path) -> str:
    cards = []
    for row in rows.itertuples(index=False):
        data = row._asdict()
        rel_image = Path(data["image"]).relative_to(out_dir).as_posix()
        key = html.escape(str(data["raw_path"]))
        note = str(data.get("prior_note") or "")
        label = str(data.get("prior_label") or "")
        cards.append(
            f"""
<section class="case" data-key="{key}">
  <div class="head">
    <div>
      <div class="title">{int(data['ordinal']):03d}. {html.escape(str(data['file']))}</div>
      <div class="meta">{html.escape(str(data['ladder']))} | current {float(data['linear_max']):.2f}/{float(data['linear_mean']):.2f} | shadow {float(data['shadow_linear_max']):.2f}/{float(data['shadow_linear_mean']):.2f} | changes {int(data['shadow_change_count'])}</div>
      <div class="path">{key}</div>
    </div>
    <div class="buttons">
      <button type="button" data-value="current">Current best</button>
      <button type="button" data-value="shadow">Blue better</button>
      <button type="button" data-value="neither">Neither</button>
      <button type="button" data-value="operator">Operator/data</button>
    </div>
  </div>
  <img src="{html.escape(rel_image)}" alt="{html.escape(str(data['file']))}">
  <div class="prior"><strong>Previous:</strong> {html.escape(label)}{' - ' if note else ''}{html.escape(note)}</div>
  <textarea placeholder="New comment..."></textarea>
</section>
"""
        )
    payload = {
        "rows": [
            {"ordinal": int(row.ordinal), "file": str(row.file), "raw_path": str(row.raw_path)}
            for row in rows.itertuples(index=False)
        ]
    }
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>HemaFrag annotated 23 shadow</title>
<style>
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #111827; }}
header {{ position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #d1d5db; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; }}
h1 {{ margin: 0; font-size: 18px; }}
.sub {{ color: #4b5563; font-size: 13px; }}
main {{ max-width: 1500px; margin: 0 auto; padding: 16px; }}
.case {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; margin-bottom: 18px; }}
.head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 10px; }}
.title {{ font-weight: 700; font-size: 15px; }}
.meta {{ margin-top: 3px; color: #374151; font-size: 13px; }}
.path {{ margin-top: 3px; color: #6b7280; font-size: 11px; word-break: break-all; }}
img {{ width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 4px; display: block; }}
.prior {{ margin-top: 10px; padding: 8px 10px; border-left: 3px solid #2563eb; background: #eff6ff; font-size: 13px; line-height: 1.35; }}
textarea {{ width: 100%; min-height: 68px; margin-top: 10px; box-sizing: border-box; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font: 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
button {{ border: 1px solid #9ca3af; background: #fff; border-radius: 6px; padding: 6px 9px; cursor: pointer; margin-left: 5px; }}
button.active {{ background: #111827; color: #fff; border-color: #111827; }}
#export {{ background: #0f766e; color: #fff; border-color: #0f766e; }}
</style>
</head>
<body>
<header>
  <div><h1>HemaFrag annotated 23 shadow</h1><div class="sub">Red circles = current Rust. Blue diamonds = experimental clean-apex snap.</div></div>
  <button id="export" type="button">Export annotations</button>
</header>
<main>{''.join(cards)}</main>
<script id="case-data" type="application/json">{html.escape(json.dumps(payload))}</script>
<script>
const storageKey = "hemafrag_shadow_annotations:" + location.pathname;
const state = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
function save() {{ localStorage.setItem(storageKey, JSON.stringify(state)); }}
for (const card of document.querySelectorAll(".case")) {{
  const key = card.dataset.key;
  state[key] = state[key] || {{}};
  const textarea = card.querySelector("textarea");
  textarea.value = state[key].note || "";
  textarea.addEventListener("input", () => {{ state[key].note = textarea.value; save(); }});
  for (const button of card.querySelectorAll(".buttons button")) {{
    if (state[key].label === button.dataset.value) button.classList.add("active");
    button.addEventListener("click", () => {{
      state[key].label = button.dataset.value;
      for (const peer of card.querySelectorAll(".buttons button")) peer.classList.remove("active");
      button.classList.add("active");
      save();
    }});
  }}
}}
document.getElementById("export").addEventListener("click", () => {{
  const payload = JSON.parse(document.getElementById("case-data").textContent);
  const rows = payload.rows.map(row => ({{...row, ...(state[row.raw_path] || {{}})}}));
  const blob = new Blob([JSON.stringify({{rows}}, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "annotated23_shadow_annotations.json";
  a.click();
  URL.revokeObjectURL(url);
}});
</script>
</body>
</html>
"""


def main() -> None:
    source = ROOT / "local_triage/ok_annotated23_focus_summary.tsv"
    out_dir = ROOT / "local_triage/ok_annotated23_shadow_html"
    image_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.read_csv(source, sep="\t").sort_values("original_ordinal").reset_index(drop=True)
    rows["ordinal"] = np.arange(1, len(rows) + 1)
    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")
    rendered = []
    for row in rows.itertuples(index=False):
        data = row._asdict()
        analysis = analyze(worker, Path(str(data["raw_path"])))
        rendered.append({**data, **render_case(pd.Series(data), analysis, out_dir, image_dir, int(data["ordinal"]))})
    out = pd.DataFrame(rendered)
    out.to_csv(out_dir / "review_rows.tsv", sep="\t", index=False)
    (out_dir / "review_panel.html").write_text(html_doc(out, out_dir), encoding="utf-8")
    print(json.dumps({"rows": len(out), "rendered": int(out["render_ok"].sum()), "html": str(out_dir / "review_panel.html")}, indent=2))


if __name__ == "__main__":
    main()
