from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
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


OUT_DIR = ROOT / "artifacts" / "fit_arbiter_offline_eval"
IMAGE_DIR = OUT_DIR / "images"

LIZ_COMBOS = {
    "default_quantile_width": ("quantile", "none", "width_prom"),
    "morph_width": ("morph_open_151", "none", "width_prom"),
    "snip_width": ("snip_40", "none", "width_prom"),
    "morph_light_width": ("morph_open_151", "light", "width_prom"),
}

ROX_COMBOS = {
    "default_quantile_width": ("quantile", "none", "width_prom"),
    "minwin_light_width": ("minwin_51", "light", "width_prom"),
    "arpls_cap_width": ("arpls_cap_q+25", "none", "width_prom"),
    "minwin_light_deriv": ("minwin_51", "light", "deriv_11_3"),
}

FOLDER_SOURCES = [
    (Path("/Volumes/T7 Shield/29_04"), 36),
    (Path("/Volumes/T7 Shield/DATA/2026/2026_03_27_TCRg_IGK_KDE_CFB_H9H1DI2F_2026-03-27_0652"), 24),
    (Path("/Volumes/T7 Shield/DATA/2026/2026_04_09_FR123_TCRB_CFB_H9H1DI1X_2026-04-10_0679"), 20),
    (Path("/Volumes/T7 Shield/DATA/2025_data/2025_10_29_tcrg_igkkde_pr_H920G04X_2025-10-29_0283"), 28),
    (Path("/Volumes/T7 Shield/DATA/2025_data/2025_01_16_TRB_IKZF1_EF_C990RHN7_2025-01-16_0400"), 24),
]


def infer_ladder(path: Path) -> str | None:
    name = path.name.lower()
    parent = path.parent.name.lower()
    text = f"{name} {parent}"
    if any(token in text for token in ["tcrg", "trg", "igk", "kde", "igkkde"]):
        return "LIZ"
    if any(token in text for token in ["fr1", "fr2", "fr3", "fr123", "dhjh", "sl", "tcrb", "trb", "igh", "ikzf"]):
        return "ROX"
    return None


def load_base_cases() -> list[dict]:
    cases_path = ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json"
    rows = json.loads(cases_path.read_text())
    cases = [r for r in rows if r.get("ladder_type") in {"LIZ", "ROX"}]
    for case in cases:
        case.setdefault("source_group", "benchmark_101")
    return cases


def collect_folder_cases() -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for folder, limit in FOLDER_SOURCES:
        if not folder.exists():
            continue
        picked = 0
        for path in sorted(folder.rglob("*.fsa")):
            if path.name.startswith("._"):
                continue
            ladder = infer_ladder(path)
            if ladder is None:
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            cases.append(
                {
                    "label": f"{folder.name}_{path.stem}",
                    "raw_path": str(path),
                    "raw_file": path.name,
                    "file": path.name,
                    "ladder_type": ladder,
                    "cohort": f"folder_{ladder.lower()}",
                    "assay": path.stem,
                    "source_group": folder.name,
                }
            )
            picked += 1
            if picked >= limit:
                break
    return cases


def load_cases() -> list[dict]:
    base = load_base_cases()
    folders = collect_folder_cases()
    by_path: dict[str, dict] = {}
    for case in base + folders:
        by_path[case["raw_path"]] = case
    return list(by_path.values())


def run_liz(case: dict, combo_name: str, combo: tuple[str, str, str]) -> dict:
    baseline_name, smoother_name, detector_name = combo
    trace = liz_eval.load_trace(case["raw_path"])
    baseline = liz_methods.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = liz_methods.SMOOTHERS[smoother_name](corrected)
    candidates = liz_methods.DETECTORS[detector_name](smoothed)
    fit = liz_eval.beam_fit_family(candidates, corrected)
    return row_from_fit(case, combo_name, baseline_name, smoother_name, detector_name, candidates, corrected, fit)


def run_rox(case: dict, combo_name: str, combo: tuple[str, str, str], gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> dict:
    baseline_name, smoother_name, detector_name = combo
    trace = rox_eval.load_trace(case["raw_path"])
    baseline = rox_eval.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = rox_eval.SMOOTHERS[smoother_name](corrected)
    candidates = rox_eval.DETECTORS[detector_name](smoothed)
    fit = rox_eval.beam_fit_family(candidates, corrected, *gaps)
    return row_from_fit(case, combo_name, baseline_name, smoother_name, detector_name, candidates, corrected, fit)


def row_from_fit(
    case: dict,
    combo_name: str,
    baseline_name: str,
    smoother_name: str,
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
        "cohort": case.get("cohort", ""),
        "source_group": case.get("source_group", ""),
        "assay": case.get("assay", ""),
        "combo": combo_name,
        "baseline": baseline_name,
        "smoothing": smoother_name,
        "detector": detector_name,
        "candidate_count": int(candidates.size),
        "early_count": int(np.sum((candidates >= 1300) & (candidates < (1650 if case["ladder_type"] == "LIZ" else 1750)))),
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
            "selected_first": int(selected[0]),
            "selected_last": int(selected[-1]),
            "selected_min_h": float(np.min(heights)),
            "selected_median_h": float(np.median(heights)),
            "selected_below30": int(np.sum(heights < 30.0)),
            "selected_below50": int(np.sum(heights < 50.0)),
            "selected_below80": int(np.sum(heights < 80.0)),
        }
    )
    row["plausibility_penalty"] = plausibility_penalty(row)
    row["arbiter_score"] = arbiter_score(row)
    return row


def plausibility_penalty(row: dict) -> float:
    if not row.get("fit_found"):
        return 999.0
    ladder = row["ladder_type"]
    weak = float(row.get("selected_below50", 0))
    very_weak = float(row.get("selected_below30", 0))
    min_h = float(row.get("selected_min_h", 0.0))
    median_h = float(row.get("selected_median_h", 1.0))
    early_count = float(row.get("early_count", 0))
    candidate_count = float(row.get("candidate_count", 0))
    first = float(row.get("selected_first", 0))
    last = float(row.get("selected_last", 0))
    penalty = 0.0
    penalty += very_weak * 1.2 + weak * 0.45
    if min_h < 20:
        penalty += 2.0
    if median_h > 0 and min_h / max(median_h, 1.0) < 0.12:
        penalty += 0.9
    if ladder == "LIZ":
        if early_count > 16 and first < 1500:
            penalty += (early_count - 16) * 0.12 + 0.8
        if last < 4000:
            penalty += 1.2
        if candidate_count > 230:
            penalty += (candidate_count - 230) / 90.0
    else:
        if early_count > 20 and first < 1600:
            penalty += 0.8
        if last < 3800:
            penalty += 1.0
        if candidate_count > 210:
            penalty += (candidate_count - 210) / 90.0
    return float(penalty)


def arbiter_score(row: dict) -> float:
    if not row.get("fit_found"):
        return 9999.0
    return (
        float(row["linear_max"])
        + 0.75 * float(row["linear_mean"])
        - 10.0 * max(0.0, float(row["linear_r2"]) - 0.999)
        + 0.95 * float(row.get("plausibility_penalty", 0.0))
    )


def fit_quality(row: dict) -> str:
    if not row.get("fit_found"):
        return "no_fit"
    lmax = float(row["linear_max"])
    lmean = float(row["linear_mean"])
    r2 = float(row["linear_r2"])
    plaus = float(row.get("plausibility_penalty", 999.0))
    if lmax <= 5.0 and lmean <= 2.3 and r2 >= 0.9995 and plaus <= 2.2:
        return "good"
    if lmax <= 8.0 and lmean <= 3.2 and r2 >= 0.9990 and plaus <= 4.0:
        return "usable"
    return "review"


def choose_arbiter(case_rows: list[dict]) -> dict:
    found = [r for r in case_rows if r.get("fit_found")]
    default = next((r for r in case_rows if r["combo"] == "default_quantile_width" and r.get("fit_found")), None)
    if not found:
        return {
            **case_rows[0],
            "decision": "missing_ladder_or_no_fit",
            "winner_combo": "",
            "winner_quality": "no_fit",
            "default_quality": "no_fit",
            "default_linear_max": "",
            "winner_linear_max": "",
            "delta_linear_max": "",
        }
    ranked = sorted(found, key=lambda r: (float(r["arbiter_score"]), float(r["linear_max"]), float(r["linear_mean"])))
    best = ranked[0]
    chosen = best
    decision = "alt_lane"
    default_quality = fit_quality(default) if default else "no_fit"
    if default is not None:
        default_score = float(default["arbiter_score"])
        best_score = float(best["arbiter_score"])
        default_good = default_quality == "good"
        best_compelling = (
            float(best["linear_max"]) <= float(default["linear_max"]) - 0.75
            and float(best["linear_mean"]) <= float(default["linear_mean"]) + 0.2
            and float(best.get("plausibility_penalty", 0.0)) <= float(default.get("plausibility_penalty", 0.0)) + 0.5
        )
        if default_good and not best_compelling:
            chosen = default
            decision = "keep_default_good"
        elif best["combo"] == "default_quantile_width" or default_score <= best_score + 0.35:
            chosen = default
            decision = "keep_default_close"
    quality = fit_quality(chosen)
    if quality == "review":
        decision = "review_required"
    return {
        "label": chosen["label"],
        "file": chosen["file"],
        "raw_path": chosen["raw_path"],
        "ladder_type": chosen["ladder_type"],
        "cohort": chosen["cohort"],
        "source_group": chosen["source_group"],
        "decision": decision,
        "winner_combo": chosen["combo"],
        "winner_quality": quality,
        "winner_linear_max": float(chosen["linear_max"]),
        "winner_linear_mean": float(chosen["linear_mean"]),
        "winner_linear_r2": float(chosen["linear_r2"]),
        "winner_plausibility_penalty": float(chosen.get("plausibility_penalty", 0.0)),
        "winner_selected_below50": int(chosen.get("selected_below50", 0)),
        "default_quality": default_quality,
        "default_linear_max": float(default["linear_max"]) if default else "",
        "default_linear_mean": float(default["linear_mean"]) if default else "",
        "default_linear_r2": float(default["linear_r2"]) if default else "",
        "default_plausibility_penalty": float(default.get("plausibility_penalty", 0.0)) if default else "",
        "delta_linear_max": float(chosen["linear_max"]) - float(default["linear_max"]) if default else "",
        "delta_linear_mean": float(chosen["linear_mean"]) - float(default["linear_mean"]) if default else "",
    }


def write_tsv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(decisions: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in decisions:
        groups[(row["ladder_type"], row["source_group"])].append(row)
    out = []
    for (ladder, source), group in groups.items():
        usable = [r for r in group if r["winner_quality"] in {"good", "usable"}]
        alt = [r for r in group if r["decision"] == "alt_lane"]
        review = [r for r in group if r["decision"] == "review_required"]
        out.append(
            {
                "ladder_type": ladder,
                "source_group": source,
                "n": len(group),
                "usable_rate": len(usable) / len(group),
                "alt_lane_rate": len(alt) / len(group),
                "review_rate": len(review) / len(group),
                "winner_linear_max_mean": float(np.mean([float(r["winner_linear_max"]) for r in usable])) if usable else "",
                "winner_linear_mean_mean": float(np.mean([float(r["winner_linear_mean"]) for r in usable])) if usable else "",
            }
        )
    out.sort(key=lambda r: (r["ladder_type"], r["source_group"]))
    return out


def numeric_or(value: object, fallback: float) -> float:
    try:
        if value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def plot_decision(case: dict, rows: list[dict], decision: dict, gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> Path | None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    ladder = case["ladder_type"]
    combos = ["default_quantile_width"]
    if decision["winner_combo"] and decision["winner_combo"] not in combos:
        combos.append(decision["winner_combo"])
    if len(combos) == 1:
        return None
    trace = liz_eval.load_trace(case["raw_path"]) if ladder == "LIZ" else rox_eval.load_trace(case["raw_path"])
    fig, axes = plt.subplots(len(combos), 1, figsize=(16, 5 * len(combos)), sharex=True)
    if len(combos) == 1:
        axes = [axes]
    for ax, combo_name in zip(axes, combos):
        if ladder == "LIZ":
            combo = LIZ_COMBOS[combo_name]
            baseline = liz_methods.BASELINES[combo[0]](trace)
            corrected = np.clip(trace - baseline, 0.0, None)
            smoothed = liz_methods.SMOOTHERS[combo[1]](corrected)
            candidates = liz_methods.DETECTORS[combo[2]](smoothed)
            fit = liz_eval.beam_fit_family(candidates, corrected)
            ymax = 350
            x0 = 1300
        else:
            combo = ROX_COMBOS[combo_name]
            baseline = rox_eval.BASELINES[combo[0]](trace)
            corrected = np.clip(trace - baseline, 0.0, None)
            smoothed = rox_eval.SMOOTHERS[combo[1]](corrected)
            candidates = rox_eval.DETECTORS[combo[2]](smoothed)
            fit = rox_eval.beam_fit_family(candidates, corrected, *gaps)
            ymax = 1000
            x0 = 1200
        ax.plot(corrected, color="black", lw=1.0)
        if candidates.size:
            ax.scatter(candidates, corrected[candidates], s=16, color="royalblue", alpha=0.55)
        title = combo_name
        if fit:
            selected = np.asarray(fit["selected"], dtype=int)
            ax.scatter(selected, corrected[selected], s=34, color="crimson", zorder=3)
            for idx, peak in enumerate(selected):
                ax.text(int(peak), float(corrected[int(peak)]) + 8, str(idx + 1), fontsize=7, color="crimson", ha="center")
            title += f" | max {fit['linear_max']:.2f} mean {fit['linear_mean']:.2f} r2 {fit['linear_r2']:.6f}"
        ax.set_title(title)
        ax.set_xlim(x0, 5000)
        ax.set_ylim(0, ymax)
        ax.grid(alpha=0.2)
    fig.suptitle(f"{decision['label']} | {decision['decision']} | winner {decision['winner_combo']}", fontsize=12)
    fig.tight_layout()
    out = IMAGE_DIR / f"{ladder.lower()}_{decision['label']}_{decision['winner_combo']}.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    rox_template_cases = rox_eval.load_benchmark_cases()
    rox_selected = rox_eval.rust_selected_map(rox_template_cases)
    rox_gaps = rox_eval.gap_template(rox_selected, rox_template_cases)

    detail_rows: list[dict] = []
    decisions: list[dict] = []
    case_by_label: dict[str, dict] = {}
    failures: list[dict] = []
    for case in cases:
        case_by_label[case["label"]] = case
        case_rows: list[dict] = []
        try:
            if case["ladder_type"] == "LIZ":
                for name, combo in LIZ_COMBOS.items():
                    case_rows.append(run_liz(case, name, combo))
            else:
                for name, combo in ROX_COMBOS.items():
                    case_rows.append(run_rox(case, name, combo, rox_gaps))
        except Exception as exc:
            failures.append(
                {
                    "label": case["label"],
                    "raw_path": case["raw_path"],
                    "ladder_type": case["ladder_type"],
                    "source_group": case.get("source_group", ""),
                    "error": repr(exc),
                }
            )
            continue
        detail_rows.extend(case_rows)
        decisions.append(choose_arbiter(case_rows))

    write_tsv(OUT_DIR / "detail.tsv", detail_rows)
    write_tsv(OUT_DIR / "decisions.tsv", decisions)
    write_tsv(OUT_DIR / "aggregate.tsv", aggregate(decisions))
    write_tsv(OUT_DIR / "failures.tsv", failures)

    alt_decisions = [d for d in decisions if d["decision"] == "alt_lane"]
    review_decisions = [d for d in decisions if d["decision"] == "review_required"]
    chosen_for_images = sorted(alt_decisions, key=lambda r: numeric_or(r.get("delta_linear_max"), 0.0))[:8]
    chosen_for_images += sorted(review_decisions, key=lambda r: numeric_or(r.get("winner_linear_max"), -1.0), reverse=True)[:4]
    image_rows = []
    row_groups: dict[str, list[dict]] = defaultdict(list)
    for row in detail_rows:
        row_groups[row["label"]].append(row)
    seen: set[str] = set()
    for decision in chosen_for_images:
        if decision["label"] in seen:
            continue
        seen.add(decision["label"])
        case = case_by_label.get(decision["label"])
        if not case:
            continue
        try:
            image = plot_decision(case, row_groups[decision["label"]], decision, rox_gaps)
        except Exception as exc:
            image_rows.append({"label": decision["label"], "image": "", "error": repr(exc)})
            continue
        if image:
            image_rows.append({"label": decision["label"], "image": str(image), "error": ""})
    write_tsv(OUT_DIR / "image_index.tsv", image_rows)

    manifest = {
        "case_count": len(cases),
        "detail_rows": len(detail_rows),
        "decision_rows": len(decisions),
        "failure_rows": len(failures),
        "decision_counts": Counter(d["decision"] for d in decisions),
        "winner_counts": Counter(d["winner_combo"] for d in decisions),
        "outputs": {
            "detail": str(OUT_DIR / "detail.tsv"),
            "decisions": str(OUT_DIR / "decisions.tsv"),
            "aggregate": str(OUT_DIR / "aggregate.tsv"),
            "failures": str(OUT_DIR / "failures.tsv"),
            "image_index": str(OUT_DIR / "image_index.tsv"),
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(OUT_DIR)
    print(f"cases={len(cases)} decisions={len(decisions)} failures={len(failures)} images={len(image_rows)}")
    print(dict(manifest["decision_counts"]))
    print(dict(manifest["winner_counts"]))


if __name__ == "__main__":
    main()
