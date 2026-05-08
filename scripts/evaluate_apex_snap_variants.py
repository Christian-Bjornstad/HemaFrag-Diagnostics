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
from scripts import fit_arbiter_v2_apex_eval as v2
from scripts import liz_baseline_family_fit_eval as liz_eval
from scripts import liz_genemapper_methods_eval as liz_methods
from scripts import rox_genemapper_methods_eval as rox_eval


OUT_DIR = ROOT / "artifacts" / "apex_snap_variant_eval"
IMAGE_DIR = OUT_DIR / "images"

REVIEW_LABEL_PARTS = [
    "26OUM05318_FR3_290426_A05",
    "26OUM05517_FR1_290426_B02",
    "25OUM16406_KDE__281025_E10",
    "25OUM16351_IGK__281025_C07",
    "25OUM01897_FR3_090426_A06",
    "25OUM01897_FR1_090426_A02",
    "26OUM06086_FR2_290426_D03",
    "25OUM16288_tcrgA__281025_B02",
]

VARIANTS = [
    "none",
    "narrow",
    "wide_blobguard",
    "wide_big_gain",
    "wide_candidate_shape",
    "wide_candidate_shape_linear_guard",
    "wide_pattern_guard",
]


def write_tsv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r.keys()}), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def read_v1_decisions() -> dict[str, dict]:
    path = ROOT / "artifacts" / "fit_arbiter_offline_eval" / "decisions.tsv"
    with path.open(newline="") as fh:
        return {r["label"]: r for r in csv.DictReader(fh, delimiter="\t")}


def fit_quality(row: dict) -> str:
    if not row.get("fit_found"):
        return "no_fit"
    lmax = float(row["linear_max"])
    lmean = float(row["linear_mean"])
    r2 = float(row["linear_r2"])
    if lmax <= 5.0 and lmean <= 2.5 and r2 >= 0.9993:
        return "good"
    if lmax <= 6.0 and lmean <= 5.0 and r2 >= 0.9975:
        return "usable"
    return "review"


def local_prominence(values: np.ndarray, idx: int, radius: int = 12) -> float:
    lo = max(0, idx - radius)
    hi = min(len(values), idx + radius + 1)
    if hi <= lo + 2:
        return 0.0
    left = values[lo : idx + 1]
    right = values[idx:hi]
    if left.size == 0 or right.size == 0:
        return 0.0
    shoulder = max(float(np.min(left)), float(np.min(right)))
    return float(values[idx] - shoulder)


def close_to_candidate(candidates: np.ndarray, idx: int, tolerance: int = 2) -> bool:
    if candidates.size == 0:
        return False
    return bool(np.any(np.abs(candidates.astype(int) - int(idx)) <= tolerance))


def local_gap_ok(ladder: str, candidate: np.ndarray, idx: int, rox_gaps: tuple[np.ndarray, np.ndarray, np.ndarray] | None) -> bool:
    if ladder == "LIZ":
        med = liz_eval.LIZ_GAP_MEDIANS
        p10 = liz_eval.LIZ_GAP_P10
        p90 = liz_eval.LIZ_GAP_P90
        slack = np.maximum(8.0, med * 0.12)
    else:
        if rox_gaps is None:
            return True
        med, p10, p90 = rox_gaps
        slack = np.maximum(7.0, med * 0.14)
    for gap_idx in (idx - 1, idx):
        if gap_idx < 0 or gap_idx >= len(candidate) - 1 or gap_idx >= len(med):
            continue
        gap = float(candidate[gap_idx + 1] - candidate[gap_idx])
        if gap < float(p10[gap_idx] - slack[gap_idx]) or gap > float(p90[gap_idx] + slack[gap_idx]):
            return False
    return True


def snap_selected(
    ladder: str,
    selected: np.ndarray,
    corrected: np.ndarray,
    candidates: np.ndarray,
    variant: str,
    rox_gaps: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> tuple[np.ndarray, dict]:
    current = np.asarray(selected, dtype=int).copy()
    original = current.copy()
    if variant == "none":
        return current, {"changes": [], "change_count": 0, "height_gain": 0.0}

    radius = 9 if ladder == "ROX" else (7 if variant == "narrow" else 24)
    original_lmax, original_lmean, _ = v2.fit_metrics(ladder, original)
    original_heights = np.asarray(corrected[original], dtype=float)
    family_height_ref = float(np.median(original_heights[original_heights > 0])) if np.any(original_heights > 0) else 0.0
    changes: list[dict] = []

    for idx, peak in enumerate(original.tolist()):
        lo = max(0, int(peak) - radius)
        hi = min(len(corrected) - 1, int(peak) + radius)
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
        height_gain = new_h - old_h
        if snapped == int(current[idx]) or height_gain < max(2.0, old_h * 0.03):
            continue
        if ladder == "LIZ" and idx < 4 and family_height_ref > 0.0:
            if new_h > max(5000.0, family_height_ref * 4.0):
                continue
        if variant == "wide_big_gain" and height_gain < max(25.0, old_h * 0.10):
            continue
        if variant in {"wide_candidate_shape", "wide_candidate_shape_linear_guard", "wide_pattern_guard"}:
            if not close_to_candidate(candidates, snapped, tolerance=2):
                continue
            prom = local_prominence(corrected, snapped, radius=12 if ladder == "LIZ" else 8)
            if prom < max(18.0, new_h * 0.04):
                continue
        candidate = current.copy()
        candidate[idx] = snapped
        if idx > 0 and candidate[idx] <= candidate[idx - 1]:
            continue
        if idx + 1 < len(candidate) and candidate[idx] >= candidate[idx + 1]:
            continue
        lmax, lmean, r2 = v2.fit_metrics(ladder, candidate)
        if lmax > 6.0 or lmean > 5.0:
            continue
        if variant == "wide_pattern_guard" and not local_gap_ok(ladder, candidate, idx, rox_gaps):
            continue
        if variant == "wide_candidate_shape_linear_guard" and original_lmax <= 5.0:
            if lmax > original_lmax + 1.25 or lmean > original_lmean + 0.65:
                continue
        current = candidate
        changes.append(
            {
                "index": idx + 1,
                "from": int(peak),
                "to": int(snapped),
                "height_gain": height_gain,
                "linear_max_after": lmax,
                "linear_mean_after": lmean,
                "linear_r2_after": r2,
            }
        )
    return current, {"changes": changes, "change_count": len(changes), "height_gain": float(sum(c["height_gain"] for c in changes))}


def compute_winner_arrays(case: dict, winner_combo: str, rox_gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray, dict | None]:
    if case["ladder_type"] == "LIZ":
        trace = liz_eval.load_trace(case["raw_path"])
        combo = v1.LIZ_COMBOS[winner_combo]
        baseline = liz_methods.BASELINES[combo[0]](trace)
        corrected = np.clip(trace - baseline, 0.0, None)
        smoothed = liz_methods.SMOOTHERS[combo[1]](corrected)
        candidates = liz_methods.DETECTORS[combo[2]](smoothed)
        fit = liz_eval.beam_fit_family(candidates, corrected)
        return corrected, candidates, fit
    trace = rox_eval.load_trace(case["raw_path"])
    combo = v1.ROX_COMBOS[winner_combo]
    baseline = rox_eval.BASELINES[combo[0]](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = rox_eval.SMOOTHERS[combo[1]](corrected)
    candidates = rox_eval.DETECTORS[combo[2]](smoothed)
    fit = rox_eval.beam_fit_family(candidates, corrected, *rox_gaps)
    return corrected, candidates, fit


def run_eval() -> tuple[list[dict], list[dict], list[dict]]:
    cases = v1.load_cases()
    case_by_label = {c["label"]: c for c in cases}
    decisions = read_v1_decisions()
    rox_template_cases = rox_eval.load_benchmark_cases()
    rox_selected = rox_eval.rust_selected_map(rox_template_cases)
    rox_gaps = rox_eval.gap_template(rox_selected, rox_template_cases)

    rows: list[dict] = []
    failures: list[dict] = []
    for label, d in decisions.items():
        case = case_by_label.get(label)
        winner_combo = d.get("winner_combo", "")
        if not case or not winner_combo:
            continue
        try:
            corrected, candidates, fit = compute_winner_arrays(case, winner_combo, rox_gaps)
        except Exception as exc:
            failures.append({"label": label, "file": d.get("file", ""), "error": repr(exc)})
            continue
        if fit is None:
            continue
        selected_original = np.asarray(fit["selected"], dtype=int)
        orig_lmax, orig_lmean, orig_r2 = v2.fit_metrics(case["ladder_type"], selected_original)
        for variant in VARIANTS:
            selected, info = snap_selected(case["ladder_type"], selected_original, corrected, candidates, variant, rox_gaps=rox_gaps)
            lmax, lmean, r2 = v2.fit_metrics(case["ladder_type"], selected)
            heights = corrected[selected]
            row = {
                "label": label,
                "file": d.get("file", ""),
                "raw_path": case["raw_path"],
                "source_group": case.get("source_group", ""),
                "cohort": case.get("cohort", ""),
                "ladder_type": case["ladder_type"],
                "winner_combo": winner_combo,
                "variant": variant,
                "fit_found": True,
                "linear_max": float(lmax),
                "linear_mean": float(lmean),
                "linear_r2": float(r2),
                "original_linear_max": float(orig_lmax),
                "original_linear_mean": float(orig_lmean),
                "original_linear_r2": float(orig_r2),
                "delta_linear_max": float(lmax - orig_lmax),
                "delta_linear_mean": float(lmean - orig_lmean),
                "snap_count": int(info["change_count"]),
                "height_gain": float(info["height_gain"]),
                "selected_below50": int(np.sum(heights < 50.0)),
                "selected_min_h": float(np.min(heights)),
                "selected_median_h": float(np.median(heights)),
                "quality": "",
                "selected": json.dumps([int(x) for x in selected.tolist()]),
                "selected_original": json.dumps([int(x) for x in selected_original.tolist()]),
                "changes": json.dumps(info["changes"]),
            }
            row["quality"] = fit_quality(row)
            rows.append(row)
    return rows, failures, cases


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["ladder_type"], row["variant"])].append(row)
    out = []
    for (ladder, variant), group in groups.items():
        snapped = [r for r in group if int(r["snap_count"]) > 0]
        review = [r for r in group if r["quality"] == "review"]
        over_guard = [r for r in group if float(r["linear_max"]) > 6.0 or float(r["linear_mean"]) > 5.0]
        out.append(
            {
                "ladder_type": ladder,
                "variant": variant,
                "n": len(group),
                "snap_rate": len(snapped) / len(group),
                "review_rate": len(review) / len(group),
                "over_guard_count": len(over_guard),
                "linear_max_mean": float(np.mean([float(r["linear_max"]) for r in group])),
                "linear_mean_mean": float(np.mean([float(r["linear_mean"]) for r in group])),
                "delta_linear_max_mean": float(np.mean([float(r["delta_linear_max"]) for r in group])),
                "delta_linear_mean_mean": float(np.mean([float(r["delta_linear_mean"]) for r in group])),
                "height_gain_mean": float(np.mean([float(r["height_gain"]) for r in group])),
                "worse_max_gt_0_5": int(sum(float(r["delta_linear_max"]) > 0.5 for r in group)),
                "better_max_lt_neg_0_5": int(sum(float(r["delta_linear_max"]) < -0.5 for r in group)),
            }
        )
    out.sort(key=lambda r: (r["ladder_type"], r["variant"]))
    return out


def pick_variant(rows: list[dict]) -> list[dict]:
    by_label: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_label[row["label"]].append(row)
    out = []
    for label, group in by_label.items():
        none = next(r for r in group if r["variant"] == "none")
        usable = [r for r in group if r["quality"] in {"good", "usable"}]
        # Prefer real apex if it gains real height, but do not spend too much
        # linear quality on routine files.
        chosen = max(
            usable or group,
            key=lambda r: (
                int(r["snap_count"] > 0),
                min(2500.0, float(r["height_gain"])) - max(0.0, float(r["delta_linear_max"])) * 450.0,
                -float(r["linear_max"]),
                -float(r["linear_mean"]),
            ),
        )
        out.append(
            {
                "label": label,
                "file": chosen["file"],
                "ladder_type": chosen["ladder_type"],
                "winner_combo": chosen["winner_combo"],
                "chosen_variant": chosen["variant"],
                "linear_max": chosen["linear_max"],
                "linear_mean": chosen["linear_mean"],
                "linear_r2": chosen["linear_r2"],
                "original_linear_max": none["linear_max"],
                "original_linear_mean": none["linear_mean"],
                "delta_linear_max": float(chosen["linear_max"]) - float(none["linear_max"]),
                "delta_linear_mean": float(chosen["linear_mean"]) - float(none["linear_mean"]),
                "snap_count": chosen["snap_count"],
                "height_gain": chosen["height_gain"],
                "quality": chosen["quality"],
                "changes": chosen["changes"],
                "selected": chosen["selected"],
                "selected_original": none["selected_original"],
            }
        )
    out.sort(key=lambda r: (r["ladder_type"], r["file"]))
    return out


def render_review_images(rows: list[dict], chosen_rows: list[dict], cases: list[dict]) -> list[dict]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    case_by_label = {c["label"]: c for c in cases}
    by_label_variant = {(r["label"], r["variant"]): r for r in rows}
    image_rows = []
    labels = [r["label"] for r in chosen_rows if any(part in r["label"] for part in REVIEW_LABEL_PARTS)]
    labels.extend([r["label"] for r in sorted(chosen_rows, key=lambda r: float(r["height_gain"]), reverse=True)[:8]])
    seen = set()
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        case = case_by_label.get(label)
        chosen = next((r for r in chosen_rows if r["label"] == label), None)
        if not case or not chosen:
            continue
        none = by_label_variant.get((label, "none"))
        variant = by_label_variant.get((label, str(chosen["chosen_variant"])))
        if not none or not variant:
            continue
        try:
            if case["ladder_type"] == "LIZ":
                trace = liz_eval.load_trace(case["raw_path"])
                combo = v1.LIZ_COMBOS[chosen["winner_combo"]]
                baseline = liz_methods.BASELINES[combo[0]](trace)
            else:
                trace = rox_eval.load_trace(case["raw_path"])
                combo = v1.ROX_COMBOS[chosen["winner_combo"]]
                baseline = rox_eval.BASELINES[combo[0]](trace)
            corrected = np.clip(trace - baseline, 0.0, None)
            selected_original = np.asarray(json.loads(none["selected"]), dtype=int)
            selected_variant = np.asarray(json.loads(variant["selected"]), dtype=int)
            fig, ax = plt.subplots(figsize=(17, 5.5))
            ax.plot(corrected, color="black", lw=1.0)
            ax.scatter(selected_original, corrected[selected_original], color="orange", marker="x", s=44, label="original")
            ax.scatter(selected_variant, corrected[selected_variant], color="crimson", s=32, label=str(chosen["chosen_variant"]))
            for idx, peak in enumerate(selected_variant):
                ax.text(int(peak), float(corrected[int(peak)]) + max(20.0, np.percentile(corrected, 99.5) * 0.015), str(idx + 1), fontsize=7, ha="center", color="crimson")
            ax.set_xlim(900 if case["ladder_type"] == "ROX" else 1000, 5200)
            vals = corrected[900:5200]
            y_max = min(9000.0 if case["ladder_type"] == "ROX" else 6000.0, max(1000.0, float(np.percentile(vals, 99.7)) * 1.55))
            ax.set_ylim(0, y_max)
            ax.grid(alpha=0.2)
            ax.legend(loc="upper right")
            ax.set_title(
                f"{label} | {chosen['winner_combo']} | {chosen['chosen_variant']} | "
                f"{float(chosen['linear_max']):.2f}/{float(chosen['linear_mean']):.2f}/{float(chosen['linear_r2']):.6f}"
            )
            fig.tight_layout()
            out = IMAGE_DIR / f"{case['ladder_type'].lower()}_{label}_{chosen['chosen_variant']}.png"
            fig.savefig(out, dpi=150)
            plt.close(fig)
            image_rows.append({"label": label, "file": chosen["file"], "variant": chosen["chosen_variant"], "image": str(out), "error": ""})
        except Exception as exc:
            image_rows.append({"label": label, "file": chosen.get("file", ""), "variant": chosen.get("chosen_variant", ""), "image": "", "error": repr(exc)})
    return image_rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, failures, cases = run_eval()
    chosen = pick_variant(rows)
    agg = aggregate(rows)
    image_rows = render_review_images(rows, chosen, cases)
    write_tsv(OUT_DIR / "detail.tsv", rows)
    write_tsv(OUT_DIR / "aggregate.tsv", agg)
    write_tsv(OUT_DIR / "chosen.tsv", chosen)
    write_tsv(OUT_DIR / "image_index.tsv", image_rows)
    write_tsv(OUT_DIR / "failures.tsv", failures)
    manifest = {
        "rows": len(rows),
        "chosen": len(chosen),
        "failures": len(failures),
        "variant_counts": Counter(r["chosen_variant"] for r in chosen),
        "quality_counts": Counter(r["quality"] for r in chosen),
        "outputs": {
            "detail": str(OUT_DIR / "detail.tsv"),
            "aggregate": str(OUT_DIR / "aggregate.tsv"),
            "chosen": str(OUT_DIR / "chosen.tsv"),
            "image_index": str(OUT_DIR / "image_index.tsv"),
            "failures": str(OUT_DIR / "failures.tsv"),
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(OUT_DIR)
    print(f"detail_rows={len(rows)} chosen={len(chosen)} failures={len(failures)} images={len(image_rows)}")
    print(dict(manifest["variant_counts"]))
    print(dict(manifest["quality_counts"]))


if __name__ == "__main__":
    main()
