from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import ndimage, signal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import (
    MIN_DISTANCE_BETWEEN_PEAKS_LIZ,
    MIN_DISTANCE_BETWEEN_PEAKS_ROX,
    MIN_SIZE_STANDARD_HEIGHT_LIZ,
    MIN_SIZE_STANDARD_HEIGHT_ROX,
    _clean_rox_size_standard_peaks,
    _compute_robust_arpls_baseline,
    _prepare_rox_size_standard_peaks,
    _rank_size_standard_combinations,
    _rolling_quantile_baseline,
    _select_best_ladder_candidate,
    _set_ladder_fit_profile,
    _supplement_rox_preferred_region_peaks,
    compute_ladder_qc_metrics,
)
from fraggler.fraggler import FsaFile, find_size_standard_peaks


OUT_DIR = Path("/Users/christian/Desktop/HemaFrag/artifacts/baseline_experiment_2025")


@dataclass(frozen=True)
class Case:
    path: str
    label: str
    kind: str


CASES: list[Case] = [
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_08_04_FR123_ikzf1_PR_H9C0ZIZD_2025-08-04_0045/25OUM11795_FR2__010825_F04_H9C0ZIZD.fsa",
        "bad_rox_fr2_11795",
        "ROX400HD",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_05_06_TCRb_SL_aw_C920XX20_2025-05-07_0696/25OUM07000_TCRb_A_060525_E02_C920XX20.fsa",
        "bad_rox_tcrba_07000",
        "ROX400HD",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_09_17_FR123_ikzf1_pr_C990WOCJ_2025-09-17_0154/25OUM13731_FR2__160925_F04_C990WOCJ.fsa",
        "bad_rox_fr2_13731",
        "ROX400HD",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16577_tcrgB__281025_E03_H920G04X.fsa",
        "bad_liz_tcrgb_16577",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16468_tcrgB__281025_D03_H920G04X.fsa",
        "bad_liz_tcrgb_16468",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16288_tcrgA__281025_B02_H920G04X.fsa",
        "bad_liz_tcrga_16288_b02",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16084_tcrgB__281025_A03_H920G04X.fsa",
        "good_liz_tcrgb_16084",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25RAH14619_tcrgB__281025_F06_H920G04X.fsa",
        "good_liz_tcrgb_rah14619",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16406_tcrgB__281025_C03_H920G04X.fsa",
        "good_liz_tcrgb_16406",
        "LIZ500_250",
    ),
    Case(
        "/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283/25OUM16586_tcrgB__281025_F03_H920G04X.fsa",
        "good_liz_tcrgb_16586",
        "LIZ500_250",
    ),
]


def _snip_baseline(trace: np.ndarray, max_half_window: int = 80) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    if values.size == 0:
        return np.zeros_like(values)
    work = np.log1p(np.maximum(values, 0.0))
    n = work.size
    baseline = work.copy()
    max_half_window = min(max_half_window, max(1, (n - 1) // 2))
    for k in range(1, max_half_window + 1):
        left = baseline[:-2 * k]
        right = baseline[2 * k :]
        center = baseline[k : n - k]
        baseline[k : n - k] = np.minimum(center, 0.5 * (left + right))
    return np.expm1(baseline)


def _morph_open_baseline(trace: np.ndarray, size: int = 121) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    if values.size == 0:
        return np.zeros_like(values)
    opened = ndimage.grey_opening(values, size=size)
    return np.asarray(opened, dtype=float)


def _quantile_smooth_baseline(trace: np.ndarray, bin_size: int = 200, quantile: float = 0.10, sigma: float = 8.0) -> np.ndarray:
    base = _rolling_quantile_baseline(trace, bin_size=bin_size, quantile=quantile)
    return np.asarray(ndimage.gaussian_filter1d(base, sigma=sigma, mode="nearest"), dtype=float)


def _quantile_arpls_cap_baseline(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    quant = _rolling_quantile_baseline(values, bin_size=200, quantile=0.10)
    arpls = _compute_robust_arpls_baseline(values, lam=100.0, ratio=0.99)
    resid = values - quant
    resid_scale = float(np.std(resid)) if resid.size else 0.0
    slack = max(6.0, 0.06 * resid_scale)
    return np.minimum(arpls, quant + slack)


def _quantile_arpls_blend_baseline(trace: np.ndarray) -> np.ndarray:
    values = np.asarray(trace, dtype=float)
    quant = _rolling_quantile_baseline(values, bin_size=200, quantile=0.10)
    arpls = _compute_robust_arpls_baseline(values, lam=100.0, ratio=0.99)
    blended = 0.75 * quant + 0.25 * arpls
    return np.minimum(blended, quant + 10.0)


def _zeros_baseline(trace: np.ndarray) -> np.ndarray:
    return np.zeros_like(trace, dtype=float)


METHODS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "raw": _zeros_baseline,
    "quantile": lambda x: _rolling_quantile_baseline(x, bin_size=200, quantile=0.10),
    "quantile_smooth": lambda x: _quantile_smooth_baseline(x, bin_size=200, quantile=0.10, sigma=8.0),
    "guarded_arpls": lambda x: _compute_robust_arpls_baseline(x, lam=100.0, ratio=0.99),
    "arpls_cap_quantile": _quantile_arpls_cap_baseline,
    "blend_quantile_arpls": _quantile_arpls_blend_baseline,
    "snip": lambda x: _snip_baseline(x, max_half_window=80),
    "morph_open": lambda x: _morph_open_baseline(x, size=121),
}


def _size_standard_channel(fsa: FsaFile, ladder: str) -> str:
    channels = set(fsa.fsa.keys())
    if ladder == "LIZ500_250":
        if "DATA105" in channels:
            return "DATA105"
        if "DATA5" in channels:
            return "DATA5"
        return "DATA4"
    return "DATA4"


def _base_params(ladder: str) -> tuple[float, float]:
    if ladder == "LIZ500_250":
        return float(MIN_DISTANCE_BETWEEN_PEAKS_LIZ), float(MIN_SIZE_STANDARD_HEIGHT_LIZ)
    return float(MIN_DISTANCE_BETWEEN_PEAKS_ROX), float(MIN_SIZE_STANDARD_HEIGHT_ROX)


def _build_fsa(path: str, ladder: str) -> FsaFile:
    min_distance, min_height = _base_params(ladder)
    probe = FsaFile(
        file=path,
        ladder=ladder,
        sample_channel="DATA1",
        min_distance_between_peaks=min_distance,
        min_size_standard_height=min_height,
        size_standard_channel="DATA4" if ladder == "ROX400HD" else "DATA105",
    )
    ss_channel = _size_standard_channel(probe, ladder)
    fsa = FsaFile(
        file=path,
        ladder=ladder,
        sample_channel="DATA1",
        min_distance_between_peaks=min_distance,
        min_size_standard_height=min_height,
        size_standard_channel=ss_channel,
    )
    fsa.analysis_id = "clonality"
    profile = "clonality_liz500" if ladder == "LIZ500_250" else "clonality_rox400hd"
    _set_ladder_fit_profile(fsa, profile, analysis_id="clonality")
    return fsa


def _prepare_peaks(fsa: FsaFile) -> FsaFile:
    fsa = find_size_standard_peaks(fsa)
    if fsa.ladder == "ROX400HD":
        raw = np.asarray(fsa.size_standard, dtype=float)
        supplemented = _supplement_rox_preferred_region_peaks(
            np.asarray(getattr(fsa, "size_standard_peaks", []), dtype=float),
            raw,
            expected_count=int(len(np.asarray(getattr(fsa, "ladder_steps", []), dtype=float))),
            min_distance=float(getattr(fsa, "min_distance_between_peaks", 1.0) or 1.0),
        )
        cleaned = _clean_rox_size_standard_peaks(np.asarray(supplemented, dtype=int), raw)
        if len(cleaned) >= 8:
            fsa.size_standard_peaks = _prepare_rox_size_standard_peaks(
                np.asarray(cleaned, dtype=float),
                raw,
                expected_count=int(len(np.asarray(getattr(fsa, "ladder_steps", []), dtype=float))),
            )
    return fsa


def _corrected_stats(corrected: np.ndarray) -> dict[str, float]:
    return {
        "corr_median": float(np.median(corrected)),
        "corr_q10": float(np.quantile(corrected, 0.10)),
        "corr_q25": float(np.quantile(corrected, 0.25)),
        "corr_mean": float(np.mean(corrected)),
    }


def _display_possible_peaks(corrected: np.ndarray, ladder: str) -> np.ndarray:
    values = np.asarray(corrected, dtype=float)
    if values.size == 0:
        return np.array([], dtype=int)
    if ladder == "LIZ500_250":
        height = max(20.0, float(np.percentile(values, 92)) * 0.10)
        prominence = max(8.0, float(np.percentile(values, 96)) * 0.04)
        distance = 10
    else:
        height = max(20.0, float(np.percentile(values, 90)) * 0.10)
        prominence = max(8.0, float(np.percentile(values, 96)) * 0.05)
        distance = 8
    peaks, _ = signal.find_peaks(
        values,
        height=height,
        prominence=prominence,
        distance=distance,
    )
    peaks = np.asarray([p for p in peaks if 1300 <= p <= 4300], dtype=int)
    return peaks


def run_case(case: Case, method_name: str, baseline_fn: Callable[[np.ndarray], np.ndarray]) -> dict[str, object]:
    fsa = _build_fsa(case.path, case.kind)
    raw = np.asarray(fsa.fsa[fsa.size_standard_channel], dtype=float)
    baseline = np.asarray(baseline_fn(raw), dtype=float)
    baseline = np.where(np.isfinite(baseline), baseline, 0.0)
    baseline = np.minimum(baseline, raw)
    corrected = raw - baseline
    corrected_clip = np.maximum(corrected, 0.0)
    display_candidates = _display_possible_peaks(corrected_clip, case.kind)
    fsa.size_standard = corrected_clip
    fsa = _prepare_peaks(fsa)
    selected: list[int] = []
    linear_max = float("nan")
    linear_mean = float("nan")
    linear_r2 = float("nan")
    ok = False
    try:
        ranked = _rank_size_standard_combinations(fsa)
        best = _select_best_ladder_candidate(fsa, ranked)
        if best is not None and getattr(best, "fitted_to_model", False):
            metrics = compute_ladder_qc_metrics(best)
            selected = [int(x) for x in np.asarray(best.best_size_standard, dtype=float)]
            linear_max = float(metrics.get("linear_max_abs_error", float("nan")))
            linear_mean = float(metrics.get("linear_mean_abs_error", float("nan")))
            linear_r2 = float(metrics.get("linear_r2", float("nan")))
            ok = True
    except Exception:
        ok = False
    return {
        "file": Path(case.path).name,
        "label": case.label,
        "ladder": case.kind,
        "method": method_name,
        "size_standard_channel": fsa.size_standard_channel,
        "candidate_count": int(len(np.asarray(getattr(fsa, "size_standard_peaks", []), dtype=float))),
        "display_candidate_count": int(display_candidates.size),
        "selected_count": len(selected),
        "selected": selected,
        "linear_max": linear_max,
        "linear_mean": linear_mean,
        "linear_r2": linear_r2,
        "ok": ok,
        **_corrected_stats(corrected),
        "_raw": raw,
        "_baseline": baseline,
        "_corrected": corrected_clip,
        "_candidates": np.asarray(getattr(fsa, "size_standard_peaks", []), dtype=float),
        "_display_candidates": display_candidates,
    }


def _plot_case(case: Case, rows: list[dict[str, object]]) -> None:
    fig, axes = plt.subplots(len(rows), 2, figsize=(16, 3.8 * len(rows)), sharex=True)
    if len(rows) == 1:
        axes = np.array([axes])

    for ax_row, row in zip(axes, rows):
        raw = np.asarray(row["_raw"], dtype=float)
        baseline = np.asarray(row["_baseline"], dtype=float)
        corrected = np.asarray(row["_corrected"], dtype=float)
        candidates = np.asarray(row["_candidates"], dtype=float)
        display_candidates = np.asarray(row["_display_candidates"], dtype=float)
        selected = np.asarray(row["selected"], dtype=float)

        ax_raw, ax_corr = ax_row
        ax_raw.plot(raw, color="black", lw=1.0)
        ax_raw.plot(baseline, color="#d95f02", lw=1.0)
        ax_raw.set_xlim(1200, 4300)
        ax_raw.set_ylim(-50, max(1500, np.percentile(raw[(raw >= 1200) if False else slice(None)], 99.5) if raw.size else 1500))
        ax_raw.set_title(
            f"{row['method']} raw/baseline\nmedian={row['corr_median']:.1f} q10={row['corr_q10']:.1f}"
        )
        ax_raw.grid(alpha=0.2)

        ax_corr.plot(corrected, color="black", lw=1.0)
        if display_candidates.size:
            ax_corr.scatter(
                display_candidates,
                corrected[display_candidates.astype(int)],
                s=14,
                color="#9e9e9e",
                alpha=0.6,
            )
        if candidates.size:
            ax_corr.scatter(candidates, corrected[candidates.astype(int)], s=20, color="#4d4d4d", alpha=0.8)
        if selected.size:
            ax_corr.scatter(selected, corrected[selected.astype(int)], s=32, color="#ff7f0e")
        ax_corr.axhline(0.0, color="#2ca02c", lw=0.8, alpha=0.7)
        ax_corr.set_xlim(1200, 4300)
        y_max = max(600.0, float(np.percentile(corrected, 99.7)) if corrected.size else 600.0)
        ax_corr.set_ylim(-20, y_max * 1.05)
        ax_corr.set_title(
            f"{row['method']} corrected\ncand={row['candidate_count']} poss={row['display_candidate_count']} sel={row['selected_count']} "
            f"lmax={row['linear_max']:.2f} lmean={row['linear_mean']:.2f} r2={row['linear_r2']:.5f}"
        )
        ax_corr.grid(alpha=0.2)

    fig.suptitle(f"{Path(case.path).name} ({case.kind})", fontsize=12)
    fig.tight_layout()
    out_path = OUT_DIR / f"{case.label}_baseline_compare.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for case in CASES:
        case_rows: list[dict[str, object]] = []
        for method_name, baseline_fn in METHODS.items():
            row = run_case(case, method_name, baseline_fn)
            rows.append(row)
            case_rows.append(row)
        _plot_case(case, case_rows)

    clean_rows: list[dict[str, object]] = []
    for row in rows:
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        clean_rows.append(clean)

    df = pd.DataFrame(clean_rows)
    df.sort_values(["label", "method"]).to_csv(OUT_DIR / "summary.tsv", sep="\t", index=False)
    (OUT_DIR / "summary.json").write_text(json.dumps(clean_rows, indent=2))

    best = (
        df.loc[df["ok"] == True]
        .sort_values(["file", "linear_max", "linear_mean", "linear_r2"], ascending=[True, True, True, False])
        .groupby("file", as_index=False)
        .head(1)
    )
    best.to_csv(OUT_DIR / "best_by_file.tsv", sep="\t", index=False)
    print(best[["file", "method", "linear_max", "linear_mean", "linear_r2", "corr_median", "corr_q10"]].to_string(index=False))


if __name__ == "__main__":
    main()
