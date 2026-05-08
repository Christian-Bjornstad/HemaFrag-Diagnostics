from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_RESULTS = ROOT / "artifacts" / "ladder_manifest_delta_eval_complete_qc_manifest_2026-05-06" / "case_results.tsv"
DEFAULT_TRIAGE = ROOT / "artifacts" / "ladder_delta_triage_complete_qc_manifest_2026-05-06" / "triage.tsv"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "ladder_reference_quality_complete_qc_manifest_2026-05-06"


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_bool(value: object) -> bool:
    return text(value).lower() in {"1", "true", "yes", "y"}


def to_int(value: object) -> int:
    raw = text(value)
    if not raw:
        return 0
    try:
        return int(round(float(raw)))
    except ValueError:
        return 0


def to_float(value: object) -> float:
    raw = text(value)
    if not raw:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def format_float(value: object, digits: int = 2) -> str:
    number = to_float(value)
    if number != number:
        return ""
    return f"{number:.{digits}f}"


def classify_reference(row: dict[str, str], triage_class: str) -> tuple[str, str]:
    ref_source = text(row.get("reference_source"))
    expected_use = text(row.get("expected_use"))
    complete_ok = to_bool(row.get("current_complete_qc_ok"))
    changed_steps = to_int(row.get("reference_changed_steps"))
    current_review = to_bool(row.get("current_review"))

    if ref_source == "manual_adjustment":
        return "manual_truth", "Keep as supervised learning/reference truth."
    if ref_source == "invalid_manifest_selected":
        return "invalid_reference", "Rebuild or remove invalid selected indices before using this row."
    if not ref_source:
        return "missing_reference", "No reference to compare against."
    if ref_source == "manifest_selected" and complete_ok and changed_steps > 0 and not current_review:
        return "stale_manifest_reference", "Do not tune motor from this delta; refresh reference only after visual/QC acceptance."
    if ref_source == "manifest_selected" and expected_use == "non_regression_control" and complete_ok:
        return "accepted_manifest_control", "Use as weak control only; manual adjustment would be stronger."
    if triage_class.startswith("accepted_complete_qc") or triage_class in {"stable_non_regression_control", "manual_match_resolved"}:
        return "accepted_reference", "Current row is accepted by triage."
    return "needs_review", "Interpret delta manually before using as training signal."


def build_report(case_results: Path, triage_path: Path, out_dir: Path) -> dict[str, object]:
    cases = read_tsv(case_results)
    triage_rows = read_tsv(triage_path) if triage_path.exists() else []
    triage_by_file = {text(row.get("file")): row for row in triage_rows}

    rows: list[dict[str, object]] = []
    for row in cases:
        triage = triage_by_file.get(text(row.get("file")), {})
        triage_class = text(triage.get("triage_class"))
        status, action = classify_reference(row, triage_class)
        rows.append(
            {
                "reference_status": status,
                "recommended_action": action,
                "triage_priority": text(triage.get("priority")),
                "triage_class": triage_class,
                "file": text(row.get("file")),
                "full_path": text(row.get("full_path")),
                "assay": text(row.get("assay")),
                "ladder": text(row.get("ladder")),
                "expected_use": text(row.get("expected_use")),
                "learning_category": text(row.get("learning_category")),
                "review_label": text(row.get("review_label")),
                "reference_source": text(row.get("reference_source")),
                "reference_changed_steps": text(row.get("reference_changed_steps")),
                "reference_max_abs_delta": format_float(row.get("reference_max_abs_delta"), 0),
                "current_complete_qc_ok": text(row.get("current_complete_qc_ok")),
                "current_review": text(row.get("current_review")),
                "current_linear_max": format_float(row.get("current_linear_max"), 2),
                "current_linear_mean": format_float(row.get("current_linear_mean"), 2),
                "current_linear_r2": format_float(row.get("current_linear_r2"), 6),
                "current_quadratic_max": format_float(row.get("current_quadratic_max"), 2),
                "current_quadratic_mean": format_float(row.get("current_quadratic_mean"), 2),
                "current_quadratic_r2": format_float(row.get("current_quadratic_r2"), 6),
                "current_selected": text(row.get("current_selected")),
                "reference_selected": text(row.get("reference_selected")),
            }
        )

    fields = [
        "reference_status",
        "recommended_action",
        "triage_priority",
        "triage_class",
        "file",
        "full_path",
        "assay",
        "ladder",
        "expected_use",
        "learning_category",
        "review_label",
        "reference_source",
        "reference_changed_steps",
        "reference_max_abs_delta",
        "current_complete_qc_ok",
        "current_review",
        "current_linear_max",
        "current_linear_mean",
        "current_linear_r2",
        "current_quadratic_max",
        "current_quadratic_mean",
        "current_quadratic_r2",
        "current_selected",
        "reference_selected",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    quality_tsv = out_dir / "reference_quality.tsv"
    write_tsv(quality_tsv, rows, fields)

    counts = Counter(text(row["reference_status"]) for row in rows)
    ladder_counts: dict[str, Counter[str]] = {}
    for row in rows:
        ladder = text(row["ladder"]) or "unknown"
        ladder_counts.setdefault(ladder, Counter())[text(row["reference_status"])] += 1

    summary = {
        "rows": len(rows),
        "status_counts": dict(counts),
        "ladder_status_counts": {ladder: dict(counter) for ladder, counter in ladder_counts.items()},
        "reference_quality": str(quality_tsv),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    stale = [row for row in rows if row["reference_status"] == "stale_manifest_reference"]
    report_lines = [
        "# Ladder Reference Quality",
        "",
        f"Rows: `{len(rows)}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, count in counts.most_common():
        report_lines.append(f"- `{key}`: `{count}`")
    report_lines.extend(["", "## Stale Manifest References", ""])
    if stale:
        for row in stale:
            report_lines.append(
                "- "
                f"{row['file']} ({row['ladder']}): {row['reference_changed_steps']} changed steps, "
                f"linear {row['current_linear_max']}/{row['current_linear_mean']}/{row['current_linear_r2']}, "
                f"quadratic {row['current_quadratic_max']}/{row['current_quadratic_mean']}/{row['current_quadratic_r2']}."
            )
    else:
        report_lines.append("- None.")
    report_lines.extend(
        [
            "",
            "## Rule",
            "",
            "- Manual `.ladder_adj.json` references are supervised truth.",
            "- `manifest_selected` references are weak controls. If current Rust is complete-QC-ok and only disagrees with old `manifest_selected`, treat the row as stale reference cleanup, not motor-learning pressure.",
        ]
    )
    (out_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Report stale or weak ladder references in manifest delta outputs.")
    parser.add_argument("--case-results", type=Path, default=DEFAULT_CASE_RESULTS)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    summary = build_report(args.case_results, args.triage, args.out_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
