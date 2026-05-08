from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_RESULTS = ROOT / "artifacts" / "ladder_manifest_delta_eval_manual_2026-05-05" / "case_results.tsv"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "ladder_delta_triage_manual_2026-05-05"


OUT_FIELDS = [
    "priority",
    "triage_class",
    "recommended_action",
    "rationale",
    "file",
    "full_path",
    "assay",
    "ladder",
    "expected_use",
    "learning_category",
    "review_label",
    "current_review",
    "current_primary_reason",
    "current_linear_max",
    "current_linear_mean",
    "current_linear_r2",
    "current_quadratic_max",
    "current_quadratic_mean",
    "current_quadratic_r2",
    "current_complete_qc_ok",
    "reference_source",
    "reference_changed_steps",
    "reference_max_abs_delta",
    "reference_mean_abs_delta",
    "selected_count",
    "expected_count",
]


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_float(value: object) -> float:
    raw = text(value)
    if not raw:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def to_int(value: object) -> int:
    raw = text(value)
    if not raw:
        return 0
    try:
        return int(round(float(raw)))
    except ValueError:
        return 0


def to_bool(value: object) -> bool:
    return text(value).lower() in {"1", "true", "yes", "y"}


def is_bad_linear(linear_max: float, linear_mean: float, linear_r2: float) -> bool:
    return (
        (not math.isnan(linear_max) and linear_max > 6.0)
        or (not math.isnan(linear_mean) and linear_mean > 3.0)
        or (not math.isnan(linear_r2) and linear_r2 < 0.999)
    )


def is_severe_linear(linear_max: float, linear_mean: float, linear_r2: float) -> bool:
    return (
        (not math.isnan(linear_max) and linear_max > 10.0)
        or (not math.isnan(linear_mean) and linear_mean > 4.5)
        or (not math.isnan(linear_r2) and linear_r2 < 0.9985)
    )


def priority(rank: int) -> str:
    return f"P{rank}"


def classify(row: dict[str, str]) -> dict[str, Any]:
    expected_use = text(row.get("expected_use"))
    learning_category = text(row.get("learning_category"))
    ref_source = text(row.get("reference_source"))
    changed_steps = to_int(row.get("reference_changed_steps"))
    max_delta = to_float(row.get("reference_max_abs_delta"))
    linear_max = to_float(row.get("current_linear_max"))
    linear_mean = to_float(row.get("current_linear_mean"))
    linear_r2 = to_float(row.get("current_linear_r2"))
    quadratic_max = to_float(row.get("current_quadratic_max"))
    quadratic_mean = to_float(row.get("current_quadratic_mean"))
    quadratic_r2 = to_float(row.get("current_quadratic_r2"))
    complete_ok = to_bool(row.get("current_complete_qc_ok"))
    current_review = to_bool(row.get("current_review"))
    ok = to_bool(row.get("ok"))
    bad_linear = is_bad_linear(linear_max, linear_mean, linear_r2)
    severe_linear = is_severe_linear(linear_max, linear_mean, linear_r2)
    big_shift = changed_steps >= 8 or (not math.isnan(max_delta) and max_delta >= 100.0)
    minor_shift = changed_steps > 0
    qc_text = (
        f"linear max {linear_max:.2f}, mean {linear_mean:.2f}, r2 {linear_r2:.6f}; "
        f"quadratic max {quadratic_max:.2f}, mean {quadratic_mean:.2f}, r2 {quadratic_r2:.6f}; "
        f"complete_qc={complete_ok}"
    )
    delta_text = (
        f"{changed_steps} changed steps vs {ref_source}, max scan delta {max_delta:.0f}"
        if ref_source and not math.isnan(max_delta)
        else f"{changed_steps} changed steps vs {ref_source or 'no reference'}"
    )

    if not ok:
        return {
            "priority": priority(0),
            "triage_class": "run_error",
            "recommended_action": "Fix analysis/runtime error before using this row for motor learning.",
            "rationale": text(row.get("error")) or "analysis failed",
        }

    if expected_use == "non_regression_control":
        if ref_source == "invalid_manifest_selected":
            return {
                "priority": priority(2),
                "triage_class": "data_quality_invalid_reference",
                "recommended_action": "Refresh reference selected peaks before interpreting this as a regression.",
                "rationale": "Manifest had non-scan selected indices; current fit should not be penalized against them.",
            }
        if minor_shift:
            if complete_ok and ref_source != "manual_adjustment" and not current_review:
                return {
                    "priority": priority(3),
                    "triage_class": "stale_reference_complete_qc_control",
                    "recommended_action": "Refresh the stored control reference if needed; current complete-QC fit is acceptable and should not drive motor changes.",
                    "rationale": f"{delta_text}; {qc_text}.",
                }
            rank = 2 if complete_ok and not big_shift and not current_review else (1 if big_shift or severe_linear else 2)
            triage_class = "control_selection_instability_complete_qc" if complete_ok and not current_review else "control_selection_instability"
            return {
                "priority": priority(rank),
                "triage_class": triage_class,
                "recommended_action": "Open visually before changing the motor; complete QC makes this a watch/control issue, not a broad motor trigger."
                if complete_ok and not current_review
                else "Open visually before changing the motor; this is a reviewed-no-change control but selected scans moved.",
                "rationale": f"{delta_text}; {qc_text}.",
            }
        if current_review or bad_linear:
            if complete_ok and not current_review:
                return {
                    "priority": priority(3),
                    "triage_class": "accepted_complete_qc_control",
                    "recommended_action": "Keep as non-regression/QC tolerance control; no motor work unless visual review shows wrong peaks.",
                    "rationale": f"Selection is stable and complete-QC is acceptable despite linear-only thresholds: {qc_text}.",
                }
            rank = 1 if current_review or severe_linear else 2
            return {
                "priority": priority(rank),
                "triage_class": "qc_tolerance_review_gate",
                "recommended_action": "Treat mainly as QC/review-gate calibration unless visual inspection shows wrong peaks.",
                "rationale": f"Selection is stable but QC/review is hard: {qc_text}; review={current_review}.",
            }
        return {
            "priority": priority(3),
            "triage_class": "stable_non_regression_control",
            "recommended_action": "Keep as non-regression control.",
            "rationale": f"Stable selected peaks and acceptable QC: {qc_text}.",
        }

    if expected_use == "training_pair":
        if ref_source != "manual_adjustment":
            return {
                "priority": priority(2),
                "triage_class": "training_pair_missing_manual_reference",
                "recommended_action": "Do not use for supervised peak learning until `.ladder_adj.json` is available.",
                "rationale": f"Reference source is {ref_source or 'empty'}.",
            }
        if not minor_shift:
            if current_review or bad_linear:
                if complete_ok and not current_review:
                    return {
                        "priority": priority(3),
                        "triage_class": "accepted_complete_qc_manual_match",
                        "recommended_action": "Use as resolved control; current peaks match manual and complete-QC is acceptable despite linear-only thresholds.",
                        "rationale": f"Manual scans match and complete-QC is acceptable: {qc_text}.",
                    }
                rank = 1 if current_review or severe_linear else 2
                return {
                    "priority": priority(rank),
                    "triage_class": "qc_tolerance_manual_match",
                    "recommended_action": "Do not tune peak selection; current peaks match manual. Calibrate QC/review thresholds or accepted-hardcase labels.",
                    "rationale": f"Manual scans match, but QC/review remains hard: {qc_text}; review={current_review}.",
                }
            return {
                "priority": priority(3),
                "triage_class": "manual_match_resolved",
                "recommended_action": "Use as resolved control.",
                "rationale": f"Current selected peaks match manual and QC is acceptable: {qc_text}.",
            }
        if learning_category == "blob_baseline_peak_selection":
            rank = 2 if complete_ok and not big_shift and not severe_linear and not current_review else (0 if severe_linear or big_shift else 1)
            triage_class = "engine_learning_blob_baseline_complete_qc_watch" if rank == 2 else "engine_learning_blob_baseline"
            return {
                "priority": priority(rank),
                "triage_class": triage_class,
                "recommended_action": "Keep as bounded visual watch; complete-QC is acceptable, so only tune if visual review confirms wrong peaks."
                if rank == 2
                else "Target candidate plausibility/start-after-blob logic; do not solve with QC tolerance alone.",
                "rationale": f"{delta_text}; {qc_text}.",
            }
        if learning_category == "major_peak_selection_shift":
            rank = 2 if complete_ok and not big_shift and not severe_linear and not current_review else (0 if severe_linear or big_shift else 1)
            triage_class = "engine_learning_major_sequence_complete_qc_watch" if rank == 2 else "engine_learning_major_sequence"
            return {
                "priority": priority(rank),
                "triage_class": triage_class,
                "recommended_action": "Keep as bounded visual watch; complete-QC is acceptable, so do not tune sequence logic from this row alone."
                if rank == 2
                else "Target sequence/anchor selection, including tail-to-front or family-pattern repair.",
                "rationale": f"{delta_text}; {qc_text}.",
            }
        if learning_category == "minor_peak_selection_shift":
            rank = 2 if complete_ok and not severe_linear and not current_review else (1 if severe_linear or (not math.isnan(max_delta) and max_delta >= 75.0) else 2)
            triage_class = "engine_learning_minor_anchor_complete_qc_watch" if complete_ok and rank == 2 else "engine_learning_minor_anchor_shift"
            return {
                "priority": priority(rank),
                "triage_class": triage_class,
                "recommended_action": "Keep as local visual watch; complete-QC is acceptable and any fix should be bounded/apex-only."
                if complete_ok and rank == 2
                else "Target local anchor/apex selection; likely smaller bounded repair, not baseline replacement.",
                "rationale": f"{delta_text}; {qc_text}.",
            }
        if learning_category == "falling_signal_review_tolerance":
            return {
                "priority": priority(2),
                "triage_class": "falling_signal_tolerance_or_start_shift",
                "recommended_action": "Keep as signal-envelope/QC-tolerance case; only adjust motor if the shifted anchors are visually wrong.",
                "rationale": f"{delta_text}; {qc_text}.",
            }
        if learning_category == "accepted_or_cosmetic_manual_save":
            rank = 3 if complete_ok and changed_steps <= 2 else (2 if complete_ok else (2 if changed_steps <= 2 else 1))
            triage_class = "accepted_complete_qc_cosmetic_delta" if complete_ok else "cosmetic_manual_delta"
            return {
                "priority": priority(rank),
                "triage_class": triage_class,
                "recommended_action": "Use as accepted/watch control; cosmetic manual delta and complete-QC are acceptable."
                if complete_ok
                else "Use cautiously; changes are likely cosmetic unless visual review says otherwise.",
                "rationale": f"{delta_text}; {qc_text}.",
            }
        return {
            "priority": priority(1 if big_shift else 2),
            "triage_class": "engine_learning_uncategorized_manual_delta",
            "recommended_action": "Inspect and add a sharper learning_category before changing the motor.",
            "rationale": f"{delta_text}; {qc_text}.",
        }

    if (bad_linear or minor_shift) and complete_ok and not current_review:
        return {
            "priority": priority(3),
            "triage_class": "accepted_complete_qc_generic",
            "recommended_action": "No motor action; complete-QC gate accepts this row.",
            "rationale": f"{delta_text}; {qc_text}; review={current_review}.",
        }
    if current_review or bad_linear or minor_shift:
        return {
            "priority": priority(2),
            "triage_class": "generic_watchlist",
            "recommended_action": "Inspect before use.",
            "rationale": f"{delta_text}; {qc_text}; review={current_review}.",
        }
    return {
        "priority": priority(3),
        "triage_class": "generic_stable",
        "recommended_action": "No immediate action.",
        "rationale": f"{qc_text}.",
    }


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def should_include(row: dict[str, Any]) -> bool:
    return text(row.get("priority")) in {"P0", "P1", "P2"} or text(row.get("triage_class")).startswith("engine_learning")


def write_outputs(rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir = out_dir if out_dir.is_absolute() else ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    actionable = [row for row in rows if should_include(row)]
    actionable.sort(key=lambda row: (text(row.get("priority")), text(row.get("ladder")), text(row.get("triage_class")), text(row.get("file"))))

    for path, dataset in [(out_dir / "triage.tsv", rows), (out_dir / "actionable.tsv", actionable)]:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(dataset)

    class_counts = Counter(text(row.get("triage_class")) for row in rows)
    priority_counts = Counter(text(row.get("priority")) for row in rows)
    ladder_class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        ladder_class_counts[text(row.get("ladder"))][text(row.get("triage_class"))] += 1

    summary = {
        "rows": len(rows),
        "actionable_rows": len(actionable),
        "priority_counts": dict(sorted(priority_counts.items())),
        "class_counts": dict(class_counts.most_common()),
        "ladder_class_counts": {ladder: dict(counter.most_common()) for ladder, counter in sorted(ladder_class_counts.items())},
        "triage": str((out_dir / "triage.tsv").relative_to(ROOT)),
        "actionable": str((out_dir / "actionable.tsv").relative_to(ROOT)),
        "report": str((out_dir / "report.md").relative_to(ROOT)),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    p0p1 = [row for row in actionable if text(row.get("priority")) in {"P0", "P1"}]
    report_lines = [
        "# Ladder Delta Triage",
        "",
        f"Rows: `{len(rows)}`",
        f"Actionable rows: `{len(actionable)}`",
        "",
        "## Priority Counts",
        "",
    ]
    for key, value in sorted(priority_counts.items()):
        report_lines.append(f"- `{key}`: `{value}`")
    report_lines += ["", "## Class Counts", ""]
    for key, value in class_counts.most_common():
        report_lines.append(f"- `{key}`: `{value}`")
    report_lines += ["", "## P0/P1 Focus", ""]
    if p0p1:
        for row in p0p1:
            report_lines.append(
                f"- `{row['priority']}` `{row['ladder']}` `{row['triage_class']}`: "
                f"`{row['file']}` - {row['recommended_action']}"
            )
    else:
        report_lines.append("- No P0/P1 rows.")
    report_lines += [
        "",
        "## Interpretation",
        "",
        "- `engine_learning_*` rows are motor targets.",
        "- `qc_tolerance_*` rows should not drive peak-selection changes unless visual review shows wrong peaks.",
        "- `control_selection_instability` rows need visual review before they are treated as regressions.",
        "- `data_quality_invalid_reference` means the reference field is not a scan-position truth source.",
    ]
    (out_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage ladder manifest delta-eval rows into learning/action classes.")
    parser.add_argument("--case-results", type=Path, default=DEFAULT_CASE_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for row in read_cases(args.case_results):
        triage = classify(row)
        out = {field: row.get(field, "") for field in OUT_FIELDS}
        out.update(triage)
        rows.append(out)
    write_outputs(rows, args.out_dir)


if __name__ == "__main__":
    main()
