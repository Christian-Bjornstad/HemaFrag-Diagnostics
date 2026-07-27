"""Build resumable, local clonality ML feature artifacts from analyzed FSA files."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from core.analyses.clonality.config import ASSAY_REFERENCE_RANGES, NONSPECIFIC_PEAKS
from core.analyses.clonality.cohort_features import (
    COHORT_FEATURE_SCHEMA_VERSION,
    enrich_feature_frame_with_cohort_context,
)
from core.analyses.clonality.interpretation import features_from_entry, interpret_entry
from core.analyses.clonality.ml_data_contract import (
    CHEMIST_LABEL_COLUMN,
    is_trace_feature,
)
from core.analyses.clonality.trace_features import (
    TRACE_FEATURE_SCHEMA_VERSION,
    flatten_numeric_features,
)


ML_FEATURE_DATASET_VERSION = "clonality_ml_feature_dataset_v3"
_LEGACY_FEATURE_DATASET_VERSION = "clonality_ml_feature_dataset_v2"
FEATURE_DATASET_FILENAMES = {
    "features": "clonality_ml_trace_features.csv",
    "errors": "clonality_ml_trace_errors.csv",
    "manifest": "clonality_ml_trace_manifest.json",
}
FEATURE_METADATA_COLUMNS = (
    "FeatureDatasetVersion",
    "TraceFeatureSchemaVersion",
    "CohortFeatureSchemaVersion",
    "IdentityKey",
    "FsaSourceHash",
    "FsaContentHash",
    "DIT",
    "Assay",
    "SourceRunKey",
    "RunDate",
    "Well",
    CHEMIST_LABEL_COLUMN,
    "RuleSuggestion",
    "RuleConfidence",
    "RuleReviewNeeded",
    "RuleEvidence",
    "RuleVersion",
)

AnalyzeFile = Callable[[Path], dict[str, Any] | None]
CheckpointCallback = Callable[["TraceFeatureDataset"], None]


@dataclass
class TraceFeatureDataset:
    features: pd.DataFrame
    errors: pd.DataFrame
    processed_count: int
    skipped_existing_count: int


def build_clonality_trace_feature_dataset(
    audit_rows: pd.DataFrame,
    *,
    analyze_file: AnalyzeFile,
    existing_features: pd.DataFrame | None = None,
    limit: int | None = None,
    checkpoint_every: int = 25,
    checkpoint_callback: CheckpointCallback | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> TraceFeatureDataset:
    """Analyze resolved audit rows and return flat, training-ready features."""
    required = {
        "IdentityKey",
        "DIT",
        "Assay",
        "ResolvedFsaPath",
        "FsaSourceHash",
        "FsaStatus",
    }
    missing = sorted(required - set(audit_rows.columns))
    if missing:
        raise KeyError(f"audit rows missing required columns: {', '.join(missing)}")

    candidates = audit_rows.loc[
        audit_rows["FsaStatus"].isin({"resolved", "resolved_recursive"})
    ].copy()
    if limit is not None:
        candidates = candidates.head(max(0, int(limit)))

    candidate_identities = {
        _clean_text(value)
        for value in candidates["IdentityKey"].tolist()
        if _clean_text(value)
    }
    records = [
        record
        for record in _existing_feature_records(existing_features)
        if _clean_text(record.get("IdentityKey")) in candidate_identities
    ]
    completed_records = {
        (
            str(record.get("IdentityKey") or ""),
            str(record.get("FsaContentHash") or ""),
            str(record.get("TraceFeatureSchemaVersion") or ""),
            str(record.get("CohortFeatureSchemaVersion") or ""),
        ): record
        for record in records
    }
    errors: list[dict[str, Any]] = []
    processed = 0
    skipped_existing = 0
    total = int(len(candidates))
    checkpoint_every = max(1, int(checkpoint_every))

    for ordinal, (_index, tracking_row) in enumerate(candidates.iterrows(), start=1):
        identity = _clean_text(tracking_row.get("IdentityKey"))
        source_hash = _clean_text(tracking_row.get("FsaSourceHash"))
        fsa_path = Path(_clean_text(tracking_row.get("ResolvedFsaPath")))
        try:
            content_hash = _file_sha256(fsa_path)
        except Exception as exc:
            errors.append(
                {
                    "IdentityKey": identity,
                    "FsaSourceHash": source_hash,
                    "DIT": _clean_text(tracking_row.get("DIT")),
                    "Assay": _clean_text(tracking_row.get("Assay")),
                    "File": _clean_text(tracking_row.get("File")),
                    "ErrorType": type(exc).__name__,
                    "Error": str(exc),
                }
            )
            if progress_callback:
                progress_callback(ordinal, total, "error")
            continue
        completion_key = (
            identity,
            content_hash,
            TRACE_FEATURE_SCHEMA_VERSION,
            COHORT_FEATURE_SCHEMA_VERSION,
        )
        if completion_key in completed_records:
            skipped_existing += 1
            existing = completed_records[completion_key]
            existing[CHEMIST_LABEL_COLUMN] = _clean_text(
                tracking_row.get(CHEMIST_LABEL_COLUMN)
            )
            existing["DIT"] = _clean_text(tracking_row.get("DIT"))
            if progress_callback:
                progress_callback(ordinal, total, "already_complete")
            continue

        try:
            entry = analyze_file(fsa_path)
            if not isinstance(entry, dict):
                raise RuntimeError("analysis returned no entry")
            tracked_assay = _clean_text(tracking_row.get("Assay"))
            analyzed_assay = _clean_text(entry.get("assay"))
            if _assay_key(tracked_assay) != _assay_key(analyzed_assay):
                raise ValueError(
                    f"assay mismatch: workbook={tracked_assay!r}, analyzed={analyzed_assay!r}"
                )
            rule = interpret_entry(entry)
            features = flatten_numeric_features(features_from_entry(entry))
            if not any(is_trace_feature(column) for column in features):
                raise ValueError("analysis produced no raw trace features")
            record = _metadata_record(tracking_row, rule, content_hash=content_hash)
            record.update(features)
            records.append(record)
            completed_records[completion_key] = record
            processed += 1
            status = "complete"
        except Exception as exc:
            errors.append(
                {
                    "IdentityKey": identity,
                    "FsaSourceHash": source_hash,
                    "DIT": _clean_text(tracking_row.get("DIT")),
                    "Assay": _clean_text(tracking_row.get("Assay")),
                    "File": _clean_text(tracking_row.get("File")),
                    "ErrorType": type(exc).__name__,
                    "Error": str(exc),
                }
            )
            status = "error"

        if progress_callback:
            progress_callback(ordinal, total, status)
        if checkpoint_callback and ordinal % checkpoint_every == 0:
            checkpoint_callback(
                _dataset_result(records, errors, processed, skipped_existing)
            )

    result = _dataset_result(records, errors, processed, skipped_existing)
    if checkpoint_callback:
        checkpoint_callback(result)
    return result


def write_clonality_trace_feature_artifact(
    dataset: TraceFeatureDataset,
    output_dir: Path | str,
    *,
    workbook_path: Path | str,
    fsa_root: Path | str,
    audit_report: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Atomically write feature/error CSVs and a provenance manifest."""
    output = Path(output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    features_path = output / FEATURE_DATASET_FILENAMES["features"]
    errors_path = output / FEATURE_DATASET_FILENAMES["errors"]
    manifest_path = output / FEATURE_DATASET_FILENAMES["manifest"]

    _atomic_write_csv(dataset.features, features_path)
    _atomic_write_csv(dataset.errors, errors_path)

    feature_columns = [
        str(column)
        for column in dataset.features.columns
        if column not in FEATURE_METADATA_COLUMNS
        and pd.api.types.is_numeric_dtype(dataset.features[column])
    ]
    manifest = {
        "dataset_version": ML_FEATURE_DATASET_VERSION,
        "trace_feature_schema_version": TRACE_FEATURE_SCHEMA_VERSION,
        "cohort_feature_schema_version": COHORT_FEATURE_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_revision": _git_revision(),
        "settings_fingerprint": _settings_fingerprint(),
        "source_workbook": str(Path(workbook_path).expanduser().resolve()),
        "fsa_root": str(Path(fsa_root).expanduser().resolve()),
        "contains_raw_traces": False,
        "features_contain_local_raw_paths": False,
        "manifest_contains_local_paths": True,
        "row_count": int(len(dataset.features)),
        "error_count": int(len(dataset.errors)),
        "processed_this_run": int(dataset.processed_count),
        "skipped_existing_this_run": int(dataset.skipped_existing_count),
        "feature_count": int(len(feature_columns)),
        "trace_feature_count": int(sum(is_trace_feature(column) for column in feature_columns)),
        "feature_columns": feature_columns,
        "assay_counts": _counts(dataset.features, "Assay"),
        "label_counts": _counts(dataset.features, CHEMIST_LABEL_COLUMN),
        "audit_status": str((audit_report or {}).get("status") or ""),
        "audit_issue_codes": [
            str(issue.get("code") or "")
            for issue in (audit_report or {}).get("issues", [])
            if isinstance(issue, Mapping)
        ],
        "output_files": {
            "features": features_path.name,
            "errors": errors_path.name,
        },
    }
    _atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
    )
    return {
        "features": features_path,
        "errors": errors_path,
        "manifest": manifest_path,
    }


def load_resumable_feature_artifact(output_dir: Path | str) -> pd.DataFrame:
    """Load a compatible existing feature CSV for ``--resume``."""
    output = Path(output_dir).expanduser()
    features_path = output / FEATURE_DATASET_FILENAMES["features"]
    manifest_path = output / FEATURE_DATASET_FILENAMES["manifest"]
    if not features_path.is_file() or not manifest_path.is_file():
        return pd.DataFrame()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_version = manifest.get("dataset_version")
    if dataset_version not in {
        ML_FEATURE_DATASET_VERSION,
        _LEGACY_FEATURE_DATASET_VERSION,
    }:
        raise ValueError("existing feature artifact uses a different dataset version")
    if manifest.get("trace_feature_schema_version") != TRACE_FEATURE_SCHEMA_VERSION:
        raise ValueError("existing feature artifact uses a different trace feature schema")
    if manifest.get("cohort_feature_schema_version") != COHORT_FEATURE_SCHEMA_VERSION:
        raise ValueError("existing feature artifact uses a different cohort feature schema")
    if manifest.get("settings_fingerprint") != _settings_fingerprint():
        raise ValueError("existing feature artifact uses different clonality settings")
    try:
        frame = pd.read_csv(features_path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if dataset_version == _LEGACY_FEATURE_DATASET_VERSION:
        frame = _upgrade_v2_feature_artifact(frame)
    return frame


def _upgrade_v2_feature_artifact(frame: pd.DataFrame) -> pd.DataFrame:
    """Migrate derived scalar/context fields without reading raw traces again."""
    upgraded = frame.copy()
    required = {
        "dominant_peak_basepairs",
        "interpretation_range_min_bp",
        "interpretation_range_max_bp",
    }
    if required.issubset(upgraded.columns):
        dominant = pd.to_numeric(
            upgraded["dominant_peak_basepairs"],
            errors="coerce",
        )
        range_min = pd.to_numeric(
            upgraded["interpretation_range_min_bp"],
            errors="coerce",
        )
        range_max = pd.to_numeric(
            upgraded["interpretation_range_max_bp"],
            errors="coerce",
        )
        width = range_max - range_min
        valid = dominant.notna() & range_min.notna() & range_max.notna() & width.gt(0)
        in_window = valid & dominant.ge(range_min) & dominant.le(range_max)
        upgraded["dom_distance_to_ref_window_center_bp"] = (
            dominant - ((range_min + range_max) / 2.0)
        ).where(valid)
        upgraded["ref_window_coverage_fraction"] = (
            (3.0 / width).where(in_window, 0.0)
        )
        upgraded["in_reference_window"] = in_window.astype(int)

    cohort_aliases = {
        "patient_assays_run_count": "cohort_patient_assay_count",
        "assay_panel_completeness_pct": "cohort_panel_completeness",
        "patient_entry_count": "cohort_patient_entry_count",
    }
    for legacy_column, cohort_column in cohort_aliases.items():
        if cohort_column in upgraded.columns:
            upgraded[legacy_column] = upgraded[cohort_column]
    upgraded["FeatureDatasetVersion"] = ML_FEATURE_DATASET_VERSION
    return upgraded


def _metadata_record(
    tracking_row: pd.Series,
    rule: Mapping[str, Any],
    *,
    content_hash: str,
) -> dict[str, Any]:
    return {
        "FeatureDatasetVersion": ML_FEATURE_DATASET_VERSION,
        "TraceFeatureSchemaVersion": TRACE_FEATURE_SCHEMA_VERSION,
        "CohortFeatureSchemaVersion": COHORT_FEATURE_SCHEMA_VERSION,
        "IdentityKey": _clean_text(tracking_row.get("IdentityKey")),
        "FsaSourceHash": _clean_text(tracking_row.get("FsaSourceHash")),
        "FsaContentHash": content_hash,
        "DIT": _clean_text(tracking_row.get("DIT")),
        "Assay": _clean_text(tracking_row.get("Assay")),
        "SourceRunKey": _source_run_key(tracking_row.get("SourceRunDir")),
        "RunDate": _clean_text(tracking_row.get("RunDate")),
        "Well": _clean_text(tracking_row.get("Well")),
        CHEMIST_LABEL_COLUMN: _clean_text(tracking_row.get(CHEMIST_LABEL_COLUMN)),
        "RuleSuggestion": _clean_text(rule.get("ClonalitySuggestion")),
        "RuleConfidence": _finite_or_zero(rule.get("ClonalityConfidence")),
        "RuleReviewNeeded": bool(rule.get("ClonalityReviewNeeded", False)),
        "RuleEvidence": _clean_text(rule.get("ClonalityEvidence")),
        "RuleVersion": _clean_text(rule.get("ClonalityModelVersion")),
    }


def _dataset_result(
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    processed: int,
    skipped_existing: int,
) -> TraceFeatureDataset:
    features = pd.DataFrame(records)
    if not features.empty and {"IdentityKey", "FsaSourceHash"}.issubset(features.columns):
        features = (
            features.drop_duplicates(
                subset=[
                    "IdentityKey",
                    "FsaSourceHash",
                    "TraceFeatureSchemaVersion",
                    "CohortFeatureSchemaVersion",
                ],
                keep="last",
            )
            .sort_values(["Assay", "DIT", "IdentityKey"], kind="stable")
            .reset_index(drop=True)
        )
        features = enrich_feature_frame_with_cohort_context(features)
    error_frame = pd.DataFrame(errors)
    return TraceFeatureDataset(
        features=features,
        errors=error_frame,
        processed_count=int(processed),
        skipped_existing_count=int(skipped_existing),
    )


def _existing_feature_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    required = {
        "IdentityKey",
        "FsaSourceHash",
        "TraceFeatureSchemaVersion",
        "CohortFeatureSchemaVersion",
    }
    required.add("FsaContentHash")
    if not required.issubset(frame.columns):
        raise KeyError("existing feature artifact is missing resume identity columns")
    return frame.to_dict(orient="records")


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _settings_fingerprint() -> str:
    payload = {
        "assay_reference_ranges": ASSAY_REFERENCE_RANGES,
        "nonspecific_peaks": NONSPECIFIC_PEAKS,
        "trace_feature_schema_version": TRACE_FEATURE_SCHEMA_VERSION,
        "cohort_feature_schema_version": COHORT_FEATURE_SCHEMA_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _counts(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if frame.empty or column not in frame.columns:
        return []
    values = frame[column].fillna("").astype(str).str.strip().replace("", "<missing>")
    return [
        {"value": str(value), "count": int(count)}
        for value, count in values.value_counts().items()
    ]


def _assay_key(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .upper()
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


def _source_run_key(value: Any) -> str:
    text = _clean_text(value).replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1] if text else ""


def _finite_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if pd.notna(number) else 0.0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "FEATURE_DATASET_FILENAMES",
    "FEATURE_METADATA_COLUMNS",
    "ML_FEATURE_DATASET_VERSION",
    "TraceFeatureDataset",
    "build_clonality_trace_feature_dataset",
    "load_resumable_feature_artifact",
    "write_clonality_trace_feature_artifact",
]
