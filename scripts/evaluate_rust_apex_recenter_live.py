from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rust_bridge import _get_rust_worker, _invalidate_rust_worker
from fraggler.fraggler import FsaFile


OUT_DIR = ROOT / "artifacts" / "rust_apex_recenter_live_eval"
IMAGE_DIR = OUT_DIR / "images"

FOCUS_PATHS = [
    "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16406_KDE__281025_E10_H920G04X.fsa",
    "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16288_tcrgA__281025_B02_H920G04X.fsa",
    "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16351_IGK__281025_C07_H920G04X.fsa",
    "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16577_tcrgB__281025_E03_H920G04X.fsa",
    "/Volumes/T7 Shield/29_04/2026_04_29_FR_DHJH_CFB_C99174FC_2026-04-29_0731/26OUM05318_FR3_290426_A05_C99174FC.fsa",
    "/Volumes/T7 Shield/29_04/2026_04_29_FR_DHJH_CFB_C99174FC_2026-04-29_0731/26OUM05517_FR1_290426_B02_C99174FC.fsa",
    "/Volumes/T7 Shield/29_04/2026_04_29_FR_DHJH_CFB_C99174FC_2026-04-29_0731/26OUM06086_FR2_290426_D03_C99174FC.fsa",
]


def load_paths() -> list[Path]:
    paths: list[str] = []
    cases_path = ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json"
    if cases_path.exists():
        rows = json.loads(cases_path.read_text())
        paths.extend(str(row["raw_path"]) for row in rows if row.get("raw_path"))

    detail_path = ROOT / "artifacts" / "fit_arbiter_v2_apex_eval" / "detail.tsv"
    if detail_path.exists():
        with detail_path.open(newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            paths.extend(row["raw_path"] for row in reader if row.get("raw_path"))

    paths.extend(FOCUS_PATHS)
    unique = []
    seen = set()
    for value in paths:
        if value in seen:
            continue
        seen.add(value)
        path = Path(value)
        if path.exists():
            unique.append(path)
    return unique


def selected_scans(preview: dict) -> list[int]:
    refinement = preview.get("refinement") or {}
    scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
    return [int(value) for value in scans]


def analyze_path(worker, path: Path) -> dict:
    response = worker.request(path, "clonality", 30)
    if not response or not response.get("ok"):
        return {
            "raw_path": str(path),
            "file": path.name,
            "ok": False,
            "error": (response or {}).get("error", "no response"),
        }
    result = response.get("result") if isinstance(response.get("result"), dict) else response
    preview = result.get("ladder_fit_preview") or {}
    model = preview.get("sizing_model") or {}
    metrics = model.get("qc_metrics") or {}
    review = result.get("ladder_review_assessment") or {}
    refinement = preview.get("refinement") or {}
    scans = selected_scans(preview)
    return {
        "raw_path": str(path),
        "file": path.name,
        "ok": True,
        "ladder": result.get("ladder") or "",
        "channel": result.get("size_standard_channel_guess") or "",
        "candidate_count": len(result.get("ladder_peak_preview") or []),
        "selected_count": len(scans),
        "selected": json.dumps(scans),
        "refinement_changed_steps": json.dumps(refinement.get("changed_step_indices") or []),
        "refinement_original": json.dumps(refinement.get("original_scan_indices") or []),
        "linear_max": metrics.get("linear_trend_max_abs_error_bp"),
        "linear_mean": metrics.get("linear_trend_mean_abs_error_bp"),
        "linear_r2": metrics.get("linear_trend_r2"),
        "review": bool(review.get("suggested_review")),
        "reason_codes": json.dumps(review.get("reason_codes") or []),
        "primary_reason": review.get("primary_reason") or "",
        "result": result,
    }


def raw_trace(path: Path, ladder: str, channel: str) -> np.ndarray | None:
    try:
        probe = FsaFile(
            file=str(path),
            ladder=ladder or "LIZ500_250",
            sample_channel="DATA1",
            min_distance_between_peaks=15,
            min_size_standard_height=50,
            size_standard_channel=channel or "DATA105",
        )
    except Exception:
        return None
    if channel in probe.fsa:
        return np.asarray(probe.fsa[channel], dtype=float)
    for fallback in ("DATA105", "DATA4", "DATA5"):
        if fallback in probe.fsa:
            return np.asarray(probe.fsa[fallback], dtype=float)
    return None


def rolling_quantile_baseline(trace: np.ndarray, bin_size: int = 200, quantile: float = 0.10) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    if values.size == 0:
        return values
    centers: list[float] = []
    base_vals: list[float] = []
    for start in range(0, values.size, bin_size):
        end = min(values.size, start + bin_size)
        centers.append((start + end - 1) * 0.5)
        base_vals.append(float(np.nanquantile(values[start:end], quantile)))
    return np.interp(np.arange(values.size), np.asarray(centers), np.asarray(base_vals))


def rolling_minimum(trace: np.ndarray, window: int) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    radius = max(1, window // 2)
    out = np.empty_like(values)
    for idx in range(values.size):
        start = max(0, idx - radius)
        end = min(values.size, idx + radius + 1)
        out[idx] = np.nanmin(values[start:end])
    return out


def rolling_maximum(trace: np.ndarray, window: int) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    radius = max(1, window // 2)
    out = np.empty_like(values)
    for idx in range(values.size):
        start = max(0, idx - radius)
        end = min(values.size, idx + radius + 1)
        out[idx] = np.nanmax(values[start:end])
    return out


def corrected_display_trace(trace: np.ndarray, ladder: str) -> tuple[np.ndarray, str]:
    values = np.asarray(trace, dtype=float)
    if ladder == "LIZ500_250":
        baseline = rolling_maximum(rolling_minimum(values, 151), 151)
        return np.maximum(values - baseline, 0.0), "baseline-corrected trace (morph_open_151)"
    baseline = rolling_quantile_baseline(values, 200, 0.10)
    return np.maximum(values - baseline, 0.0), "baseline-corrected trace (quantile_200)"


def render_image(row: dict) -> str | None:
    result = row.get("result") or {}
    path = Path(row["raw_path"])
    ladder = row.get("ladder") or result.get("ladder") or ""
    channel = row.get("channel") or result.get("size_standard_channel_guess") or ""
    raw = raw_trace(path, ladder, channel)
    if raw is None or raw.size == 0:
        return None
    trace, trace_label = corrected_display_trace(raw, ladder)

    preview = result.get("ladder_fit_preview") or {}
    scans = selected_scans(preview)
    refinement = preview.get("refinement") or {}
    original_scans = [int(value) for value in refinement.get("original_scan_indices") or []]
    candidate_peaks = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or []]

    x_max = min(5000, trace.size - 1)
    x_min = 1200 if ladder == "LIZ500_250" else 1300
    window = trace[x_min:x_max] if x_max > x_min else trace
    if window.size:
        p1, p99 = np.nanpercentile(window, [1.0, 99.0])
        ymin = float(min(0.0, p1 * 1.10))
        ymax = float(max(50.0, p99 * 1.15))
    else:
        ymin = float(min(0.0, np.nanmin(trace)))
        ymax = float(max(50.0, np.nanmax(trace)))
    selected_y = [trace[idx] for idx in scans if 0 <= idx < trace.size]
    if selected_y:
        ymin = min(ymin, float(min(selected_y)) - 30.0)
        ymax = max(ymax, float(max(selected_y)) + 30.0)
    if ymax - ymin < 160.0:
        center = (ymax + ymin) / 2.0
        ymin = center - 80.0
        ymax = center + 80.0
    ymax = min(max(ymax, 300.0), 5000.0)
    ymin = max(ymin, -2000.0)

    fig, ax = plt.subplots(figsize=(12, 4.6), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#1f2937", linewidth=0.85, alpha=0.95, label=trace_label)

    cand = [idx for idx in candidate_peaks if x_min <= idx <= x_max and 0 <= idx < trace.size]
    if cand:
        ax.scatter(cand, [trace[idx] for idx in cand], s=18, color="#9ca3af", alpha=0.6, label="possible peaks")

    if original_scans and original_scans != scans:
        original = [idx for idx in original_scans if x_min <= idx <= x_max and 0 <= idx < trace.size]
        ax.scatter(
            original,
            [trace[idx] for idx in original],
            s=42,
            marker="x",
            linewidths=1.8,
            color="#f97316",
            label="before recenter",
        )

    selected = [idx for idx in scans if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(selected, [trace[idx] for idx in selected], s=44, color="#dc2626", zorder=4, label="Rust selected")

    sizes = [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500]
    if ladder == "ROX400HD":
        sizes = [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400]
    for i, idx in enumerate(scans):
        if x_min <= idx <= x_max and 0 <= idx < trace.size:
            label = str(sizes[i]) if i < len(sizes) else str(i + 1)
            label_y = min(max(trace[idx] + (ymax - ymin) * 0.035, ymin + (ymax - ymin) * 0.04), ymax - (ymax - ymin) * 0.06)
            ax.text(idx, label_y, label, fontsize=7, ha="center", color="#7f1d1d")

    linear_max = row.get("linear_max")
    linear_mean = row.get("linear_mean")
    linear_r2 = row.get("linear_r2")
    metric_text = ""
    if linear_max is not None:
        metric_text = f" | linear {float(linear_max):.2f} / {float(linear_mean):.2f} / {float(linear_r2):.6f}"
    ax.set_title(f"{path.name} | {ladder} {channel}{metric_text}", fontsize=10)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(ymin, ymax)
    ax.set_xlabel("scan time")
    ax.set_ylabel("RFU")
    ax.grid(alpha=0.18)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()

    safe_name = path.stem.replace("/", "_")
    out = IMAGE_DIR / f"{safe_name}.png"
    fig.savefig(out)
    plt.close(fig)
    return str(out)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker not available")

    rows = []
    for path in load_paths():
        row = analyze_path(worker, path)
        rows.append(row)
        if row.get("error", "").startswith("worker timeout"):
            _invalidate_rust_worker()
            worker = _get_rust_worker()
            if worker is None:
                raise SystemExit("Rust worker not available after timeout restart")

    fieldnames = [
        "file",
        "raw_path",
        "ok",
        "ladder",
        "channel",
        "candidate_count",
        "selected_count",
        "linear_max",
        "linear_mean",
        "linear_r2",
        "review",
        "primary_reason",
        "reason_codes",
        "refinement_changed_steps",
        "refinement_original",
        "selected",
        "error",
    ]
    with (OUT_DIR / "summary.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    focus_set = {str(Path(value)) for value in FOCUS_PATHS}
    image_rows = [row for row in rows if row.get("raw_path") in focus_set and row.get("ok")]
    image_paths = []
    for row in image_rows:
        image_path = render_image(row)
        if image_path:
            image_paths.append({"file": row["file"], "image": image_path})
    with (OUT_DIR / "image_index.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "image"], delimiter="\t")
        writer.writeheader()
        writer.writerows(image_paths)

    ok_rows = [row for row in rows if row.get("ok")]
    by_ladder = defaultdict(list)
    for row in ok_rows:
        by_ladder[row.get("ladder") or "unknown"].append(row)

    print(f"evaluated={len(rows)} ok={len(ok_rows)} errors={len(rows) - len(ok_rows)}")
    print(f"review={sum(1 for row in ok_rows if row.get('review'))}")
    print("ladder_counts", Counter(row.get("ladder") or "unknown" for row in ok_rows))
    for ladder, group in sorted(by_ladder.items()):
        max_values = [float(row["linear_max"]) for row in group if row.get("linear_max") is not None]
        mean_values = [float(row["linear_mean"]) for row in group if row.get("linear_mean") is not None]
        if max_values:
            print(
                ladder,
                f"n={len(group)}",
                f"mean_max={np.mean(max_values):.3f}",
                f"p95_max={np.percentile(max_values, 95):.3f}",
                f"mean_mean={np.mean(mean_values):.3f}",
                f"over6={sum(value > 6.0 for value in max_values)}",
            )
    print(f"images={len(image_paths)} out={OUT_DIR}")


if __name__ == "__main__":
    main()
