from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.evaluate_rust_apex_recenter_live as live_eval  # noqa: E402
from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker  # noqa: E402
from scripts.rox_start_prefix_diagnostics import selected_scans, unwrap_response  # noqa: E402


DEFAULT_EVAL = ROOT / "artifacts" / "rox_prefix_feature_rule_eval_2026-05-06" / "prefix_feature_eval.tsv"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "rox_prefix_feature_rule_eval_2026-05-06" / "images"
ROX_SIZES = [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400]


def parse_pair(value: object) -> list[int]:
    raw = str(value or "").strip()
    if not raw or "," not in raw:
        return []
    try:
        return [int(part) for part in raw.split(",")[:2]]
    except ValueError:
        return []


def analyze(raw_path: Path, timeout: int) -> dict:
    worker = _get_rust_worker()
    if worker is None:
        return {"ok": False, "error": "Rust worker unavailable"}
    response = worker.request(raw_path, "clonality", timeout)
    result, error = unwrap_response(response)
    if error and "timeout" in error.lower():
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is not None:
            response = worker.request(raw_path, "clonality", max(timeout * 2, 120))
            result, error = unwrap_response(response)
    if error:
        return {"ok": False, "error": error}
    return {"ok": True, "result": result, "selected": selected_scans(result.get("ladder_fit_preview") or {})}


def render_row(row: pd.Series, out_dir: Path, timeout: int) -> str:
    raw_path = Path(str(row.raw_path))
    analysis = analyze(raw_path, timeout)
    if not analysis.get("ok"):
        return ""
    result = analysis["result"]
    ladder = str(result.get("ladder") or "")
    raw = live_eval.raw_trace(raw_path, ladder, str(result.get("size_standard_channel_guess") or ""))
    if raw is None or raw.size == 0:
        return ""
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)
    current_full = analysis["selected"]
    current_pair = parse_pair(row.current_pair)
    feature_pair = parse_pair(row.feature_pair)
    manual_pair = parse_pair(row.manual_pair)
    candidates = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or [] if "index" in peak]

    x_min = max(1250, min([*current_pair, *feature_pair, *manual_pair, *(current_full[:3] or [1600])]) - 350)
    x_max = min(trace.size - 1, max([*current_pair, *feature_pair, *manual_pair, *(current_full[:4] or [2100])]) + 550)
    window = trace[x_min:x_max]
    y_max = 1000.0
    if window.size:
        y_max = max(180.0, min(1800.0, float(np.nanpercentile(window, 99.5) * 1.18)))

    fig, ax = plt.subplots(figsize=(12, 4.6), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.8, label=trace_label)
    visible_candidates = [idx for idx in candidates if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(visible_candidates, [trace[idx] for idx in visible_candidates], s=18, color="#9ca3af", alpha=0.55, label="possible")
    if current_pair:
        ax.scatter(current_pair, [trace[idx] for idx in current_pair], color="#dc2626", marker="x", s=68, linewidth=1.8, label="current 50/60")
    if feature_pair:
        ax.scatter(feature_pair, [trace[idx] for idx in feature_pair], color="#059669", marker="^", s=70, alpha=0.88, label="feature 50/60")
    if manual_pair:
        ax.scatter(manual_pair, [trace[idx] for idx in manual_pair], facecolors="none", edgecolors="#2563eb", marker="o", s=92, linewidth=1.9, label="manual 50/60")
    for idx, scan in enumerate(current_full[: min(len(current_full), len(ROX_SIZES))]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.annotate(str(ROX_SIZES[idx]), (scan, trace[scan]), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=7, color="#374151")
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-20, y_max)
    ax.grid(True, alpha=0.18)
    ax.set_title(
        f"{raw_path.name} | {row.status} | current {row.current_pair} | feature {row.feature_pair} | manual {row.manual_pair}"
    )
    ax.legend(loc="upper right", fontsize=8)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{raw_path.stem}_rox_prefix_feature.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def run(args: argparse.Namespace) -> None:
    eval_path = args.eval if args.eval.is_absolute() else ROOT / args.eval
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    df = pd.read_csv(eval_path, sep="\t")
    focus_status = set(args.status)
    focus = df[df["status"].isin(focus_status)].copy()
    if args.limit:
        focus = focus.head(args.limit)
    rows = []
    for idx, row in enumerate(focus.itertuples(index=False), start=1):
        image = render_row(pd.Series(row._asdict()), out_dir, args.timeout)
        rows.append({"file": row.file, "status": row.status, "image": image})
        print(f"{idx}/{len(focus)} {row.file}: {image}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(out_dir.parent / "prefix_feature_image_index.tsv", sep="\t", index=False)
    print(f"rendered={out['image'].astype(bool).sum()} out={out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--status", action="append", default=["manual_closer_feature_pair", "control_would_change"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=90)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
