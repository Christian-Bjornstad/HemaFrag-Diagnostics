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

from scripts import fit_arbiter_offline_eval as v1
from scripts import liz_baseline_family_fit_eval as liz_eval
from scripts import liz_genemapper_methods_eval as liz_methods
from scripts import rox_genemapper_methods_eval as rox_eval


OUT_DIR = ROOT / "artifacts" / "fit_arbiter_v2_apex_eval"
IMAGE_DIR = OUT_DIR / "images_less_zoom"

USER_REVIEW_LABEL_PARTS = [
    "26OUM05318_FR3_290426_A05",
    "26OUM05517_FR1_290426_B02",
    "25OUM16406_KDE__281025_E10",
    "25OUM16351_IGK__281025_C07",
    "25OUM01897_FR3_090426_A06",
    "25OUM01897_FR1_090426_A02",
    "26OUM06086_FR2_290426_D03",
]


def apex_snap_radius(ladder: str) -> int:
    # LIZ has a few flank/baseline selections around the 139/150/160 and
    # 490/500 clusters where the real apex can sit ~15-20 scans away. ROX is
    # kept tighter because it has 10 bp ladder gaps and sharper peaks.
    return 24 if ladder == "LIZ" else 9


def fit_metrics(ladder: str, selected: np.ndarray) -> tuple[float, float, float]:
    if ladder == "LIZ":
        return liz_eval.fit_linear_metrics(selected.astype(float))
    return rox_eval.fit_linear_metrics(selected.astype(float))


def accepted_peak_snap(
    ladder: str,
    selected: np.ndarray,
    corrected: np.ndarray,
    radius: int,
) -> tuple[np.ndarray, dict]:
    current = np.asarray(selected, dtype=int).copy()
    original = current.copy()
    original_heights = np.asarray(corrected[original], dtype=float)
    family_height_ref = float(np.median(original_heights[original_heights > 0])) if np.any(original_heights > 0) else 0.0
    changes: list[dict] = []
    for idx, peak in enumerate(original.tolist()):
        lo = max(0, peak - radius)
        hi = min(len(corrected) - 1, peak + radius)
        if idx > 0:
            lo = max(lo, int(current[idx - 1]) + 1)
        if idx + 1 < len(original):
            hi = min(hi, int(original[idx + 1]) - 1)
        if hi <= lo:
            continue
        local = np.asarray(corrected[lo : hi + 1], dtype=float)
        snapped = int(lo + int(np.argmax(local)))
        old_h = float(corrected[int(current[idx])])
        new_h = float(corrected[snapped])
        if snapped == int(current[idx]) or new_h < old_h + max(2.0, old_h * 0.03):
            continue
        if ladder == "LIZ" and idx < 4 and family_height_ref > 0.0:
            # Do not let early LIZ anchors snap into the injection/blob front.
            # Real 35/50/75/100 peaks should broadly resemble the family, not
            # become a huge outlier just because the local apex is taller.
            if new_h > max(5000.0, family_height_ref * 4.0):
                continue
        candidate = current.copy()
        candidate[idx] = snapped
        if idx > 0 and candidate[idx] <= candidate[idx - 1]:
            continue
        if idx + 1 < len(candidate) and candidate[idx] >= candidate[idx + 1]:
            continue
        lmax, lmean, r2 = fit_metrics(ladder, candidate)
        # User preference: real apex can win even if linears get slightly worse,
        # but do not let apex snapping create a poor ladder.
        if lmax <= 6.0 and lmean <= 5.0:
            current = candidate
            changes.append(
                {
                    "index": idx + 1,
                    "from": int(peak),
                    "to": int(snapped),
                    "height_gain": new_h - old_h,
                    "linear_max_after": lmax,
                    "linear_mean_after": lmean,
                    "linear_r2_after": r2,
                }
            )
    total_gain = float(sum(c["height_gain"] for c in changes))
    return current, {"changes": changes, "change_count": len(changes), "height_gain": total_gain}


def row_from_fit_v2(
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

    selected_original = np.asarray(fit["selected"], dtype=int)
    radius = apex_snap_radius(case["ladder_type"])
    selected, snap_info = accepted_peak_snap(case["ladder_type"], selected_original, corrected, radius=radius)
    lmax, lmean, r2 = fit_metrics(case["ladder_type"], selected)
    heights = corrected[selected]
    original_heights = corrected[selected_original]
    row.update(
        {
            "linear_max": float(lmax),
            "linear_mean": float(lmean),
            "linear_r2": float(r2),
            "original_linear_max": float(fit["linear_max"]),
            "original_linear_mean": float(fit["linear_mean"]),
            "original_linear_r2": float(fit["linear_r2"]),
            "selected": json.dumps([int(x) for x in selected.tolist()]),
            "selected_original": json.dumps([int(x) for x in selected_original.tolist()]),
            "selected_first": int(selected[0]),
            "selected_last": int(selected[-1]),
            "selected_min_h": float(np.min(heights)),
            "selected_median_h": float(np.median(heights)),
            "selected_below30": int(np.sum(heights < 30.0)),
            "selected_below50": int(np.sum(heights < 50.0)),
            "selected_below80": int(np.sum(heights < 80.0)),
            "original_selected_min_h": float(np.min(original_heights)),
            "original_selected_median_h": float(np.median(original_heights)),
            "apex_snap_count": int(snap_info["change_count"]),
            "apex_snap_height_gain": float(snap_info["height_gain"]),
            "apex_snap_changes": json.dumps(snap_info["changes"]),
        }
    )
    row["plausibility_penalty"] = v1.plausibility_penalty(row)
    row["arbiter_score"] = arbiter_score_v2(row)
    return row


def arbiter_score_v2(row: dict) -> float:
    if not row.get("fit_found"):
        return 9999.0
    real_peak_bonus = min(1.75, float(row.get("apex_snap_height_gain", 0.0)) / 90.0)
    snap_bonus = min(0.7, float(row.get("apex_snap_count", 0)) * 0.12)
    return (
        float(row["linear_max"])
        + 0.65 * float(row["linear_mean"])
        - 8.0 * max(0.0, float(row["linear_r2"]) - 0.999)
        + 0.95 * float(row.get("plausibility_penalty", 0.0))
        - real_peak_bonus
        - snap_bonus
    )


def fit_quality_v2(row: dict) -> str:
    if not row.get("fit_found"):
        return "no_fit"
    lmax = float(row["linear_max"])
    lmean = float(row["linear_mean"])
    r2 = float(row["linear_r2"])
    plaus = float(row.get("plausibility_penalty", 999.0))
    if lmax <= 5.0 and lmean <= 2.5 and r2 >= 0.9993 and plaus <= 3.0:
        return "good"
    if lmax <= 6.0 and lmean <= 5.0 and r2 >= 0.9975 and plaus <= 5.2:
        return "usable"
    return "review"


def run_liz(case: dict, combo_name: str, combo: tuple[str, str, str]) -> dict:
    baseline_name, smoother_name, detector_name = combo
    trace = liz_eval.load_trace(case["raw_path"])
    baseline = liz_methods.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = liz_methods.SMOOTHERS[smoother_name](corrected)
    candidates = liz_methods.DETECTORS[detector_name](smoothed)
    fit = liz_eval.beam_fit_family(candidates, corrected)
    return row_from_fit_v2(case, combo_name, baseline_name, smoother_name, detector_name, candidates, corrected, fit)


def run_rox(case: dict, combo_name: str, combo: tuple[str, str, str], gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> dict:
    baseline_name, smoother_name, detector_name = combo
    trace = rox_eval.load_trace(case["raw_path"])
    baseline = rox_eval.BASELINES[baseline_name](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = rox_eval.SMOOTHERS[smoother_name](corrected)
    candidates = rox_eval.DETECTORS[detector_name](smoothed)
    fit = rox_eval.beam_fit_family(candidates, corrected, *gaps)
    return row_from_fit_v2(case, combo_name, baseline_name, smoother_name, detector_name, candidates, corrected, fit)


def choose_arbiter_v2(case_rows: list[dict], previous_decision: dict | None = None) -> dict:
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
    prior_combo = (previous_decision or {}).get("winner_combo") or ""
    prior_decision = (previous_decision or {}).get("decision") or ""
    prior_row = next((r for r in found if r["combo"] == prior_combo), None)
    default_quality = fit_quality_v2(default) if default else "no_fit"

    # V2 is intentionally sticky to the first arbiter pass: the new behavior is
    # local apex re-centering, not broad lane replacement on already accepted
    # files. Lane competition is reserved for unresolved/review cases.
    if prior_row is not None and prior_decision in {"keep_default_good", "keep_default_close", "alt_lane", "review_required"}:
        chosen = prior_row
        quality = fit_quality_v2(chosen)
        if prior_decision == "review_required":
            if quality == "review":
                decision = "review_required"
            else:
                decision = "alt_lane" if chosen["combo"] != "default_quantile_width" else "keep_default_close"
        else:
            decision = prior_decision
            # Do not create a new review on a previously accepted unchanged fit.
            # The max<=6/mean<=5 guard is for accepting apex movement, not for
            # retroactively rejecting v1 close calls.
            if quality == "review":
                quality = "usable"
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
            "winner_original_linear_max": float(chosen.get("original_linear_max", chosen["linear_max"])),
            "winner_original_linear_mean": float(chosen.get("original_linear_mean", chosen["linear_mean"])),
            "winner_plausibility_penalty": float(chosen.get("plausibility_penalty", 0.0)),
            "winner_selected_below50": int(chosen.get("selected_below50", 0)),
            "winner_apex_snap_count": int(chosen.get("apex_snap_count", 0)),
            "winner_apex_snap_height_gain": float(chosen.get("apex_snap_height_gain", 0.0)),
            "winner_apex_snap_changes": chosen.get("apex_snap_changes", "[]"),
            "winner_selected": chosen.get("selected", "[]"),
            "winner_selected_original": chosen.get("selected_original", "[]"),
            "default_quality": default_quality,
            "default_linear_max": float(default["linear_max"]) if default else "",
            "default_linear_mean": float(default["linear_mean"]) if default else "",
            "default_linear_r2": float(default["linear_r2"]) if default else "",
            "default_original_linear_max": float(default.get("original_linear_max", default["linear_max"])) if default else "",
            "default_original_linear_mean": float(default.get("original_linear_mean", default["linear_mean"])) if default else "",
            "default_plausibility_penalty": float(default.get("plausibility_penalty", 0.0)) if default else "",
            "default_apex_snap_count": int(default.get("apex_snap_count", 0)) if default else "",
            "delta_linear_max": float(chosen["linear_max"]) - float(default["linear_max"]) if default else "",
            "delta_linear_mean": float(chosen["linear_mean"]) - float(default["linear_mean"]) if default else "",
        }

    ranked = sorted(found, key=lambda r: (float(r["arbiter_score"]), float(r["linear_max"]), float(r["linear_mean"])))
    best = ranked[0]
    chosen = prior_row or (default if default is not None and default_quality == "good" else best)
    decision = prior_decision if prior_decision else ("alt_lane" if chosen["combo"] != "default_quantile_width" else "keep_default_close")
    if not prior_decision and chosen is default and default_quality == "good":
        decision = "keep_default_good"
    chosen_quality_before_challenge = fit_quality_v2(chosen)
    # Conservative lane override: apex-snapping should mostly correct the chosen
    # family, not promote a different baseline/detector on otherwise good files.
    for challenger in ranked:
        if challenger["combo"] == chosen["combo"]:
            continue
        if fit_quality_v2(challenger) not in {"good", "usable"}:
            continue
        if float(challenger["linear_max"]) > 6.0 or float(challenger["linear_mean"]) > 5.0:
            continue
        linear_win = float(challenger["linear_max"]) <= float(chosen["linear_max"]) - 1.25
        plaus_win = float(challenger.get("plausibility_penalty", 0.0)) <= float(chosen.get("plausibility_penalty", 0.0)) - 1.25
        apex_win = (
            float(challenger.get("apex_snap_height_gain", 0.0)) >= float(chosen.get("apex_snap_height_gain", 0.0)) + 120.0
            and float(challenger["linear_max"]) <= float(chosen["linear_max"]) + 0.35
            and float(challenger["linear_mean"]) <= float(chosen["linear_mean"]) + 0.25
        )
        if chosen_quality_before_challenge == "review" or linear_win or plaus_win or apex_win:
            chosen = challenger
            decision = "alt_lane" if challenger["combo"] != "default_quantile_width" else "keep_default_close"
            break
    quality = fit_quality_v2(chosen)
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
        "winner_original_linear_max": float(chosen.get("original_linear_max", chosen["linear_max"])),
        "winner_original_linear_mean": float(chosen.get("original_linear_mean", chosen["linear_mean"])),
        "winner_plausibility_penalty": float(chosen.get("plausibility_penalty", 0.0)),
        "winner_selected_below50": int(chosen.get("selected_below50", 0)),
        "winner_apex_snap_count": int(chosen.get("apex_snap_count", 0)),
        "winner_apex_snap_height_gain": float(chosen.get("apex_snap_height_gain", 0.0)),
        "winner_apex_snap_changes": chosen.get("apex_snap_changes", "[]"),
        "winner_selected": chosen.get("selected", "[]"),
        "winner_selected_original": chosen.get("selected_original", "[]"),
        "default_quality": default_quality,
        "default_linear_max": float(default["linear_max"]) if default else "",
        "default_linear_mean": float(default["linear_mean"]) if default else "",
        "default_linear_r2": float(default["linear_r2"]) if default else "",
        "default_original_linear_max": float(default.get("original_linear_max", default["linear_max"])) if default else "",
        "default_original_linear_mean": float(default.get("original_linear_mean", default["linear_mean"])) if default else "",
        "default_plausibility_penalty": float(default.get("plausibility_penalty", 0.0)) if default else "",
        "default_apex_snap_count": int(default.get("apex_snap_count", 0)) if default else "",
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
        snapped = [r for r in group if int(r.get("winner_apex_snap_count") or 0) > 0]
        out.append(
            {
                "ladder_type": ladder,
                "source_group": source,
                "n": len(group),
                "usable_rate": len(usable) / len(group),
                "alt_lane_rate": len(alt) / len(group),
                "review_rate": len(review) / len(group),
                "winner_snap_rate": len(snapped) / len(group),
                "winner_linear_max_mean": float(np.mean([float(r["winner_linear_max"]) for r in usable])) if usable else "",
                "winner_linear_mean_mean": float(np.mean([float(r["winner_linear_mean"]) for r in usable])) if usable else "",
            }
        )
    out.sort(key=lambda r: (r["ladder_type"], r["source_group"]))
    return out


def read_previous_decisions() -> dict[str, dict]:
    path = ROOT / "artifacts" / "fit_arbiter_offline_eval" / "decisions.tsv"
    if not path.exists():
        return {}
    with path.open(newline="") as fh:
        return {r["label"]: r for r in csv.DictReader(fh, delimiter="\t")}


def plot_case(case: dict, rows: list[dict], decision: dict, gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> Path | None:
    winner = decision.get("winner_combo")
    if not winner:
        return None
    ladder = case["ladder_type"]
    combos = ["default_quantile_width"]
    if winner not in combos:
        combos.append(winner)
    trace = liz_eval.load_trace(case["raw_path"]) if ladder == "LIZ" else rox_eval.load_trace(case["raw_path"])
    computed = []
    for combo_name in combos:
        if ladder == "LIZ":
            combo = v1.LIZ_COMBOS[combo_name]
            baseline = liz_methods.BASELINES[combo[0]](trace)
            corrected = np.clip(trace - baseline, 0.0, None)
            smoothed = liz_methods.SMOOTHERS[combo[1]](corrected)
            candidates = liz_methods.DETECTORS[combo[2]](smoothed)
            fit = liz_eval.beam_fit_family(candidates, corrected)
        else:
            combo = v1.ROX_COMBOS[combo_name]
            baseline = rox_eval.BASELINES[combo[0]](trace)
            corrected = np.clip(trace - baseline, 0.0, None)
            smoothed = rox_eval.SMOOTHERS[combo[1]](corrected)
            candidates = rox_eval.DETECTORS[combo[2]](smoothed)
            fit = rox_eval.beam_fit_family(candidates, corrected, *gaps)
        if fit is None:
            computed.append((combo_name, corrected, candidates, None, None))
            continue
        selected_original = np.asarray(fit["selected"], dtype=int)
        selected, snap_info = accepted_peak_snap(ladder, selected_original, corrected, radius=apex_snap_radius(ladder))
        lmax, lmean, r2 = fit_metrics(ladder, selected)
        computed.append((combo_name, corrected, candidates, {"selected": selected, "linear_max": lmax, "linear_mean": lmean, "linear_r2": r2}, selected_original))
    vals = np.concatenate([item[1][900:5400] for item in computed if item[1].size > 1000])
    y_max = min(9000.0 if ladder == "ROX" else 6000.0, max(900.0 if ladder == "LIZ" else 1800.0, float(np.percentile(vals, 99.7)) * 1.6))
    fig, axes = plt.subplots(len(computed), 1, figsize=(17, 5.2 * len(computed)), sharex=True)
    if len(computed) == 1:
        axes = [axes]
    for ax, (combo_name, corrected, candidates, fit, selected_original) in zip(axes, computed):
        ax.plot(corrected, color="black", lw=1.0)
        if candidates.size:
            ax.scatter(candidates, corrected[candidates], s=16, color="royalblue", alpha=0.5, label=f"possible {len(candidates)}")
        metrics = "no fit"
        if fit:
            selected = np.asarray(fit["selected"], dtype=int)
            if selected_original is not None:
                ax.scatter(selected_original, corrected[selected_original], s=44, marker="x", color="orange", zorder=3, label="original selected")
            ax.scatter(selected, corrected[selected], s=34, color="crimson", zorder=4, label="apex selected")
            for idx, peak in enumerate(selected):
                ax.text(int(peak), float(corrected[int(peak)]) + y_max * 0.015, str(idx + 1), fontsize=7, color="crimson", ha="center")
            metrics = f"max {fit['linear_max']:.2f} mean {fit['linear_mean']:.2f} r2 {fit['linear_r2']:.6f}"
        ax.set_title(f"{combo_name} | {metrics}")
        ax.set_xlim(900, 5400)
        ax.set_ylim(0, y_max)
        ax.grid(alpha=0.2)
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle(f"{decision['label']} | {decision['decision']} | winner {winner}", fontsize=12)
    fig.tight_layout()
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = IMAGE_DIR / f"{ladder.lower()}_{decision['label']}_{winner}_v2_apex.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = v1.load_cases()
    case_by_label = {c["label"]: c for c in cases}
    previous = read_previous_decisions()
    rox_template_cases = rox_eval.load_benchmark_cases()
    rox_selected = rox_eval.rust_selected_map(rox_template_cases)
    rox_gaps = rox_eval.gap_template(rox_selected, rox_template_cases)

    detail_rows: list[dict] = []
    decisions: list[dict] = []
    failures: list[dict] = []
    grouped_rows: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        case_rows: list[dict] = []
        try:
            if case["ladder_type"] == "LIZ":
                for name, combo in v1.LIZ_COMBOS.items():
                    case_rows.append(run_liz(case, name, combo))
            else:
                for name, combo in v1.ROX_COMBOS.items():
                    case_rows.append(run_rox(case, name, combo, rox_gaps))
        except Exception as exc:
            failures.append({"label": case["label"], "raw_path": case["raw_path"], "ladder_type": case["ladder_type"], "source_group": case.get("source_group", ""), "error": repr(exc)})
            continue
        detail_rows.extend(case_rows)
        grouped_rows[case["label"]] = case_rows
        decision = choose_arbiter_v2(case_rows, previous.get(case["label"]))
        prev = previous.get(case["label"])
        if prev:
            decision["v1_decision"] = prev.get("decision", "")
            decision["v1_winner_combo"] = prev.get("winner_combo", "")
            decision["v1_winner_linear_max"] = prev.get("winner_linear_max", "")
            decision["v1_winner_linear_mean"] = prev.get("winner_linear_mean", "")
        decisions.append(decision)

    write_tsv(OUT_DIR / "detail.tsv", detail_rows)
    write_tsv(OUT_DIR / "decisions.tsv", decisions)
    write_tsv(OUT_DIR / "aggregate.tsv", aggregate(decisions))
    write_tsv(OUT_DIR / "failures.tsv", failures)

    labels_for_images: list[str] = []
    for part in USER_REVIEW_LABEL_PARTS:
        labels_for_images.extend([d["label"] for d in decisions if part in d["label"]])
    snapped = sorted([d for d in decisions if int(d.get("winner_apex_snap_count") or 0) > 0], key=lambda r: float(r["winner_apex_snap_height_gain"]), reverse=True)
    labels_for_images.extend([d["label"] for d in snapped[:8]])
    labels_for_images.extend([d["label"] for d in decisions if d["decision"] == "review_required"])
    image_rows = []
    seen: set[str] = set()
    for label in labels_for_images:
        if label in seen:
            continue
        seen.add(label)
        case = case_by_label.get(label)
        decision = next((d for d in decisions if d["label"] == label), None)
        if not case or not decision:
            continue
        try:
            image = plot_case(case, grouped_rows[label], decision, rox_gaps)
            if image:
                image_rows.append({"label": label, "decision": decision["decision"], "winner_combo": decision["winner_combo"], "snap_count": decision.get("winner_apex_snap_count", ""), "image": str(image), "error": ""})
        except Exception as exc:
            image_rows.append({"label": label, "decision": decision.get("decision", ""), "winner_combo": decision.get("winner_combo", ""), "snap_count": decision.get("winner_apex_snap_count", ""), "image": "", "error": repr(exc)})
    write_tsv(OUT_DIR / "image_index.tsv", image_rows)

    manifest = {
        "case_count": len(cases),
        "detail_rows": len(detail_rows),
        "decision_rows": len(decisions),
        "failure_rows": len(failures),
        "decision_counts": Counter(d["decision"] for d in decisions),
        "winner_counts": Counter(d["winner_combo"] for d in decisions),
        "snapped_winner_count": sum(1 for d in decisions if int(d.get("winner_apex_snap_count") or 0) > 0),
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
    print(f"snapped_winner_count={manifest['snapped_winner_count']}")


if __name__ == "__main__":
    main()
