"""Audit a labeled clonality workbook against local real FSA data."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.analyses.clonality.interpretation_units import (
    CHANNEL_CHEMIST_LABEL_COLUMNS,
    interpretation_units_for_assay,
)
from core.analyses.clonality.ml_data_contract import (
    CHEMIST_LABEL_COLUMN,
    RULE_LABEL_COLUMN,
    is_trace_feature,
    load_tracking_run_table,
    missing_required_columns,
)
from core.analyses.clonality.ml_training import (
    ANNOTATION_CLASSES_ORDER,
    normalize_annotation_label,
)


ML_DATA_AUDIT_VERSION = "v1"
REQUIRED_TRAINING_COLUMNS = ("IdentityKey", "File", "DIT", "Assay")
NON_FEATURE_COLUMNS = {
    "Month",
    "IdentityKey",
    "File",
    "SourceRunDir",
    "DIT",
    "Assay",
    "SampleKind",
    "Group",
    "Control",
    "RunDate",
    "RunCode",
    "Well",
    "Batch",
    "Ladder",
    CHEMIST_LABEL_COLUMN,
    RULE_LABEL_COLUMN,
    "ClonalityConfidence",
    "ClonalityReviewNeeded",
    "ClonalityEvidence",
    "ClonalityModelVersion",
    "ClonalityMLSuggestion",
    "ClonalityMLConfidence",
    "ClonalityMLThreshold",
    "ClonalityMLReviewNeeded",
    "ClonalityMLEvidence",
    "ClonalityMLModelVersion",
    "_TrackingSheet",
    "_TrackingRowNumber",
}


@dataclass
class ClonalityDataAudit:
    report: dict[str, Any]
    rows: pd.DataFrame
    feature_quality: pd.DataFrame

    @property
    def has_errors(self) -> bool:
        return any(issue.get("severity") == "error" for issue in self.report.get("issues", []))


def audit_clonality_ml_data(
    workbook_path: Path | str,
    fsa_root: Path | str,
    *,
    label_column: str = CHEMIST_LABEL_COLUMN,
    include_controls: bool = False,
    recursive_fallback: bool = True,
) -> ClonalityDataAudit:
    workbook = Path(workbook_path).expanduser()
    root = Path(fsa_root).expanduser()
    table = load_tracking_run_table(workbook, include_controls=include_controls)
    rows = table.frame.copy()
    issues: list[dict[str, Any]] = []

    missing_columns = missing_required_columns(rows, REQUIRED_TRAINING_COLUMNS)
    if missing_columns:
        _add_issue(
            issues,
            "error",
            "missing_required_columns",
            len(missing_columns),
            f"Missing required columns: {', '.join(missing_columns)}",
        )

    if label_column not in rows.columns:
        rows[label_column] = ""
        _add_issue(
            issues,
            "error",
            "missing_label_column",
            len(rows),
            f"Missing chemist label column {label_column!r}.",
        )
    elif label_column == RULE_LABEL_COLUMN:
        _add_issue(
            issues,
            "warning",
            "rule_label_selected",
            len(rows),
            "The selected label column is also the rule-based output; verify labels are chemist-reviewed.",
        )

    for column in REQUIRED_TRAINING_COLUMNS:
        if column not in rows.columns:
            rows[column] = ""

    for column in REQUIRED_TRAINING_COLUMNS:
        rows[column] = rows[column].map(_clean_text)
    rows[label_column] = rows[label_column].map(normalize_annotation_label)
    for channel_column in CHANNEL_CHEMIST_LABEL_COLUMNS:
        if channel_column not in rows.columns:
            rows[channel_column] = ""
        rows[channel_column] = rows[channel_column].map(
            normalize_annotation_label
        )

    if rows.empty:
        _add_issue(issues, "error", "no_training_rows", 0, "No patient rows were found.")

    for column, code in (
        ("IdentityKey", "missing_identity_key"),
        ("File", "missing_file_name"),
        ("DIT", "missing_dit"),
        ("Assay", "missing_assay"),
    ):
        count = int(rows[column].eq("").sum())
        if count:
            _add_issue(issues, "error", code, count, f"{count} row(s) have no {column}.")

    unit_labels = (
        _interpretation_unit_label_table(rows)
        if label_column == CHEMIST_LABEL_COLUMN
        else pd.DataFrame()
    )
    labels = (
        unit_labels["ChemistLabel"]
        if not unit_labels.empty
        else rows[label_column]
    )
    valid_labels = set(ANNOTATION_CLASSES_ORDER)
    invalid_mask = labels.ne("") & ~labels.isin(valid_labels)
    unlabeled_count = int(labels.eq("").sum())
    invalid_count = int(invalid_mask.sum())
    if unlabeled_count:
        _add_issue(
            issues,
            "warning",
            "unlabelled_rows",
            unlabeled_count,
            f"{unlabeled_count} row(s) still need a chemist label.",
        )
    if invalid_count:
        invalid_values = sorted(labels.loc[invalid_mask].unique().tolist())
        _add_issue(
            issues,
            "error",
            "invalid_labels",
            invalid_count,
            f"Unknown labels: {', '.join(invalid_values)}",
        )

    duplicate_identity = rows["IdentityKey"].ne("") & rows["IdentityKey"].duplicated(keep=False)
    duplicate_identity_count = int(duplicate_identity.sum())
    if duplicate_identity_count:
        _add_issue(
            issues,
            "error",
            "duplicate_identity_keys",
            duplicate_identity_count,
            f"{duplicate_identity_count} row(s) share an IdentityKey.",
        )

    path_results = _resolve_fsa_rows(rows, root, recursive_fallback=recursive_fallback)
    rows = pd.concat([rows.reset_index(drop=True), path_results], axis=1)
    missing_fsa_count = int(
        (~rows["FsaStatus"].isin({"resolved", "resolved_recursive"})).sum()
    )
    zero_byte_count = int(rows["FsaZeroBytes"].sum())
    if not root.exists():
        _add_issue(issues, "error", "missing_fsa_root", 1, f"FSA root does not exist: {root}")
    if missing_fsa_count:
        _add_issue(
            issues,
            "error",
            "missing_fsa_files",
            missing_fsa_count,
            f"{missing_fsa_count} tracked FSA file(s) could not be resolved.",
        )
    if zero_byte_count:
        _add_issue(
            issues,
            "error",
            "zero_byte_fsa_files",
            zero_byte_count,
            f"{zero_byte_count} resolved FSA file(s) are empty.",
        )

    duplicate_path_mask = (
        rows["ResolvedFsaPath"].ne("")
        & rows["ResolvedFsaPath"].duplicated(keep=False)
    )
    duplicate_path_count = int(duplicate_path_mask.sum())
    if duplicate_path_count:
        _add_issue(
            issues,
            "error",
            "duplicate_fsa_assignments",
            duplicate_path_count,
            f"{duplicate_path_count} row(s) resolve to an FSA used more than once.",
        )

    feature_quality = _feature_quality_table(rows)
    trace_feature_count = sum(
        1 for column in feature_quality.get("feature", []) if is_trace_feature(column)
    )
    if trace_feature_count == 0:
        _add_issue(
            issues,
            "warning",
            "no_trace_features",
            0,
            "No raw FSA trace features are present yet; audit is useful, but this table is not training-ready.",
        )
    grouping = _grouping_summary(rows)
    if grouping["multi_row_dit_count"] == 0 and grouping["unique_dit_count"] > 1:
        _add_issue(
            issues,
            "warning",
            "no_repeated_dit_groups",
            grouping["unique_dit_count"],
            "Every non-empty DIT is a singleton; patient-group splitting cannot test cross-assay leakage.",
        )

    severity = "failed" if any(item["severity"] == "error" for item in issues) else (
        "review" if issues else "ready"
    )
    report = {
        "audit_version": ML_DATA_AUDIT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": severity,
        "workbook": str(workbook.resolve()),
        "fsa_root": str(root.resolve()),
        "label_column": label_column,
        "include_controls": bool(include_controls),
        "source_sheets": list(table.source_sheets),
        "available_sheets": list(table.available_sheets),
        "row_count": int(len(rows)),
        "interpretation_unit_count": int(
            len(unit_labels) if not unit_labels.empty else len(rows)
        ),
        "labeled_row_count": int(labels.ne("").sum()),
        "unlabeled_row_count": unlabeled_count,
        "resolved_fsa_count": int(rows["FsaStatus"].isin({"resolved", "resolved_recursive"}).sum()),
        "missing_fsa_count": missing_fsa_count,
        "zero_byte_fsa_count": zero_byte_count,
        "assay_counts": _value_counts(rows["Assay"]),
        "label_counts": _value_counts(labels),
        "assay_label_counts": (
            _unit_label_counts(unit_labels)
            if not unit_labels.empty
            else _assay_label_counts(rows, label_column)
        ),
        "grouping": grouping,
        "feature_quality_summary": {
            "feature_count": int(len(feature_quality)),
            "trace_feature_count": int(trace_feature_count),
            "all_zero_feature_count": int(feature_quality.get("all_zero", pd.Series(dtype=bool)).sum()),
            "constant_feature_count": int(feature_quality.get("constant", pd.Series(dtype=bool)).sum()),
        },
        "issues": issues,
    }
    return ClonalityDataAudit(report=report, rows=rows, feature_quality=feature_quality)


def write_clonality_ml_audit(audit: ClonalityDataAudit, output_dir: Path | str) -> dict[str, Path]:
    output = Path(output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "clonality_ml_data_audit.json"
    rows_path = output / "clonality_ml_data_rows.csv"
    missing_path = output / "clonality_ml_missing_fsa.csv"
    features_path = output / "clonality_ml_feature_quality.csv"

    report_path.write_text(
        json.dumps(audit.report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    audit.rows.to_csv(rows_path, index=False)
    audit.rows.loc[
        ~audit.rows["FsaStatus"].isin({"resolved", "resolved_recursive"})
    ].to_csv(missing_path, index=False)
    audit.feature_quality.to_csv(features_path, index=False)
    return {
        "report": report_path,
        "rows": rows_path,
        "missing_fsa": missing_path,
        "feature_quality": features_path,
    }


def _resolve_fsa_rows(
    rows: pd.DataFrame,
    root: Path,
    *,
    recursive_fallback: bool,
) -> pd.DataFrame:
    initial: list[dict[str, Any]] = []
    unresolved: list[int] = []
    for index, row in rows.iterrows():
        result = _resolve_direct_fsa(row, root)
        initial.append(result)
        if result["FsaStatus"] == "missing":
            unresolved.append(index)

    basename_index: dict[str, list[Path]] = {}
    if unresolved and recursive_fallback and root.is_dir():
        for candidate in root.rglob("*"):
            if candidate.is_file() and candidate.suffix.lower() == ".fsa":
                basename_index.setdefault(candidate.name.lower(), []).append(candidate)

    for index in unresolved:
        file_name = _clean_text(rows.at[index, "File"])
        matches = basename_index.get(Path(file_name).name.lower(), [])
        if len(matches) == 1:
            initial[index] = _path_result(matches[0], root, "resolved_recursive")
        elif len(matches) > 1:
            initial[index]["FsaStatus"] = "ambiguous"
            initial[index]["FsaCandidateCount"] = len(matches)

    return pd.DataFrame(initial)


def _resolve_direct_fsa(row: pd.Series, root: Path) -> dict[str, Any]:
    file_name = _clean_text(row.get("File"))
    source_run_dir = _clean_text(row.get("SourceRunDir"))
    if not file_name:
        return _missing_path_result("missing_file_name")

    file_path = Path(file_name).expanduser()
    source_path = Path(source_run_dir).expanduser() if source_run_dir else None
    candidates: list[Path] = []
    if file_path.is_absolute():
        candidates.append(file_path)
    if source_path is not None and source_path.is_absolute():
        candidates.append(source_path / file_path.name)
    if source_run_dir:
        candidates.append(root / source_run_dir / file_path.name)
        candidates.append(root / Path(source_run_dir).name / file_path.name)
    candidates.append(root / file_path.name)

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return _path_result(candidate, root, "resolved")
    return _missing_path_result("missing")


def _path_result(path: Path, root: Path, status: str) -> dict[str, Any]:
    absolute = path.resolve()
    try:
        relative = absolute.relative_to(root.resolve())
        identity_text = relative.as_posix().lower()
    except ValueError:
        identity_text = absolute.name.lower()
    source_hash = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()[:16]
    size = int(absolute.stat().st_size)
    return {
        "FsaStatus": status,
        "ResolvedFsaPath": str(absolute),
        "FsaSourceHash": source_hash,
        "FsaBytes": size,
        "FsaZeroBytes": size == 0,
        "FsaCandidateCount": 1,
    }


def _missing_path_result(status: str) -> dict[str, Any]:
    return {
        "FsaStatus": status,
        "ResolvedFsaPath": "",
        "FsaSourceHash": "",
        "FsaBytes": 0,
        "FsaZeroBytes": False,
        "FsaCandidateCount": 0,
    }


def _feature_quality_table(rows: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for column in rows.columns:
        if column in NON_FEATURE_COLUMNS or column.startswith("Fsa"):
            continue
        raw = rows[column]
        nonempty = raw.notna() & raw.astype(str).str.strip().ne("")
        numeric = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan)
        numeric_fraction = float(numeric[nonempty].notna().mean()) if nonempty.any() else 0.0
        if not pd.api.types.is_numeric_dtype(raw) and numeric_fraction < 0.95:
            continue
        nonnull = numeric.dropna()
        zero_count = int(nonnull.eq(0).sum())
        unique_count = int(nonnull.nunique())
        records.append(
            {
                "feature": str(column),
                "row_count": int(len(rows)),
                "non_null_count": int(numeric.notna().sum()),
                "null_count": int(numeric.isna().sum()),
                "null_rate": float(numeric.isna().mean()) if len(rows) else 0.0,
                "zero_count": zero_count,
                "zero_rate_non_null": float(zero_count / len(nonnull)) if len(nonnull) else 0.0,
                "unique_count": unique_count,
                "constant": unique_count <= 1,
                "all_zero": bool(len(nonnull) > 0 and zero_count == len(nonnull)),
            }
        )
    return pd.DataFrame(records).sort_values("feature", kind="stable").reset_index(drop=True) if records else pd.DataFrame()


def _grouping_summary(rows: pd.DataFrame) -> dict[str, Any]:
    dits = rows["DIT"].map(_clean_text)
    nonempty = dits[dits.ne("")]
    sizes = nonempty.value_counts()
    assay_per_dit = (
        rows.loc[dits.ne("")]
        .assign(_DIT=dits[dits.ne("")])
        .groupby("_DIT")["Assay"]
        .nunique()
    )
    return {
        "missing_dit_row_count": int(dits.eq("").sum()),
        "unique_dit_count": int(nonempty.nunique()),
        "singleton_dit_count": int(sizes.eq(1).sum()),
        "multi_row_dit_count": int(sizes.gt(1).sum()),
        "multi_assay_dit_count": int(assay_per_dit.gt(1).sum()),
        "max_rows_per_dit": int(sizes.max()) if not sizes.empty else 0,
        "unique_source_run_dir_count": int(
            rows.get("SourceRunDir", pd.Series("", index=rows.index))
            .map(_clean_text)
            .replace("", np.nan)
            .nunique()
        ),
    }


def _interpretation_unit_label_table(rows: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in rows.iterrows():
        units = interpretation_units_for_assay(row.get("Assay"))
        legacy = normalize_annotation_label(row.get(CHEMIST_LABEL_COLUMN))
        if not units:
            records.append(
                {
                    "Assay": _clean_text(row.get("Assay")),
                    "InterpretationUnit": "",
                    "Channel": "",
                    "ChemistLabel": legacy,
                }
            )
            continue
        for unit in units:
            label = normalize_annotation_label(row.get(unit.label_column))
            if not label and len(units) == 1:
                label = legacy
            records.append(
                {
                    "Assay": _clean_text(row.get("Assay")),
                    "InterpretationUnit": unit.unit_id,
                    "Channel": unit.channel,
                    "ChemistLabel": label,
                }
            )
    return pd.DataFrame(records)


def _unit_label_counts(unit_labels: pd.DataFrame) -> list[dict[str, Any]]:
    if unit_labels.empty:
        return []
    grouped = (
        unit_labels.assign(
            _Label=unit_labels["ChemistLabel"].replace("", "<unlabelled>")
        )
        .groupby(["Assay", "InterpretationUnit", "Channel", "_Label"])
        .size()
        .reset_index(name="count")
    )
    return [
        {
            "assay": str(row["Assay"]),
            "interpretation_unit": str(row["InterpretationUnit"]),
            "channel": str(row["Channel"]),
            "label": str(row["_Label"]),
            "count": int(row["count"]),
        }
        for _, row in grouped.iterrows()
    ]


def _assay_label_counts(rows: pd.DataFrame, label_column: str) -> list[dict[str, Any]]:
    if rows.empty:
        return []
    grouped = (
        rows.assign(
            Assay=rows["Assay"].replace("", "<missing>"),
            _Label=rows[label_column].replace("", "<unlabelled>"),
        )
        .groupby(["Assay", "_Label"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    return [
        {"assay": str(row["Assay"]), "label": str(row["_Label"]), "count": int(row["count"])}
        for _, row in grouped.iterrows()
    ]


def _value_counts(series: pd.Series) -> list[dict[str, Any]]:
    cleaned = series.map(_clean_text).replace("", "<missing>")
    counts = cleaned.value_counts(dropna=False)
    return [{"value": str(value), "count": int(count)} for value, count in counts.items()]


def _add_issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    count: int,
    message: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "count": int(count),
            "message": message,
        }
    )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


__all__ = [
    "ClonalityDataAudit",
    "ML_DATA_AUDIT_VERSION",
    "REQUIRED_TRAINING_COLUMNS",
    "audit_clonality_ml_data",
    "write_clonality_ml_audit",
]
