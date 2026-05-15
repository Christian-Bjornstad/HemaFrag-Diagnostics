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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gs500rox_start_strategy_shadow_eval import (  # noqa: E402
    GS500ROX_SIZES,
    analyze_path,
    corrected_trace,
    linear_metrics,
    raw_trace,
    resolve_path,
)
from scripts.render_flt3_gs500rox_50_candidate_html import _local_peaks  # noqa: E402
from scripts.render_flt3_gs500rox_start_proposal_html import _safe_name  # noqa: E402

DEFAULT_PANEL = (
    ROOT
    / "local_triage"
    / "flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15"
    / "wrong_35_50_panel_for_shadow.csv"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "local_triage"
    / "flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15"
    / "html_wrong_35_50_reverse_projection_candidates"
)
DEFAULT_DATA_ROOT = Path("/Volumes/T7 Shield/DATA/flt3")

TARGET_BPS = [35, 50, 75, 100, 139]
METHODS: dict[str, list[int]] = {
    "tail_300_500": list(range(9, 16)),
    "tail_200_500": list(range(7, 16)),
    "anchor_340_350": [10, 11],
}
COLORS = {
    35: "#0891b2",
    50: "#7c3aed",
    75: "#16a34a",
    100: "#ea580c",
    139: "#be123c",
}


def _parse_int(value: object) -> int | None:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def _selected_scans(analysis: dict[str, Any]) -> list[int]:
    return [int(value) for value in analysis.get("selected") or []]


def _projection(current: list[int], fit_indices: list[int]) -> np.ndarray | None:
    if len(current) != len(GS500ROX_SIZES):
        return None
    scans = [current[idx] for idx in fit_indices]
    bps = [GS500ROX_SIZES[idx] for idx in fit_indices]
    if len(scans) < 2:
        return None
    return np.polyfit(np.asarray(bps, dtype=float), np.asarray(scans, dtype=float), deg=1)


def _candidate_score(peak: dict[str, Any], expected: float) -> float:
    distance = abs(int(peak["scan"]) - expected)
    height = min(float(peak["height"]), 5000.0)
    prominence = min(float(peak["prominence"]), 4000.0)
    return height * 0.55 + prominence * 0.75 - distance * 10.0


def _projection_candidates(
    trace: np.ndarray,
    expected: float,
    *,
    bp: int,
    radius: int,
    limit: int = 4,
) -> list[dict[str, Any]]:
    peaks = _local_peaks(trace, int(expected - radius), int(expected + radius))
    if not peaks:
        return []
    local_max = max(float(peak["height"]) for peak in peaks)
    min_height = max(20.0 if bp >= 75 else 45.0, local_max * 0.03)
    out: list[dict[str, Any]] = []
    for peak in peaks:
        height = float(peak["height"])
        prominence = float(peak["prominence"])
        if height < min_height or prominence < max(5.0, height * 0.04):
            continue
        scan = int(peak["scan"])
        item = dict(peak)
        item["bp"] = bp
        item["expected"] = float(expected)
        item["distance_from_expected"] = float(scan - expected)
        item["score"] = _candidate_score(item, expected)
        out.append(item)
    out.sort(key=lambda item: (-float(item["score"]), abs(float(item["distance_from_expected"])), int(item["scan"])))
    return out[:limit]


def _method_candidates(trace: np.ndarray, current: list[int], method: str, fit_indices: list[int]) -> dict[str, Any] | None:
    coef = _projection(current, fit_indices)
    if coef is None:
        return None
    candidates: dict[int, list[dict[str, Any]]] = {}
    for bp in TARGET_BPS:
        expected = float(np.polyval(coef, bp))
        radius = 95 if bp <= 50 else 80
        candidates[bp] = _projection_candidates(trace, expected, bp=bp, radius=radius)
    selected: list[int] = []
    for bp in TARGET_BPS:
        if not candidates[bp]:
            return None
        chosen = int(candidates[bp][0]["scan"])
        if selected and chosen <= selected[-1] + 8:
            return None
        selected.append(chosen)
    full = selected + current[len(selected) :]
    linear_max, linear_mean, linear_r2 = linear_metrics(full)
    return {
        "method": method,
        "fit_bps": [GS500ROX_SIZES[idx] for idx in fit_indices],
        "coef": [float(value) for value in coef],
        "selected": selected,
        "full_selected": full,
        "linear_max": linear_max,
        "linear_mean": linear_mean,
        "linear_r2": linear_r2,
        "candidates": candidates,
    }


def _choose_methods(trace: np.ndarray, current: list[int]) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for name, indices in METHODS.items():
        item = _method_candidates(trace, current, name, indices)
        if item is not None:
            methods.append(item)
    methods.sort(
        key=lambda item: (
            0 if item["method"] == "tail_300_500" else 1,
            float(item["linear_max"]) if math.isfinite(float(item["linear_max"])) else 999.0,
        )
    )
    return methods


def _render_case(out_dir: Path, row: dict[str, Any], trace: np.ndarray, current: list[int], methods: list[dict[str, Any]]) -> str:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    ordinal = int(row["panel_no"])
    file_name = str(row["file"])
    out = image_dir / f"{ordinal:03d}_{_safe_name(Path(file_name).stem)}_reverse_projection_candidates.png"

    focus = current[:8]
    for method in methods:
        focus.extend(int(scan) for scan in method["selected"])
        for bp in TARGET_BPS:
            focus.extend(int(candidate["scan"]) for candidate in method["candidates"][bp])
    x_min = max(1150, min(focus) - 190)
    x_max = min(trace.size - 1, max(focus) + 260)
    window = trace[x_min:x_max]
    y_max = max(280.0, float(np.nanpercentile(window, 99.5) * 1.2)) if window.size else 1500.0
    y_max = min(max(y_max, max(float(trace[idx]) for idx in focus if 0 <= idx < trace.size) * 1.10 + 60.0), 8000.0)

    fig, axes = plt.subplots(len(methods), 1, figsize=(15, 4.3 * max(len(methods), 1)), dpi=150, sharex=True)
    if not isinstance(axes, np.ndarray):
        axes = np.asarray([axes])
    xs = np.arange(trace.size)
    for ax, method in zip(axes, methods):
        ax.plot(xs, trace, color="#111827", linewidth=0.82, label="corrected DATA4")
        visible_current = [scan for scan in current[:8] if x_min <= scan <= x_max and 0 <= scan < trace.size]
        ax.scatter(visible_current, [trace[scan] for scan in visible_current], marker="x", s=54, color="#dc2626", label="current")
        for idx, scan in enumerate(current[:8]):
            if x_min <= scan <= x_max and 0 <= scan < trace.size:
                ax.text(scan, min(y_max * 0.91, trace[scan] + y_max * 0.028), str(GS500ROX_SIZES[idx]), ha="center", fontsize=7, color="#991b1b")

        for bp in TARGET_BPS:
            candidates = method["candidates"][bp]
            color = COLORS[bp]
            for rank, candidate in enumerate(candidates):
                scan = int(candidate["scan"])
                if not (x_min <= scan <= x_max and 0 <= scan < trace.size):
                    continue
                size = 68 if rank == 0 else 42
                linewidth = 2.0 if rank == 0 else 1.3
                alpha = 1.0 if rank == 0 else 0.55
                ax.scatter([scan], [trace[scan]], marker="o", s=size, facecolors="none", edgecolors=color, linewidth=linewidth, alpha=alpha)
                ax.text(
                    scan,
                    min(y_max * 0.985, trace[scan] + y_max * (0.065 + rank * 0.025)),
                    f"{bp}{chr(65 + rank)}",
                    ha="center",
                    fontsize=7,
                    color=color,
                    fontweight="bold" if rank == 0 else "normal",
                )
        ax.set_ylabel("RFU")
        ax.set_ylim(-max(35.0, y_max * 0.04), y_max)
        ax.grid(alpha=0.15)
        ax.set_title(
            f"{method['method']} fit={method['fit_bps']} selected={method['selected']} "
            f"linear {method['linear_max']:.2f}/{method['linear_mean']:.2f}/r2 {method['linear_r2']:.5f}",
            fontsize=9,
        )
        ax.legend(loc="upper right", fontsize=7)
    axes[-1].set_xlabel("scan")
    axes[-1].set_xlim(x_min, x_max)
    fig.suptitle(f"{ordinal:03d} {file_name}", fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out.relative_to(out_dir).as_posix()


def _write_html(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    cards: list[str] = []
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        method_lines = []
        for method in row["methods"]:
            bits = []
            for bp in TARGET_BPS:
                bits.append(
                    f"{bp}: "
                    + ", ".join(
                        f"{chr(65+i)}={int(c['scan'])}(d={float(c['distance_from_expected']):+.1f},h={float(c['height']):.0f},p={float(c['prominence']):.0f})"
                        for i, c in enumerate(method["candidates"][bp])
                    )
                )
            method_lines.append(
                f"<div><b>{html.escape(method['method'])}</b> selected={html.escape(str(method['selected']))} "
                f"linear={float(method['linear_max']):.2f}/{float(method['linear_mean']):.2f}<br>{html.escape(' | '.join(bits))}</div>"
            )
        cards.append(
            f"""
<section class="case" data-key="{html.escape(row['raw_path'])}">
  <div class="title">{int(row['panel_no']):03d}. {html.escape(row['file'])}</div>
  <div class="meta">{html.escape(row['raw_path'])}</div>
  <div class="methods">{''.join(method_lines)}</div>
  <img src="{html.escape(row['image'])}" alt="{html.escape(row['file'])}">
  <textarea placeholder="Kommentar eller valgte labels, f.eks. tail_300_500: 35A 50B 75A 100A 139C"></textarea>
</section>
"""
        )
        payload_rows.append(
            {
                "ordinal": int(row["panel_no"]),
                "file": row["file"],
                "raw_path": row["raw_path"],
                "methods": row["methods"],
            }
        )
    payload = json.dumps({"review_class": "flt3_gs500rox_reverse_projection_candidates", "rows": payload_rows}).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>FLT3 Reverse Projection Candidates</title>
<style>
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f7f9; color:#111827; }}
header {{ position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid #d1d5db; padding:12px 18px; display:flex; justify-content:space-between; align-items:center; }}
h1 {{ margin:0; font-size:18px; }}
main {{ max-width:1500px; margin:0 auto; padding:16px; }}
.case {{ background:white; border:1px solid #d1d5db; border-radius:8px; padding:12px; margin-bottom:18px; }}
.title {{ font-weight:700; font-size:15px; }}
.meta,.methods {{ margin-top:5px; color:#374151; font-size:12px; line-height:1.38; }}
img {{ display:block; width:100%; height:auto; border:1px solid #e5e7eb; border-radius:4px; margin-top:10px; }}
textarea,#exportBox {{ width:100%; min-height:64px; margin-top:10px; box-sizing:border-box; border:1px solid #cbd5e1; border-radius:6px; padding:8px; font:13px/1.35 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; }}
#export {{ background:#111827; color:#fff; border:1px solid #111827; border-radius:6px; padding:7px 11px; cursor:pointer; }}
#exportBox {{ display:none; min-height:180px; }}
</style></head><body>
<header><h1>FLT3 Reverse Projection Candidates</h1><button id="export" type="button">Export notes</button></header>
<main><textarea id="exportBox" readonly></textarea>{''.join(cards)}</main>
<script>
const payload = {payload};
const storageKey = "flt3_gs500rox_reverse_projection_candidate_notes";
const state = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
document.querySelectorAll(".case").forEach((card, idx) => {{
  const key = payload.rows[idx].raw_path;
  const textarea = card.querySelector("textarea");
  textarea.value = state[key] || "";
  textarea.addEventListener("input", () => {{ state[key] = textarea.value; localStorage.setItem(storageKey, JSON.stringify(state)); }});
}});
document.getElementById("export").addEventListener("click", () => {{
  const rows = payload.rows.map(row => {{ return {{...row, note: state[row.raw_path] || ""}}; }});
  const text = JSON.stringify({{exported_at:new Date().toISOString(), rows}}, null, 2);
  const box = document.getElementById("exportBox"); box.value = text; box.style.display = "block"; box.focus(); box.select();
  const blob = new Blob([text], {{type:"application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "flt3_gs500rox_reverse_projection_candidate_notes.json"; a.click(); URL.revokeObjectURL(a.href);
}});
</script></body></html>"""
    (out_dir / "review_panel.html").write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with args.panel.open(newline="", encoding="utf-8") as handle:
        panel_rows = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for panel_no, panel_row in enumerate(panel_rows, start=1):
        path = resolve_path(panel_row, args.data_root)
        file_name = panel_row.get("File") or panel_row.get("file") or path.name
        print(f"[{panel_no}/{len(panel_rows)}] {file_name}", flush=True)
        analysis = analyze_path(path, args.timeout)
        if not analysis.get("ok"):
            continue
        current = _selected_scans(analysis)
        if len(current) != len(GS500ROX_SIZES):
            continue
        trace = corrected_trace(raw_trace(path, analysis.get("channel") or "DATA4"))
        methods = _choose_methods(trace, current)
        if not methods:
            continue
        row = {
            "panel_no": panel_no,
            "file": file_name,
            "raw_path": str(path),
            "methods": methods,
        }
        row["image"] = _render_case(args.out_dir, row, trace, current, methods)
        rows.append(row)
    with (args.out_dir / "candidate_rows.json").open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    _write_html(args.out_dir, rows)
    print(json.dumps({"rows": len(rows), "html": str(args.out_dir / "review_panel.html")}, indent=2))


if __name__ == "__main__":
    main()
