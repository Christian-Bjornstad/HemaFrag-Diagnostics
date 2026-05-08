from __future__ import annotations

import argparse
import ast
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

LADDER_SIZES = {
    "ROX400HD": [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
    "LIZ500_250": [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500],
}


def parse_selected(value: object) -> list[int]:
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for item in parsed:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def changed_indices(old: list[int], new: list[int]) -> list[int]:
    return [
        idx
        for idx, (old_scan, new_scan) in enumerate(zip(old, new))
        if int(old_scan) != int(new_scan)
    ]


def render_row(row: pd.Series, out_dir: Path, y_max: float | None) -> dict[str, object]:
    raw_path = Path(str(row.raw_path))
    ladder = str(row.ladder_new or row.ladder_old or "")
    old = parse_selected(row.selected_old)
    new = parse_selected(row.selected_new)
    changed = changed_indices(old, new)
    if not old or not new or not changed:
        return {"file": raw_path.name, "image": "", "changed_steps": ""}

    channel = "DATA4" if ladder == "ROX400HD" else "DATA105"
    raw = live_eval.raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return {"file": raw_path.name, "image": "", "changed_steps": ",".join(map(str, changed))}
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)
    sizes = LADDER_SIZES.get(ladder, list(range(1, len(new) + 1)))

    changed_scans = [*old, *new]
    first_focus = max(0, min(changed_scans) - 300)
    last_focus = min(trace.size - 1, max(changed_scans) + 350)
    if ladder == "ROX400HD" and max(changed) <= 2:
        first_focus = max(0, min(old[:3] + new[:3]) - 260)
        last_focus = min(trace.size - 1, max(old[:4] + new[:4]) + 350)
    window = trace[first_focus:last_focus]
    local_y_max = y_max
    if local_y_max is None:
        local_y_max = 500.0
        if window.size:
            local_y_max = max(180.0, min(2500.0, float(np.nanpercentile(window, 99.7) * 1.18)))

    fig, ax = plt.subplots(figsize=(12, 4.8), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.8, label=trace_label)
    ax.scatter(old, [trace[idx] if 0 <= idx < trace.size else np.nan for idx in old], s=48, marker="x", color="#dc2626", label="old")
    ax.scatter(new, [trace[idx] if 0 <= idx < trace.size else np.nan for idx in new], s=42, marker="o", facecolors="none", edgecolors="#059669", linewidth=1.7, label="new")

    for idx in changed:
        if idx < len(old) and 0 <= old[idx] < trace.size:
            label = str(sizes[idx]) if idx < len(sizes) else str(idx + 1)
            ax.annotate(f"old {label}", (old[idx], trace[old[idx]]), xytext=(0, 12), textcoords="offset points", ha="center", fontsize=7, color="#dc2626")
        if idx < len(new) and 0 <= new[idx] < trace.size:
            label = str(sizes[idx]) if idx < len(sizes) else str(idx + 1)
            ax.annotate(f"new {label}", (new[idx], trace[new[idx]]), xytext=(0, -16), textcoords="offset points", ha="center", fontsize=7, color="#059669")

    title = (
        f"{raw_path.name} | {ladder} | changed steps {','.join(str(i + 1) for i in changed)} | "
        f"max {row.linear_max_old:.2f}->{row.linear_max_new:.2f} mean {row.linear_mean_old:.2f}->{row.linear_mean_new:.2f}"
    )
    ax.set_title(title, fontsize=10)
    ax.set_xlim(first_focus, last_focus)
    ax.set_ylim(-20, local_y_max)
    ax.grid(True, alpha=0.18)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_xlabel("scan")
    ax.set_ylabel("corrected intensity")
    fig.tight_layout()

    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / f"{raw_path.stem}_selection_delta.png"
    fig.savefig(image_path)
    plt.close(fig)
    return {
        "file": raw_path.name,
        "ladder": ladder,
        "changed_steps": ",".join(str(idx + 1) for idx in changed),
        "old_selected": old,
        "new_selected": new,
        "image": str(image_path),
    }


def run(args: argparse.Namespace) -> None:
    old_path = args.old if args.old.is_absolute() else ROOT / args.old
    new_path = args.new if args.new.is_absolute() else ROOT / args.new
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    old = pd.read_csv(old_path, sep="\t")
    new = pd.read_csv(new_path, sep="\t")
    keep = ["raw_path", "file", "ladder", "selected", "linear_max", "linear_mean", "linear_r2"]
    merged = new[keep].merge(old[keep], on="raw_path", suffixes=("_new", "_old"))
    for col in ["linear_max_new", "linear_max_old", "linear_mean_new", "linear_mean_old"]:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
    merged["selected_changed"] = merged["selected_new"].astype(str) != merged["selected_old"].astype(str)
    focus = merged[merged["selected_changed"]].copy()
    if args.limit:
        focus = focus.head(args.limit)

    rows = [render_row(row, out_dir, args.y_max) for row in focus.itertuples(index=False)]
    index = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    index.to_csv(out_dir / "selection_delta_image_index.tsv", sep="\t", index=False)
    print(f"changed={len(focus)} rendered={index['image'].astype(bool).sum() if not index.empty else 0} out={out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--y-max", type=float, default=None)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
