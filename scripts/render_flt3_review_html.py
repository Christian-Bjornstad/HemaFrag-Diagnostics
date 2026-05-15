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

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker
from fraggler.fraggler import FsaFile
from scripts.evaluate_rust_apex_recenter_live import corrected_display_trace, selected_scans


GS500ROX_SIZES = [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500]


def safe_name(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))[:190]


def as_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def parse_scan_list(value: object) -> list[int]:
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


def as_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def resolve_raw_path(row: pd.Series, fsa_dir: Path) -> Path:
    file_name = str(row.get("File") or "")
    source_run_dir = str(row.get("SourceRunDir") or "")
    direct = fsa_dir / source_run_dir / file_name
    if direct.exists():
        return direct
    matches = list(fsa_dir.rglob(file_name))
    if not matches:
        return direct
    if source_run_dir:
        for match in matches:
            if match.parent.name == source_run_dir:
                return match
    return matches[0]


def raw_trace(path: Path, ladder: str, channel: str) -> np.ndarray | None:
    try:
        probe = FsaFile(
            file=str(path),
            ladder=ladder or "GS500ROX",
            sample_channel="DATA1",
            min_distance_between_peaks=15,
            min_size_standard_height=50,
            size_standard_channel=channel or "DATA4",
        )
    except Exception:
        return None
    for candidate in [channel, "DATA4", "DATA105", "DATA5"]:
        if candidate and candidate in probe.fsa:
            return np.asarray(probe.fsa[candidate], dtype=float)
    return None


def analyze(worker: Any, path: Path) -> dict[str, Any]:
    response = worker.request(path, "flt3", 45)
    if not response or not response.get("ok"):
        error = (response or {}).get("error", "no response")
        if str(error).startswith("worker timeout") or error == "no response":
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            if worker is not None:
                response = worker.request(path, "flt3", 90)
    if not response or not response.get("ok"):
        return {"ok": False, "error": (response or {}).get("error", "no response")}
    result = response.get("result") if isinstance(response.get("result"), dict) else response
    return {"ok": True, "result": result}


def plot_case(row: pd.Series, image_dir: Path, ordinal: int, worker: Any | None) -> tuple[str, str]:
    raw_path = Path(str(row["raw_path"]))
    ladder = str(row.get("Ladder") or row.get("InternalLadder") or "GS500ROX")
    channel = str(row.get("SizeStandardChannel") or "DATA4")
    result: dict[str, Any] = {}
    render_error = ""
    if worker is not None and raw_path.exists():
        analysis = analyze(worker, raw_path)
        if analysis.get("ok"):
            result = analysis.get("result") or {}
            ladder = str(result.get("ladder") or ladder)
            channel = str(result.get("size_standard_channel_guess") or channel)
        else:
            render_error = str(analysis.get("error") or "")

    raw = raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return "", render_error or "raw trace unavailable"
    trace, trace_label = corrected_display_trace(raw, "LIZ500_250")

    preview = result.get("ladder_fit_preview") or {}
    selected = selected_scans(preview) if preview else []
    prior_mode = str(row.get("GS500ROXStartPriorMode") or "")
    prior_review_band = as_bool(row.get("GS500ROXStartPriorReviewBand"))
    prior_curved_review_band = as_bool(row.get("GS500ROXStartPriorCurvedReviewBand"))
    show_prior_proposal = (
        prior_review_band
        or prior_curved_review_band
        or prior_mode == "start_block_35_50_75_100_139"
    )
    prior_selected = parse_scan_list(row.get("GS500ROXStartPriorSelected")) if show_prior_proposal else []
    if prior_selected:
        selected = prior_selected
    candidates = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or [] if peak.get("index") is not None]

    focus = [idx for idx in selected + candidates if 0 <= idx < trace.size]
    if focus:
        x_min = max(0, min(focus) - 360)
        x_max = min(trace.size - 1, max(focus) + 520)
    else:
        x_min = 900
        x_max = min(trace.size - 1, 5000)
    x_min = min(x_min, 1150)
    x_max = max(x_max, min(trace.size - 1, 4500))
    window = trace[x_min : x_max + 1] if x_max > x_min else trace
    ymax = float(max(180.0, np.nanpercentile(window, 99.7) * 1.18)) if window.size else 500.0
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
        ax.scatter(visible_candidates, [trace[idx] for idx in visible_candidates], s=13, color="#9ca3af", alpha=0.48, label="candidate peaks")

    visible_selected = [idx for idx in selected if x_min <= idx <= x_max and 0 <= idx < trace.size]
    selected_label = "Start-prior applied" if prior_review_band and prior_selected else "Start-prior proposal" if prior_selected else "Rust selected"
    if visible_selected:
        ax.scatter(visible_selected, [trace[idx] for idx in visible_selected], s=48, color="#dc2626", edgecolor="white", linewidth=0.5, zorder=4, label=selected_label)
    for step, scan in enumerate(selected):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            bp = str(GS500ROX_SIZES[step]) if step < len(GS500ROX_SIZES) else str(step + 1)
            y = min(max(float(trace[scan]) + ymax * 0.035, ymax * 0.06), ymax * 0.965)
            color = "#7f1d1d" if bp not in {"35", "50"} else "#1d4ed8"
            ax.text(scan, y, bp, fontsize=7, ha="center", va="bottom", color=color)

    title = (
        f"{ordinal:03d} | {raw_path.name} | {row.get('QCStatus')} {row.get('LadderQC')} | "
        f"{row.get('SizeStandard')} {ladder} {channel} | "
        f"linear {as_float(row.get('LadderLinearMaxBp')):.2f}/"
        f"{as_float(row.get('LadderLinearMeanBp')):.2f}/"
        f"{as_float(row.get('LadderLinearR2')):.6f}"
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
    return str(out), render_error


def html_doc(rows: pd.DataFrame, out_dir: Path, title: str) -> str:
    cards: list[str] = []
    for row in rows.itertuples(index=False):
        row_dict = row._asdict()
        image = str(row_dict.get("image") or "")
        rel_image = Path(image).relative_to(out_dir).as_posix() if image and Path(image).is_absolute() else image
        ident = safe_name(f"{row_dict.get('ordinal')}_{row_dict.get('File')}")
        metrics = (
            f"{row_dict.get('SizeStandard')} / {row_dict.get('InternalLadder')} / {row_dict.get('SizeStandardChannel')} | "
            f"{row_dict.get('QCStatus')} / {row_dict.get('LadderQC')} | "
            f"linear {as_float(row_dict.get('LadderLinearMaxBp')):.2f}/"
            f"{as_float(row_dict.get('LadderLinearMeanBp')):.2f}/"
            f"{as_float(row_dict.get('LadderLinearR2')):.6f}"
        )
        badge_class = "fail" if str(row_dict.get("QCStatus")) == "FAIL" else "review"
        buttons = "".join(
            f"<button type='button' data-value='{html.escape(value)}'>{html.escape(label)}</button>"
            for value, label in [
                ("good", "Good"),
                ("minor", "Minor"),
                ("wrong_35_50", "Wrong 35/50"),
                ("weak_missing_ladder", "Weak/missing ladder"),
                ("operator_data", "Operator/data"),
                ("unclear", "Unclear"),
            ]
        )
        cards.append(
            f"""
<section class="case" id="case-{html.escape(ident)}" data-key="{html.escape(str(row_dict.get('raw_path')))}">
  <div class="case-head">
    <div>
      <div class="case-title">{int(row_dict.get('ordinal')):03d}. {html.escape(str(row_dict.get('File')))}</div>
      <div class="meta">{html.escape(metrics)} <span class="badge {badge_class}">{html.escape(str(row_dict.get('QCReason') or 'review'))}</span></div>
      <div class="path">{html.escape(str(row_dict.get('raw_path')))}</div>
      <div class="reason">{html.escape(str(row_dict.get('ReviewReason') or row_dict.get('render_error') or ''))}</div>
    </div>
    <div class="buttons">{buttons}</div>
  </div>
  {'<img src="' + html.escape(rel_image) + '" alt="' + html.escape(str(row_dict.get('File'))) + '">' if rel_image else '<div class="missing">Image unavailable</div>'}
  <textarea placeholder="Annotation..."></textarea>
</section>
"""
        )

    payload = {
        "review_class": "flt3_rox500_review",
        "rows": [
            {
                "ordinal": int(row.ordinal),
                "file": str(row.File),
                "raw_path": str(row.raw_path),
                "qc_status": str(row.QCStatus),
                "ladder_qc": str(row.LadderQC),
                "size_standard_channel": str(row.SizeStandardChannel),
            }
            for row in rows.itertuples(index=False)
        ],
    }
    payload_json = json.dumps(payload).replace("</", "<\\/")
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
.badge.review {{ background: #fef3c7; color: #92400e; }}
.badge.fail {{ background: #fee2e2; color: #991b1b; }}
.path {{ margin-top: 3px; color: #6b7280; font-size: 11px; word-break: break-all; }}
.reason {{ margin-top: 5px; color: #374151; font-size: 12px; }}
img {{ width: 100%; height: auto; display: block; border: 1px solid #e5e7eb; border-radius: 4px; background: #fff; }}
.missing {{ padding: 32px; border: 1px dashed #cbd5e1; color: #64748b; }}
textarea {{ width: 100%; min-height: 68px; margin-top: 10px; box-sizing: border-box; font: 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; }}
button {{ border: 1px solid #9ca3af; background: #fff; border-radius: 6px; padding: 6px 9px; cursor: pointer; margin-left: 5px; }}
button.active {{ background: #111827; color: white; border-color: #111827; }}
#export {{ background: #0f766e; color: white; border-color: #0f766e; }}
#export-json {{ display: block; max-width: 1500px; min-height: 120px; margin: 0 auto 16px; border-color: #0f766e; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>{html.escape(title)}</h1>
    <div class="sub">{len(rows)} FLT3 cases. Labels are stored in this browser; use Export annotations when done.</div>
  </div>
  <button id="export" type="button">Export annotations</button>
</header>
<textarea id="export-json" readonly placeholder="Export JSON backup appears here after clicking Export annotations."></textarea>
<main>
{''.join(cards)}
</main>
	<script id="case-data" type="application/json">{payload_json}</script>
	<script>
	const storageKey = "hemafrag_flt3_annotations:" + location.pathname;
	let state = {{}};
	function loadState() {{
	  try {{
	    state = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
	  }} catch (error) {{
	    state = {{}};
	  }}
	}}
	function save() {{
	  try {{
	    localStorage.setItem(storageKey, JSON.stringify(state));
	  }} catch (error) {{}}
	}}
	loadState();
	function currentRows(payload) {{
	  return payload.rows.map(row => {{
	    const card = Array.from(document.querySelectorAll(".case")).find(candidate => candidate.dataset.key === row.raw_path);
	    const live = card ? {{
	      label: card.querySelector(".buttons button.active")?.dataset.value || "",
	      note: card.querySelector("textarea")?.value || "",
	    }} : {{}};
	    return {{...row, ...(state[row.raw_path] || {{}}), ...live}};
	  }});
	}}
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
	  const rows = currentRows(payload);
	  const exportText = JSON.stringify({{review_class: payload.review_class, rows}}, null, 2);
	  document.getElementById("export-json").value = exportText;
	  const blob = new Blob([exportText], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "flt3_rox500_review_annotations.json";
  a.click();
  URL.revokeObjectURL(url);
}});
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--fsa-dir", type=Path, default=Path("/Volumes/T7 Shield/DATA/flt3"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    image_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = pd.read_csv(args.review_csv).copy()
    rows["sort_status"] = rows["QCStatus"].map({"FAIL": 0, "REVIEW": 1}).fillna(2)
    rows["linear_max_num"] = pd.to_numeric(rows.get("LadderLinearMaxBp"), errors="coerce")
    rows = rows.sort_values(["sort_status", "SourceRunDir", "Well", "File"], ascending=[True, True, True, True])
    if args.limit:
        rows = rows.head(args.limit).copy()
    rows = rows.reset_index(drop=True)
    rows["ordinal"] = np.arange(1, len(rows) + 1)
    rows["raw_path"] = [str(resolve_raw_path(row, args.fsa_dir)) for _, row in rows.iterrows()]

    worker = _get_rust_worker()
    rendered: list[dict[str, Any]] = []
    for row in rows.itertuples(index=False):
        row_series = pd.Series(row._asdict())
        image, render_error = plot_case(row_series, image_dir, int(row.ordinal), worker)
        rendered.append({**row._asdict(), "image": image, "render_ok": bool(image), "render_error": render_error})
        print(f"rendered {int(row.ordinal)}/{len(rows)}", flush=True)

    out = pd.DataFrame(rendered)
    out = out.drop(columns=["sort_status", "linear_max_num"], errors="ignore")
    out.to_csv(out_dir / "review_rows.tsv", sep="\t", index=False)
    title = "HemaFrag FLT3 ROX500 ladder review"
    html_path = out_dir / "review_panel.html"
    html_path.write_text(html_doc(out, out_dir, title), encoding="utf-8")
    summary = {
        "rows": int(len(out)),
        "rendered": int(out["render_ok"].sum()) if not out.empty else 0,
        "out_dir": str(out_dir),
        "html": str(html_path),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
