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

from scripts import liz_baseline_family_fit_eval as base_eval


OUT_DIR = ROOT / "artifacts" / "liz_genemapper_methods_eval"


def load_benchmark_cases() -> list[dict]:
    rows = json.loads((ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json").read_text())
    good = [r for r in rows if r["ladder_type"] == "LIZ" and r["cohort"] == "liz_good"][:12]
    bad = [r for r in rows if r["ladder_type"] == "LIZ" and r["cohort"] == "liz_bad"][:12]
    special_labels = {"special_liz_blob_16577", "special_liz_blob_16468", "special_liz_blob_16288_b02"}
    special = [r for r in rows if r["label"] in special_labels]
    return good + bad + special


def baseline_quantile(trace: np.ndarray) -> np.ndarray:
    return base_eval.quantile_baseline(trace)


def baseline_minwin51(trace: np.ndarray) -> np.ndarray:
    return minimum_filter1d(np.asarray(trace, dtype=float), size=51, mode="nearest")


def baseline_morph151(trace: np.ndarray) -> np.ndarray:
    return grey_opening(np.asarray(trace, dtype=float), size=151)


def baseline_snip40(trace: np.ndarray) -> np.ndarray:
    return base_eval.snip_baseline(trace)


BASELINES = {
    "quantile": baseline_quantile,
    "minwin_51": baseline_minwin51,
    "morph_open_151": baseline_morph151,
    "snip_40": baseline_snip40,
}


def smooth_none(values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float)


def smooth_light(values: np.ndarray) -> np.ndarray:
    return signal.savgol_filter(np.asarray(values, dtype=float), window_length=11, polyorder=3, mode="interp")


def smooth_heavy(values: np.ndarray) -> np.ndarray:
    return signal.savgol_filter(np.asarray(values, dtype=float), window_length=21, polyorder=3, mode="interp")


SMOOTHERS = {
    "none": smooth_none,
    "light": smooth_light,
    "heavy": smooth_heavy,
}


def _width_prom_candidates(values: np.ndarray, strict: bool) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    peaks, props = signal.find_peaks(
        arr,
        height=max(12.0, float(np.percentile(arr, 90)) * 0.07),
        prominence=max(5.0, float(np.percentile(arr, 95)) * 0.025),
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
            if wd < 3.0 or purity < 0.16 or prom < 8.0:
                continue
        else:
            if wd > 90 or purity < 0.08:
                continue
        keep.append(int(peak))
    return np.asarray(sorted(set(keep)), dtype=int)


def detect_width_prom(values: np.ndarray) -> np.ndarray:
    return _width_prom_candidates(values, strict=False)


def detect_width_prom_strict(values: np.ndarray) -> np.ndarray:
    return _width_prom_candidates(values, strict=True)


def _derivative_candidates(values: np.ndarray, window: int, poly: int, height_scale: float, prom_scale: float) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    smooth = signal.savgol_filter(arr, window_length=window, polyorder=poly, mode="interp")
    deriv = signal.savgol_filter(arr, window_length=window, polyorder=poly, deriv=1, delta=1.0, mode="interp")
    sign = np.sign(deriv)
    zero_cross = np.where((sign[:-1] > 0) & (sign[1:] <= 0))[0] + 1
    if zero_cross.size == 0:
        return np.asarray([], dtype=int)
    min_height = max(12.0, float(np.percentile(smooth, 90)) * height_scale)
    min_prom = max(5.0, float(np.percentile(smooth, 95)) * prom_scale)
    peaks, props = signal.find_peaks(
        smooth,
        height=min_height,
        prominence=min_prom,
        distance=8,
        width=(2, 120),
    )
    peak_set = set(int(p) for p in peaks.tolist())
    widths = signal.peak_widths(smooth, peaks, rel_height=0.5)[0] if peaks.size else np.asarray([])
    width_map = {int(p): float(w) for p, w in zip(peaks, widths)}
    prom_map = {int(p): float(v) for p, v in zip(peaks, props.get("prominences", []))}
    height_map = {int(p): float(v) for p, v in zip(peaks, props.get("peak_heights", []))}
    keep: list[int] = []
    for p in zero_cross:
        p = int(p)
        nearby = [q for q in peak_set if abs(q - p) <= 6]
        if not nearby:
            continue
        q = min(nearby, key=lambda x: abs(x - p))
        wd = width_map.get(q, 0.0)
        prom = prom_map.get(q, 0.0)
        ph = height_map.get(q, 1.0)
        purity = prom / max(ph, 1.0)
        if 1300 <= q <= 5000 and wd >= 3.0 and purity >= 0.12:
            keep.append(q)
    return np.asarray(sorted(set(keep)), dtype=int)


def detect_deriv_11_3(values: np.ndarray) -> np.ndarray:
    return _derivative_candidates(values, window=11, poly=3, height_scale=0.07, prom_scale=0.025)


def detect_deriv_17_3(values: np.ndarray) -> np.ndarray:
    return _derivative_candidates(values, window=17, poly=3, height_scale=0.065, prom_scale=0.022)


DETECTORS = {
    "width_prom": detect_width_prom,
    "width_prom_strict": detect_width_prom_strict,
    "deriv_11_3": detect_deriv_11_3,
    "deriv_17_3": detect_deriv_17_3,
}


def early_blob_count(candidates: np.ndarray) -> int:
    return int(np.sum((candidates >= 1300) & (candidates < 1650)))


def run_case(case: dict, baseline_name: str, smoother_name: str, detector_name: str) -> dict:
    trace = base_eval.load_trace(case["raw_path"])
    baseline = BASELINES[baseline_name](trace)
    corrected = np.clip(np.asarray(trace, dtype=float) - np.asarray(baseline, dtype=float), 0.0, None)
    smoothed = SMOOTHERS[smoother_name](corrected)
    candidates = DETECTORS[detector_name](smoothed)
    fit = base_eval.beam_fit_family(candidates, corrected)
    row = {
        "label": case["label"],
        "cohort": case["cohort"],
        "assay": case["assay"],
        "baseline": baseline_name,
        "smoothing": smoother_name,
        "detector": detector_name,
        "candidate_count": int(candidates.size),
        "early_blob_count": early_blob_count(candidates),
        "fit_found": fit is not None,
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
            "selected_mean_h": float(np.mean(heights)),
            "selected_below20": int(np.sum(heights < 20.0)),
            "selected_below30": int(np.sum(heights < 30.0)),
        }
    )
    return row


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_benchmark_cases()
    combos = [
        ("quantile", "none", "width_prom"),
        ("quantile", "light", "width_prom"),
        ("quantile", "light", "deriv_11_3"),
        ("minwin_51", "none", "width_prom"),
        ("minwin_51", "light", "width_prom"),
        ("minwin_51", "light", "deriv_11_3"),
        ("morph_open_151", "none", "width_prom"),
        ("morph_open_151", "none", "width_prom_strict"),
        ("morph_open_151", "light", "width_prom"),
        ("morph_open_151", "light", "width_prom_strict"),
        ("snip_40", "none", "width_prom"),
        ("snip_40", "light", "width_prom"),
        ("snip_40", "light", "deriv_11_3"),
    ]
    rows: list[dict] = []
    for case in cases:
        for baseline_name, smoother_name, detector_name in combos:
            rows.append(run_case(case, baseline_name, smoother_name, detector_name))

    detail_path = OUT_DIR / "detail.tsv"
    with detail_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    agg: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        agg[(row["cohort"], row["baseline"], row["smoothing"], row["detector"])].append(row)

    aggregate_rows: list[dict] = []
    for (cohort, baseline_name, smoother_name, detector_name), group in agg.items():
        found = [g for g in group if g.get("fit_found")]
        base = {
            "cohort": cohort,
            "baseline": baseline_name,
            "smoothing": smoother_name,
            "detector": detector_name,
            "n": len(group),
            "fit_found_rate": len(found) / len(group) if group else 0.0,
        }
        if found:
            for key in [
                "linear_max",
                "linear_mean",
                "linear_r2",
                "candidate_count",
                "early_blob_count",
                "selected_median_h",
                "selected_min_h",
                "selected_mean_h",
                "selected_below20",
                "selected_below30",
                "family_score",
            ]:
                base[f"{key}_mean"] = float(np.mean([float(r[key]) for r in found]))
        aggregate_rows.append(base)

    aggregate_rows.sort(
        key=lambda r: (
            r["cohort"],
            r.get("linear_max_mean", 999.0),
            r.get("early_blob_count_mean", 999.0),
            r.get("candidate_count_mean", 999.0),
            -r.get("fit_found_rate", 0.0),
        )
    )
    with (OUT_DIR / "aggregate.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in aggregate_rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(aggregate_rows)

    winners: list[dict] = []
    by_case: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("fit_found"):
            by_case[row["label"]].append(row)
    for label, group in by_case.items():
        best = min(
            group,
            key=lambda r: (
                float(r["linear_max"]),
                float(r["linear_mean"]),
                -float(r["linear_r2"]),
                float(r["selected_below20"]),
                float(r["selected_below30"]),
                float(r["early_blob_count"]),
                float(r["candidate_count"]),
            ),
        )
        winners.append(best)
    with (OUT_DIR / "best_by_case.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in winners for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(winners)

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "case_count": len(cases),
                "combo_count": len(combos),
                "baselines": list(BASELINES.keys()),
                "smoothers": list(SMOOTHERS.keys()),
                "detectors": list(DETECTORS.keys()),
                "detail_tsv": str(detail_path),
                "aggregate_tsv": str(OUT_DIR / "aggregate.tsv"),
                "best_by_case_tsv": str(OUT_DIR / "best_by_case.tsv"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(OUT_DIR)
    print(f"cases={len(cases)} combos={len(combos)} rows={len(rows)}")


if __name__ == "__main__":
    main()
