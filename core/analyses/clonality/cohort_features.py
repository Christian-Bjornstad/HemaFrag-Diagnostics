"""Leakage-safe same-run patient and replicate context for clonality ML."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


COHORT_FEATURE_SCHEMA_VERSION = "clonality_cohort_features_v1"
COHORT_FEATURE_FIELDS = (
    "cohort_context_available",
    "cohort_patient_entry_count",
    "cohort_patient_assay_count",
    "cohort_panel_completeness",
    "cohort_same_assay_entry_count",
    "cohort_same_assay_replicate_count",
    "cohort_replicate_bp_observation_count",
    "cohort_replicate_nearest_delta_bp",
    "cohort_replicate_mean_delta_bp",
    "cohort_replicate_max_delta_bp",
    "cohort_replicate_within_2bp_fraction",
    "cohort_replicate_concordant",
)

_CANONICAL_PANEL = {
    "FR1",
    "FR2",
    "FR3",
    "IGK",
    "KDE",
    "TCRGA",
    "TCRGB",
    "TCRBA",
    "TCRBB",
    "TCRBC",
    "DHJHD",
    "DHJHE",
}


def cohort_context_features(
    current: Mapping[str, Any],
    same_run_patient_rows: Iterable[Mapping[str, Any]],
) -> dict[str, float | int]:
    """Summarize context available when this same run is reported."""
    siblings = list(same_run_patient_rows)
    dit = _text(_value(current, "DIT", "dit"))
    if not dit:
        return _empty_context()

    current_assay = _assay_key(_value(current, "Assay", "assay"))
    current_identity = _identity(current)
    assay_keys = {
        _assay_key(_value(row, "Assay", "assay"))
        for row in siblings
    }
    assay_keys.discard("")
    panel_count = len(assay_keys & _CANONICAL_PANEL)
    same_assay = [
        row
        for row in siblings
        if _assay_key(_value(row, "Assay", "assay")) == current_assay
    ]
    replicates = [
        row for row in same_assay if _identity(row) != current_identity
    ]
    current_bp = _finite_number(_value(current, "dominant_peak_basepairs"))
    deltas: list[float] = []
    if current_bp is not None:
        for row in replicates:
            sibling_bp = _finite_number(
                _value(row, "dominant_peak_basepairs")
            )
            if sibling_bp is not None:
                deltas.append(abs(current_bp - sibling_bp))

    delta_array = np.asarray(deltas, dtype=float)
    observation_count = int(delta_array.size)
    return {
        "cohort_context_available": 1,
        "cohort_patient_entry_count": int(len(siblings)),
        "cohort_patient_assay_count": int(len(assay_keys)),
        "cohort_panel_completeness": float(
            panel_count / len(_CANONICAL_PANEL)
        ),
        "cohort_same_assay_entry_count": int(len(same_assay)),
        "cohort_same_assay_replicate_count": int(len(replicates)),
        "cohort_replicate_bp_observation_count": observation_count,
        "cohort_replicate_nearest_delta_bp": (
            float(np.min(delta_array)) if observation_count else 0.0
        ),
        "cohort_replicate_mean_delta_bp": (
            float(np.mean(delta_array)) if observation_count else 0.0
        ),
        "cohort_replicate_max_delta_bp": (
            float(np.max(delta_array)) if observation_count else 0.0
        ),
        "cohort_replicate_within_2bp_fraction": (
            float(np.mean(delta_array <= 2.0)) if observation_count else 0.0
        ),
        "cohort_replicate_concordant": int(
            observation_count > 0 and bool(np.all(delta_array <= 2.0))
        ),
    }


def enrich_feature_frame_with_cohort_context(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Add same-run cohort fields to a flat local feature artifact."""
    if frame.empty:
        return frame.copy()
    required = {"DIT", "Assay", "SourceRunKey"}
    if not required.issubset(frame.columns):
        raise KeyError("cohort enrichment requires DIT and Assay columns")

    enriched = frame.copy().reset_index(drop=True)
    enriched["_CohortRowIndex"] = np.arange(len(enriched), dtype=int)
    for field in COHORT_FEATURE_FIELDS:
        enriched[field] = 0.0
    group_columns = ["DIT", "SourceRunKey"]

    dit_text = enriched["DIT"].fillna("").astype(str).str.strip()
    run_text = enriched["SourceRunKey"].fillna("").astype(str).str.strip()
    patient_mask = enriched.apply(_is_patient_context_row, axis=1)
    patient_rows = enriched.loc[
        dit_text.ne("") & run_text.ne("") & patient_mask
    ]
    for _key, group in patient_rows.groupby(
        group_columns,
        dropna=False,
        sort=False,
    ):
        records = group.to_dict(orient="records")
        by_index = {
            int(record["_CohortRowIndex"]): record for record in records
        }
        for row_index, current in by_index.items():
            context = cohort_context_features(current, records)
            for field, value in context.items():
                enriched.at[row_index, field] = value
    return enriched.drop(columns=["_CohortRowIndex"])


def enrich_entries_with_cohort_context(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inject same-run context into analyzed entries before ML inference."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        dit = _text(_value(entry, "DIT", "dit"))
        if not dit:
            continue
        source_run = _source_run_key(
            _value(entry, "SourceRunKey", "source_run_dir")
        )
        if not source_run or not _is_patient_context_row(entry):
            continue
        groups.setdefault((dit, source_run), []).append(entry)

    for group_entries in groups.values():
        for entry in group_entries:
            context = cohort_context_features(entry, group_entries)
            rule_result = entry.get("clonality_interpretation")
            rule_features = (
                rule_result.get("features")
                if isinstance(rule_result, Mapping)
                else None
            )
            base_features = (
                dict(rule_features)
                if isinstance(rule_features, Mapping)
                else {}
            )
            existing_features = entry.get("features")
            if isinstance(existing_features, Mapping):
                base_features.update(existing_features)
            base_features.update(context)
            entry["features"] = base_features
            if isinstance(rule_result, dict):
                rule_result["features"] = {
                    **dict(rule_result.get("features") or {}),
                    **context,
                }
    return entries


def _empty_context() -> dict[str, float | int]:
    return {field: 0 for field in COHORT_FEATURE_FIELDS}


def _value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    features = row.get("features")
    if isinstance(features, Mapping):
        for key in keys:
            if key in features and features.get(key) not in (None, ""):
                return features.get(key)
    rule = row.get("clonality_interpretation")
    if isinstance(rule, Mapping):
        nested = rule.get("features")
        if isinstance(nested, Mapping):
            for key in keys:
                if key in nested and nested.get(key) not in (None, ""):
                    return nested.get(key)
    return ""


def _identity(row: Mapping[str, Any]) -> str:
    return _text(
        _value(
            row,
            "_CohortRowIndex",
            "IdentityKey",
            "identity_key",
            "file_name",
            "File",
        )
    )


def _source_run_key(value: Any) -> str:
    text = _text(value).replace("\\", "/").rstrip("/")
    return Path(text).name if text else ""


def _is_patient_context_row(row: Mapping[str, Any]) -> bool:
    assay = _assay_key(_value(row, "Assay", "assay"))
    sample_kind = _text(_value(row, "SampleKind", "sample_kind")).lower()
    control = _text(_value(row, "Control", "control")).lower()
    return (
        assay != "SL"
        and sample_kind != "control"
        and control not in {"1", "true", "yes", "control"}
    )


def _assay_key(value: Any) -> str:
    return (
        _text(value)
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .upper()
    )


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


__all__ = [
    "COHORT_FEATURE_FIELDS",
    "COHORT_FEATURE_SCHEMA_VERSION",
    "cohort_context_features",
    "enrich_entries_with_cohort_context",
    "enrich_feature_frame_with_cohort_context",
]
