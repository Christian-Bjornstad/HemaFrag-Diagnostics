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

import scripts.evaluate_rust_apex_recenter_live as live_eval
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker


LADDER_SIZES = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


def safe_name(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))[:190]


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def as_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def choose_rows(summary: Path, review_class: str, limit: int | None) -> pd.DataFrame:
    df = pd.read_csv(summary, sep="\t")
    rows = df[df["morning_class"].astype(str).eq(review_class)].copy()
    rows["linear_max_num"] = pd.to_numeric(rows.get("linear_max"), errors="coerce")
    rows["linear_mean_num"] = pd.to_numeric(rows.get("linear_mean"), errors="coerce")
    rows = rows.sort_values(["ladder", "linear_max_num", "linear_mean_num", "file"], ascending=[True, False, False, True])
    if limit is not None:
        rows = rows.head(limit).copy()
    return rows


def analyze(worker: Any, raw_path: Path) -> dict[str, Any]:
    analysis = live_eval.analyze_path(worker, raw_path)
    error = str(analysis.get("error", ""))
    if error.startswith("worker timeout") or error == "no response":
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is None:
            raise RuntimeError("Rust worker unavailable after timeout")
        analysis = live_eval.analyze_path(worker, raw_path)
    return analysis


def plot_case(analysis: dict[str, Any], source_row: pd.Series, image_dir: Path, ordinal: int) -> str | None:
    if not analysis.get("ok"):
        return None
    result = analysis.get("result") or {}
    raw_path = Path(str(source_row["raw_path"]))
    ladder = str(analysis.get("ladder") or source_row.get("ladder") or "")
    channel = str(analysis.get("channel") or result.get("size_standard_channel_guess") or "")
    raw = live_eval.raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return None
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)

    preview = result.get("ladder_fit_preview") or {}
    selected = live_eval.selected_scans(preview)
    candidates = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or [] if peak.get("index") is not None]
    sizes = LADDER_SIZES.get(ladder, [])

    focus = [idx for idx in selected + candidates if 0 <= idx < trace.size]
    if selected:
        x_min = max(0, min(selected) - (360 if ladder == "LIZ500_250" else 300))
        x_max = min(trace.size - 1, max(selected) + (520 if ladder == "LIZ500_250" else 420))
    elif focus:
        x_min = max(0, min(focus) - 300)
        x_max = min(trace.size - 1, max(focus) + 400)
    else:
        x_min = 1100 if ladder == "LIZ500_250" else 1200
        x_max = min(trace.size - 1, 5000)
    if ladder == "LIZ500_250":
        x_min = min(x_min, 1150)
    else:
        x_min = min(x_min, 1250)
    x_max = max(x_max, min(trace.size - 1, 4500 if ladder == "LIZ500_250" else 4100))

    window = trace[x_min : x_max + 1] if x_max > x_min else trace
    if window.size:
        ymax = float(max(80.0, np.nanpercentile(window, 99.7) * 1.18))
    else:
        ymax = float(max(80.0, np.nanmax(trace)))
    selected_y = [float(trace[idx]) for idx in selected if x_min <= idx <= x_max and 0 <= idx < trace.size]
    candidate_y = [float(trace[idx]) for idx in candidates if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if selected_y:
        ymax = max(ymax, max(selected_y) * 1.18 + 35.0)
    if candidate_y:
        ymax = max(ymax, np.nanpercentile(candidate_y, 98.0) * 1.12 + 25.0)
    ymax = min(max(ymax, 260.0), 6500.0)
    ymin = -max(20.0, ymax * 0.035)

    fig, ax = plt.subplots(figsize=(15.5, 5.8), dpi=150)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.8, label=trace_label)

    visible_candidates = [idx for idx in candidates if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if visible_candidates:
        ax.scatter(
            visible_candidates,
            [trace[idx] for idx in visible_candidates],
            s=13,
            color="#9ca3af",
            alpha=0.48,
            label="candidate peaks",
        )

    visible_selected = [idx for idx in selected if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if visible_selected:
        ax.scatter(
            visible_selected,
            [trace[idx] for idx in visible_selected],
            s=48,
            color="#dc2626",
            edgecolor="white",
            linewidth=0.5,
            zorder=4,
            label="Rust selected",
        )
    for step, scan in enumerate(selected):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            bp = str(sizes[step]) if step < len(sizes) else str(step + 1)
            y = min(max(float(trace[scan]) + ymax * 0.035, ymax * 0.06), ymax * 0.965)
            ax.text(scan, y, bp, fontsize=7, ha="center", va="bottom", color="#7f1d1d")

    linear_max = as_float(source_row.get("linear_max"))
    linear_mean = as_float(source_row.get("linear_mean"))
    linear_r2 = as_float(source_row.get("linear_r2"))
    title = (
        f"{ordinal:03d} | {raw_path.name} | {ladder} {channel} | "
        f"linear {linear_max:.2f}/{linear_mean:.2f}/{linear_r2:.6f}"
    )
    ax.set_title(title, fontsize=10)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(ymin, ymax)
    ax.set_xlabel("scan")
    ax.set_ylabel("baseline-corrected RFU")
    ax.grid(alpha=0.16)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()

    image_dir.mkdir(parents=True, exist_ok=True)
    out = image_dir / f"{ordinal:03d}_{safe_name(raw_path.stem)}.png"
    fig.savefig(out)
    plt.close(fig)
    return str(out)


def html_doc(rows: pd.DataFrame, out_dir: Path, review_class: str, title: str) -> str:
    cards: list[str] = []
    for row in rows.itertuples(index=False):
        row_dict = row._asdict()
        image = str(row_dict.get("image") or "")
        rel_image = Path(image).relative_to(out_dir).as_posix() if image and Path(image).is_absolute() else image
        ident = safe_name(f"{row_dict.get('ordinal')}_{row_dict.get('file')}")
        metrics = (
            f"{row_dict.get('ladder')} | linear "
            f"{as_float(row_dict.get('linear_max')):.2f}/"
            f"{as_float(row_dict.get('linear_mean')):.2f}/"
            f"{as_float(row_dict.get('linear_r2')):.6f}"
        )
        is_review = as_bool(row_dict.get("review"))
        primary_reason = str(row_dict.get("primary_reason") or "")
        review_badge = (
            f"<span class='badge review'>REVIEW: {html.escape(primary_reason or 'review_required')}</span>"
            if is_review
            else "<span class='badge ok'>OK</span>"
        )
        prior_label = str(row_dict.get("prior_label") or "")
        prior_note = str(row_dict.get("prior_note") or "")
        prior_annotation = ""
        if prior_label or prior_note:
            prior_annotation = (
                "<div class='prior'>"
                f"<strong>Previous:</strong> {html.escape(prior_label or 'note')}"
                f"{' - ' if prior_note else ''}{html.escape(prior_note)}"
                "</div>"
            )
        buttons = "".join(
            f"<button type='button' data-value='{html.escape(value)}'>{html.escape(label)}</button>"
            for value, label in [
                ("good", "Good"),
                ("minor", "Minor"),
                ("wrong", "Wrong"),
                ("operator", "Operator/data"),
                ("unclear", "Unclear"),
            ]
        )
        cards.append(
            f"""
<section class="case" id="case-{html.escape(ident)}" data-key="{html.escape(str(row_dict.get('raw_path')))}">
  <div class="case-head">
    <div>
      <div class="case-title">{int(row_dict.get('ordinal')):03d}. {html.escape(str(row_dict.get('file')))}</div>
      <div class="meta">{html.escape(metrics)} {review_badge}</div>
      <div class="path">{html.escape(str(row_dict.get('raw_path')))}</div>
    </div>
    <div class="buttons">{buttons}</div>
  </div>
  <img src="{html.escape(rel_image)}" alt="{html.escape(str(row_dict.get('file')))}">
  {prior_annotation}
  <textarea placeholder="Annotation..."></textarea>
</section>
"""
        )

    payload = {
        "review_class": review_class,
        "rows": [
            {
                "ordinal": int(row.ordinal),
                "file": str(row.file),
                "raw_path": str(row.raw_path),
                "ladder": str(row.ladder),
            }
            for row in rows.itertuples(index=False)
        ],
    }
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #111827; }}
header {{ position: sticky; top: 0; z-index: 10; padding: 12px 18px; background: #ffffff; border-bottom: 1px solid #d1d5db; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
h1 {{ margin: 0; font-size: 18px; }}
.sub {{ color: #4b5563; font-size: 13px; }}
main {{ max-width: 1500px; margin: 0 auto; padding: 16px; }}
.case {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px; margin: 0 0 18px; padding: 12px; }}
.case-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 10px; }}
.case-title {{ font-weight: 700; font-size: 15px; }}
.meta {{ margin-top: 3px; color: #374151; font-size: 13px; }}
.badge {{ display: inline-block; margin-left: 8px; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 700; vertical-align: 1px; }}
.badge.ok {{ background: #dcfce7; color: #166534; }}
.badge.review {{ background: #fee2e2; color: #991b1b; }}
.path {{ margin-top: 3px; color: #6b7280; font-size: 11px; word-break: break-all; }}
.prior {{ margin-top: 10px; padding: 8px 10px; border-left: 3px solid #2563eb; background: #eff6ff; color: #1f2937; font-size: 13px; line-height: 1.35; }}
img {{ width: 100%; height: auto; display: block; border: 1px solid #e5e7eb; border-radius: 4px; background: #fff; }}
textarea {{ width: 100%; min-height: 68px; margin-top: 10px; box-sizing: border-box; font: 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; }}
button {{ border: 1px solid #9ca3af; background: #fff; border-radius: 6px; padding: 6px 9px; cursor: pointer; margin-left: 5px; }}
button.active {{ background: #111827; color: white; border-color: #111827; }}
#export {{ background: #0f766e; color: white; border-color: #0f766e; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>{html.escape(title)}</h1>
    <div class="sub">{len(rows)} cases. Annotations are stored in this browser and can be exported as JSON.</div>
  </div>
  <button id="export" type="button">Export annotations</button>
</header>
<main>
{''.join(cards)}
</main>
<script id="case-data" type="application/json">{html.escape(json.dumps(payload))}</script>
<script>
const storageKey = "hemafrag_annotations:" + location.pathname;
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
  const blob = new Blob([JSON.stringify({{review_class: payload.review_class, rows}}, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = payload.review_class + "_annotations.json";
  a.click();
  URL.revokeObjectURL(url);
}});
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--class", dest="review_class", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    image_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = choose_rows(args.summary, args.review_class, args.limit or None)
    rows = rows.reset_index(drop=True)
    rows["ordinal"] = np.arange(1, len(rows) + 1)

    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")

    rendered: list[dict[str, Any]] = []
    for row in rows.itertuples(index=False):
        raw_path = Path(str(row.raw_path))
        analysis = analyze(worker, raw_path)
        image = plot_case(analysis, pd.Series(row._asdict()), image_dir, int(row.ordinal))
        rendered.append({**row._asdict(), "image": image or "", "render_ok": bool(image), "render_error": analysis.get("error", "")})
        if int(row.ordinal) % 25 == 0 or int(row.ordinal) == len(rows):
            print(f"rendered {int(row.ordinal)}/{len(rows)}", flush=True)

    out = pd.DataFrame(rendered)
    out.to_csv(out_dir / "review_rows.tsv", sep="\t", index=False)
    title = f"HemaFrag clonality {args.review_class} review"
    (out_dir / "review_panel.html").write_text(html_doc(out, out_dir, args.review_class, title), encoding="utf-8")
    summary = {
        "review_class": args.review_class,
        "rows": int(len(out)),
        "rendered": int(out["render_ok"].sum()) if not out.empty else 0,
        "out_dir": str(out_dir),
        "html": str(out_dir / "review_panel.html"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
