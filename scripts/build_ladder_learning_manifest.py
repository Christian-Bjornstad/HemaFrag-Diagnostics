from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "artifacts" / "ladder_learning_manifest"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.known_ladder_cases import has_known_operator_or_bad_data_token  # noqa: E402

DEFAULT_SOURCES = [
    ROOT / "artifacts" / "ladder_learning_benchmark" / "cases.json",
    ROOT / "artifacts" / "broad_live_complete_qc_aware_balanced_3000_2026-05-06" / "live_summary.tsv",
    ROOT / "artifacts" / "broad_live_ladder_learning_height_envelope_2026-05-05" / "live_summary.tsv",
    ROOT / "review_bundle_overnight_soft_fail_2026-05-05" / "ladder_review_cases.csv",
    ROOT / "artifacts" / "overnight_manual_review_learning_2026-05-05" / "manual_review_learning_cases.tsv",
]

FIELDNAMES = [
    "file",
    "full_path",
    "assay",
    "ladder",
    "source_group",
    "cohort",
    "workbook_bucket",
    "workbook_qc",
    "auto_qc_status",
    "review_label",
    "learning_category",
    "tags",
    "review_note",
    "review_required",
    "primary_reason",
    "reason_codes",
    "soft_fail",
    "severe_fail",
    "nonlinear_complete_ok",
    "candidate_count",
    "selected_count",
    "expected_count",
    "auto_count",
    "manual_count",
    "changed_steps",
    "linear_max",
    "linear_mean",
    "linear_r2",
    "quadratic_max",
    "quadratic_mean",
    "quadratic_r2",
    "workbook_linear_max",
    "workbook_linear_mean",
    "workbook_linear_r2",
    "selected_peaks",
    "manual_adjustment_path",
    "has_manual_adjustment",
    "expected_use",
    "sources",
    "source_artifacts",
]


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def first(row: dict[str, object], names: Iterable[str]) -> str:
    for name in names:
        value = text(row.get(name))
        if value:
            return value
    return ""


def bool_text(value: object) -> str:
    raw = text(value).lower()
    if raw in {"1", "true", "yes", "y"}:
        return "true"
    if raw in {"0", "false", "no", "n"}:
        return "false"
    return text(value)


def normalize_ladder(value: object) -> str:
    raw = text(value)
    upper = raw.upper()
    if upper in {"LIZ", "LIZ500", "LIZ500_250"}:
        return "LIZ500_250"
    if upper in {"ROX", "ROX400", "ROX400HD"}:
        return "ROX400HD"
    return raw


def record_key(full_path: str, file_name: str) -> tuple[str, str]:
    if full_path:
        return ("path", str(Path(full_path).expanduser()))
    return ("file", file_name.lower())


def new_record() -> dict[str, object]:
    record: dict[str, object] = {field: "" for field in FIELDNAMES}
    record["_sources"] = set()
    record["_source_artifacts"] = set()
    return record


def set_if_present(record: dict[str, object], field: str, value: object, *, overwrite: bool = False) -> None:
    clean = text(value)
    if not clean:
        return
    if overwrite or not text(record.get(field)):
        record[field] = clean


def add_source(record: dict[str, object], source: str, artifact: Path) -> None:
    record["_sources"].add(source)  # type: ignore[union-attr]
    record["_source_artifacts"].add(str(artifact.relative_to(ROOT)))  # type: ignore[union-attr]


def selected_text(value: object) -> str:
    if isinstance(value, list):
        return json.dumps(value, separators=(",", ":"))
    return text(value)


def manual_adjustment_path(full_path: str) -> str:
    if not full_path:
        return ""
    candidate = Path(full_path).with_suffix(".ladder_adj.json")
    return str(candidate) if candidate.exists() else ""


def expected_use(record: dict[str, object]) -> str:
    category = text(record.get("learning_category"))
    label = text(record.get("review_label"))
    severe = text(record.get("severe_fail")).lower()
    review = text(record.get("review_required")).lower()
    file_name = text(record.get("file")).lower()
    if has_known_operator_or_bad_data_token(file_name):
        return "exclude_from_motor_training"
    if category in {"operator_or_bad_ladder", "missing_ladder", "broken_file"}:
        return "exclude_from_motor_training"
    if label == "manual_adjusted":
        return "training_pair"
    if label == "reviewed_no_change":
        return "non_regression_control"
    if severe == "true":
        return "hardcase_candidate"
    if review == "true":
        return "review_candidate"
    return "benchmark_control"


def upsert(records: dict[tuple[str, str], dict[str, object]], row: dict[str, object], source: str, artifact: Path) -> None:
    full_path = first(row, ["full_path", "raw_path", "path"])
    file_name = first(row, ["file", "raw_file", "raw_path", "full_path"])
    if "/" in file_name:
        file_name = Path(file_name).name
    if not file_name and full_path:
        file_name = Path(full_path).name
    if not file_name:
        return

    key = record_key(full_path, file_name)
    record = records.setdefault(key, new_record())
    add_source(record, source, artifact)

    set_if_present(record, "file", file_name)
    set_if_present(record, "full_path", full_path)
    set_if_present(record, "assay", first(row, ["assay", "Assay"]))
    set_if_present(record, "ladder", normalize_ladder(first(row, ["ladder", "ladder_type", "workbook_ladder", "workbook_ladder_type"])))
    set_if_present(record, "source_group", first(row, ["source_group", "source", "month", "source_run_dir"]))
    set_if_present(record, "cohort", first(row, ["cohort", "scope"]))
    set_if_present(record, "workbook_bucket", first(row, ["workbook_bucket", "bucket"]))
    set_if_present(record, "workbook_qc", first(row, ["workbook_qc", "ladder_qc", "LadderQC"]))
    set_if_present(record, "auto_qc_status", first(row, ["ladder_qc", "qc_status", "workbook_qc"]))
    if source in {"review_bundle", "manual_review_learning"}:
        set_if_present(record, "review_label", first(row, ["label", "review_label"]), overwrite=True)
    set_if_present(record, "learning_category", first(row, ["learning_category"]))
    if has_known_operator_or_bad_data_token(file_name):
        set_if_present(record, "learning_category", "operator_or_bad_ladder", overwrite=True)
    set_if_present(record, "tags", first(row, ["tags"]))
    set_if_present(record, "review_note", first(row, ["note", "label_note", "review_note"]))
    set_if_present(record, "review_required", bool_text(first(row, ["review", "review_required", "suggested_review"])))
    set_if_present(record, "primary_reason", first(row, ["primary_reason"]))
    set_if_present(record, "reason_codes", first(row, ["reason_codes", "rust_review_codes"]))
    set_if_present(record, "soft_fail", bool_text(first(row, ["soft_fail"])))
    set_if_present(record, "severe_fail", bool_text(first(row, ["severe_fail"])))
    set_if_present(record, "nonlinear_complete_ok", bool_text(first(row, ["nonlinear_complete_ok", "complete_qc_ok"])))
    set_if_present(record, "candidate_count", first(row, ["candidate_count"]))
    set_if_present(record, "selected_count", first(row, ["selected_count", "ladder_fitted_step_count"]))
    set_if_present(record, "expected_count", first(row, ["expected_count", "ladder_expected_step_count"]))
    set_if_present(record, "auto_count", first(row, ["auto_count"]))
    set_if_present(record, "manual_count", first(row, ["manual_count"]))
    set_if_present(record, "changed_steps", first(row, ["changed_steps"]))
    set_if_present(record, "linear_max", first(row, ["linear_max", "rust_linear_max", "ladder_linear_max_residual_bp"]))
    set_if_present(record, "linear_mean", first(row, ["linear_mean", "rust_linear_mean", "ladder_linear_mean_residual_bp"]))
    set_if_present(record, "linear_r2", first(row, ["linear_r2", "rust_linear_r2", "ladder_linear_r2", "ladder_r2"]))
    set_if_present(record, "quadratic_max", first(row, ["quadratic_max", "quadratic_trend_max_abs_error_bp"]))
    set_if_present(record, "quadratic_mean", first(row, ["quadratic_mean", "quadratic_trend_mean_abs_error_bp"]))
    set_if_present(record, "quadratic_r2", first(row, ["quadratic_r2", "quadratic_trend_r2"]))
    set_if_present(record, "workbook_linear_max", first(row, ["workbook_linear_max", "excel_linear_max", "LadderLinearMaxResidualBp"]))
    set_if_present(record, "workbook_linear_mean", first(row, ["workbook_linear_mean", "excel_linear_mean", "LadderLinearMeanResidualBp"]))
    set_if_present(record, "workbook_linear_r2", first(row, ["workbook_linear_r2", "excel_linear_r2", "LadderLinearR2"]))
    set_if_present(record, "selected_peaks", selected_text(first(row, ["selected", "rust_selected_peaks"])))

    adjustment = first(row, ["adjustment_path", "manual_adjustment_path"])
    if not adjustment:
        adjustment = manual_adjustment_path(text(record.get("full_path")))
    set_if_present(record, "manual_adjustment_path", adjustment, overwrite=bool(adjustment))
    set_if_present(record, "has_manual_adjustment", "true" if adjustment else "false", overwrite=True)


def read_delimited(path: Path, delimiter: str) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def load_cases_json(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = payload.get("cases", [])
    else:
        cases = payload
    return [case for case in cases if isinstance(case, dict)]


def source_rows(path: Path) -> tuple[str, list[dict[str, object]]]:
    if path.name == "cases.json":
        return "benchmark_cases", load_cases_json(path)
    if path.name == "live_summary.tsv":
        return "broad_live_eval", read_delimited(path, "\t")
    if path.name == "manual_review_learning_cases.tsv":
        return "manual_review_learning", read_delimited(path, "\t")
    if path.name == "ladder_review_cases.csv":
        return "review_bundle", read_delimited(path, ",")
    raise ValueError(f"Unsupported source: {path}")


def finalize(records: dict[tuple[str, str], dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records.values():
        record["expected_use"] = expected_use(record)
        record["sources"] = ";".join(sorted(record.pop("_sources")))  # type: ignore[arg-type]
        record["source_artifacts"] = ";".join(sorted(record.pop("_source_artifacts")))  # type: ignore[arg-type]
        rows.append(record)
    return sorted(rows, key=lambda row: (text(row.get("ladder")), text(row.get("expected_use")), text(row.get("file"))))


def write_outputs(rows: list[dict[str, object]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tsv_path = OUT_DIR / "current_manifest.tsv"
    json_path = OUT_DIR / "current_manifest.json"
    with tsv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        ladder = text(row.get("ladder")) or "unknown"
        use = text(row.get("expected_use")) or "unknown"
        counts.setdefault(ladder, {})
        counts[ladder][use] = counts[ladder].get(use, 0) + 1
    summary = {
        "rows": len(rows),
        "sources": [str(path.relative_to(ROOT)) for path in DEFAULT_SOURCES if path.exists()],
        "counts_by_ladder_and_expected_use": counts,
        "tsv": str(tsv_path.relative_to(ROOT)),
        "json": str(json_path.relative_to(ROOT)),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main() -> None:
    records: dict[tuple[str, str], dict[str, object]] = {}
    for path in DEFAULT_SOURCES:
        if not path.exists():
            continue
        source, rows = source_rows(path)
        for row in rows:
            upsert(records, row, source, path)
    write_outputs(finalize(records))


if __name__ == "__main__":
    main()
