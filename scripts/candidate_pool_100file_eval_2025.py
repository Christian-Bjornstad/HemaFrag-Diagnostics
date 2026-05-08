from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import _compute_robust_arpls_baseline, _rolling_quantile_baseline
from core.rust_bridge import _get_rust_worker, _rust_timeout_seconds
from fraggler.fraggler import FsaFile


OUT_DIR = Path("/Users/christian/Desktop/HemaFrag/artifacts/candidate_pool_100file_eval_2025")
WORKBOOK_ROOT = Path("/Volumes/T7 Shield/HemaFrag_2025_safe_reruns_2026-04-28")
DATA_ROOT = Path("/Volumes/T7 Shield/DATA/2025_data")
PREFIX_RE = re.compile(r"^\d+_[0-9a-f]+_")


def strip_stage_prefix(name: str) -> str:
    return PREFIX_RE.sub("", name)


def ladder_type(assay: str, file_name: str) -> str:
    assay = str(assay or "")
    lower = file_name.lower()
    if assay in ("TCRgA", "TCRgB", "IGK", "KDE") or any(k in lower for k in ("tcrg", "igk", "kde", "trga", "trgb")):
        return "LIZ"
    return "ROX"


def bucket(qc: str, lmax: float) -> str:
    if str(qc or "") == "ok" and float(lmax) < 5:
        return "good"
    if str(qc or "") != "ok" or float(lmax) > 10:
        return "bad"
    return "mid"


def quantile_baseline(trace: np.ndarray, bin_size: int) -> np.ndarray:
    return _rolling_quantile_baseline(np.asarray(trace, dtype=float), bin_size=bin_size, quantile=0.10)


def blend_baseline(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    quant = quantile_baseline(values, 200)
    arpls = _compute_robust_arpls_baseline(values, lam=100.0, ratio=0.99)
    blended = 0.75 * quant + 0.25 * arpls
    return np.minimum(blended, quant + 10.0)


BASELINES = {
    "quantile_120": lambda x: quantile_baseline(x, 120),
    "quantile_200": lambda x: quantile_baseline(x, 200),
    "quantile_320": lambda x: quantile_baseline(x, 320),
    "blend": blend_baseline,
}


def detect_width_prom_loose(values: np.ndarray, ladder: str) -> np.ndarray:
    if ladder == "LIZ":
        height = max(15.0, float(np.percentile(values, 90)) * 0.08)
        prominence = max(6.0, float(np.percentile(values, 95)) * 0.03)
        distance = 8
    else:
        height = max(15.0, float(np.percentile(values, 88)) * 0.08)
        prominence = max(5.0, float(np.percentile(values, 94)) * 0.025)
        distance = 8
    peaks, props = signal.find_peaks(values, height=height, prominence=prominence, distance=distance, width=(2, 120))
    if peaks.size == 0:
        return peaks.astype(int)
    widths = signal.peak_widths(values, peaks, rel_height=0.5)[0]
    keep = []
    for peak, prom, ph, wd in zip(peaks, props["prominences"], props["peak_heights"], widths):
        purity = float(prom) / max(float(ph), 1.0)
        if 1300 <= int(peak) <= 4300 and wd <= 80 and purity >= 0.10:
            keep.append(int(peak))
    return np.asarray(keep, dtype=int)


def detect_width_prom_halfwidth(values: np.ndarray, ladder: str) -> np.ndarray:
    peaks = detect_width_prom_loose(values, ladder)
    if peaks.size == 0:
        return peaks
    widths = signal.peak_widths(values, peaks, rel_height=0.5)[0]
    min_half = 4 if ladder == "LIZ" else 3
    keep = [int(p) for p, wd in zip(peaks, widths) if wd >= min_half]
    return np.asarray(keep, dtype=int)


def detect_wavelet(values: np.ndarray, ladder: str) -> np.ndarray:
    widths = np.arange(2, 16) if ladder == "LIZ" else np.arange(2, 12)
    peaks = signal.find_peaks_cwt(values, widths, min_snr=1.5, noise_perc=20)
    peaks = np.asarray([int(p) for p in peaks if 1300 <= int(p) <= 4300], dtype=int)
    if peaks.size == 0:
        return peaks
    vals = values[peaks]
    keep = peaks[vals >= max(15.0, float(np.percentile(values, 85)) * (0.08 if ladder == "LIZ" else 0.07))]
    return np.asarray(keep, dtype=int)


DETECTORS = {
    "width_prom_loose": detect_width_prom_loose,
    "width_prom_halfwidth": detect_width_prom_halfwidth,
    "wavelet": detect_wavelet,
}


def choose_rows(df: pd.DataFrame, ladder: str, status: str, n: int) -> pd.DataFrame:
    sub = df[(df["ladder_type"] == ladder) & (df["bucket"] == status)].copy()
    if sub.empty:
        return sub
    # deterministic, but spread across months/assays
    sub = sub.sort_values(["Month", "Assay", "LadderLinearMaxResidualBp", "File"])
    if len(sub) <= n:
        return sub
    idx = np.linspace(0, len(sub) - 1, n).round().astype(int)
    return sub.iloc[idx].copy()


def load_workbook_rows() -> pd.DataFrame:
    frames = []
    for wb in sorted(WORKBOOK_ROOT.glob("2025_*/reports_2026-04-28/Clonality_Tracking.xlsx")):
        df = pd.read_excel(wb)
        df["Month"] = wb.parts[-3]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["raw_file"] = df["File"].map(strip_stage_prefix)
    df["ladder_type"] = [ladder_type(a, f) for a, f in zip(df["Assay"], df["raw_file"])]
    df["bucket"] = [bucket(qc, lmax) for qc, lmax in zip(df["LadderQC"], df["LadderLinearMaxResidualBp"])]
    df["raw_path"] = [str(DATA_ROOT / str(run) / str(name)) for run, name in zip(df["SourceRunDir"], df["raw_file"])]
    df = df[df["raw_path"].map(lambda p: Path(p).exists())].copy()
    return df


def load_trace(path: str, ladder: str) -> np.ndarray:
    probe = FsaFile(
        file=path,
        ladder="LIZ500_250" if ladder == "LIZ" else "ROX400HD",
        sample_channel="DATA1",
        min_distance_between_peaks=30 if ladder == "LIZ" else 15,
        min_size_standard_height=300 if ladder == "LIZ" else 200,
        size_standard_channel="DATA105" if ladder == "LIZ" else "DATA4",
    )
    channel = "DATA105" if ladder == "LIZ" and "DATA105" in probe.fsa else "DATA4"
    return np.asarray(probe.fsa[channel], dtype=float)


def rust_selected_map(paths: list[Path]) -> dict[str, list[int]]:
    worker = _get_rust_worker()
    if worker is None:
        return {}
    timeout = max(_rust_timeout_seconds("clonality"), 1)
    out: dict[str, list[int]] = {}
    chunk_size = 16
    for i in range(0, len(paths), chunk_size):
        chunk = paths[i:i + chunk_size]
        resp = worker.request_many(chunk, "clonality", timeout)
        if not resp or not resp.get("ok"):
            continue
        results = resp.get("results")
        if not isinstance(results, list):
            single = resp.get("result")
            results = [single] if isinstance(single, dict) else []
        for path, res in zip(chunk, results):
            if not isinstance(res, dict):
                continue
            preview = res.get("ladder_fit_preview") or {}
            refinement = preview.get("refinement") or {}
            scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
            out[str(path)] = [int(x) for x in scans]
    return out


def recall(candidates: np.ndarray, selected: list[int], tol: int = 12) -> float:
    if not selected:
        return float("nan")
    if candidates.size == 0:
        return 0.0
    hits = 0
    for s in selected:
        if np.any(np.abs(candidates - int(s)) <= tol):
            hits += 1
    return hits / len(selected)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_workbook_rows()
    chosen = pd.concat(
        [
            choose_rows(df, "LIZ", "good", 25),
            choose_rows(df, "LIZ", "bad", 25),
            choose_rows(df, "ROX", "good", 25),
            choose_rows(df, "ROX", "bad", 25),
        ],
        ignore_index=True,
    )
    chosen_paths = [Path(p) for p in chosen["raw_path"].tolist()]
    selected_map = rust_selected_map(chosen_paths)

    rows = []
    for _, row in chosen.iterrows():
        raw_path = str(row["raw_path"])
        ladder = str(row["ladder_type"])
        selected = selected_map.get(raw_path, [])
        raw = load_trace(raw_path, ladder)
        for bname, bfn in BASELINES.items():
            baseline = bfn(raw)
            corrected = np.maximum(raw - baseline, 0.0)
            for dname, dfn in DETECTORS.items():
                cand = dfn(corrected, ladder)
                rows.append(
                    {
                        "file": row["raw_file"],
                        "month": row["Month"],
                        "ladder_type": ladder,
                        "bucket": row["bucket"],
                        "baseline": bname,
                        "detector": dname,
                        "candidate_count": int(cand.size),
                        "early_blob_count": int(np.sum(cand < 1500)),
                        "first_candidate": int(cand[0]) if cand.size else -1,
                        "recall_tol12": recall(cand, selected, 12),
                        "selected_count": len(selected),
                        "workbook_lmax": float(row["LadderLinearMaxResidualBp"]),
                    }
                )

    out_df = pd.DataFrame(rows)
    out_df.to_csv(OUT_DIR / "summary.tsv", sep="\t", index=False)
    (OUT_DIR / "summary.json").write_text(json.dumps(rows, indent=2))

    agg = (
        out_df.groupby(["ladder_type", "bucket", "baseline", "detector"], as_index=False)[
            ["candidate_count", "early_blob_count", "recall_tol12"]
        ]
        .mean()
        .sort_values(["ladder_type", "bucket", "recall_tol12", "early_blob_count"], ascending=[True, True, False, True])
    )
    agg.to_csv(OUT_DIR / "aggregate.tsv", sep="\t", index=False)
    print(agg.to_string(index=False))


if __name__ == "__main__":
    main()
