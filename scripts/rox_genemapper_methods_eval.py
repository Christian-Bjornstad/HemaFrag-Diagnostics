from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.ndimage import grey_opening, minimum_filter1d

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import _compute_robust_arpls_baseline, _rolling_quantile_baseline
from core.rust_bridge import _get_rust_worker
from fraggler.fraggler import FsaFile


OUT_DIR = ROOT / "artifacts" / "rox_genemapper_methods_eval"
ROX_BPS = np.asarray(
    [50, 60, 90, 100, 120, 150, 160, 180, 190, 200, 220, 240, 260, 280, 290, 300, 320, 340, 360, 380, 400],
    dtype=float,
)


def load_benchmark_cases() -> list[dict]:
    rows = json.loads((ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json").read_text())
    good = [r for r in rows if r["ladder_type"] == "ROX" and r["cohort"] == "rox_good"][:18]
    bad = [r for r in rows if r["ladder_type"] == "ROX" and r["cohort"] == "rox_bad"][:18]
    special = [r for r in rows if r["ladder_type"] == "ROX" and r["cohort"] == "special"]
    return good + bad + special


def load_trace(path: str) -> np.ndarray:
    probe = FsaFile(
        file=path,
        ladder="ROX400HD",
        sample_channel="DATA1",
        min_distance_between_peaks=15,
        min_size_standard_height=200,
        size_standard_channel="DATA4",
    )
    channel = "DATA4" if "DATA4" in probe.fsa else "DATA105"
    return np.asarray(probe.fsa[channel], dtype=float)


def rust_selected_map(cases: list[dict]) -> dict[str, list[int]]:
    worker = _get_rust_worker()
    if worker is None:
        return {}
    out: dict[str, list[int]] = {}
    for case in cases:
        path = Path(case["raw_path"])
        resp = worker.request(path, "clonality", 6)
        if not resp or not resp.get("ok"):
            continue
        res = resp.get("result") if isinstance(resp.get("result"), dict) else resp
        preview = res.get("ladder_fit_preview") or {}
        refinement = preview.get("refinement") or {}
        scans = refinement.get("refined_scan_indices") or preview.get("best_scan_indices") or []
        if len(scans) == len(ROX_BPS):
            out[str(path)] = [int(x) for x in scans]
    return out


def gap_template(selected_map: dict[str, list[int]], cases: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    good_gaps = []
    for case in cases:
        if case["cohort"] != "rox_good":
            continue
        scans = selected_map.get(case["raw_path"])
        if scans and len(scans) == len(ROX_BPS):
            good_gaps.append(np.diff(np.asarray(scans, dtype=float)))
    if not good_gaps:
        scale = 10.5
        gaps = np.diff(ROX_BPS) * scale
        return gaps, gaps * 0.85, gaps * 1.18
    arr = np.vstack(good_gaps)
    return np.median(arr, axis=0), np.percentile(arr, 10, axis=0), np.percentile(arr, 90, axis=0)


def baseline_quantile(trace: np.ndarray) -> np.ndarray:
    return _rolling_quantile_baseline(np.asarray(trace, dtype=float), bin_size=200, quantile=0.10)


def baseline_minwin51(trace: np.ndarray) -> np.ndarray:
    return minimum_filter1d(np.asarray(trace, dtype=float), size=51, mode="nearest")


def baseline_morph151(trace: np.ndarray) -> np.ndarray:
    return grey_opening(np.asarray(trace, dtype=float), size=151)


def baseline_snip40(trace: np.ndarray) -> np.ndarray:
    baseline = np.asarray(trace, dtype=float).copy()
    for k in range(1, 41):
        left = np.empty_like(baseline)
        right = np.empty_like(baseline)
        left[:k] = baseline[:k]
        left[k:] = baseline[:-k]
        right[-k:] = baseline[-k:]
        right[:-k] = baseline[k:]
        baseline = np.minimum(baseline, (left + right) / 2.0)
    return baseline


def baseline_arpls_cap(trace: np.ndarray) -> np.ndarray:
    q = baseline_quantile(trace)
    a = _compute_robust_arpls_baseline(np.asarray(trace, dtype=float), lam=100.0, ratio=0.99)
    return np.minimum(a, q + 25.0)


BASELINES = {
    "quantile": baseline_quantile,
    "minwin_51": baseline_minwin51,
    "morph_open_151": baseline_morph151,
    "snip_40": baseline_snip40,
    "arpls_cap_q+25": baseline_arpls_cap,
}


def smooth_none(values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float)


def smooth_light(values: np.ndarray) -> np.ndarray:
    return signal.savgol_filter(np.asarray(values, dtype=float), window_length=11, polyorder=3, mode="interp")


SMOOTHERS = {"none": smooth_none, "light": smooth_light}


def detect_width_prom(values: np.ndarray, strict: bool = False) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    peaks, props = signal.find_peaks(
        arr,
        height=max(15.0, float(np.percentile(arr, 88)) * 0.08),
        prominence=max(5.0, float(np.percentile(arr, 94)) * 0.025),
        distance=8,
        width=(2, 120),
    )
    if peaks.size == 0:
        return peaks.astype(int)
    widths = signal.peak_widths(arr, peaks, rel_height=0.5)[0]
    keep: list[int] = []
    for peak, prom, ph, wd in zip(peaks, props["prominences"], props["peak_heights"], widths):
        purity = float(prom) / max(float(ph), 1.0)
        if not (1300 <= int(peak) <= 5000):
            continue
        if strict:
            if wd < 2.5 or purity < 0.14 or prom < 7.0:
                continue
        else:
            if wd > 90 or purity < 0.08:
                continue
        keep.append(int(peak))
    return np.asarray(sorted(set(keep)), dtype=int)


def detect_width_prom_loose(values: np.ndarray) -> np.ndarray:
    return detect_width_prom(values, strict=False)


def detect_width_prom_strict(values: np.ndarray) -> np.ndarray:
    return detect_width_prom(values, strict=True)


def detect_wavelet(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    peaks = signal.find_peaks_cwt(arr, np.arange(2, 12), min_snr=1.5, noise_perc=20)
    peaks = np.asarray([int(p) for p in peaks if 1300 <= int(p) <= 5000], dtype=int)
    if peaks.size == 0:
        return peaks
    vals = arr[peaks]
    keep = peaks[vals >= max(15.0, float(np.percentile(arr, 85)) * 0.07)]
    return np.asarray(sorted(set(int(p) for p in keep)), dtype=int)


def detect_deriv_11_3(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    smooth = signal.savgol_filter(arr, window_length=11, polyorder=3, mode="interp")
    deriv = signal.savgol_filter(arr, window_length=11, polyorder=3, deriv=1, delta=1.0, mode="interp")
    sign = np.sign(deriv)
    zero_cross = np.where((sign[:-1] > 0) & (sign[1:] <= 0))[0] + 1
    peaks, props = signal.find_peaks(
        smooth,
        height=max(15.0, float(np.percentile(smooth, 88)) * 0.07),
        prominence=max(5.0, float(np.percentile(smooth, 94)) * 0.022),
        distance=8,
        width=(2, 120),
    )
    peak_set = set(int(p) for p in peaks.tolist())
    widths = signal.peak_widths(smooth, peaks, rel_height=0.5)[0] if peaks.size else np.asarray([])
    width_map = {int(p): float(w) for p, w in zip(peaks, widths)}
    keep: list[int] = []
    for p in zero_cross:
        nearby = [q for q in peak_set if abs(q - int(p)) <= 6]
        if not nearby:
            continue
        q = min(nearby, key=lambda x: abs(x - int(p)))
        if 1300 <= q <= 5000 and width_map.get(q, 0.0) >= 2.5:
            keep.append(q)
    return np.asarray(sorted(set(keep)), dtype=int)


DETECTORS = {
    "width_prom": detect_width_prom_loose,
    "width_prom_strict": detect_width_prom_strict,
    "wavelet": detect_wavelet,
    "deriv_11_3": detect_deriv_11_3,
}


def fit_linear_metrics(scans: np.ndarray) -> tuple[float, float, float]:
    coeff = np.polyfit(scans.astype(float), ROX_BPS, deg=1)
    pred = np.polyval(coeff, scans.astype(float))
    residuals = np.abs(pred - ROX_BPS)
    ss_res = float(np.sum((ROX_BPS - pred) ** 2))
    ss_tot = float(np.sum((ROX_BPS - np.mean(ROX_BPS)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return float(np.max(residuals)), float(np.mean(residuals)), float(r2)


def reduce_candidates(candidates: np.ndarray, corrected: np.ndarray) -> np.ndarray:
    cand = np.asarray(sorted(set(int(p) for p in candidates)), dtype=int)
    if cand.size <= 42:
        return cand
    kept: set[int] = set()
    for left in range(1300, 5001, 115):
        window = cand[(cand >= left) & (cand < left + 115)]
        if window.size == 0:
            continue
        ranked = sorted(window.tolist(), key=lambda p: float(corrected[p]), reverse=True)
        kept.update(ranked[:3])
    if len(kept) > 48:
        ranked = sorted(kept, key=lambda p: float(corrected[p]), reverse=True)
        anchors = set(ranked[:42])
        anchors.update(cand[:4].tolist())
        anchors.update(cand[-4:].tolist())
        kept = anchors
    return np.asarray(sorted(kept), dtype=int)


def beam_fit_family(
    candidates: np.ndarray,
    corrected: np.ndarray,
    gap_medians: np.ndarray,
    gap_p10: np.ndarray,
    gap_p90: np.ndarray,
    beam_width: int = 256,
) -> dict | None:
    if candidates.size < len(ROX_BPS):
        return None
    cand = reduce_candidates(candidates, corrected)
    height_map = {int(p): float(corrected[int(p)]) for p in cand}
    partials: list[tuple[list[int], float]] = [([int(p)], 0.0) for p in cand if 1450 <= int(p) <= 1900]
    if not partials:
        partials = [([int(p)], 0.0) for p in cand[: min(14, cand.size)]]

    for step in range(1, len(ROX_BPS)):
        next_partials: list[tuple[list[int], float]] = []
        expected_gap = float(gap_medians[step - 1])
        p10 = float(gap_p10[step - 1])
        p90 = float(gap_p90[step - 1])
        low = max(8.0, p10 - 14.0)
        high = p90 + 22.0
        for seq, score in partials:
            last = seq[-1]
            later = cand[cand > last]
            if later.size == 0:
                continue
            for nxt in later:
                gap = float(nxt - last)
                if gap < low or gap > high * 1.8:
                    continue
                outside = 0.0
                if gap < low:
                    outside = low - gap
                elif gap > high:
                    outside = gap - high
                gap_pen = outside / max(p90 - p10, 8.0)
                center_pen = max(0.0, abs(gap - expected_gap) - (p90 - p10) * 0.65) / max(p90 - p10, 8.0)
                prev_heights = [height_map[x] for x in seq[-3:] if x in height_map]
                ref_height = float(np.median(prev_heights)) if prev_heights else height_map[last]
                this_height = height_map[int(nxt)]
                ratio = this_height / max(ref_height, 1.0)
                family_pen = max(0.0, abs(np.log(max(ratio, 1e-6))) - 0.75)
                real_peak_bonus = -0.08 if this_height >= 50.0 else 0.0
                next_partials.append((seq + [int(nxt)], score + gap_pen * 1.4 + center_pen * 0.7 + family_pen * 0.45 + real_peak_bonus))
        if not next_partials:
            return None
        next_partials.sort(key=lambda item: (item[1], item[0][-1]))
        partials = next_partials[:beam_width]

    best = None
    for seq, family_score in partials:
        scans = np.asarray(seq, dtype=float)
        lmax, lmean, r2 = fit_linear_metrics(scans)
        heights = corrected[np.asarray(seq, dtype=int)]
        weak_count = int(np.sum(heights < 50.0))
        key = (lmax, lmean, -r2, weak_count * 0.15, family_score)
        if best is None or key < best["key"]:
            best = {
                "selected": seq,
                "family_score": family_score,
                "linear_max": lmax,
                "linear_mean": lmean,
                "linear_r2": r2,
                "selected_below50": weak_count,
                "key": key,
            }
    return best


def run_case(case: dict, selected_map: dict[str, list[int]], gaps: tuple[np.ndarray, np.ndarray, np.ndarray], combo: tuple[str, str, str]) -> dict:
    baseline_name, smoother_name, detector_name = combo
    trace = load_trace(case["raw_path"])
    baseline = BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = SMOOTHERS[smoother_name](corrected)
    candidates = DETECTORS[detector_name](smoothed)
    fit = beam_fit_family(candidates, corrected, *gaps)
    selected_ref = selected_map.get(case["raw_path"], [])
    row = {
        "label": case["label"],
        "cohort": case["cohort"],
        "assay": case["assay"],
        "baseline": baseline_name,
        "smoothing": smoother_name,
        "detector": detector_name,
        "candidate_count": int(candidates.size),
        "early_count": int(np.sum((candidates >= 1300) & (candidates < 1600))),
        "fit_found": fit is not None,
        "rust_selected_count": len(selected_ref),
    }
    if fit is None:
        return row
    sel = np.asarray(fit["selected"], dtype=int)
    heights = corrected[sel]
    row.update(
        {
            "linear_max": float(fit["linear_max"]),
            "linear_mean": float(fit["linear_mean"]),
            "linear_r2": float(fit["linear_r2"]),
            "family_score": float(fit["family_score"]),
            "selected": json.dumps([int(x) for x in sel.tolist()]),
            "selected_median_h": float(np.median(heights)),
            "selected_min_h": float(np.min(heights)),
            "selected_below50": int(np.sum(heights < 50.0)),
        }
    )
    return row


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_benchmark_cases()
    selected_map = rust_selected_map(cases)
    gaps = gap_template(selected_map, cases)
    combos = [
        ("quantile", "none", "width_prom"),
        ("quantile", "light", "width_prom"),
        ("quantile", "light", "deriv_11_3"),
        ("minwin_51", "none", "width_prom"),
        ("minwin_51", "light", "width_prom"),
        ("morph_open_151", "none", "width_prom"),
        ("morph_open_151", "light", "width_prom"),
        ("morph_open_151", "light", "width_prom_strict"),
        ("snip_40", "none", "width_prom"),
        ("snip_40", "light", "width_prom"),
        ("arpls_cap_q+25", "none", "width_prom"),
        ("quantile", "none", "wavelet"),
    ]
    rows: list[dict] = []
    for case in cases:
        for combo in combos:
            rows.append(run_case(case, selected_map, gaps, combo))

    with (OUT_DIR / "detail.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    agg: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        agg[(row["cohort"], row["baseline"], row["smoothing"], row["detector"])].append(row)
    aggregate_rows: list[dict] = []
    for (cohort, baseline, smoothing, detector), group in agg.items():
        found = [g for g in group if g.get("fit_found")]
        base = {
            "cohort": cohort,
            "baseline": baseline,
            "smoothing": smoothing,
            "detector": detector,
            "n": len(group),
            "fit_found_rate": len(found) / len(group) if group else 0.0,
        }
        if found:
            for key in ["linear_max", "linear_mean", "linear_r2", "candidate_count", "early_count", "selected_below50", "selected_median_h", "selected_min_h"]:
                base[f"{key}_mean"] = float(np.mean([float(r[key]) for r in found]))
        aggregate_rows.append(base)
    aggregate_rows.sort(key=lambda r: (r["cohort"], r.get("linear_max_mean", 999.0), r.get("selected_below50_mean", 999.0), r.get("candidate_count_mean", 999.0)))
    with (OUT_DIR / "aggregate.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in aggregate_rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(aggregate_rows)

    by_case: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("fit_found"):
            by_case[row["label"]].append(row)
    winners = []
    for group in by_case.values():
        winners.append(min(group, key=lambda r: (float(r["linear_max"]), float(r["linear_mean"]), float(r["selected_below50"]), -float(r["linear_r2"]))))
    with (OUT_DIR / "best_by_case.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in winners for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(winners)

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "case_count": len(cases),
                "combo_count": len(combos),
                "selected_map_count": len(selected_map),
                "gap_medians": [float(x) for x in gaps[0].tolist()],
                "aggregate_tsv": str(OUT_DIR / "aggregate.tsv"),
                "best_by_case_tsv": str(OUT_DIR / "best_by_case.tsv"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(OUT_DIR)
    print(f"cases={len(cases)} combos={len(combos)} rows={len(rows)} selected_refs={len(selected_map)}")


if __name__ == "__main__":
    main()
