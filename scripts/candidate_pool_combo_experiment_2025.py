from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import ndimage, signal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import _compute_robust_arpls_baseline, _rolling_quantile_baseline
from fraggler.fraggler import FsaFile

OUT_DIR = Path("/Users/christian/Desktop/HemaFrag/artifacts/candidate_pool_combo_experiment_2025")


@dataclass(frozen=True)
class Case:
    path: str
    label: str
    ladder: str


CASES = [
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16577_tcrgB__281025_E03_H920G04X.fsa", "16577", "LIZ500_250"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16468_tcrgB__281025_D03_H920G04X.fsa", "16468", "LIZ500_250"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16288_tcrgA__281025_B02_H920G04X.fsa", "16288_B02", "LIZ500_250"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16084_tcrgB__281025_A03_H920G04X.fsa", "16084_control", "LIZ500_250"),
]


def quantile_baseline(trace: np.ndarray) -> np.ndarray:
    return _rolling_quantile_baseline(np.asarray(trace, dtype=float), bin_size=200, quantile=0.10)


def blend_baseline(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    quant = quantile_baseline(values)
    arpls = _compute_robust_arpls_baseline(values, lam=100.0, ratio=0.99)
    blended = 0.75 * quant + 0.25 * arpls
    return np.minimum(blended, quant + 10.0)


BASELINES = {
    "quantile": quantile_baseline,
    "blend": blend_baseline,
}


def load_trace(case: Case) -> np.ndarray:
    probe = FsaFile(
        file=case.path,
        ladder=case.ladder,
        sample_channel="DATA1",
        min_distance_between_peaks=30,
        min_size_standard_height=300,
        size_standard_channel="DATA105",
    )
    channel = "DATA105" if "DATA105" in probe.fsa else "DATA4"
    return np.asarray(probe.fsa[channel], dtype=float)


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
    keep = []
    widths = signal.peak_widths(values, peaks, rel_height=0.5)[0]
    for peak, prom, ph, wd in zip(peaks, props["prominences"], props["peak_heights"], widths):
        purity = float(prom) / max(float(ph), 1.0)
        if 1300 <= int(peak) <= 4300 and wd <= 80 and purity >= 0.10:
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


def detect_hybrid_union(values: np.ndarray) -> np.ndarray:
    a = detect_wavelet_filtered(values)
    b = detect_width_prom(values)
    merged = np.unique(np.concatenate([a, b]))
    merged = np.asarray([int(p) for p in merged if 1300 <= int(p) <= 4300], dtype=int)
    return _filter_width_prominence(values, merged)


DETECTORS = {
    "width_prom": detect_width_prom,
    "wavelet": detect_wavelet,
    "wavelet_filtered": detect_wavelet_filtered,
    "hybrid_union": detect_hybrid_union,
}


def plot_case(case: Case, baseline_name: str, raw: np.ndarray, baseline: np.ndarray, corrected: np.ndarray, detections: dict[str, np.ndarray]) -> None:
    fig, axes = plt.subplots(len(detections), 1, figsize=(14, 3.2 * len(detections)), sharex=True)
    if len(detections) == 1:
        axes = [axes]
    for ax, (name, peaks) in zip(axes, detections.items()):
        ax.plot(corrected, color="black", lw=1.0)
        if peaks.size:
            ax.scatter(peaks, corrected[peaks], s=18, color="#1f77b4", alpha=0.8)
        ax.axhline(0.0, color="#d62728", lw=0.8, alpha=0.6)
        ax.set_xlim(1200, 4300)
        ax.set_ylim(-20, max(700.0, float(np.percentile(corrected, 99.7)) * 1.05))
        ax.set_title(f"{baseline_name} + {name} ({len(peaks)} peaks)")
        ax.grid(alpha=0.2)
    fig.suptitle(f"{Path(case.path).name}", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_DIR / f"{case.label}_{baseline_name}_detectors.png", dpi=150)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in CASES:
        raw = load_trace(case)
        for baseline_name, baseline_fn in BASELINES.items():
            baseline = baseline_fn(raw)
            corrected = np.maximum(raw - baseline, 0.0)
            detections = {name: fn(corrected) for name, fn in DETECTORS.items()}
            plot_case(case, baseline_name, raw, baseline, corrected, detections)
            for name, peaks in detections.items():
                rows.append(
                    {
                        "file": Path(case.path).name,
                        "label": case.label,
                        "baseline": baseline_name,
                        "detector": name,
                        "candidate_count": int(peaks.size),
                        "first_candidates": [int(x) for x in peaks[:12]],
                        "corr_median": float(np.median(corrected)),
                        "corr_q10": float(np.quantile(corrected, 0.10)),
                    }
                )
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "summary.tsv", sep="\t", index=False)
    (OUT_DIR / "summary.json").write_text(json.dumps(rows, indent=2))
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
