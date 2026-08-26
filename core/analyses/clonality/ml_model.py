"""core/analyses/clonality/ml_model.py

Lazy-loading, per-assay wrapper around the joblib pickles that
``ml_training.serialize_model`` writes. Used by the runtime
hook ``attach_ml_prediction_if_enabled`` and by the GUI.

Layout on disk (one folder per assay):
    <model_dir>/
        FR1/
            random_forest-<sha256-prefix>.joblib
            metadata.json
        TCRG-A/
            random_forest-<sha256-prefix>.joblib
            metadata.json
        ...

Public surface (see __all__):
    ClonalityModelStore
    flatten_features_for_inference
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib  # noqa: F401 – eksplisitt modulattributt (tester monkeypatcher ml_model.joblib)
import numpy as np
import pandas as pd

from core.analyses.clonality.cohort_features import (
    COHORT_FEATURE_SCHEMA_VERSION,
)
from core.analyses.clonality.ml_data_contract import is_raw_trace_feature
from core.analyses.clonality.ml_training import (
    RUNTIME_MODEL_SCHEMA_VERSION,
    deserialize_model,
    verify_model_artifact,
)


__all__ = [
    "ClonalityModelStore",
    "DEFAULT_CLASSIFIER_KIND",
    "flatten_features_for_inference",
]


# Order preference when selecting which joblib under an assay folder
# to load first. A fresh immutable training output normally contains one.
DEFAULT_CLASSIFIER_KIND = "random_forest"
_CLASSIFIER_PREFERENCE = ("random_forest", "extra_trees", "qda_calibrated")


# Keys inside features dicts (from features_from_entry) that carry nested
# per-channel frames; we expand these into flat columns named
# ``<prefix>_<upper(channel)>``.
_NESTED_FIELD_EXPANSION: tuple[tuple[str, str], ...] = (
    ("peak_count_per_channel", "trace_peak_count"),
    ("peak_variance_per_channel", "trace_peak_variance"),
    ("mad_per_channel", "trace_mad"),
    ("dome_peak_count_per_channel", "trace_dome_peak_count"),
    ("dome_height_ratio_per_channel", "trace_dome_height_ratio"),
)


@dataclass
class _AssayArtifact:
    """One assay's preloaded joblib + metadata pair."""
    estimator: Any
    metadata: dict[str, Any]


@dataclass
class ClonalityModelStore:
    """Lazily load and cache per-assay ML models.

    Pass ``model_dir=None`` to disable. Empty (non-model) dirs are
    tolerated; unknown assays gracefully return ``None`` from
    ``predict``.

    No sklearn import is required to construct the store; we only
    invoke sklearn inside ``predict`` once an assay is requested.
    """
    model_dir: Path | None = None
    _cache: dict[str, _AssayArtifact] = field(default_factory=dict)
    _available: set[str] = field(default_factory=set)
    _discovered: bool = False

    def __post_init__(self) -> None:
        # Eagerly discover at construction so ``is_enabled`` does not
        # need to read the disk on every call. Cheap: one stat per dir.
        if self.model_dir is not None:
            self._discover()

    def is_enabled(self, assay: str) -> bool:
        return self.load_validated_artifact(assay) is not None

    def has_eligible_models(self) -> bool:
        """Return whether at least one artifact passes load-time validation."""
        return any(
            self.load_validated_artifact(assay) is not None
            for assay in sorted(self._available)
        )

    def required_feature_columns(self, assay: str) -> list[str]:
        """Return an eligible assay artifact's ordered feature contract."""
        loaded = self.load_validated_artifact(assay)
        if loaded is None:
            return []
        _estimator, metadata = loaded
        return [
            str(column)
            for column in (metadata.get("feature_columns") or ())
        ]

    def load_validated_artifact(
        self,
        assay: str,
    ) -> tuple[Any, dict[str, Any]] | None:
        """Load one integrity-checked, promotion-eligible assay artifact."""
        if self.model_dir is None or not assay:
            return None
        norm = _normalise_assay(assay)
        if norm not in self._available:
            return None
        artifact = self._cache.get(norm) or self._load_assay(norm)
        if artifact is None:
            return None
        return artifact.estimator, dict(artifact.metadata)

    def predict(
        self,
        assay: str,
        features: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Predict a single (assay, features) tuple.

        Returns ``None`` when ML is disabled or unknown for ``assay``.
        Otherwise returns::

            {
                "label":          "monoklonal" | ... ,
                "confidence":     0.0 .. 1.0,
                "review_needed":  bool,
                "model_version":  <metadata.schema_version>,
                "threshold_tau":  float,
                "all_scores":     {label: prob, ...} (best-effort; absent if
                                  the estimator has no predict_proba),
            }
        """
        loaded = self.load_validated_artifact(assay)
        if loaded is None:
            return None
        estimator, metadata = loaded
        if features is None:
            return None

        feature_columns = list(metadata.get("feature_columns") or ())
        if not feature_columns:
            return None

        X = flatten_features_for_inference(
            dict(features), columns=feature_columns,
        )
        if X.empty:
            return None
        try:
            proba = estimator.predict_proba(_estimator_input(estimator, X))
        except Exception:  # noqa: BLE001 - defensive: any sklearn quirk
            return None

        classes_attr = getattr(estimator, "classes_", None)
        if classes_attr is None:
            return None
        classes = [str(c) for c in np.asarray(classes_attr).tolist()]
        if proba.shape[0] != 1 or not classes:
            return None

        row = np.asarray(proba[0])
        best_idx = int(np.argmax(row))
        label = classes[best_idx]
        confidence = float(row[best_idx])

        # Multi-class absolute confidence check (calibrated RF gives
        # well-scaled probs; we use max prob).
        tau = float(metadata.get("accept_threshold_tau") or 0.80)
        review_needed = bool(confidence < tau)

        all_scores = {str(classes[i]): float(row[i]) for i in range(len(classes))}
        return {
            "label": label,
            "confidence": confidence,
            "review_needed": review_needed,
            "model_version": str(metadata.get("schema_version") or ""),
            "threshold_tau": tau,
            "all_scores": all_scores,
        }

    # ---- internals ------------------------------------------------------

    def _discover(self) -> None:
        if self.model_dir is None:
            return
        root = Path(self.model_dir)
        self._available = set()
        if not root.exists() or not root.is_dir():
            return
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            meta = child / "metadata.json"
            if not meta.exists():
                continue
            try:
                metadata = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not _runtime_eligible_metadata(metadata):
                continue
            classifier_kind = str(metadata.get("classifier_kind") or "")
            artifact_name = _artifact_joblib_name(metadata)
            artifact_path = child / artifact_name if artifact_name else None
            if (
                classifier_kind in _CLASSIFIER_PREFERENCE
                and artifact_name is not None
                and artifact_path is not None
                and artifact_path.is_file()
            ):
                try:
                    verify_model_artifact(artifact_path, metadata)
                except ValueError:
                    continue
                # Register common spellings plus the separator-free key used
                # by runtime assay classifiers (TCRG-A vs TCRGA).
                self._available.add(child.name)
                self._available.add(child.name.upper())
                self._available.add(_assay_key(child.name))
        self._discovered = True

    def _load_assay(self, norm_assay: str) -> _AssayArtifact | None:
        if self.model_dir is None:
            return None
        # We may have registered an uppercase variant; resolve back to
        # the actual on-disk folder name.
        candidates = _resolve_assay_path(self.model_dir, norm_assay)
        if not candidates:
            return None
        assay_dir = candidates[0]
        meta_path = assay_dir / "metadata.json"
        if not meta_path.exists():
            return None
        try:
            metadata_preview = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not _runtime_eligible_metadata(metadata_preview):
            return None
        artifact_name = _artifact_joblib_name(metadata_preview)
        if artifact_name is None:
            return None
        joblib_path = assay_dir / artifact_name
        if not joblib_path.is_file():
            return None
        try:
            estimator, metadata = deserialize_model(
                joblib_path=joblib_path, metadata_path=meta_path,
            )
        except Exception:  # noqa: BLE001 - load tolerance
            return None
        if not _runtime_eligible_metadata(metadata):
            return None
        if _assay_key(metadata.get("assay")) != _assay_key(assay_dir.name):
            return None
        if metadata != metadata_preview:
            return None
        if not _estimator_calibration_matches_metadata(estimator, metadata):
            return None
        artifact = _AssayArtifact(estimator=estimator, metadata=metadata)
        self._cache[norm_assay] = artifact
        return artifact


def _normalise_assay(assay: str | None) -> str:
    """Normalise assay key for folder lookup.

    Mirrors the canonical form used by the trainer, which is just
    the original spelling (the metadata.json carries ``assay``+``feature_columns``).
    Falls back to a stable strip/upper form for case-folded queries.
    """
    if not assay:
        return ""
    s = str(assay).strip()
    if not s:
        return ""
    # The trained pipeline saves the assay using the exact form passed in
    # (e.g. "FR1", "TCRG-A"), while runtime classifiers sometimes emit a
    # compact form ("TCRGA"). Use the compact key for cache/discovery and let
    # _resolve_assay_path map back to the on-disk spelling.
    return _assay_key(s)


def _assay_key(assay: str | None) -> str:
    return str(assay or "").strip().replace(" ", "").replace("-", "").replace("_", "").upper()


def _resolve_assay_path(model_dir: Path, raw_assay: str) -> list[Path]:
    """Return the candidate assay folder names under model_dir."""
    s = str(raw_assay).strip()
    candidates = []
    for c in (s, s.upper(), s.replace("-", "_"), s.replace("_", "-")):
        if c and (model_dir / c).is_dir():
            candidates.append(model_dir / c)
    raw_key = _assay_key(s)
    for child in sorted(Path(model_dir).iterdir()):
        if child.is_dir() and _assay_key(child.name) == raw_key and child not in candidates:
            candidates.append(child)
    return candidates


def _estimator_input(estimator: Any, X: pd.DataFrame) -> pd.DataFrame | np.ndarray:
    """Return X in the shape least likely to trigger sklearn feature warnings."""
    feature_names = getattr(estimator, "feature_names_in_", None)
    if feature_names is None:
        return X.values
    names = [str(name) for name in np.asarray(feature_names).tolist()]
    if all(name in X.columns for name in names):
        return X[names]
    return X


def _runtime_eligible_metadata(metadata: Mapping[str, Any]) -> bool:
    validation = metadata.get("validation")
    if not isinstance(validation, Mapping):
        return False
    promotion_gate = validation.get("promotion_gate")
    if not isinstance(promotion_gate, Mapping):
        return False
    class_support_gate = validation.get("class_support_gate")
    if not isinstance(class_support_gate, Mapping):
        return False
    class_support_thresholds = class_support_gate.get("thresholds")
    if not isinstance(class_support_thresholds, Mapping):
        return False
    calibration_gate = validation.get("calibration_gate")
    if not isinstance(calibration_gate, Mapping):
        return False
    run_stress = validation.get("source_run_stress")
    if not isinstance(run_stress, Mapping):
        return False
    run_gate = run_stress.get("promotion_gate")
    if not isinstance(run_gate, Mapping):
        return False
    feature_columns = metadata.get("feature_columns")
    if not isinstance(feature_columns, list):
        return False
    data_provenance = metadata.get("training_data_provenance")
    if not isinstance(data_provenance, Mapping):
        return False
    training_class_support = metadata.get("training_class_support")
    if not isinstance(training_class_support, Mapping):
        return False
    final_fit_calibration = metadata.get("final_fit_calibration")
    if not isinstance(final_fit_calibration, Mapping):
        return False
    if not _valid_artifact_manifest(metadata):
        return False
    try:
        effective_splits = int(validation.get("effective_splits") or 0)
        unique_primary_groups = int(validation.get("unique_groups") or 0)
        primary_validation_rows = int(validation.get("row_count") or 0)
        run_effective_splits = int(run_stress.get("effective_splits") or 0)
        unique_run_groups = int(run_stress.get("unique_groups") or 0)
        run_validation_rows = int(run_stress.get("row_count") or 0)
        group_provenance = validation.get("group_provenance")
        content_hash_coverage = float(
            group_provenance.get("content_hash_coverage") or 0.0
            if isinstance(group_provenance, Mapping)
            else 0.0
        )
        training_hash_coverage = float(
            data_provenance.get("content_hash_coverage") or 0.0
        )
        raw_training_rows = int(data_provenance.get("raw_row_count") or 0)
        fitted_training_rows = int(metadata.get("training_rows") or 0)
        unique_trace_rows = int(
            data_provenance.get("unique_trace_row_count") or 0
        )
        duplicate_rows_removed = int(
            data_provenance.get("duplicate_rows_removed") or 0
        )
        conflicting_label_hashes = int(
            data_provenance.get("conflicting_label_content_hashes") or 0
        )
        conflicting_run_hashes = int(
            data_provenance.get("conflicting_source_run_content_hashes") or 0
        )
        max_class_dit_row_fraction = float(
            class_support_thresholds.get("max_class_dit_row_fraction")
        )
    except (TypeError, ValueError):
        return False
    requires_cohort_context = any(
        str(column).startswith("cohort_") for column in feature_columns
    )
    cohort_schema_compatible = (
        not requires_cohort_context
        or metadata.get("cohort_feature_schema_version")
        == COHORT_FEATURE_SCHEMA_VERSION
    )
    content_grouping_compatible = bool(
        isinstance(group_provenance, Mapping)
        and group_provenance.get("method")
        == "dit_fsa_content_connected_components"
        and content_hash_coverage == 1.0
    )
    deduplication_compatible = bool(
        data_provenance.get("method") == "per_assay_fsa_content_hash_v1"
        and training_hash_coverage == 1.0
        and raw_training_rows >= unique_trace_rows > 0
        and duplicate_rows_removed
        == raw_training_rows - unique_trace_rows
        and fitted_training_rows
        == primary_validation_rows
        == run_validation_rows
        == unique_trace_rows
        and conflicting_label_hashes == 0
        and conflicting_run_hashes == 0
    )
    class_support_compatible = _valid_training_class_support(
        training_class_support,
        max_dit_row_fraction=max_class_dit_row_fraction,
    )
    primary_fold_support_compatible = _valid_class_fold_support(validation)
    run_fold_support_compatible = _valid_class_fold_support(run_stress)
    calibration_compatible = _valid_calibration_provenance(
        classifier_kind=str(metadata.get("classifier_kind") or ""),
        validation=validation,
        run_stress=run_stress,
        final_fit=final_fit_calibration,
    )
    return bool(
        metadata.get("schema_version") == RUNTIME_MODEL_SCHEMA_VERSION
        and metadata.get("deployment_status") == "validated"
        and metadata.get("runtime_eligible") is True
        and metadata.get("trace_feature_schema_version")
        == "clonality_trace_features_v1"
        and cohort_schema_compatible
        and any(is_raw_trace_feature(column) for column in feature_columns)
        and validation.get("strategy") == "StratifiedGroupKFold"
        and validation.get("group_column") == "DITContentComponent"
        and validation.get("every_row_oof_once") is True
        and effective_splits >= 2
        and unique_primary_groups >= 2
        and content_grouping_compatible
        and deduplication_compatible
        and class_support_compatible
        and primary_fold_support_compatible
        and run_fold_support_compatible
        and class_support_gate.get("passed") is True
        and calibration_compatible
        and calibration_gate.get("passed") is True
        and promotion_gate.get("passed") is True
        and run_stress.get("status") == "complete"
        and run_stress.get("strategy") == "StratifiedGroupKFold"
        and run_stress.get("group_column") == "SourceRunKey"
        and run_stress.get("every_row_oof_once") is True
        and run_effective_splits >= 2
        and unique_run_groups >= 2
        and run_gate.get("passed") is True
    )


def _artifact_joblib_name(metadata: Mapping[str, Any]) -> str | None:
    artifact = metadata.get("artifact")
    if not isinstance(artifact, Mapping):
        return None
    value = str(artifact.get("joblib_file") or "")
    if not value or Path(value).name != value:
        return None
    return value


def _valid_artifact_manifest(metadata: Mapping[str, Any]) -> bool:
    artifact = metadata.get("artifact")
    if not isinstance(artifact, Mapping):
        return False
    classifier_kind = str(metadata.get("classifier_kind") or "")
    joblib_file = _artifact_joblib_name(metadata)
    digest = str(artifact.get("joblib_sha256") or "").lower()
    try:
        size_bytes = int(artifact.get("joblib_size_bytes"))
    except (TypeError, ValueError):
        return False
    return bool(
        artifact.get("format") == "joblib"
        and artifact.get("hash_algorithm") == "sha256"
        and joblib_file
        and joblib_file.startswith(f"{classifier_kind}-")
        and joblib_file.endswith(".joblib")
        and len(digest) == 64
        and all(char in "0123456789abcdef" for char in digest)
        and size_bytes > 0
    )


def _valid_training_class_support(
    support: Mapping[str, Any],
    *,
    max_dit_row_fraction: float,
) -> bool:
    if not support:
        return False
    if not 0.0 < float(max_dit_row_fraction) <= 1.0:
        return False
    for label, values in support.items():
        if not str(label) or not isinstance(values, Mapping):
            return False
        try:
            rows = int(values.get("rows") or 0)
            dit_groups = int(values.get("unique_dit_groups") or 0)
            effective_dits = float(
                values.get("effective_dit_groups") or 0.0
            )
            max_dit_rows = int(values.get("max_rows_per_dit") or 0)
            max_dit_fraction = float(
                values.get("max_dit_row_fraction") or 0.0
            )
            run_groups = int(values.get("unique_source_run_groups") or 0)
            missing_runs = int(values.get("rows_missing_source_run") or 0)
        except (TypeError, ValueError):
            return False
        if (
            rows <= 0
            or dit_groups <= 0
            or not 0.0 < effective_dits <= dit_groups
            or not 0 < max_dit_rows <= rows
            or not 0.0 < max_dit_fraction <= 1.0
            or max_dit_fraction > float(max_dit_row_fraction)
            or abs(max_dit_fraction - max_dit_rows / rows) > 1e-9
            or run_groups <= 0
            or missing_runs
        ):
            return False
    return all(label in support for label in ("monoklonal", "polyklonal"))


def _valid_class_fold_support(container: Mapping[str, Any]) -> bool:
    fold_support = container.get("class_fold_support")
    if not isinstance(fold_support, Mapping):
        return False
    try:
        effective_splits = int(container.get("effective_splits") or 0)
    except (TypeError, ValueError):
        return False
    if effective_splits < 2:
        return False
    required_evaluation_folds = min(2, effective_splits)
    for label in ("monoklonal", "polyklonal"):
        values = fold_support.get(label)
        if not isinstance(values, Mapping):
            return False
        try:
            total_folds = int(values.get("total_folds") or 0)
            training_folds = int(
                values.get("training_folds_with_examples") or 0
            )
            evaluation_folds = int(
                values.get("evaluation_folds_with_examples") or 0
            )
            minimum_training_rows = int(values.get("min_train_rows") or 0)
        except (TypeError, ValueError):
            return False
        if (
            total_folds != effective_splits
            or training_folds != effective_splits
            or evaluation_folds < required_evaluation_folds
            or minimum_training_rows < 6
        ):
            return False
    return True


def _valid_calibration_provenance(
    *,
    classifier_kind: str,
    validation: Mapping[str, Any],
    run_stress: Mapping[str, Any],
    final_fit: Mapping[str, Any],
) -> bool:
    if classifier_kind not in {"random_forest", "extra_trees"}:
        return final_fit.get("status") == "native_probability"
    try:
        primary_folds = int(validation.get("effective_splits") or 0)
        run_folds = int(run_stress.get("effective_splits") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        _valid_calibration_manifest(
            validation.get("calibration"),
            expected_folds=primary_folds,
        )
        and _valid_calibration_manifest(
            run_stress.get("calibration"),
            expected_folds=run_folds,
        )
        and _valid_calibration_record(final_fit)
    )


def _valid_calibration_manifest(
    value: Any,
    *,
    expected_folds: int,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    folds = value.get("folds")
    if not isinstance(folds, list) or not folds:
        return False
    try:
        fold_count = int(value.get("fold_count") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        value.get("required_for_runtime") is True
        and value.get("method") == "sigmoid"
        and value.get("group_column") == "DITContentComponent"
        and value.get("every_fold_complete") is True
        and value.get("every_fold_grouped") is True
        and fold_count == expected_folds == len(folds)
        and all(
            _valid_calibration_record(fold)
            for fold in folds
            if isinstance(fold, Mapping)
        )
        and all(isinstance(fold, Mapping) for fold in folds)
    )


def _valid_calibration_record(value: Mapping[str, Any]) -> bool:
    try:
        folds = int(value.get("folds") or 0)
        unique_groups = int(value.get("unique_groups") or 0)
        min_train = int(value.get("minimum_train_class_rows") or 0)
        min_test = int(value.get("minimum_test_class_rows") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        value.get("status") == "complete"
        and value.get("required_for_runtime") is True
        and value.get("method") == "sigmoid"
        and value.get("strategy") == "StratifiedGroupKFold"
        and value.get("group_column") == "DITContentComponent"
        and value.get("grouped") is True
        and value.get("every_group_held_out_once") is True
        and folds == 3
        and unique_groups >= 3
        and min_train >= 2
        and min_test >= 2
    )


def _estimator_calibration_matches_metadata(
    estimator: Any,
    metadata: Mapping[str, Any],
) -> bool:
    actual = getattr(estimator, "hemafrag_calibration_", None)
    expected = metadata.get("final_fit_calibration")
    if not isinstance(actual, Mapping) or not isinstance(expected, Mapping):
        return False
    classifier_kind = str(metadata.get("classifier_kind") or "")
    if classifier_kind in {"random_forest", "extra_trees"}:
        if not _valid_calibration_record(actual):
            return False
        fields = (
            "status",
            "method",
            "strategy",
            "group_column",
            "grouped",
            "folds",
            "unique_groups",
            "minimum_train_class_rows",
            "minimum_test_class_rows",
            "every_group_held_out_once",
        )
        return all(actual.get(field) == expected.get(field) for field in fields)
    return (
        actual.get("status") == "native_probability"
        and expected.get("status") == "native_probability"
    )


def flatten_features_for_inference(
    features: Mapping[str, Any],
    *,
    columns: Sequence[str],
) -> pd.DataFrame:
    """Project a runtime ``features_from_entry`` dict into the column
    layout expected by the loaded estimator.

    - Numeric, float-ish, and bool scalars fill 0.0 on column miss.
    - Nested per-``DATA*`` dicts (``peak_count_per_channel.DATA1``)
      expand to columns named with the chosen prefix.
    - Anything not in ``columns`` is ignored.
    - Missing values are filled with 0.0; non-finite values too. The
      loaded estimator (with its own sklearn imputer, if any) is the
      authoritative normaliser — this helper just guarantees shape.
    """
    if not columns:
        return pd.DataFrame()
    flat: dict[str, Any] = {}

    # First pass: numeric scalars / strings / lists
    for key, value in features.items():
        if key in columns:
            flat[key] = value

    # Second pass: nested per-channel fields
    for raw_key, nested in features.items():
        if not isinstance(nested, Mapping):
            continue
        for nested_key, sub_value in nested.items():
            dotted = f"{raw_key}.{str(nested_key).upper()}"
            if dotted in columns:
                flat[dotted] = sub_value

    # Backward-compatible aliases used by the first synthetic model artifacts.
    for raw_key, prefix in _NESTED_FIELD_EXPANSION:
        nested = features.get(raw_key)
        if not isinstance(nested, dict):
            continue
        for channel, sub_value in nested.items():
            channel_key = str(channel).upper()
            for col in (
                f"{prefix}_{channel_key}",
                f"{raw_key}.{channel_key}",
            ):
                if col in columns:
                    flat[col] = sub_value

    # Third pass: ensure every required column is present with at least NaN
    for col in columns:
        flat.setdefault(col, np.nan)

    df = pd.DataFrame([{col: flat.get(col, np.nan) for col in columns}],
                      columns=list(columns))
    # Coerce to numeric (non-numeric -> NaN); the imputer in the loaded
    # scikit-learn pipeline is expected to handle NaN when present.
    for col in df.columns:
        series = df[col]
        if series.dtype == object or series.dtype.name == "category":
            df[col] = pd.to_numeric(series, errors="coerce")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df
