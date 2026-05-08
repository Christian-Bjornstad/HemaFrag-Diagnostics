from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import liz_baseline_family_fit_eval as base_eval


OUT_DIR = ROOT / "artifacts" / "liz_baseline_combo_family_eval"


def morph_cap_quantile(trace: np.ndarray) -> np.ndarray:
    q = base_eval.quantile_baseline(trace)
    m = base_eval.morph_open_baseline(trace)
    return np.minimum(m, q + 20.0)


def snip_cap_quantile(trace: np.ndarray) -> np.ndarray:
    q = base_eval.quantile_baseline(trace)
    s = base_eval.snip_baseline(trace)
    return np.minimum(s, q + 20.0)


def morph_smooth_blend(trace: np.ndarray) -> np.ndarray:
    m = base_eval.morph_open_baseline(trace)
    s = base_eval.snip_baseline(trace)
    return 0.65 * m + 0.35 * s


BASELINES = {
    "quantile": base_eval.quantile_baseline,
    "morph_open_151": base_eval.morph_open_baseline,
    "snip_40": base_eval.snip_baseline,
    "morph_cap_q+20": morph_cap_quantile,
    "snip_cap_q+20": snip_cap_quantile,
    "morph65_snip35": morph_smooth_blend,
}


def detect_union(values: np.ndarray) -> np.ndarray:
    w = set(int(x) for x in base_eval.detect_wavelet(values).tolist())
    p = set(int(x) for x in base_eval.detect_width_prom(values).tolist())
    return np.asarray(sorted(w | p), dtype=int)


def detect_consensus(values: np.ndarray) -> np.ndarray:
    w = np.asarray(base_eval.detect_wavelet(values), dtype=int)
    p = np.asarray(base_eval.detect_width_prom(values), dtype=int)
    if w.size == 0 or p.size == 0:
        return np.asarray(sorted(set(w.tolist()) | set(p.tolist())), dtype=int)
    keep: set[int] = set()
    for a in w:
        for b in p:
            if abs(int(a) - int(b)) <= 12:
                keep.add(int(a))
                keep.add(int(b))
    if not keep:
        keep.update(set(w.tolist()) | set(p.tolist()))
    return np.asarray(sorted(keep), dtype=int)


DETECTORS = {
    "wavelet": base_eval.detect_wavelet,
    "width_prom": base_eval.detect_width_prom,
    "union": detect_union,
    "consensus": detect_consensus,
}


def load_benchmark_cases() -> list[dict]:
    rows = json.loads((ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json").read_text())
    good = [r for r in rows if r["ladder_type"] == "LIZ" and r["cohort"] == "liz_good"][:8]
    bad = [r for r in rows if r["ladder_type"] == "LIZ" and r["cohort"] == "liz_bad"][:8]
    special_labels = {"special_liz_blob_16577", "special_liz_blob_16468", "special_liz_blob_16288_b02"}
    special = [r for r in rows if r["label"] in special_labels]
    return good + bad + special


def run_case(case: dict, baseline_name: str, detector_name: str) -> dict:
    trace = base_eval.load_trace(case["raw_path"])
    baseline = BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    candidates = DETECTORS[detector_name](corrected)
    fit = base_eval.beam_fit_family(candidates, corrected)
    row = {
        "label": case["label"],
        "cohort": case["cohort"],
        "assay": case["assay"],
        "baseline": baseline_name,
        "detector": detector_name,
        "candidate_count": int(candidates.size),
    }
    if fit is None:
        row["fit_found"] = False
        return row
    sel = np.asarray(fit["selected"], dtype=int)
    heights = corrected[sel]
    row.update(
        {
            "fit_found": True,
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
        ("quantile", "width_prom"),
        ("morph_open_151", "width_prom"),
        ("snip_40", "width_prom"),
        ("morph_cap_q+20", "width_prom"),
        ("snip_cap_q+20", "width_prom"),
        ("morph_open_151", "consensus"),
        ("snip_40", "consensus"),
        ("morph_cap_q+20", "consensus"),
        ("snip_cap_q+20", "consensus"),
    ]
    rows: list[dict] = []
    for case in cases:
        for baseline_name, detector_name in combos:
            rows.append(run_case(case, baseline_name, detector_name))

    detail_path = OUT_DIR / "detail.tsv"
    with detail_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    agg: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        agg[(row["cohort"], row["baseline"], row["detector"])].append(row)

    aggregate_rows: list[dict] = []
    for (cohort, baseline_name, detector_name), group in agg.items():
        found = [g for g in group if g.get("fit_found")]
        base = {
            "cohort": cohort,
            "baseline": baseline_name,
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
            r.get("selected_below20_mean", 999.0),
            -r.get("selected_median_h_mean", -999.0),
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
                -float(r["selected_median_h"]),
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
