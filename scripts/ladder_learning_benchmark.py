from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import grey_opening

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analysis import _compute_robust_arpls_baseline, _rolling_quantile_baseline
from core.rust_bridge import _get_rust_worker, _rust_timeout_seconds
from fraggler.fraggler import FsaFile


OUT_DIR = Path("/Users/christian/Desktop/HemaFrag/artifacts/ladder_learning_benchmark")
WORKBOOK_ROOT = Path("/Volumes/T7 Shield/HemaFrag_2025_safe_reruns_2026-04-28")
DATA_ROOT = Path("/Volumes/T7 Shield/DATA/2025_data")
PREFIX_RE = re.compile(r"^\d+_[0-9a-f]+_")

SPECIAL_CASES = [
    {
        "label": "special_rox_false_complete_29_04_fr3",
        "raw_path": "/Volumes/T7 Shield/29_04/2026_04_29_FR_DHJH_CFB_C99174FC_2026-04-29_0731/26OUM05318_FR3_290426_A05_C99174FC.fsa",
        "ladder_type": "ROX",
        "cohort": "special",
        "assay": "FR3",
        "source": "29_04",
    },
    {
        "label": "special_liz_blob_16577",
        "raw_path": "/Volumes/T7 Shield/DATA/2025_data/2025_10_28_TCRg_CFB_H920G04X_2025-10-28_1643/25OUM16577_tcrgB__281025_E03_H920G04X.fsa",
        "ladder_type": "LIZ",
        "cohort": "special",
        "assay": "TCRgB",
        "source": "2025_10",
    },
    {
        "label": "special_liz_blob_16468",
        "raw_path": "/Volumes/T7 Shield/DATA/2025_data/2025_10_28_TCRg_CFB_H920G04X_2025-10-28_1643/25OUM16468_tcrgB__281025_D03_H920G04X.fsa",
        "ladder_type": "LIZ",
        "cohort": "special",
        "assay": "TCRgB",
        "source": "2025_10",
    },
    {
        "label": "special_liz_blob_16288_b02",
        "raw_path": "/Volumes/T7 Shield/DATA/2025_data/2025_10_28_TCRg_CFB_H920G04X_2025-10-28_1643/25OUM16288_tcrgA__281025_B02_H920G04X.fsa",
        "ladder_type": "LIZ",
        "cohort": "special",
        "assay": "TCRgA",
        "source": "2025_10",
    },
]


@dataclass(frozen=True)
class Experiment:
    baseline_name: str
    detector_name: str
    lane_name: str


EXPERIMENTS = [
    Experiment("quantile_200", "width_prom_loose", "default"),
    Experiment("quantile_200", "wavelet", "blob_suspect"),
    Experiment("blend", "wavelet", "blob_suspect_blend"),
    Experiment("quantile_200", "width_prom_halfwidth", "default_halfwidth"),
    Experiment("morph_open_151", "width_prom_loose", "hardcase_morph_width"),
    Experiment("morph_open_151", "wavelet", "hardcase_morph_wavelet"),
    Experiment("snip_40", "width_prom_loose", "hardcase_snip_width"),
    Experiment("snip_40", "wavelet", "hardcase_snip_wavelet"),
]


def strip_stage_prefix(name: str) -> str:
    return PREFIX_RE.sub("", name)


def ladder_type(assay: str, file_name: str) -> str:
    assay = str(assay or "")
    lower = str(file_name or "").lower()
    if assay in ("TCRgA", "TCRgB", "IGK", "KDE") or any(k in lower for k in ("tcrg", "igk", "kde", "trga", "trgb")):
        return "LIZ"
    return "ROX"


def bucket(qc: str, lmax: float) -> str:
    qc = str(qc or "")
    lmax = float(lmax or 0.0)
    if qc == "ok" and lmax < 5:
        return "good"
    if qc != "ok" or lmax > 10:
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


def morph_open_baseline(trace: np.ndarray) -> np.ndarray:
    return grey_opening(np.asarray(trace, dtype=float), size=151)


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
    "quantile_120": lambda x: quantile_baseline(x, 120),
    "quantile_200": lambda x: quantile_baseline(x, 200),
    "quantile_320": lambda x: quantile_baseline(x, 320),
    "blend": blend_baseline,
    "morph_open_151": morph_open_baseline,
    "snip_40": snip_baseline,
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
    return df[df["raw_path"].map(lambda p: Path(p).exists())].copy()


def build_benchmark_cases() -> pd.DataFrame:
    df = load_workbook_rows()
    sampled = pd.concat(
        [
            choose_rows(df, "LIZ", "good", 25),
            choose_rows(df, "LIZ", "bad", 25),
            choose_rows(df, "ROX", "good", 25),
            choose_rows(df, "ROX", "bad", 25),
        ],
        ignore_index=True,
    )
    sampled = sampled.assign(
        cohort=lambda d: d["ladder_type"].str.lower() + "_" + d["bucket"].astype(str),
        source=lambda d: d["Month"].astype(str),
        label=lambda d: d["raw_file"].astype(str).str.replace(".fsa", "", regex=False),
        assay=lambda d: d["Assay"].astype(str),
    )
    cols = ["label", "raw_path", "raw_file", "ladder_type", "cohort", "assay", "source", "LadderQC", "LadderLinearMaxResidualBp", "LadderLinearMeanResidualBp", "LadderLinearR2"]
    sampled = sampled[cols].rename(
        columns={
            "LadderQC": "workbook_qc",
            "LadderLinearMaxResidualBp": "workbook_linear_max",
            "LadderLinearMeanResidualBp": "workbook_linear_mean",
            "LadderLinearR2": "workbook_linear_r2",
        }
    )

    special_rows = pd.DataFrame(SPECIAL_CASES)
    special_rows["raw_file"] = special_rows["raw_path"].map(lambda p: Path(p).name)
    special_rows["workbook_qc"] = ""
    special_rows["workbook_linear_max"] = np.nan
    special_rows["workbook_linear_mean"] = np.nan
    special_rows["workbook_linear_r2"] = np.nan

    combined = pd.concat([sampled, special_rows[sampled.columns]], ignore_index=True)
    combined = combined.drop_duplicates(subset=["raw_path"], keep="first").copy()
    combined = combined[combined["raw_path"].map(lambda p: Path(p).exists())].copy()
    return combined


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


def rust_selected_map(paths: list[Path]) -> dict[str, dict]:
    worker = _get_rust_worker()
    if worker is None:
        return {}
    timeout = max(_rust_timeout_seconds("clonality"), 1)
    out: dict[str, dict] = {}
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
            review = res.get("ladder_review_assessment") or {}
            sizing = preview.get("sizing_model") or {}
            qc = sizing.get("qc_metrics") or {}
            out[str(path)] = {
                "selected_scans": [int(x) for x in scans],
                "review_reason": review.get("primary_reason"),
                "review_codes": review.get("reason_codes") or [],
                "linear_max": qc.get("linear_trend_max_abs_error_bp"),
                "linear_mean": qc.get("linear_trend_mean_abs_error_bp"),
                "linear_r2": qc.get("linear_trend_r2"),
                "quadratic_r2": qc.get("quadratic_trend_r2"),
            }
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


def head_tail_recall(candidates: np.ndarray, selected: list[int], n: int, tol: int = 12) -> tuple[float, float]:
    if not selected:
        return float("nan"), float("nan")
    head = selected[:n]
    tail = selected[-n:]
    return recall(candidates, head, tol), recall(candidates, tail, tol)


def early_blob_count(candidates: np.ndarray, ladder: str) -> int:
    boundary = 1550 if ladder == "LIZ" else 1700
    return int(np.sum(candidates < boundary))


def recommend_lane(candidates_default: np.ndarray, candidates_blob: np.ndarray, ladder: str) -> str:
    if ladder != "LIZ":
        return "default"
    default_blob = early_blob_count(candidates_default, ladder)
    blob_blob = early_blob_count(candidates_blob, ladder)
    if default_blob >= 8 and blob_blob <= max(4, default_blob - 3):
        return "blob_suspect"
    return "default"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = build_benchmark_cases()
    case_paths = [Path(p) for p in cases["raw_path"].tolist()]
    rust_map = rust_selected_map(case_paths)

    case_records = []
    rows = []

    for _, case in cases.iterrows():
        raw_path = str(case["raw_path"])
        ladder = str(case["ladder_type"])
        trace = load_trace(raw_path, ladder)
        selected_meta = rust_map.get(raw_path, {})
        selected = selected_meta.get("selected_scans", [])

        baseline_cache = {name: fn(trace) for name, fn in BASELINES.items()}
        corrected_cache = {name: np.maximum(trace - baseline, 0.0) for name, baseline in baseline_cache.items()}
        detector_cache: dict[tuple[str, str], np.ndarray] = {}

        for exp in EXPERIMENTS:
            corrected = corrected_cache[exp.baseline_name]
            candidates = DETECTORS[exp.detector_name](corrected, ladder)
            detector_cache[(exp.baseline_name, exp.detector_name)] = candidates
            head_rec, tail_rec = head_tail_recall(candidates, selected, 4)
            rows.append(
                {
                    "label": case["label"],
                    "raw_file": case["raw_file"],
                    "raw_path": raw_path,
                    "ladder_type": ladder,
                    "cohort": str(case["cohort"]),
                    "assay": str(case["assay"]),
                    "source": str(case["source"]),
                    "baseline_method": exp.baseline_name,
                    "candidate_method": exp.detector_name,
                    "lane_used": exp.lane_name,
                    "candidate_count": int(candidates.size),
                    "early_blob_count": early_blob_count(candidates, ladder),
                    "recall_tol12": recall(candidates, selected, 12),
                    "head_recall_tol12": head_rec,
                    "tail_recall_tol12": tail_rec,
                    "selected_count": len(selected),
                    "selected_peaks": json.dumps(selected),
                    "candidate_peaks": json.dumps([int(x) for x in candidates.tolist()]),
                    "workbook_qc": case["workbook_qc"],
                    "workbook_linear_max": case["workbook_linear_max"],
                    "workbook_linear_mean": case["workbook_linear_mean"],
                    "workbook_linear_r2": case["workbook_linear_r2"],
                    "rust_linear_max": selected_meta.get("linear_max"),
                    "rust_linear_mean": selected_meta.get("linear_mean"),
                    "rust_linear_r2": selected_meta.get("linear_r2"),
                    "review_reason": selected_meta.get("review_reason"),
                    "review_codes": json.dumps(selected_meta.get("review_codes") or []),
                }
            )

        default_candidates = detector_cache.get(("quantile_200", "width_prom_loose"), np.asarray([], dtype=int))
        blob_candidates = detector_cache.get(("quantile_200", "wavelet"), np.asarray([], dtype=int))
        case_records.append(
            {
                **case.to_dict(),
                "rust_selected_peaks": selected,
                "rust_review_reason": selected_meta.get("review_reason"),
                "rust_review_codes": selected_meta.get("review_codes") or [],
                "rust_linear_max": selected_meta.get("linear_max"),
                "rust_linear_mean": selected_meta.get("linear_mean"),
                "rust_linear_r2": selected_meta.get("linear_r2"),
                "recommended_lane": recommend_lane(default_candidates, blob_candidates, ladder),
            }
        )

    detail_df = pd.DataFrame(rows)
    detail_df.to_csv(OUT_DIR / "detail.tsv", sep="\t", index=False)
    (OUT_DIR / "detail.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    aggregate = (
        detail_df.groupby(["ladder_type", "cohort", "baseline_method", "candidate_method", "lane_used"], dropna=False, as_index=False)[
            ["candidate_count", "early_blob_count", "recall_tol12", "head_recall_tol12", "tail_recall_tol12"]
        ]
        .mean()
        .sort_values(["ladder_type", "cohort", "recall_tol12", "early_blob_count"], ascending=[True, True, False, True])
    )
    aggregate.to_csv(OUT_DIR / "aggregate.tsv", sep="\t", index=False)

    manifest = {
        "version": "v1",
        "case_count": int(len(case_records)),
        "detail_rows": int(len(detail_df)),
        "experiments": [asdict(exp) for exp in EXPERIMENTS],
        "special_cases": SPECIAL_CASES,
        "outputs": {
            "detail_tsv": str(OUT_DIR / "detail.tsv"),
            "detail_json": str(OUT_DIR / "detail.json"),
            "aggregate_tsv": str(OUT_DIR / "aggregate.tsv"),
            "cases_json": str(OUT_DIR / "cases.json"),
            "review_labels_csv": str(OUT_DIR / "review_labels_template.csv"),
        },
    }
    review_template = pd.DataFrame(
        [
            {
                "label": case["label"],
                "raw_file": case["raw_file"],
                "raw_path": case["raw_path"],
                "ladder_type": case["ladder_type"],
                "cohort": case["cohort"],
                "assay": case["assay"],
                "source": case["source"],
                "recommended_lane": case["recommended_lane"],
                "review_status": "",
                "hardcase_tags": "",
                "approved_selected_peaks": "",
                "rejected_candidate_peaks": "",
                "notes": "",
            }
            for case in case_records
        ]
    )
    (OUT_DIR / "cases.json").write_text(json.dumps(case_records, indent=2), encoding="utf-8")
    review_template.to_csv(OUT_DIR / "review_labels_template.csv", index=False)
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(aggregate.to_string(index=False))
    lane_counts = pd.DataFrame(case_records)["recommended_lane"].value_counts(dropna=False)
    print("\nRecommended lanes:")
    print(lane_counts.to_string())


if __name__ == "__main__":
    main()
