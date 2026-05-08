from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import grey_opening

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import _compute_robust_arpls_baseline, _rolling_quantile_baseline
from fraggler.fraggler import FsaFile


OUT_DIR = ROOT / "artifacts" / "liz_baseline_family_fit_eval"
LIZ_BPS = np.asarray([35, 50, 75, 100, 139, 150, 160, 200, 250, 300, 340, 350, 400, 450, 490, 500], dtype=float)
LIZ_GAP_MEDIANS = np.asarray([76.0, 148.0, 139.0, 223.0, 56.0, 57.0, 234.0, 283.0, 312.0, 231.0, 59.0, 303.0, 278.0, 226.0, 46.0], dtype=float)
LIZ_GAP_P10 = np.asarray([73.0, 142.0, 136.0, 217.0, 55.0, 56.0, 227.0, 277.0, 300.0, 224.0, 56.0, 290.2, 268.0, 219.0, 45.0], dtype=float)
LIZ_GAP_P90 = np.asarray([81.0, 156.0, 148.0, 236.0, 60.0, 60.0, 247.8, 301.0, 328.0, 243.8, 62.0, 318.8, 295.8, 240.0, 50.0], dtype=float)


@dataclass(frozen=True)
class Case:
    path: str
    label: str
    note: str


CASES = [
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16288_tcrgA__281025_B02_H920G04X.fsa", "16288_B02", "bad_blob"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16577_tcrgB__281025_E03_H920G04X.fsa", "16577", "bad_blob"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16468_tcrgB__281025_D03_H920G04X.fsa", "16468", "bad_blob"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16406_tcrgB__281025_C03_H920G04X.fsa", "16406", "goodish"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_03_19_tcrg_igkkde_pr_H9C0VAEA_2025-03-19_0566/25OUM03856_tcrgA__180325_A02_H9C0VAEA.fsa", "03856_A", "good"),
    Case("/Volumes/T7 Shield/DATA/2025_data/2025_03_19_tcrg_igkkde_pr_H9C0VAEA_2025-03-19_0566/25OUM03856_tcrgB__180325_A03_H9C0VAEA.fsa", "03856_B", "good"),
]


def load_trace(path: str) -> np.ndarray:
    probe = FsaFile(
        file=path,
        ladder="LIZ500_250",
        sample_channel="DATA1",
        min_distance_between_peaks=30,
        min_size_standard_height=300,
        size_standard_channel="DATA105",
    )
    return np.asarray(probe.fsa["DATA105"], dtype=float)


def quantile_baseline(trace: np.ndarray) -> np.ndarray:
    return _rolling_quantile_baseline(trace, bin_size=5000, quantile=0.01)


def robust_arpls_baseline(trace: np.ndarray) -> np.ndarray:
    return _compute_robust_arpls_baseline(trace, lam=100.0, ratio=0.99)


def blend_baseline(trace: np.ndarray) -> np.ndarray:
    q = quantile_baseline(trace)
    a = robust_arpls_baseline(trace)
    return 0.6 * q + 0.4 * a


def arpls_cap_quantile(trace: np.ndarray) -> np.ndarray:
    q = quantile_baseline(trace)
    a = robust_arpls_baseline(trace)
    return np.minimum(a, q + 25.0)


def morph_open_baseline(trace: np.ndarray) -> np.ndarray:
    return grey_opening(trace, size=151)


def snip_baseline(trace: np.ndarray, iterations: int = 40) -> np.ndarray:
    baseline = np.asarray(trace, dtype=float).copy()
    for k in range(1, iterations + 1):
        left = np.empty_like(baseline)
        right = np.empty_like(baseline)
        left[:k] = baseline[:k]
        left[k:] = baseline[:-k]
        right[-k:] = baseline[-k:]
        right[:-k] = baseline[k:]
        baseline = np.minimum(baseline, (left + right) / 2.0)
    return baseline


BASELINES = {
    "quantile": quantile_baseline,
    "robust_arpls": robust_arpls_baseline,
    "blend_q60_a40": blend_baseline,
    "arpls_cap_q+25": arpls_cap_quantile,
    "morph_open_151": morph_open_baseline,
    "snip_40": snip_baseline,
}


def detect_wavelet(values: np.ndarray) -> np.ndarray:
    peaks = signal.find_peaks_cwt(values, np.arange(2, 16), min_snr=1.5, noise_perc=20)
    peaks = np.asarray([int(p) for p in peaks if 1300 <= int(p) <= 5000], dtype=int)
    if peaks.size == 0:
        return peaks
    vals = values[peaks]
    keep = peaks[vals >= max(12.0, float(np.percentile(values, 85)) * 0.07)]
    return np.asarray(sorted(set(int(p) for p in keep)), dtype=int)


def detect_width_prom(values: np.ndarray) -> np.ndarray:
    peaks, props = signal.find_peaks(
        values,
        height=max(12.0, float(np.percentile(values, 90)) * 0.07),
        prominence=max(5.0, float(np.percentile(values, 95)) * 0.025),
        distance=8,
        width=(2, 120),
    )
    if peaks.size == 0:
        return peaks.astype(int)
    widths = signal.peak_widths(values, peaks, rel_height=0.5)[0]
    keep = []
    for peak, prom, ph, wd in zip(peaks, props["prominences"], props["peak_heights"], widths):
        purity = float(prom) / max(float(ph), 1.0)
        if 1300 <= int(peak) <= 5000 and wd <= 90 and purity >= 0.08:
            keep.append(int(peak))
    return np.asarray(sorted(set(keep)), dtype=int)


DETECTORS = {
    "wavelet": detect_wavelet,
    "width_prom": detect_width_prom,
}


def fit_linear_metrics(scans: np.ndarray) -> tuple[float, float, float]:
    coeff = np.polyfit(scans.astype(float), LIZ_BPS, deg=1)
    pred = np.polyval(coeff, scans.astype(float))
    residuals = np.abs(pred - LIZ_BPS)
    ss_res = float(np.sum((LIZ_BPS - pred) ** 2))
    ss_tot = float(np.sum((LIZ_BPS - np.mean(LIZ_BPS)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return float(np.max(residuals)), float(np.mean(residuals)), float(r2)


def beam_fit_family(candidates: np.ndarray, corrected: np.ndarray, beam_width: int = 192) -> dict | None:
    if candidates.size < len(LIZ_BPS):
        return None
    cand = np.asarray(sorted(set(int(p) for p in candidates)), dtype=int)
    if cand.size > 24:
        window_kept: list[int] = []
        start = 0
        while start < cand.size:
            left = cand[start]
            mask = cand[(cand >= left) & (cand <= left + 110)]
            if mask.size:
                ranked = sorted(mask.tolist(), key=lambda p: (float(corrected[int(p)]), -abs(int(p) - int(left))), reverse=True)
                window_kept.extend(ranked[:2])
            start += 2
        cand = np.asarray(sorted(set(int(p) for p in window_kept)), dtype=int)
    if cand.size > 36:
        ranked = sorted(cand.tolist(), key=lambda p: float(corrected[int(p)]), reverse=True)
        anchors = set(ranked[:32])
        anchors.update(cand[:4].tolist())
        anchors.update(cand[-4:].tolist())
        cand = np.asarray(sorted(anchors), dtype=int)
    peak_set = set(int(p) for p in cand.tolist())
    height_map = {int(p): float(corrected[int(p)]) for p in cand}

    partials: list[tuple[list[int], float]] = [([int(p)], 0.0) for p in cand if 1450 <= int(p) <= 1700]
    if not partials:
        partials = [([int(p)], 0.0) for p in cand[: min(12, cand.size)]]

    for step in range(1, len(LIZ_BPS)):
        next_partials: list[tuple[list[int], float]] = []
        expected_gap = float(LIZ_GAP_MEDIANS[step - 1])
        p10 = float(LIZ_GAP_P10[step - 1])
        p90 = float(LIZ_GAP_P90[step - 1])
        low = p10 - 18.0
        high = p90 + 28.0
        for seq, score in partials:
            last = seq[-1]
            later = cand[cand > last]
            if later.size == 0:
                continue
            for nxt in later:
                gap = float(nxt - last)
                if gap < low or gap > high * 1.7:
                    continue
                outside = 0.0
                if gap < low:
                    outside = low - gap
                elif gap > high:
                    outside = gap - high
                gap_pen = outside / max(p90 - p10, 8.0)
                center_pen = max(0.0, abs(gap - expected_gap) - (p90 - p10) * 0.60) / max((p90 - p10), 8.0)
                neighbor_heights = [height_map[x] for x in seq[-3:] if x in height_map]
                ref_height = float(np.median(neighbor_heights)) if neighbor_heights else height_map[last]
                this_height = height_map[int(nxt)]
                ratio = this_height / max(ref_height, 1.0)
                family_pen = max(0.0, abs(np.log(max(ratio, 1e-6))) - 0.55)
                bonus = -0.10 if this_height >= 20.0 else 0.0
                next_partials.append((seq + [int(nxt)], score + gap_pen * 1.6 + center_pen * 0.8 + family_pen * 0.7 + bonus))
        if not next_partials:
            return None
        next_partials.sort(key=lambda item: (item[1], item[0][-1]))
        partials = next_partials[:beam_width]

    best = None
    for seq, family_score in partials:
        if len(seq) != len(LIZ_BPS):
            continue
        scans = np.asarray(seq, dtype=float)
        lmax, lmean, r2 = fit_linear_metrics(scans)
        key = (lmax, lmean, -r2, family_score)
        if best is None or key < best["key"]:
            best = {
                "selected": seq,
                "family_score": family_score,
                "linear_max": lmax,
                "linear_mean": lmean,
                "linear_r2": r2,
                "key": key,
            }
    return best


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for case in CASES:
        raw = load_trace(case.path)
        for bname, bfn in BASELINES.items():
            baseline = bfn(raw)
            corrected = np.clip(raw - baseline, 0, None)
            for dname, dfn in DETECTORS.items():
                candidates = dfn(corrected)
                fit = beam_fit_family(candidates, corrected)
                row = {
                    "file": Path(case.path).name,
                    "label": case.label,
                    "note": case.note,
                    "baseline": bname,
                    "detector": dname,
                    "candidate_count": int(candidates.size),
                    "first_candidates": [int(x) for x in candidates[:12]],
                    "last_candidates": [int(x) for x in candidates[-12:]],
                    "fit_found": fit is not None,
                }
                if fit is not None:
                    row.update(
                        {
                            "linear_max": fit["linear_max"],
                            "linear_mean": fit["linear_mean"],
                            "linear_r2": fit["linear_r2"],
                            "family_score": fit["family_score"],
                            "selected": fit["selected"],
                        }
                    )
                rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "summary.tsv", sep="\t", index=False)
    (OUT_DIR / "summary.json").write_text(json.dumps(rows, indent=2))

    best = (
        df[df["fit_found"]]
        .sort_values(["label", "linear_max", "linear_mean", "linear_r2"], ascending=[True, True, True, False])
        .groupby("label", as_index=False)
        .first()
    )
    best.to_csv(OUT_DIR / "best_by_case.tsv", sep="\t", index=False)
    print(best.to_string(index=False))


if __name__ == "__main__":
    main()
