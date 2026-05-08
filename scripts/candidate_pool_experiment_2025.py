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


OUT_DIR = Path("/Users/christian/Desktop/HemaFrag/artifacts/candidate_pool_experiment_2025")


@dataclass(frozen=True)
class Case:
    path: str
    label: str
    ladder: str


CASES = [
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16577_tcrgB__281025_E03_H920G04X.fsa",
        "16577_tcrgB",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16468_tcrgB__281025_D03_H920G04X.fsa",
        "16468_tcrgB",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16288_tcrgA__281025_B02_H920G04X.fsa",
        "16288_tcrgA_B02",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16084_tcrgB__281025_A03_H920G04X.fsa",
        "16084_tcrgB_control",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25RAH14619_tcrgB__281025_F06_H920G04X.fsa",
        "RAH14619_tcrgB_control",
        "LIZ500_250",
    ),
]


def blend_quantile_arpls(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    quant = _rolling_quantile_baseline(values, bin_size=200, quantile=0.10)
    arpls = _compute_robust_arpls_baseline(values, lam=100.0, ratio=0.99)
    blended = 0.75 * quant + 0.25 * arpls
    return np.minimum(blended, quant + 10.0)


def load_trace(case: Case) -> tuple[np.ndarray, str]:
    probe = FsaFile(
        file=case.path,
        ladder=case.ladder,
        sample_channel="DATA1",
        min_distance_between_peaks=30,
        min_size_standard_height=300,
        size_standard_channel="DATA105",
    )
    ss_channel = "DATA105" if "DATA105" in probe.fsa else "DATA4"
    trace = np.asarray(probe.fsa[ss_channel], dtype=float)
    return trace, ss_channel


def detect_standard(corrected: np.ndarray) -> np.ndarray:
    height = max(20.0, float(np.percentile(corrected, 92)) * 0.10)
    prominence = max(8.0, float(np.percentile(corrected, 96)) * 0.04)
    peaks, _ = signal.find_peaks(corrected, height=height, prominence=prominence, distance=10)
    return np.asarray([p for p in peaks if 1300 <= p <= 4300], dtype=int)


def detect_width_prom(corrected: np.ndarray) -> np.ndarray:
    height = max(15.0, float(np.percentile(corrected, 90)) * 0.08)
    prominence = max(6.0, float(np.percentile(corrected, 95)) * 0.03)
    peaks, props = signal.find_peaks(
        corrected,
        height=height,
        prominence=prominence,
        distance=8,
        width=(2, 120),
    )
    if peaks.size == 0:
        return np.array([], dtype=int)
    widths = signal.peak_widths(corrected, peaks, rel_height=0.5)[0]
    keep = []
    for peak, width, prom, ph in zip(peaks, widths, props["prominences"], props["peak_heights"]):
        purity = float(prom) / max(float(ph), 1.0)
        if 1300 <= int(peak) <= 4300 and width <= 80 and purity >= 0.10:
            keep.append(int(peak))
    return np.asarray(keep, dtype=int)


def detect_wavelet(corrected: np.ndarray) -> np.ndarray:
    widths = np.arange(2, 16)
    peaks = signal.find_peaks_cwt(corrected, widths, min_snr=1.5, noise_perc=20)
    peaks = np.asarray([int(p) for p in peaks if 1300 <= int(p) <= 4300], dtype=int)
    if peaks.size == 0:
        return peaks
    vals = corrected[peaks]
    keep = peaks[vals >= max(15.0, float(np.percentile(corrected, 85)) * 0.08)]
    return np.asarray(keep, dtype=int)


DETECTORS = {
    "standard": detect_standard,
    "width_prom": detect_width_prom,
    "wavelet": detect_wavelet,
}


def plot_case(case: Case, raw: np.ndarray, baseline: np.ndarray, corrected: np.ndarray, detections: dict[str, np.ndarray]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    ax0, ax1 = axes

    ax0.plot(raw, color="black", lw=1.0, label="raw")
    ax0.plot(baseline, color="#d95f02", lw=1.0, label="blend baseline")
    ax0.set_xlim(1200, 4300)
    ax0.set_title(f"{Path(case.path).name}\nraw + blend baseline")
    ax0.grid(alpha=0.2)
    ax0.legend(loc="upper right", fontsize=8)

    ax1.plot(corrected, color="black", lw=1.0)
    colors = {"standard": "#7f7f7f", "width_prom": "#1f77b4", "wavelet": "#2ca02c"}
    for name, peaks in detections.items():
        if peaks.size:
            ax1.scatter(peaks, corrected[peaks], s=18, color=colors[name], alpha=0.75, label=f"{name} ({len(peaks)})")
    ax1.axhline(0.0, color="#d62728", lw=0.8, alpha=0.6)
    ax1.set_xlim(1200, 4300)
    ax1.set_ylim(-20, max(700.0, float(np.percentile(corrected, 99.7)) * 1.05))
    ax1.set_title("corrected trace + candidate pools")
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    fig.savefig(OUT_DIR / f"{case.label}_candidate_pool_compare.png", dpi=150)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in CASES:
        raw, channel = load_trace(case)
        baseline = blend_quantile_arpls(raw)
        corrected = np.maximum(raw - baseline, 0.0)
        detections = {name: fn(corrected) for name, fn in DETECTORS.items()}
        plot_case(case, raw, baseline, corrected, detections)
        for name, peaks in detections.items():
            rows.append(
                {
                    "file": Path(case.path).name,
                    "label": case.label,
                    "method": name,
                    "channel": channel,
                    "candidate_count": int(peaks.size),
                    "first_candidates": [int(x) for x in peaks[:10]],
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
