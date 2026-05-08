from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any


os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker  # noqa: E402
from scripts import evaluate_rust_apex_recenter_live as live_eval  # noqa: E402


DEFAULT_CASE_RESULTS = ROOT / "artifacts" / "ladder_manifest_delta_eval_manual_2026-05-05" / "case_results.tsv"
DEFAULT_TRIAGE = ROOT / "artifacts" / "ladder_delta_triage_manual_2026-05-05" / "triage.tsv"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "ladder_delta_triage_manual_2026-05-05" / "images"

LADDER_SIZES = {
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
}


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_json_ints(value: object) -> list[int]:
    raw = text(value)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = re.findall(r"-?\d+(?:\.\d+)?", raw)
    out: list[int] = []
    if isinstance(payload, list):
        for item in payload:
            try:
                out.append(int(round(float(item))))
            except (TypeError, ValueError):
                continue
    return out


def to_float(value: object) -> float:
    raw = text(value)
    if not raw:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def join_rows(case_results: Path, triage_path: Path) -> list[dict[str, str]]:
    triage_by_path = {text(row.get("full_path")): row for row in load_tsv(triage_path)}
    rows: list[dict[str, str]] = []
    for row in load_tsv(case_results):
        triage = triage_by_path.get(text(row.get("full_path")))
        if not triage:
            continue
        merged = dict(row)
        merged.update({f"triage_{key}": value for key, value in triage.items()})
        rows.append(merged)
    return rows


def selected_from_analysis(analysis: dict[str, Any]) -> list[int]:
    result = analysis.get("result") or {}
    preview = result.get("ladder_fit_preview") or {}
    return live_eval.selected_scans(preview)


def plot_row(row: dict[str, str], analysis: dict[str, Any], out_dir: Path) -> str | None:
    raw_path = Path(text(row.get("full_path")))
    ladder = text(row.get("ladder")) or text(analysis.get("ladder"))
    channel = text(analysis.get("channel"))
    raw = live_eval.raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return None
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)
    result = analysis.get("result") or {}
    current = selected_from_analysis(analysis) or parse_json_ints(row.get("current_selected"))
    reference = parse_json_ints(row.get("reference_selected"))
    candidate_peaks = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or [] if peak.get("index") is not None]

    x_min = 1200 if ladder == "LIZ500_250" else 1300
    x_max = min(5000, trace.size - 1)
    window = trace[x_min:x_max] if x_max > x_min else trace
    if window.size:
        ymax = float(max(120.0, np.nanpercentile(window, 99.3) * 1.20))
    else:
        ymax = float(max(120.0, np.nanmax(trace)))
    focus_y = [trace[idx] for idx in current + reference if 0 <= idx < trace.size]
    if focus_y:
        ymax = max(ymax, float(max(focus_y)) + 60.0)
    ymax = min(max(ymax, 250.0), 5000.0)

    fig, ax = plt.subplots(figsize=(15, 5.4), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.9, label=trace_label)

    cand = [idx for idx in candidate_peaks if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if cand:
        ax.scatter(cand, [trace[idx] for idx in cand], s=16, color="#9ca3af", alpha=0.55, label="possible peaks")

    ref = [idx for idx in reference if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if ref:
        ax.scatter(ref, [trace[idx] for idx in ref], s=72, marker="^", color="#0f766e", alpha=0.92, zorder=4, label="manual/reference")

    cur = [idx for idx in current if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if cur:
        ax.scatter(cur, [trace[idx] for idx in cur], s=42, color="#dc2626", zorder=5, label="current Rust")

    sizes = LADDER_SIZES.get(ladder, [])
    for idx, scan in enumerate(current):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            label = str(sizes[idx]) if idx < len(sizes) else str(idx + 1)
            ax.text(scan, min(trace[scan] + ymax * 0.035, ymax * 0.96), label, fontsize=7, ha="center", color="#7f1d1d")
    for idx, scan in enumerate(reference):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            label = str(sizes[idx]) if idx < len(sizes) else str(idx + 1)
            ax.text(scan, max(trace[scan] - ymax * 0.055, 5), label, fontsize=7, ha="center", color="#115e59")

    linear_max = to_float(row.get("current_linear_max"))
    linear_mean = to_float(row.get("current_linear_mean"))
    linear_r2 = to_float(row.get("current_linear_r2"))
    metric = ""
    if not math.isnan(linear_max):
        metric = f" | linear {linear_max:.2f}/{linear_mean:.2f}/{linear_r2:.6f}"
    title = (
        f"{text(row.get('triage_priority'))} {text(row.get('triage_triage_class'))} | "
        f"{raw_path.name} | {ladder}{metric}"
    )
    ax.set_title(title, fontsize=10)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, ymax)
    ax.set_xlabel("scan time")
    ax.set_ylabel("baseline-corrected RFU")
    ax.grid(alpha=0.18)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()

    out_name = f"{text(row.get('triage_priority'))}_{safe_name(text(row.get('triage_triage_class')))}_{safe_name(raw_path.stem)}.png"
    out_path = out_dir / out_name
    fig.savefig(out_path)
    plt.close(fig)
    return str(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render P0/P1 ladder delta triage images.")
    parser.add_argument("--case-results", type=Path, default=DEFAULT_CASE_RESULTS)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--priorities", default="P0,P1")
    args = parser.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    priorities = {item.strip() for item in args.priorities.split(",") if item.strip()}
    rows = [row for row in join_rows(args.case_results, args.triage) if text(row.get("triage_priority")) in priorities]
    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")

    image_rows: list[dict[str, str]] = []
    for row in rows:
        raw_path = Path(text(row.get("full_path")))
        analysis = live_eval.analyze_path(worker, raw_path)
        image = plot_row(row, analysis, out_dir) if analysis.get("ok") else None
        image_rows.append(
            {
                "priority": text(row.get("triage_priority")),
                "triage_class": text(row.get("triage_triage_class")),
                "file": text(row.get("file")),
                "ladder": text(row.get("ladder")),
                "image": image or "",
                "ok": str(bool(analysis.get("ok"))),
                "error": text(analysis.get("error")),
            }
        )

    index_path = out_dir / "images.tsv"
    with index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["priority", "triage_class", "file", "ladder", "image", "ok", "error"], delimiter="\t")
        writer.writeheader()
        writer.writerows(image_rows)

    report_lines = ["# Ladder Delta Triage Images", ""]
    for row in image_rows:
        if row["image"]:
            report_lines.append(f"- `{row['priority']}` `{row['triage_class']}` `{row['file']}`: `{row['image']}`")
        else:
            report_lines.append(f"- `{row['priority']}` `{row['triage_class']}` `{row['file']}`: render failed `{row['error']}`")
    (out_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    summary = {
        "rows": len(rows),
        "rendered": sum(1 for row in image_rows if row["image"]),
        "images": str(index_path.relative_to(ROOT)),
        "report": str((out_dir / "report.md").relative_to(ROOT)),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
