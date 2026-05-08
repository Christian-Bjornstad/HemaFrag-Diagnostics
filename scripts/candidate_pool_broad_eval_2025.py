from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import _compute_robust_arpls_baseline, _rolling_quantile_baseline
from fraggler.fraggler import FsaFile


OUT_DIR = Path("/Users/christian/Desktop/HemaFrag/artifacts/candidate_pool_broad_eval_2025")
SUMMARY_JSON = Path("/Users/christian/Desktop/HemaFrag/artifacts/2025_remaining_rerun_summary.json")
DATA_ROOT = Path("/Volumes/T7 Shield/DATA/2025_data")


def quantile_baseline(trace: np.ndarray) -> np.ndarray:
    return _rolling_quantile_baseline(np.asarray(trace, dtype=float), bin_size=200, quantile=0.10)


def blend_baseline(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    quant = quantile_baseline(values)
    arpls = _compute_robust_arpls_baseline(values, lam=100.0, ratio=0.99)
    blended = 0.75 * quant + 0.25 * arpls
    return np.minimum(blended, quant + 10.0)


def detect_width_prom(values: np.ndarray) -> np.ndarray:
    peaks, props = signal.find_peaks(
        values,
        height=max(15.0, float(np.percentile(values, 90)) * 0.08),
        prominence=max(6.0, float(np.percentile(values, 95)) * 0.03),
        distance=8,
        width=(2, 120),
    )
    if peaks.size == 0:
        return peaks.astype(int)
    widths = signal.peak_widths(values, peaks, rel_height=0.5)[0]
    keep = []
    for peak, prom, ph, wd in zip(peaks, props["prominences"], props["peak_heights"], widths):
        purity = float(prom) / max(float(ph), 1.0)
        if 1300 <= int(peak) <= 4300 and wd <= 80 and purity >= 0.10:
            keep.append(int(peak))
    return np.asarray(keep, dtype=int)


def _filter_width_prominence(values: np.ndarray, peaks: np.ndarray) -> np.ndarray:
    if peaks.size == 0:
        return peaks
    prom, left_bases, right_bases = signal.peak_prominences(values, peaks)
    widths = signal.peak_widths(values, peaks, rel_height=0.5, prominence_data=(prom, left_bases, right_bases))[0]
    keep = []
    for peak, pr, wd in zip(peaks, prom, widths):
        height = float(values[int(peak)])
        purity = float(pr) / max(height, 1.0)
        if wd <= 90 and purity >= 0.08:
            keep.append(int(peak))
    return np.asarray(keep, dtype=int)


def detect_wavelet(values: np.ndarray) -> np.ndarray:
    peaks = signal.find_peaks_cwt(values, np.arange(2, 16), min_snr=1.5, noise_perc=20)
    peaks = np.asarray([int(p) for p in peaks if 1300 <= int(p) <= 4300], dtype=int)
    if peaks.size == 0:
        return peaks
    vals = values[peaks]
    return np.asarray(peaks[vals >= max(15.0, float(np.percentile(values, 85)) * 0.08)], dtype=int)


def detect_wavelet_filtered(values: np.ndarray) -> np.ndarray:
    return _filter_width_prominence(values, detect_wavelet(values))


BASELINES = {
    "quantile": quantile_baseline,
    "blend": blend_baseline,
}

DETECTORS = {
    "width_prom": detect_width_prom,
    "wavelet": detect_wavelet,
    "wavelet_filtered": detect_wavelet_filtered,
}


def resolve_paths(selected_files: list[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for name in selected_files:
        matches = list(DATA_ROOT.rglob(name))
        if matches:
            found[name] = matches[0]
    return found


def load_trace(path: Path) -> np.ndarray:
    probe = FsaFile(
        file=str(path),
        ladder="LIZ500_250",
        sample_channel="DATA1",
        min_distance_between_peaks=30,
        min_size_standard_height=300,
        size_standard_channel="DATA105",
    )
    channel = "DATA105" if "DATA105" in probe.fsa else "DATA4"
    return np.asarray(probe.fsa[channel], dtype=float)


def match_recall(candidates: np.ndarray, selected: list[int], tol: int = 12) -> float:
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
    data = json.loads(SUMMARY_JSON.read_text())
    liz_rows = [r for r in data if any(k in r["file"].lower() for k in ("tcrg", "igk", "kde")) and r.get("selected")]
    hard = sorted([r for r in liz_rows if r["linear_max"] > 10], key=lambda r: r["linear_max"], reverse=True)[:8]
    controls = sorted([r for r in liz_rows if 5 <= r["linear_max"] <= 7.5], key=lambda r: r["linear_max"])[:8]
    chosen = hard + [r for r in controls if r["file"] not in {x["file"] for x in hard}]
    names = [r["file"] for r in chosen]
    paths = resolve_paths(names)

    rows = []
    for row in chosen:
        file = row["file"]
        path = paths.get(file)
        if path is None:
            continue
        raw = load_trace(path)
        selected = row["selected"]
        for bname, bfn in BASELINES.items():
            baseline = bfn(raw)
            corrected = np.maximum(raw - baseline, 0.0)
            for dname, dfn in DETECTORS.items():
                cand = dfn(corrected)
                early_blob = int(np.sum(cand < 1500))
                rows.append(
                    {
                        "file": file,
                        "linear_max": row["linear_max"],
                        "baseline": bname,
                        "detector": dname,
                        "candidate_count": int(cand.size),
                        "early_blob_count": early_blob,
                        "first_candidate": int(cand[0]) if cand.size else -1,
                        "recall_tol12": match_recall(cand, selected, tol=12),
                        "selected_count": len(selected),
                    }
                )

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "summary.tsv", sep="\t", index=False)
    (OUT_DIR / "summary.json").write_text(json.dumps(rows, indent=2))

    agg = (
        df.groupby(["baseline", "detector"], as_index=False)[["candidate_count", "early_blob_count", "recall_tol12"]]
        .mean()
        .sort_values(["recall_tol12", "early_blob_count", "candidate_count"], ascending=[False, True, True])
    )
    agg.to_csv(OUT_DIR / "aggregate.tsv", sep="\t", index=False)
    print("AGGREGATE")
    print(agg.to_string(index=False))
    print("\nPER FILE BEST")
    scored = df.copy()
    scored["score"] = -scored["recall_tol12"].fillna(0) + 0.01 * scored["early_blob_count"] + 0.0005 * scored["candidate_count"]
    best = scored.sort_values(["file", "score"]).groupby("file", as_index=False).head(1)
    print(best[["file", "baseline", "detector", "candidate_count", "early_blob_count", "first_candidate", "recall_tol12"]].to_string(index=False))


if __name__ == "__main__":
    main()
