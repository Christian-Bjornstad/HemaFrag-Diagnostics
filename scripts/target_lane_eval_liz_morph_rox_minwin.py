from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hemafrag")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import liz_baseline_family_fit_eval as liz_eval
from scripts import liz_genemapper_methods_eval as liz_methods
from scripts import rox_genemapper_methods_eval as rox_eval


OUT_DIR = ROOT / "artifacts" / "target_lane_eval_liz_morph_rox_minwin"
IMAGE_DIR = OUT_DIR / "images"


LIZ_COMBOS = {
    "default_quantile_width": ("quantile", "none", "width_prom"),
    "morph_width": ("morph_open_151", "none", "width_prom"),
    "morph_light_width": ("morph_open_151", "light", "width_prom"),
    "morph_strict": ("morph_open_151", "none", "width_prom_strict"),
}

ROX_COMBOS = {
    "default_quantile_width": ("quantile", "none", "width_prom"),
    "minwin_width": ("minwin_51", "none", "width_prom"),
    "minwin_light_width": ("minwin_51", "light", "width_prom"),
    "minwin_light_deriv": ("minwin_51", "light", "deriv_11_3"),
}


def load_cases() -> list[dict]:
    rows = json.loads((ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json").read_text())
    return [r for r in rows if r["ladder_type"] in {"LIZ", "ROX"}]


def run_liz(case: dict, combo_name: str, combo: tuple[str, str, str]) -> dict:
    baseline_name, smoothing_name, detector_name = combo
    trace = liz_eval.load_trace(case["raw_path"])
    baseline = liz_methods.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = liz_methods.SMOOTHERS[smoothing_name](corrected)
    candidates = liz_methods.DETECTORS[detector_name](smoothed)
    fit = liz_eval.beam_fit_family(candidates, corrected)
    return row_from_fit(case, combo_name, baseline_name, smoothing_name, detector_name, candidates, corrected, fit)


def run_rox(case: dict, combo_name: str, combo: tuple[str, str, str], gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> dict:
    baseline_name, smoothing_name, detector_name = combo
    trace = rox_eval.load_trace(case["raw_path"])
    baseline = rox_eval.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = rox_eval.SMOOTHERS[smoothing_name](corrected)
    candidates = rox_eval.DETECTORS[detector_name](smoothed)
    fit = rox_eval.beam_fit_family(candidates, corrected, *gaps)
    return row_from_fit(case, combo_name, baseline_name, smoothing_name, detector_name, candidates, corrected, fit)


def row_from_fit(
    case: dict,
    combo_name: str,
    baseline_name: str,
    smoothing_name: str,
    detector_name: str,
    candidates: np.ndarray,
    corrected: np.ndarray,
    fit: dict | None,
) -> dict:
    row = {
        "label": case["label"],
        "file": Path(case["raw_path"]).name,
        "raw_path": case["raw_path"],
        "ladder_type": case["ladder_type"],
        "cohort": case["cohort"],
        "assay": case["assay"],
        "combo": combo_name,
        "baseline": baseline_name,
        "smoothing": smoothing_name,
        "detector": detector_name,
        "candidate_count": int(candidates.size),
        "early_count": int(np.sum((candidates >= 1300) & (candidates < 1650))),
        "fit_found": fit is not None,
    }
    if fit is None:
        return row
    selected = np.asarray(fit["selected"], dtype=int)
    heights = corrected[selected]
    row.update(
        {
            "linear_max": float(fit["linear_max"]),
            "linear_mean": float(fit["linear_mean"]),
            "linear_r2": float(fit["linear_r2"]),
            "selected": json.dumps([int(x) for x in selected.tolist()]),
            "selected_min_h": float(np.min(heights)),
            "selected_median_h": float(np.median(heights)),
            "selected_below30": int(np.sum(heights < 30.0)),
            "selected_below50": int(np.sum(heights < 50.0)),
        }
    )
    return row


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["ladder_type"], row["cohort"], row["combo"])].append(row)
    out = []
    for (ladder, cohort, combo), group in groups.items():
        found = [r for r in group if r.get("fit_found")]
        base = {
            "ladder_type": ladder,
            "cohort": cohort,
            "combo": combo,
            "n": len(group),
            "fit_found_rate": len(found) / len(group) if group else 0.0,
        }
        if found:
            for key in [
                "linear_max",
                "linear_mean",
                "linear_r2",
                "candidate_count",
                "early_count",
                "selected_min_h",
                "selected_median_h",
                "selected_below30",
                "selected_below50",
            ]:
                base[f"{key}_mean"] = float(np.mean([float(r[key]) for r in found]))
        out.append(base)
    out.sort(key=lambda r: (r["ladder_type"], r["cohort"], r.get("linear_max_mean", 999), r.get("candidate_count_mean", 999)))
    return out


def delta_rows(rows: list[dict]) -> list[dict]:
    by_case: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_case[row["label"]][row["combo"]] = row
    out = []
    for label, combos in by_case.items():
        default = combos.get("default_quantile_width")
        if not default or not default.get("fit_found"):
            continue
        targets = [r for name, r in combos.items() if name != "default_quantile_width" and r.get("fit_found")]
        if not targets:
            continue
        best = min(targets, key=lambda r: (float(r["linear_max"]), float(r["linear_mean"]), -float(r["linear_r2"])))
        out.append(
            {
                "label": label,
                "file": default["file"],
                "raw_path": default["raw_path"],
                "ladder_type": default["ladder_type"],
                "cohort": default["cohort"],
                "best_target_combo": best["combo"],
                "default_linear_max": float(default["linear_max"]),
                "target_linear_max": float(best["linear_max"]),
                "delta_linear_max": float(best["linear_max"]) - float(default["linear_max"]),
                "default_linear_mean": float(default["linear_mean"]),
                "target_linear_mean": float(best["linear_mean"]),
                "delta_linear_mean": float(best["linear_mean"]) - float(default["linear_mean"]),
                "default_candidate_count": int(default["candidate_count"]),
                "target_candidate_count": int(best["candidate_count"]),
                "default_selected_below50": int(default["selected_below50"]),
                "target_selected_below50": int(best["selected_below50"]),
            }
        )
    out.sort(key=lambda r: (r["ladder_type"], r["delta_linear_max"]))
    return out


def plot_case(case: dict, default_row: dict, target_row: dict, gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> Path:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    if case["ladder_type"] == "LIZ":
        trace = liz_eval.load_trace(case["raw_path"])
        runners = {
            "default_quantile_width": lambda: run_liz_arrays(trace, LIZ_COMBOS["default_quantile_width"]),
            target_row["combo"]: lambda: run_liz_arrays(trace, LIZ_COMBOS[target_row["combo"]]),
        }
        y_max = 300
    else:
        trace = rox_eval.load_trace(case["raw_path"])
        runners = {
            "default_quantile_width": lambda: run_rox_arrays(trace, ROX_COMBOS["default_quantile_width"], gaps),
            target_row["combo"]: lambda: run_rox_arrays(trace, ROX_COMBOS[target_row["combo"]], gaps),
        }
        y_max = 1000

    panels = [
        ("default_quantile_width", "default: quantile + width_prom"),
        (target_row["combo"], f"target: {target_row['combo']}"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharex=True)
    for ax, (combo_name, title) in zip(axes, panels):
        corrected, candidates, fit = runners[combo_name]()
        ax.plot(corrected, color="black", lw=1.0)
        if candidates.size:
            ax.scatter(candidates, corrected[candidates], s=18, color="royalblue", alpha=0.65, label=f"possible ({len(candidates)})")
        if fit is not None:
            sel = np.asarray(fit["selected"], dtype=int)
            ax.scatter(sel, corrected[sel], s=34, color="crimson", zorder=3, label="selected")
            for i, p in enumerate(sel):
                ax.text(int(p), float(corrected[int(p)]) + (5 if case["ladder_type"] == "LIZ" else 12), str(i + 1), color="crimson", fontsize=7, ha="center")
            metrics = f"max {fit['linear_max']:.2f} mean {fit['linear_mean']:.2f} r2 {fit['linear_r2']:.6f}"
        else:
            metrics = "no fit"
        ax.set_title(f"{case['label']} | {title} | {metrics}")
        ax.set_xlim(1200 if case["ladder_type"] == "ROX" else 1300, 5000)
        ax.set_ylim(0, y_max)
        ax.grid(alpha=0.2)
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("scan")
    fig.tight_layout()
    out = IMAGE_DIR / f"{case['ladder_type'].lower()}_{case['label']}_{target_row['combo']}.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def run_liz_arrays(trace: np.ndarray, combo: tuple[str, str, str]) -> tuple[np.ndarray, np.ndarray, dict | None]:
    baseline_name, smoothing_name, detector_name = combo
    baseline = liz_methods.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = liz_methods.SMOOTHERS[smoothing_name](corrected)
    candidates = liz_methods.DETECTORS[detector_name](smoothed)
    return corrected, candidates, liz_eval.beam_fit_family(candidates, corrected)


def run_rox_arrays(trace: np.ndarray, combo: tuple[str, str, str], gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray, dict | None]:
    baseline_name, smoothing_name, detector_name = combo
    baseline = rox_eval.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = rox_eval.SMOOTHERS[smoothing_name](corrected)
    candidates = rox_eval.DETECTORS[detector_name](smoothed)
    return corrected, candidates, rox_eval.beam_fit_family(candidates, corrected, *gaps)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    rox_cases = [c for c in rox_eval.load_benchmark_cases()]
    rox_selected = rox_eval.rust_selected_map(rox_cases)
    rox_gaps = rox_eval.gap_template(rox_selected, rox_cases)
    rows: list[dict] = []
    for case in cases:
        if case["ladder_type"] == "LIZ":
            for name, combo in LIZ_COMBOS.items():
                rows.append(run_liz(case, name, combo))
        elif case["ladder_type"] == "ROX":
            for name, combo in ROX_COMBOS.items():
                rows.append(run_rox(case, name, combo, rox_gaps))

    with (OUT_DIR / "detail.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    aggregate_rows = aggregate(rows)
    with (OUT_DIR / "aggregate.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in aggregate_rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(aggregate_rows)

    deltas = delta_rows(rows)
    with (OUT_DIR / "delta_vs_default.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in deltas for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(deltas)

    case_by_label = {c["label"]: c for c in cases}
    row_by_key = {(r["label"], r["combo"]): r for r in rows}
    selected_for_images = []
    for ladder in ["LIZ", "ROX"]:
        sub = [d for d in deltas if d["ladder_type"] == ladder]
        selected_for_images.extend(sub[:3])
        selected_for_images.extend(sub[-2:])
    image_rows = []
    seen: set[tuple[str, str]] = set()
    for d in selected_for_images:
        key = (d["label"], d["best_target_combo"])
        if key in seen:
            continue
        seen.add(key)
        case = case_by_label[d["label"]]
        default_row = row_by_key[(d["label"], "default_quantile_width")]
        target_row = row_by_key[(d["label"], d["best_target_combo"])]
        path = plot_case(case, default_row, target_row, rox_gaps)
        image_rows.append({"label": d["label"], "ladder_type": d["ladder_type"], "target_combo": d["best_target_combo"], "image": str(path)})
    with (OUT_DIR / "image_index.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["label", "ladder_type", "target_combo", "image"], delimiter="\t")
        writer.writeheader()
        writer.writerows(image_rows)

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "case_count": len(cases),
                "row_count": len(rows),
                "liz_combos": LIZ_COMBOS,
                "rox_combos": ROX_COMBOS,
                "aggregate_tsv": str(OUT_DIR / "aggregate.tsv"),
                "delta_tsv": str(OUT_DIR / "delta_vs_default.tsv"),
                "image_index_tsv": str(OUT_DIR / "image_index.tsv"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(OUT_DIR)
    print(f"cases={len(cases)} rows={len(rows)} images={len(image_rows)}")


if __name__ == "__main__":
    main()
