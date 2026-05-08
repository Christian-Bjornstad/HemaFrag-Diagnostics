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

from scripts import fit_arbiter_offline_eval as arb
from scripts import liz_baseline_family_fit_eval as liz_eval
from scripts import liz_genemapper_methods_eval as liz_methods
from scripts import rox_genemapper_methods_eval as rox_eval


SRC_DIR = ROOT / "artifacts" / "fit_arbiter_offline_eval"
OUT_DIR = SRC_DIR / "images_less_zoom"


def read_tsv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def selected_labels() -> list[str]:
    labels = [r["label"] for r in read_tsv(SRC_DIR / "image_index.tsv") if r.get("label")]
    review_labels = [r["label"] for r in read_tsv(SRC_DIR / "decisions.tsv") if r.get("decision") == "review_required"]
    out: list[str] = []
    seen: set[str] = set()
    for label in labels + review_labels:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def arrays_for(ladder: str, trace: np.ndarray, combo_name: str, gaps: tuple[np.ndarray, np.ndarray, np.ndarray]):
    if ladder == "LIZ":
        combo = arb.LIZ_COMBOS[combo_name]
        baseline = liz_methods.BASELINES[combo[0]](trace)
        corrected = np.clip(trace - baseline, 0.0, None)
        smoothed = liz_methods.SMOOTHERS[combo[1]](corrected)
        candidates = liz_methods.DETECTORS[combo[2]](smoothed)
        fit = liz_eval.beam_fit_family(candidates, corrected)
        return corrected, candidates, fit
    combo = arb.ROX_COMBOS[combo_name]
    baseline = rox_eval.BASELINES[combo[0]](trace)
    corrected = np.clip(trace - baseline, 0.0, None)
    smoothed = rox_eval.SMOOTHERS[combo[1]](corrected)
    candidates = rox_eval.DETECTORS[combo[2]](smoothed)
    fit = rox_eval.beam_fit_family(candidates, corrected, *gaps)
    return corrected, candidates, fit


def dynamic_ylim(arrays: list[np.ndarray], ladder: str) -> float:
    vals = np.concatenate([a[1000:5200] for a in arrays if a.size > 1100])
    if vals.size == 0:
        return 1000.0
    q = float(np.percentile(vals, 99.7))
    mx = float(np.max(vals))
    floor = 900.0 if ladder == "LIZ" else 1800.0
    cap = 6000.0 if ladder == "LIZ" else 9000.0
    return min(cap, max(floor, min(mx * 1.08, q * 1.6)))


def plot_case(case: dict, decision: dict, gaps: tuple[np.ndarray, np.ndarray, np.ndarray]) -> Path | None:
    ladder = case["ladder_type"]
    winner = decision.get("winner_combo")
    if not winner:
        return None
    combos = ["default_quantile_width"]
    if winner not in combos:
        combos.append(winner)
    trace = liz_eval.load_trace(case["raw_path"]) if ladder == "LIZ" else rox_eval.load_trace(case["raw_path"])
    computed = [(name, *arrays_for(ladder, trace, name, gaps)) for name in combos]
    y_max = dynamic_ylim([item[1] for item in computed], ladder)
    fig, axes = plt.subplots(len(computed), 1, figsize=(17, 5.2 * len(computed)), sharex=True)
    if len(computed) == 1:
        axes = [axes]
    for ax, (combo_name, corrected, candidates, fit) in zip(axes, computed):
        ax.plot(corrected, color="black", lw=1.0)
        if candidates.size:
            ax.scatter(candidates, corrected[candidates], s=16, color="royalblue", alpha=0.55, label=f"possible {len(candidates)}")
        metrics = "no fit"
        if fit:
            selected = np.asarray(fit["selected"], dtype=int)
            ax.scatter(selected, corrected[selected], s=34, color="crimson", zorder=3, label="selected")
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{ladder.lower()}_{decision['label']}_{winner}_less_zoom.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> None:
    decisions = {r["label"]: r for r in read_tsv(SRC_DIR / "decisions.tsv")}
    cases = {c["label"]: c for c in arb.load_cases()}
    rox_template_cases = rox_eval.load_benchmark_cases()
    rox_selected = rox_eval.rust_selected_map(rox_template_cases)
    rox_gaps = rox_eval.gap_template(rox_selected, rox_template_cases)
    rows = []
    for label in selected_labels():
        case = cases.get(label)
        decision = decisions.get(label)
        if not case or not decision:
            continue
        try:
            image = plot_case(case, decision, rox_gaps)
            if image:
                rows.append({"label": label, "decision": decision["decision"], "winner_combo": decision["winner_combo"], "image": str(image), "error": ""})
        except Exception as exc:
            rows.append({"label": label, "decision": decision.get("decision", ""), "winner_combo": decision.get("winner_combo", ""), "image": "", "error": repr(exc)})
    with (SRC_DIR / "image_index_less_zoom.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["label", "decision", "winner_combo", "image", "error"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(SRC_DIR / "image_index_less_zoom.tsv")
    print(f"images={sum(1 for r in rows if r['image'])} errors={sum(1 for r in rows if r['error'])}")


if __name__ == "__main__":
    main()
