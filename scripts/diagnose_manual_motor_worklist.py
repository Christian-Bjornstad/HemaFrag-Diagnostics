from __future__ import annotations

import csv
import json
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


OUT_DIR = ROOT / "artifacts" / "manual_motor_worklist_diagnostics_2026-05-04"
IMAGE_DIR = OUT_DIR / "images"
ANNOTATION_DIR = ROOT / "artifacts" / "manual_review_annotations_2026-05-04"

LIZ_SIZES = [35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500]
ROX_SIZES = [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400]


def ladder_sizes(ladder: str) -> list[int]:
    return ROX_SIZES if ladder == "ROX400HD" else LIZ_SIZES


def load_worklist() -> pd.DataFrame:
    worklist = pd.read_csv(ANNOTATION_DIR / "motor_worklist.tsv", sep="\t")
    lookup = pd.read_csv(
        ROOT / "artifacts" / "historical_ladder_qc_overview_2026-05-04" / "all_rows.tsv",
        sep="\t",
        usecols=["raw_file", "raw_path", "source_group", "Assay", "SourceRunDir"],
    ).drop_duplicates(subset=["raw_file"], keep="first")
    rows = worklist.merge(lookup, left_on="file", right_on="raw_file", how="left")
    missing = rows[rows["raw_path"].isna()]["file"].tolist()
    if missing:
        raise SystemExit(f"Missing raw_path lookup for: {missing}")
    rows = rows[rows["raw_path"].map(lambda value: Path(str(value)).exists())].copy()
    return rows


def safe_analyze(worker, path: Path) -> dict:
    analysis = analyze_path_with_timeout(worker, path, timeout_seconds=45)
    error = str(analysis.get("error", ""))
    if error.startswith("worker timeout") or error == "no response":
        _invalidate_rust_worker()
        worker = _get_rust_worker()
        if worker is None:
            raise SystemExit("Rust worker unavailable after timeout")
        analysis = analyze_path_with_timeout(worker, path, timeout_seconds=120)
    return analysis


def analyze_path_with_timeout(worker, path: Path, timeout_seconds: int) -> dict:
    response = worker.request(path, "clonality", timeout_seconds)
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
    scans = live_eval.selected_scans(preview)
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


def peak_rows(analysis: dict, annotation: pd.Series) -> list[dict]:
    result = analysis.get("result") or {}
    selected = live_eval.selected_scans(result.get("ladder_fit_preview") or {})
    selected_set = set(selected)
    sizes = ladder_sizes(str(analysis.get("ladder") or annotation.get("ladder") or ""))
    bp_by_scan = {scan: sizes[idx] for idx, scan in enumerate(selected[: len(sizes)])}
    rows: list[dict] = []
    for peak in result.get("ladder_peak_preview") or []:
        scan = int(peak.get("index", -1))
        rows.append(
            {
                "file": analysis["file"],
                "ladder": analysis.get("ladder", ""),
                "scan": scan,
                "selected": scan in selected_set,
                "selected_bp": bp_by_scan.get(scan, ""),
                "height": peak.get("height", ""),
                "prominence": peak.get("prominence", ""),
                "width": peak.get("width", ""),
                "local_baseline": peak.get("local_baseline", ""),
                "score": peak.get("score", ""),
            }
        )
    return rows


def selected_rows(analysis: dict, annotation: pd.Series) -> list[dict]:
    result = analysis.get("result") or {}
    selected = live_eval.selected_scans(result.get("ladder_fit_preview") or {})
    sizes = ladder_sizes(str(analysis.get("ladder") or annotation.get("ladder") or ""))
    peaks = {int(peak["index"]): peak for peak in result.get("ladder_peak_preview") or []}
    rows: list[dict] = []
    for idx, scan in enumerate(selected[: len(sizes)]):
        peak = peaks.get(scan, {})
        rows.append(
            {
                "file": analysis["file"],
                "step": idx + 1,
                "bp": sizes[idx],
                "scan": scan,
                "height": peak.get("height", ""),
                "prominence": peak.get("prominence", ""),
                "width": peak.get("width", ""),
                "local_baseline": peak.get("local_baseline", ""),
                "score": peak.get("score", ""),
            }
        )
    return rows


def nearest_candidate_summary(analysis: dict, targets: list[int], radius: int = 35) -> str:
    result = analysis.get("result") or {}
    peaks = result.get("ladder_peak_preview") or []
    parts: list[str] = []
    for target in targets:
        nearby = [peak for peak in peaks if abs(int(peak.get("index", -999999)) - target) <= radius]
        if not nearby:
            parts.append(f"{target}:no_candidate")
            continue
        best = max(nearby, key=lambda peak: float(peak.get("height") or 0.0))
        parts.append(f"{target}:{int(best['index'])}/h{float(best.get('height') or 0):.0f}")
    return "; ".join(parts)


def manual_target_probes(file_name: str) -> list[int]:
    if "16288" in file_name:
        return [1500, 1550, 4500, 4550]
    if "16586" in file_name:
        return [1800, 1900, 2000, 2100, 2200]
    if "00537" in file_name:
        return [1500, 1700, 1900, 2100, 2500, 3000, 3500]
    if "03951" in file_name:
        return [1450, 1500, 1580, 3400, 4000]
    if "04026" in file_name or "04155" in file_name:
        return [1450, 1500, 1550, 1600, 2100, 2200]
    if "14507" in file_name or "14619" in file_name:
        return [1450, 1500, 2100, 2200, 2500]
    return []


def render_diagnostic_image(analysis: dict, annotation: pd.Series) -> str | None:
    result = analysis.get("result") or {}
    raw_path = Path(str(annotation["raw_path"]))
    ladder = str(analysis.get("ladder") or annotation["ladder"])
    channel = str(analysis.get("channel") or result.get("size_standard_channel_guess") or "")
    raw = live_eval.raw_trace(raw_path, ladder, channel)
    if raw is None or raw.size == 0:
        return None
    trace, trace_label = live_eval.corrected_display_trace(raw, ladder)
    selected = live_eval.selected_scans(result.get("ladder_fit_preview") or {})
    candidates = [int(peak["index"]) for peak in result.get("ladder_peak_preview") or []]
    sizes = ladder_sizes(ladder)

    x_min = 1200 if ladder == "LIZ500_250" else 1300
    x_max = min(5000, trace.size - 1)
    y_max = 1000.0
    if ladder == "LIZ500_250":
        y_max = 700.0
    window = trace[x_min:x_max]
    if window.size:
        y_max = max(250.0, min(y_max, float(np.nanpercentile(window, 99.5) * 1.15)))

    fig, ax = plt.subplots(figsize=(13, 4.8), dpi=160)
    xs = np.arange(trace.size)
    ax.plot(xs, trace, color="#111827", linewidth=0.85, label=trace_label)
    visible_candidates = [idx for idx in candidates if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(
        visible_candidates,
        [trace[idx] for idx in visible_candidates],
        color="#9ca3af",
        s=18,
        alpha=0.65,
        label="possible",
    )
    visible_selected = [idx for idx in selected if x_min <= idx <= x_max and 0 <= idx < trace.size]
    ax.scatter(
        visible_selected,
        [trace[idx] for idx in visible_selected],
        color="#dc2626",
        s=42,
        marker="x",
        linewidth=1.5,
        label="selected",
    )
    for idx, scan in enumerate(selected[: len(sizes)]):
        if x_min <= scan <= x_max and 0 <= scan < trace.size:
            ax.annotate(
                str(sizes[idx]),
                (scan, trace[scan]),
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color="#b91c1c",
            )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-20, y_max)
    ax.grid(True, alpha=0.18)
    ax.set_title(
        f"{analysis['file']} | {ladder} | max/mean/r2="
        f"{float(analysis.get('linear_max') or float('nan')):.2f}/"
        f"{float(analysis.get('linear_mean') or float('nan')):.2f}/"
        f"{float(analysis.get('linear_r2') or float('nan')):.6f}"
    )
    ax.legend(loc="upper right", fontsize=8)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = analysis["file"].replace(".fsa", "").replace("/", "_")
    out = IMAGE_DIR / f"{safe_name}_diagnostic.png"
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return str(out)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_worklist()
    worker = _get_rust_worker()
    if worker is None:
        raise SystemExit("Rust worker unavailable")

    summary_rows: list[dict] = []
    all_peak_rows: list[dict] = []
    all_selected_rows: list[dict] = []
    for row in rows.itertuples(index=False):
        annotation = pd.Series(row._asdict())
        raw_path = Path(str(annotation["raw_path"]))
        analysis = safe_analyze(worker, raw_path)
        if not analysis.get("ok"):
            summary_rows.append(
                {
                    "file": raw_path.name,
                    "raw_path": str(raw_path),
                    "ok": False,
                    "error": analysis.get("error", ""),
                    "note": annotation.get("note", ""),
                }
            )
            continue
        selected = json.loads(analysis.get("selected") or "[]")
        candidates = analysis.get("result", {}).get("ladder_peak_preview") or []
        image = render_diagnostic_image(analysis, annotation)
        probes = manual_target_probes(raw_path.name)
        summary_rows.append(
            {
                "file": raw_path.name,
                "raw_path": str(raw_path),
                "ok": True,
                "ladder": analysis.get("ladder", ""),
                "verdict": annotation.get("verdict", ""),
                "tags": annotation.get("tags", ""),
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "first_selected": selected[0] if selected else "",
                "last_selected": selected[-1] if selected else "",
                "linear_max": analysis.get("linear_max", ""),
                "linear_mean": analysis.get("linear_mean", ""),
                "linear_r2": analysis.get("linear_r2", ""),
                "review": analysis.get("review", ""),
                "reason_codes": analysis.get("reason_codes", ""),
                "manual_probe_candidates": nearest_candidate_summary(analysis, probes),
                "selected": json.dumps(selected),
                "note": annotation.get("note", ""),
                "image": image or "",
            }
        )
        all_peak_rows.extend(peak_rows(analysis, annotation))
        all_selected_rows.extend(selected_rows(analysis, annotation))

    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "summary.tsv", sep="\t", index=False)
    pd.DataFrame(all_peak_rows).to_csv(OUT_DIR / "candidate_peaks.tsv", sep="\t", index=False)
    pd.DataFrame(all_selected_rows).to_csv(OUT_DIR / "selected_peaks.tsv", sep="\t", index=False)
    with (OUT_DIR / "image_index.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "image"], delimiter="\t")
        writer.writeheader()
        for row in summary_rows:
            if row.get("image"):
                writer.writerow({"file": row["file"], "image": row["image"]})

    print(f"diagnosed={len(summary_rows)} out={OUT_DIR}")
    print(
        pd.DataFrame(summary_rows)[
            [
                "file",
                "ladder",
                "candidate_count",
                "first_selected",
                "last_selected",
                "linear_max",
                "linear_mean",
                "linear_r2",
                "review",
                "manual_probe_candidates",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
