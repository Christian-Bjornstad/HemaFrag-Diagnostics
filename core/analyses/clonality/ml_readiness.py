"""Aggregate preflight evidence for real clonality model training."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from core.analyses.clonality.interpretation_units import (
    CHANNEL_CHEMIST_LABEL_COLUMNS,
    interpretation_units_for_assay,
)
from core.analyses.clonality.ml_data_contract import CHEMIST_LABEL_COLUMN
from core.analyses.clonality.ml_training import (
    ANNOTATION_CLASSES_ORDER,
    normalize_annotation_label,
    summarize_class_support,
)
from core.analyses.clonality.ml_validation import CORE_CLONALITY_LABELS


LABEL_READINESS_SCHEMA_VERSION = "clonality_label_readiness_v1"
READINESS_FILENAMES = {
    "report": "clonality_label_readiness.json",
    "assays": "clonality_assay_readiness.csv",
    "classes": "clonality_class_support.csv",
}


@dataclass(frozen=True)
class LabelReadiness:
    report: dict[str, Any]
    assays: pd.DataFrame
    classes: pd.DataFrame


def assess_clonality_label_readiness(
    tracking_rows: pd.DataFrame,
    feature_rows: pd.DataFrame,
    *,
    min_samples: int = 200,
    validation_folds: int = 5,
    source_run_validation_folds: int = 3,
    min_dit_groups: int = 50,
    min_class_dit_groups: int = 10,
    min_core_class_dit_groups: int = 20,
    min_class_source_run_groups: int = 3,
    min_class_evaluation_folds: int = 2,
    min_class_training_rows_per_fold: int = 6,
    max_class_dit_row_fraction: float = 0.10,
) -> LabelReadiness:
    """Assess whether each assay has enough independent chemist labels."""
    thresholds = {
        "min_samples": int(min_samples),
        "validation_folds": int(validation_folds),
        "source_run_validation_folds": int(source_run_validation_folds),
        "min_dit_groups": int(min_dit_groups),
        "min_class_dit_groups": int(min_class_dit_groups),
        "min_core_class_dit_groups": int(min_core_class_dit_groups),
        "min_class_source_run_groups": int(min_class_source_run_groups),
        "min_class_evaluation_folds": int(min_class_evaluation_folds),
        "min_class_training_rows_per_fold": int(
            min_class_training_rows_per_fold
        ),
        "max_class_dit_row_fraction": float(max_class_dit_row_fraction),
    }
    _validate_thresholds(thresholds)

    tracking = tracking_rows.copy()
    features = feature_rows.copy()
    _require_columns(tracking, {"IdentityKey", "DIT", "Assay"}, "tracking rows")
    _require_columns(
        features,
        {"IdentityKey", "Assay", "SourceRunKey", "FsaContentHash"},
        "feature rows",
    )
    channel_level = {
        "InterpretationUnit",
        "Channel",
    }.issubset(features.columns)
    if CHEMIST_LABEL_COLUMN not in tracking.columns:
        tracking[CHEMIST_LABEL_COLUMN] = ""
    tracking["_AssayKey"] = tracking["Assay"].map(_assay_key)
    features["_AssayKey"] = features["Assay"].map(_assay_key)
    join_columns = ["IdentityKey", "_AssayKey"]
    _reject_duplicate_keys(tracking, join_columns, "tracking")
    feature_identity_columns = (
        [*join_columns, "InterpretationUnit"]
        if channel_level
        else join_columns
    )
    _reject_duplicate_keys(features, feature_identity_columns, "features")

    metadata_columns = [
        *join_columns,
        "SourceRunKey",
        "FsaContentHash",
    ]
    if channel_level:
        metadata_columns.extend(
            ["InterpretationUnit", "Channel", "TargetName"]
        )
    metadata = features[metadata_columns].copy()
    merged = metadata.merge(
        tracking,
        on=join_columns,
        how="left",
        validate="many_to_one" if channel_level else "one_to_one",
        indicator=True,
    )
    unmatched = merged["_merge"].ne("both")
    if unmatched.any():
        raise ValueError(
            f"{int(unmatched.sum())} feature row(s) have no tracking metadata"
        )
    merged = merged.drop(columns=["_merge"])
    if channel_level:
        merged["_ChannelChemistLabel"] = ""
        for channel, label_column in zip(
            ("DATA1", "DATA2", "DATA3"),
            CHANNEL_CHEMIST_LABEL_COLUMNS,
        ):
            if label_column not in merged.columns:
                continue
            mask = merged["Channel"].fillna("").astype(str).str.upper().eq(
                channel
            )
            merged.loc[mask, "_ChannelChemistLabel"] = (
                merged.loc[mask, label_column]
                .fillna("")
                .astype(str)
                .str.strip()
            )
        missing = merged["_ChannelChemistLabel"].eq("")
        single_channel = merged["Assay"].map(
            lambda assay: len(interpretation_units_for_assay(assay)) == 1
        )
        merged.loc[missing & single_channel, "_ChannelChemistLabel"] = (
            merged.loc[missing & single_channel, CHEMIST_LABEL_COLUMN]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        merged[CHEMIST_LABEL_COLUMN] = merged["_ChannelChemistLabel"]
    merged[CHEMIST_LABEL_COLUMN] = (
        merged[CHEMIST_LABEL_COLUMN]
        .fillna("")
        .map(normalize_annotation_label)
    )
    invalid = sorted(
        set(merged[CHEMIST_LABEL_COLUMN].unique())
        - {""}
        - set(ANNOTATION_CLASSES_ORDER)
    )
    if invalid:
        raise ValueError(f"invalid chemist labels: {', '.join(invalid)}")

    assay_records: list[dict[str, Any]] = []
    class_records: list[dict[str, Any]] = []
    duplicate_rows_removed = 0
    target_column = "InterpretationUnit" if channel_level else "Assay"
    for assay, assay_rows in merged.groupby(
        target_column,
        sort=True,
        dropna=False,
    ):
        available_rows = int(len(assay_rows))
        labeled = assay_rows.loc[
            assay_rows[CHEMIST_LABEL_COLUMN].ne("")
        ].copy()
        raw_labeled_rows = int(len(labeled))
        deduplicated, removed = _deduplicate_labeled_content(
            labeled,
            assay=str(assay),
        )
        duplicate_rows_removed += removed
        labels = deduplicated[CHEMIST_LABEL_COLUMN].reset_index(drop=True)
        dits = (
            deduplicated["DIT"].fillna("").astype(str).str.strip().reset_index(drop=True)
        )
        support = summarize_class_support(
            labels,
            dits,
            deduplicated.reset_index(drop=True),
        )
        candidate_blockers = _candidate_blockers(
            deduplicated,
            support,
            thresholds,
        )
        promotion_blockers = _promotion_blockers(
            deduplicated,
            support,
            thresholds,
        )
        candidate_ready = not candidate_blockers
        promotion_ready = candidate_ready and not promotion_blockers
        if raw_labeled_rows == 0:
            status = "awaiting_labels"
        elif promotion_ready:
            status = "promotion_preflight_ready"
        elif candidate_ready:
            status = "candidate_ready"
        else:
            status = "not_ready"

        assay_records.append(
            {
                "Assay": str(assay),
                "AvailableRows": available_rows,
                "RawLabeledRows": raw_labeled_rows,
                "UniqueTraceLabeledRows": int(len(deduplicated)),
                "LabelCoverage": (
                    float(raw_labeled_rows / available_rows)
                    if available_rows
                    else 0.0
                ),
                "ObservedClasses": int(len(support)),
                "DistinctDITs": int(dits.loc[dits.ne("")].nunique()),
                "SourceRuns": int(
                    deduplicated["SourceRunKey"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .replace("", pd.NA)
                    .nunique()
                ),
                "DuplicateRowsRemoved": int(removed),
                "CandidateReady": bool(candidate_ready),
                "PromotionPreflightReady": bool(promotion_ready),
                "Status": status,
                "CandidateBlockers": " | ".join(candidate_blockers),
                "PromotionBlockers": " | ".join(promotion_blockers),
            }
        )
        for label in ANNOTATION_CLASSES_ORDER:
            label_support = support.get(label, {})
            observed = label in support
            required_dits = (
                max(
                    thresholds["min_class_dit_groups"],
                    thresholds["min_core_class_dit_groups"],
                )
                if label in CORE_CLONALITY_LABELS
                else thresholds["min_class_dit_groups"]
            )
            class_records.append(
                {
                    "Assay": str(assay),
                    "ChemistLabel": label,
                    "Observed": bool(observed),
                    "Rows": int(label_support.get("rows") or 0),
                    "UniqueDITGroups": int(
                        label_support.get("unique_dit_groups") or 0
                    ),
                    "EffectiveDITGroups": float(
                        label_support.get("effective_dit_groups") or 0.0
                    ),
                    "MaxRowsPerDIT": int(
                        label_support.get("max_rows_per_dit") or 0
                    ),
                    "MaxDITRowFraction": float(
                        label_support.get("max_dit_row_fraction") or 0.0
                    ),
                    "SourceRunGroups": int(
                        label_support.get("unique_source_run_groups") or 0
                    ),
                    "RowsMissingSourceRun": int(
                        label_support.get("rows_missing_source_run") or 0
                    ),
                    "RequiredDITGroups": int(required_dits),
                    "RequiredSourceRunGroups": int(
                        thresholds["min_class_source_run_groups"]
                    ),
                    "StaticPromotionSupportPass": bool(
                        observed
                        and int(label_support.get("unique_dit_groups") or 0)
                        >= required_dits
                        and int(
                            label_support.get("unique_source_run_groups") or 0
                        )
                        >= thresholds["min_class_source_run_groups"]
                        and float(
                            label_support.get("max_dit_row_fraction") or 0.0
                        )
                        <= thresholds["max_class_dit_row_fraction"]
                        and int(label_support.get("rows_missing_source_run") or 0)
                        == 0
                    ),
                }
            )

    assays = pd.DataFrame(assay_records).sort_values(
        "Assay",
        kind="stable",
    ).reset_index(drop=True)
    classes = pd.DataFrame(class_records).sort_values(
        ["Assay", "ChemistLabel"],
        kind="stable",
    ).reset_index(drop=True)
    labeled_rows = int(
        merged[CHEMIST_LABEL_COLUMN].fillna("").astype(str).str.strip().ne("").sum()
    )
    candidate_assays = int(assays["CandidateReady"].sum()) if not assays.empty else 0
    promotion_assays = (
        int(assays["PromotionPreflightReady"].sum()) if not assays.empty else 0
    )
    if labeled_rows == 0:
        status = "awaiting_labels"
    elif promotion_assays:
        status = "promotion_preflight_ready"
    elif candidate_assays:
        status = "candidate_ready"
    else:
        status = "not_ready"
    report = {
        "schema_version": LABEL_READINESS_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "thresholds": thresholds,
        "available_rows": int(len(merged)),
        "labeled_rows": labeled_rows,
        "label_coverage": float(labeled_rows / len(merged)) if len(merged) else 0.0,
        "assay_count": int(len(assays)),
        "candidate_ready_assay_count": candidate_assays,
        "promotion_preflight_ready_assay_count": promotion_assays,
        "duplicate_labeled_rows_removed": int(duplicate_rows_removed),
        "label_counts": _counts(merged, CHEMIST_LABEL_COLUMN),
    }
    return LabelReadiness(report=report, assays=assays, classes=classes)


def write_clonality_label_readiness(
    readiness: LabelReadiness,
    output_dir: Path | str,
    *,
    source_workbook: Path | str,
    source_features: Path | str,
) -> dict[str, Path]:
    """Write aggregate readiness artifacts without patient-level rows."""
    output = Path(output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / READINESS_FILENAMES["report"]
    assays_path = output / READINESS_FILENAMES["assays"]
    classes_path = output / READINESS_FILENAMES["classes"]
    report = {
        **readiness.report,
        "source_workbook": str(Path(source_workbook).expanduser().resolve()),
        "source_features": str(Path(source_features).expanduser().resolve()),
        "output_files": {
            "assays": assays_path.name,
            "classes": classes_path.name,
        },
    }
    _atomic_write_csv(readiness.assays, assays_path)
    _atomic_write_csv(readiness.classes, classes_path)
    _atomic_write_text(
        report_path,
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
    )
    return {
        "report": report_path,
        "assays": assays_path,
        "classes": classes_path,
    }


def _candidate_blockers(
    rows: pd.DataFrame,
    support: Mapping[str, Mapping[str, int | float]],
    thresholds: Mapping[str, int | float],
) -> list[str]:
    blockers: list[str] = []
    if len(rows) < int(thresholds["min_samples"]):
        blockers.append(
            f"labeled_rows={len(rows)} below {int(thresholds['min_samples'])}"
        )
    for label in CORE_CLONALITY_LABELS:
        if label not in support:
            blockers.append(f"required_class={label} absent")
    if len(support) < 2:
        blockers.append("fewer than two observed chemist classes")
    if rows["DIT"].fillna("").astype(str).str.strip().eq("").any():
        blockers.append("one or more labeled rows have no DIT")
    for label, label_support in support.items():
        rows_for_label = int(label_support.get("rows") or 0)
        dit_groups = int(label_support.get("unique_dit_groups") or 0)
        run_groups = int(label_support.get("unique_source_run_groups") or 0)
        if rows_for_label < int(thresholds["min_class_training_rows_per_fold"]):
            blockers.append(
                f"class[{label}].rows={rows_for_label} below "
                f"{int(thresholds['min_class_training_rows_per_fold'])}"
            )
        if dit_groups < int(thresholds["min_class_evaluation_folds"]):
            blockers.append(
                f"class[{label}].dit_groups={dit_groups} below "
                f"{int(thresholds['min_class_evaluation_folds'])}"
            )
        if run_groups < min(
            int(thresholds["source_run_validation_folds"]),
            int(thresholds["min_class_source_run_groups"]),
        ):
            blockers.append(
                f"class[{label}].source_runs={run_groups} below grouped "
                "validation support"
            )
    return blockers


def _promotion_blockers(
    rows: pd.DataFrame,
    support: Mapping[str, Mapping[str, int | float]],
    thresholds: Mapping[str, int | float],
) -> list[str]:
    blockers: list[str] = []
    distinct_dits = int(
        rows["DIT"].fillna("").astype(str).str.strip().replace("", pd.NA).nunique()
    )
    if distinct_dits < int(thresholds["min_dit_groups"]):
        blockers.append(
            f"distinct_dits={distinct_dits} below "
            f"{int(thresholds['min_dit_groups'])}"
        )
    for label in CORE_CLONALITY_LABELS:
        if label not in support:
            blockers.append(f"required_class={label} absent")
    for label, label_support in support.items():
        required_dits = (
            max(
                int(thresholds["min_class_dit_groups"]),
                int(thresholds["min_core_class_dit_groups"]),
            )
            if label in CORE_CLONALITY_LABELS
            else int(thresholds["min_class_dit_groups"])
        )
        dit_groups = int(label_support.get("unique_dit_groups") or 0)
        run_groups = int(label_support.get("unique_source_run_groups") or 0)
        concentration = float(label_support.get("max_dit_row_fraction") or 0.0)
        missing_runs = int(label_support.get("rows_missing_source_run") or 0)
        if dit_groups < required_dits:
            blockers.append(
                f"class[{label}].dit_groups={dit_groups} below {required_dits}"
            )
        if run_groups < int(thresholds["min_class_source_run_groups"]):
            blockers.append(
                f"class[{label}].source_runs={run_groups} below "
                f"{int(thresholds['min_class_source_run_groups'])}"
            )
        if concentration > float(thresholds["max_class_dit_row_fraction"]):
            blockers.append(
                f"class[{label}].max_dit_fraction={concentration:.3f} above "
                f"{float(thresholds['max_class_dit_row_fraction']):.3f}"
            )
        if missing_runs:
            blockers.append(f"class[{label}].missing_source_runs={missing_runs}")
    return blockers


def _deduplicate_labeled_content(
    frame: pd.DataFrame,
    *,
    assay: str,
) -> tuple[pd.DataFrame, int]:
    if frame.empty:
        return frame.copy(), 0
    hashes = frame["FsaContentHash"].fillna("").astype(str).str.strip()
    if hashes.eq("").any():
        raise ValueError(f"assay {assay!r} has labeled rows without content hashes")
    working = frame.copy()
    working["_ContentHash"] = hashes
    grouped = working.groupby("_ContentHash", sort=False)
    conflicting_labels = grouped[CHEMIST_LABEL_COLUMN].nunique().gt(1)
    if conflicting_labels.any():
        raise ValueError(
            f"assay {assay!r} has {int(conflicting_labels.sum())} content "
            "hash(es) with conflicting chemist labels"
        )
    conflicting_runs = grouped["SourceRunKey"].nunique().gt(1)
    if conflicting_runs.any():
        raise ValueError(
            f"assay {assay!r} has {int(conflicting_runs.sum())} content "
            "hash(es) assigned to conflicting source runs"
        )
    keep = ~working["_ContentHash"].duplicated(keep="first")
    deduplicated = working.loc[keep].drop(columns=["_ContentHash"])
    return deduplicated, int(len(working) - len(deduplicated))


def _validate_thresholds(thresholds: Mapping[str, int | float]) -> None:
    integer_names = (
        "min_samples",
        "validation_folds",
        "source_run_validation_folds",
        "min_dit_groups",
        "min_class_dit_groups",
        "min_core_class_dit_groups",
        "min_class_source_run_groups",
        "min_class_evaluation_folds",
        "min_class_training_rows_per_fold",
    )
    for name in integer_names:
        if int(thresholds[name]) < 1:
            raise ValueError(f"{name} must be at least 1")
    fraction = float(thresholds["max_class_dit_row_fraction"])
    if not 0.0 < fraction <= 1.0:
        raise ValueError("max_class_dit_row_fraction must be in (0, 1]")


def _reject_duplicate_keys(
    frame: pd.DataFrame,
    columns: list[str],
    name: str,
) -> None:
    duplicate = frame.duplicated(subset=columns, keep=False)
    if duplicate.any():
        raise ValueError(
            f"{int(duplicate.sum())} {name} row(s) duplicate {'+'.join(columns)}"
        )


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} missing required columns: {', '.join(missing)}")


def _assay_key(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .upper()
    )


def _counts(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    values = frame[column].fillna("").astype(str).str.strip().replace("", "<missing>")
    return [
        {"value": str(value), "count": int(count)}
        for value, count in values.value_counts().items()
    ]


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


__all__ = [
    "LABEL_READINESS_SCHEMA_VERSION",
    "LabelReadiness",
    "assess_clonality_label_readiness",
    "write_clonality_label_readiness",
]
