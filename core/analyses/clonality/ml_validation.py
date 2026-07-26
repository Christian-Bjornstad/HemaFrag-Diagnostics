"""Patient-grouped validation and review artifacts for clonality ML."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import StratifiedGroupKFold

from core.analyses.clonality.ml_training import (
    CALIBRATION_FOLDS,
    CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT,
    TREE_CLASSIFIER_KINDS,
    PerAssayDataset,
    PerAssayMetrics,
    fit_classifier,
    per_assay_metrics,
)


REVIEW_ROUTED_LABELS = {
    "bi_oligoklonal",
    "irregulaer",
    "pseudoklonal",
    "intet_pcr_produkt_darlig_dna",
    "qc_teknisk_fail",
    "usikker_review",
}
CORE_CLONALITY_LABELS = ("monoklonal", "polyklonal")


@dataclass
class GroupedValidationResult:
    predictions: pd.DataFrame
    review_cases: pd.DataFrame
    fold_metrics: pd.DataFrame
    drift_summary: pd.DataFrame
    feature_importance: pd.DataFrame
    aggregate_metrics: PerAssayMetrics
    split_manifest: dict[str, Any]


@dataclass
class PromotionGate:
    passed: bool
    reasons: list[str]
    thresholds: dict[str, float | int]


def grouped_oof_validate(
    dataset: PerAssayDataset,
    *,
    classifier_kind: str,
    n_splits: int = 5,
    random_state: int = 12345,
    accept_threshold_tau: float = 0.85,
    importance_max_features: int = 25,
    importance_repeats: int = 1,
    validation_groups: pd.Series | None = None,
    group_column: str = "DIT",
    calibration_groups: pd.Series | None = None,
    calibration_group_column: str = "DITContentComponent",
) -> GroupedValidationResult:
    """Evaluate every row out of fold while keeping each group in one fold."""
    groups = (
        dataset.dit.reset_index(drop=True).copy()
        if validation_groups is None
        else pd.Series(validation_groups).reset_index(drop=True)
    )
    if len(groups) != dataset.n_samples:
        raise ValueError(
            f"{group_column} validation groups do not match assay rows"
        )
    groups = groups.fillna("").astype(str).str.strip()
    if groups.eq("").any():
        raise ValueError(
            f"{group_column} validation requires a non-empty group for every row"
        )
    unique_groups = int(groups.nunique())
    effective_splits = min(max(2, int(n_splits)), unique_groups)
    if unique_groups < 2:
        raise ValueError(
            f"assay {dataset.assay!r} has fewer than two unique "
            f"{group_column} groups"
        )
    if dataset.y.nunique() < 2:
        raise ValueError(
            f"assay {dataset.assay!r} has fewer than two chemist label classes"
        )
    calibration_values = (
        dataset.dit.reset_index(drop=True).copy()
        if calibration_groups is None
        else pd.Series(calibration_groups).reset_index(drop=True)
    )
    if len(calibration_values) != dataset.n_samples:
        raise ValueError("calibration groups do not match assay rows")

    splitter = StratifiedGroupKFold(
        n_splits=effective_splits,
        shuffle=True,
        random_state=int(random_state),
    )
    prediction_frames: list[pd.DataFrame] = []
    fold_records: list[dict[str, Any]] = []
    split_records: list[dict[str, Any]] = []
    importance_records: list[dict[str, Any]] = []

    for fold, (train_idx, test_idx) in enumerate(
        splitter.split(dataset.X, dataset.y, groups=groups),
        start=1,
    ):
        train_groups = set(groups.iloc[train_idx])
        test_groups = set(groups.iloc[test_idx])
        if train_groups & test_groups:
            raise AssertionError(
                f"{group_column} leakage detected in grouped validation"
            )

        estimator = fit_classifier(
            dataset.X.iloc[train_idx],
            dataset.y.iloc[train_idx],
            kind=classifier_kind,
            random_state=int(random_state) + fold - 1,
            calibration_groups=calibration_values.iloc[train_idx],
            calibration_group_column=calibration_group_column,
        )
        calibration = dict(
            getattr(estimator, "hemafrag_calibration_", {}) or {}
        )
        X_test = dataset.X.iloc[test_idx]
        y_test = dataset.y.iloc[test_idx].reset_index(drop=True)
        y_pred = np.asarray(estimator.predict(X_test), dtype=str)
        probabilities = _predict_probabilities(estimator, X_test)
        classes = _estimator_classes(estimator, y_pred)
        confidence = _prediction_confidence(probabilities, y_pred, classes)
        importance_records.extend(
            _fold_permutation_importance(
                estimator,
                X_test,
                y_test,
                fold=fold,
                max_features=importance_max_features,
                repeats=importance_repeats,
                random_state=int(random_state) + fold - 1,
            )
        )
        fold_metric = per_assay_metrics(
            y_test,
            y_pred,
            probabilities,
            classes=classes,
            assay=dataset.assay,
            training_samples=int(len(train_idx)),
            rare_class_counts=dataset.rare_class_counts,
            accept_threshold_tau=accept_threshold_tau,
            classifier_kind=classifier_kind,
        )
        fold_records.append(
            {
                "Fold": fold,
                "TrainRows": int(len(train_idx)),
                "TestRows": int(len(test_idx)),
                "ValidationGroupColumn": str(group_column),
                "TrainGroups": int(len(train_groups)),
                "TestGroups": int(len(test_groups)),
                "MacroF1": fold_metric.macro_f1,
                "BalancedAccuracy": fold_metric.balanced_accuracy,
                "MonoklonalF1": fold_metric.monoklonal_f1,
                "Accuracy": fold_metric.accuracy,
                "AcceptedAccuracy": fold_metric.accepted_accuracy,
                "AcceptedCoverage": fold_metric.accepted_coverage,
                "ExpectedCalibrationError": (
                    fold_metric.expected_calibration_error
                ),
                "CalibrationStatus": calibration.get("status", ""),
                "CalibrationStrategy": calibration.get("strategy", ""),
                "CalibrationGroups": int(
                    calibration.get("unique_groups") or 0
                ),
            }
        )
        split_records.append(
            {
                "fold": fold,
                "train_rows": int(len(train_idx)),
                "test_rows": int(len(test_idx)),
                "train_groups": int(len(train_groups)),
                "test_groups": int(len(test_groups)),
                "test_label_counts": {
                    str(key): int(value)
                    for key, value in y_test.value_counts().sort_index().items()
                },
                "train_label_counts": {
                    str(key): int(value)
                    for key, value in (
                        dataset.y.iloc[train_idx]
                        .value_counts()
                        .sort_index()
                        .items()
                    )
                },
                "calibration": calibration,
            }
        )
        prediction_frames.append(
            _prediction_frame(
                dataset,
                test_idx=np.asarray(test_idx),
                fold=fold,
                predictions=y_pred,
                confidence=confidence,
                probabilities=probabilities,
                classes=classes,
                accept_threshold_tau=accept_threshold_tau,
            )
        )

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        .sort_values("RowIndex", kind="stable")
        .reset_index(drop=True)
    )
    if len(predictions) != dataset.n_samples:
        raise AssertionError("grouped validation did not predict every assay row once")
    if predictions["RowIndex"].duplicated().any():
        raise AssertionError("grouped validation predicted an assay row more than once")

    aggregate = per_assay_metrics(
        predictions["ChemistLabel"],
        predictions["MLSuggestion"],
        None,
        classes=sorted(set(predictions["MLSuggestion"].astype(str))),
        assay=dataset.assay,
        training_samples=dataset.n_samples,
        rare_class_counts=dataset.rare_class_counts,
        accept_threshold_tau=accept_threshold_tau,
        classifier_kind=classifier_kind,
        prediction_confidence=predictions["MLConfidence"],
    )
    review_cases = (
        predictions.loc[predictions["ReviewReason"].ne("")]
        .sort_values(
            ["MonoklonalFalsePositive", "RuleMLAgree", "MLConfidence"],
            ascending=[False, True, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )
    split_manifest = {
        "strategy": "StratifiedGroupKFold",
        "group_column": str(group_column),
        "requested_splits": int(n_splits),
        "effective_splits": effective_splits,
        "random_state": int(random_state),
        "row_count": dataset.n_samples,
        "unique_groups": unique_groups,
        "unique_dit_groups": int(dataset.dit.nunique()),
        "every_row_oof_once": True,
        "feature_importance": {
            "method": "held_out_permutation_balanced_accuracy",
            "shortlist_method": (
                "fold_model_native_importance_or_unlabelled_fold_variance"
            ),
            "max_features_per_fold": max(0, int(importance_max_features)),
            "repeats_per_feature_per_fold": max(0, int(importance_repeats)),
        },
        "class_fold_support": _class_fold_support(
            split_records,
            labels=sorted(set(dataset.y.astype(str))),
            effective_splits=effective_splits,
        ),
        "calibration": _calibration_manifest(
            split_records,
            classifier_kind=classifier_kind,
            calibration_group_column=calibration_group_column,
        ),
        "folds": split_records,
    }
    return GroupedValidationResult(
        predictions=predictions,
        review_cases=review_cases,
        fold_metrics=pd.DataFrame(fold_records),
        drift_summary=_drift_summary(predictions),
        feature_importance=_aggregate_feature_importance(
            importance_records,
            effective_splits=effective_splits,
        ),
        aggregate_metrics=aggregate,
        split_manifest=split_manifest,
    )


def source_run_grouped_validate(
    dataset: PerAssayDataset,
    *,
    classifier_kind: str,
    n_splits: int = 3,
    random_state: int = 12345,
    accept_threshold_tau: float = 0.85,
) -> GroupedValidationResult:
    """Stress-test an assay while holding complete source runs out."""
    if "SourceRunKey" not in dataset.rows.columns:
        raise ValueError("SourceRunKey is required for source-run validation")
    calibration_groups, _ = dit_content_validation_groups(dataset)
    return grouped_oof_validate(
        dataset,
        classifier_kind=classifier_kind,
        n_splits=n_splits,
        random_state=random_state,
        accept_threshold_tau=accept_threshold_tau,
        importance_max_features=0,
        importance_repeats=0,
        validation_groups=dataset.rows["SourceRunKey"],
        group_column="SourceRunKey",
        calibration_groups=calibration_groups,
        calibration_group_column="DITContentComponent",
    )


def dit_content_grouped_validate(
    dataset: PerAssayDataset,
    *,
    classifier_kind: str,
    n_splits: int = 5,
    random_state: int = 12345,
    accept_threshold_tau: float = 0.85,
    importance_max_features: int = 25,
    importance_repeats: int = 1,
) -> GroupedValidationResult:
    """Hold out DITs and any DITs linked by identical raw FSA content."""
    groups, provenance = dit_content_validation_groups(dataset)
    validation = grouped_oof_validate(
        dataset,
        classifier_kind=classifier_kind,
        n_splits=n_splits,
        random_state=random_state,
        accept_threshold_tau=accept_threshold_tau,
        importance_max_features=importance_max_features,
        importance_repeats=importance_repeats,
        validation_groups=groups,
        group_column="DITContentComponent",
        calibration_groups=groups,
        calibration_group_column="DITContentComponent",
    )
    validation.split_manifest["group_provenance"] = provenance
    return validation


def assess_promotion_gate(
    validation: GroupedValidationResult,
    *,
    min_macro_f1: float,
    min_monoklonal_f1: float,
    min_monoklonal_precision: float,
    min_dit_groups: int,
    min_accepted_accuracy: float = 0.95,
    min_accepted_coverage: float = 0.10,
    max_expected_calibration_error: float = 0.10,
) -> PromotionGate:
    """Return an explicit, auditable runtime-promotion decision."""
    metrics = validation.aggregate_metrics
    mono = metrics.classification_report.get("monoklonal", {})
    mono_precision = float(mono.get("precision", 0.0))
    groups = int(validation.split_manifest.get("unique_groups") or 0)
    thresholds: dict[str, float | int] = {
        "min_macro_f1": float(min_macro_f1),
        "min_monoklonal_f1": float(min_monoklonal_f1),
        "min_monoklonal_precision": float(min_monoklonal_precision),
        "min_dit_groups": int(min_dit_groups),
        "min_accepted_accuracy": float(min_accepted_accuracy),
        "min_accepted_coverage": float(min_accepted_coverage),
        "max_expected_calibration_error": float(
            max_expected_calibration_error
        ),
    }
    reasons: list[str] = []
    if metrics.macro_f1 < float(min_macro_f1):
        reasons.append(
            f"macro_f1={metrics.macro_f1:.3f} below {float(min_macro_f1):.3f}"
        )
    if metrics.monoklonal_f1 < float(min_monoklonal_f1):
        reasons.append(
            "monoklonal_f1="
            f"{metrics.monoklonal_f1:.3f} below {float(min_monoklonal_f1):.3f}"
        )
    if mono_precision < float(min_monoklonal_precision):
        reasons.append(
            "monoklonal_precision="
            f"{mono_precision:.3f} below {float(min_monoklonal_precision):.3f}"
        )
    if groups < int(min_dit_groups):
        reasons.append(
            f"independent_dit_content_groups={groups} below "
            f"{int(min_dit_groups)}"
        )
    if metrics.accepted_accuracy < float(min_accepted_accuracy):
        reasons.append(
            "accepted_accuracy="
            f"{metrics.accepted_accuracy:.3f} below "
            f"{float(min_accepted_accuracy):.3f}"
        )
    if metrics.accepted_coverage < float(min_accepted_coverage):
        reasons.append(
            "accepted_coverage="
            f"{metrics.accepted_coverage:.3f} below "
            f"{float(min_accepted_coverage):.3f}"
        )
    if metrics.expected_calibration_error > float(max_expected_calibration_error):
        reasons.append(
            "expected_calibration_error="
            f"{metrics.expected_calibration_error:.3f} above "
            f"{float(max_expected_calibration_error):.3f}"
        )
    return PromotionGate(
        passed=not reasons,
        reasons=reasons,
        thresholds=thresholds,
    )


def assess_source_run_gate(
    validation: GroupedValidationResult,
    *,
    min_run_groups: int,
    min_macro_f1: float,
    min_monoklonal_precision: float,
) -> PromotionGate:
    """Require generalization to laboratory runs unseen during fitting."""
    metrics = validation.aggregate_metrics
    mono = metrics.classification_report.get("monoklonal", {})
    mono_precision = float(mono.get("precision", 0.0))
    groups = int(validation.split_manifest.get("unique_groups") or 0)
    thresholds: dict[str, float | int] = {
        "min_source_run_groups": int(min_run_groups),
        "min_source_run_macro_f1": float(min_macro_f1),
        "min_source_run_monoklonal_precision": float(
            min_monoklonal_precision
        ),
    }
    reasons: list[str] = []
    if groups < int(min_run_groups):
        reasons.append(
            f"source_run_groups={groups} below {int(min_run_groups)}"
        )
    if metrics.macro_f1 < float(min_macro_f1):
        reasons.append(
            "source_run_macro_f1="
            f"{metrics.macro_f1:.3f} below {float(min_macro_f1):.3f}"
        )
    if mono_precision < float(min_monoklonal_precision):
        reasons.append(
            "source_run_monoklonal_precision="
            f"{mono_precision:.3f} below "
            f"{float(min_monoklonal_precision):.3f}"
        )
    return PromotionGate(
        passed=not reasons,
        reasons=reasons,
        thresholds=thresholds,
    )


def assess_class_support_gate(
    dataset: PerAssayDataset,
    validation: GroupedValidationResult,
    *,
    source_run_validation: GroupedValidationResult | None,
    min_class_dit_groups: int,
    min_core_class_dit_groups: int,
    min_class_source_run_groups: int,
    min_class_evaluation_folds: int,
    min_class_training_rows_per_fold: int,
    max_class_dit_row_fraction: float,
) -> PromotionGate:
    """Require each modeled label to have independent, evaluable support."""
    thresholds: dict[str, float | int] = {
        "min_class_dit_groups": int(min_class_dit_groups),
        "min_core_class_dit_groups": int(min_core_class_dit_groups),
        "min_class_source_run_groups": int(min_class_source_run_groups),
        "min_class_evaluation_folds": int(min_class_evaluation_folds),
        "min_class_training_rows_per_fold": int(
            min_class_training_rows_per_fold
        ),
        "max_class_dit_row_fraction": float(
            max_class_dit_row_fraction
        ),
    }
    support = dataset.class_support
    observed_labels = sorted(support)
    reasons: list[str] = []
    for label in CORE_CLONALITY_LABELS:
        if label not in support:
            reasons.append(f"required_class={label} absent from training data")

    primary_fold_support = validation.split_manifest.get(
        "class_fold_support", {}
    )
    source_fold_support = (
        source_run_validation.split_manifest.get("class_fold_support", {})
        if source_run_validation is not None
        else {}
    )
    for label in observed_labels:
        label_support = support[label]
        required_dits = (
            max(
                int(min_class_dit_groups),
                int(min_core_class_dit_groups),
            )
            if label in CORE_CLONALITY_LABELS
            else int(min_class_dit_groups)
        )
        dit_groups = int(label_support.get("unique_dit_groups") or 0)
        run_groups = int(
            label_support.get("unique_source_run_groups") or 0
        )
        max_dit_fraction = float(
            label_support.get("max_dit_row_fraction") or 0.0
        )
        if dit_groups < required_dits:
            reasons.append(
                f"class_support[{label}].unique_dit_groups={dit_groups} "
                f"below {required_dits}"
            )
        if run_groups < int(min_class_source_run_groups):
            reasons.append(
                f"class_support[{label}].unique_source_run_groups="
                f"{run_groups} below {int(min_class_source_run_groups)}"
            )
        if max_dit_fraction > float(max_class_dit_row_fraction):
            reasons.append(
                f"class_support[{label}].max_dit_row_fraction="
                f"{max_dit_fraction:.3f} above "
                f"{float(max_class_dit_row_fraction):.3f}"
            )
        missing_runs = int(label_support.get("rows_missing_source_run") or 0)
        if missing_runs:
            reasons.append(
                f"class_support[{label}].rows_missing_source_run="
                f"{missing_runs} above 0"
            )
        _append_fold_support_reasons(
            reasons,
            label=label,
            prefix="dit_oof",
            support=primary_fold_support.get(label),
            effective_splits=int(
                validation.split_manifest.get("effective_splits") or 0
            ),
            min_evaluation_folds=int(min_class_evaluation_folds),
            min_training_rows=int(min_class_training_rows_per_fold),
        )
        if source_run_validation is not None:
            _append_fold_support_reasons(
                reasons,
                label=label,
                prefix="source_run_oof",
                support=source_fold_support.get(label),
                effective_splits=int(
                    source_run_validation.split_manifest.get(
                        "effective_splits"
                    )
                    or 0
                ),
                min_evaluation_folds=int(min_class_evaluation_folds),
                min_training_rows=int(min_class_training_rows_per_fold),
            )
    return PromotionGate(
        passed=not reasons,
        reasons=reasons,
        thresholds=thresholds,
    )


def assess_calibration_gate(
    validation: GroupedValidationResult,
    *,
    source_run_validation: GroupedValidationResult | None,
    final_estimator: Any,
    classifier_kind: str,
) -> PromotionGate:
    """Require patient/content-grouped confidence calibration for tree models."""
    required = classifier_kind in TREE_CLASSIFIER_KINDS
    thresholds: dict[str, float | int] = {
        "require_grouped_tree_calibration": int(required),
        "calibration_folds": CALIBRATION_FOLDS if required else 0,
        "min_calibration_split_class_rows": (
            CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT if required else 0
        ),
    }
    reasons: list[str] = []
    if required:
        _append_validation_calibration_reasons(
            reasons,
            prefix="dit_oof",
            manifest=validation.split_manifest.get("calibration"),
        )
        if source_run_validation is None:
            reasons.append("source_run_oof.calibration_missing")
        else:
            _append_validation_calibration_reasons(
                reasons,
                prefix="source_run_oof",
                manifest=source_run_validation.split_manifest.get(
                    "calibration"
                ),
            )
        final = getattr(final_estimator, "hemafrag_calibration_", {})
        _append_calibration_record_reasons(
            reasons,
            prefix="final_fit",
            record=final if isinstance(final, Mapping) else {},
        )
    return PromotionGate(
        passed=not reasons,
        reasons=reasons,
        thresholds=thresholds,
    )


def _append_validation_calibration_reasons(
    reasons: list[str],
    *,
    prefix: str,
    manifest: Any,
) -> None:
    if not isinstance(manifest, Mapping):
        reasons.append(f"{prefix}.calibration_manifest_missing")
        return
    folds = manifest.get("folds")
    if not isinstance(folds, list) or not folds:
        reasons.append(f"{prefix}.calibration_folds_missing")
        return
    if manifest.get("every_fold_complete") is not True:
        reasons.append(f"{prefix}.every_calibration_fold_complete=false")
    if manifest.get("every_fold_grouped") is not True:
        reasons.append(f"{prefix}.every_calibration_fold_grouped=false")
    for index, record in enumerate(folds, start=1):
        _append_calibration_record_reasons(
            reasons,
            prefix=f"{prefix}.fold[{index}]",
            record=record if isinstance(record, Mapping) else {},
        )


def _append_calibration_record_reasons(
    reasons: list[str],
    *,
    prefix: str,
    record: Mapping[str, Any],
) -> None:
    if record.get("status") != "complete":
        reason = str(record.get("reason") or "not complete")
        reasons.append(f"{prefix}.calibration_status={reason}")
    if record.get("strategy") != "StratifiedGroupKFold":
        reasons.append(f"{prefix}.calibration_strategy_not_grouped")
    if record.get("grouped") is not True:
        reasons.append(f"{prefix}.calibration_grouped=false")
    if record.get("group_column") != "DITContentComponent":
        reasons.append(f"{prefix}.calibration_group_column_incompatible")
    if record.get("every_group_held_out_once") is not True:
        reasons.append(f"{prefix}.every_calibration_group_held_out_once=false")
    try:
        folds = int(record.get("folds") or 0)
        min_train = int(record.get("minimum_train_class_rows") or 0)
        min_test = int(record.get("minimum_test_class_rows") or 0)
    except (TypeError, ValueError):
        folds = min_train = min_test = 0
    if folds != CALIBRATION_FOLDS:
        reasons.append(
            f"{prefix}.calibration_folds={folds} below {CALIBRATION_FOLDS}"
        )
    if min_train < CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT:
        reasons.append(
            f"{prefix}.minimum_train_class_rows={min_train} below "
            f"{CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT}"
        )
    if min_test < CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT:
        reasons.append(
            f"{prefix}.minimum_test_class_rows={min_test} below "
            f"{CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT}"
        )


def _append_fold_support_reasons(
    reasons: list[str],
    *,
    label: str,
    prefix: str,
    support: Mapping[str, Any] | None,
    effective_splits: int,
    min_evaluation_folds: int,
    min_training_rows: int,
) -> None:
    support = support if isinstance(support, Mapping) else {}
    train_folds = int(support.get("training_folds_with_examples") or 0)
    evaluation_folds = int(
        support.get("evaluation_folds_with_examples") or 0
    )
    minimum_training_rows = int(support.get("min_train_rows") or 0)
    required_evaluation = min(
        max(1, int(min_evaluation_folds)),
        max(1, int(effective_splits)),
    )
    if train_folds < int(effective_splits):
        reasons.append(
            f"{prefix}.class[{label}].training_folds_with_examples="
            f"{train_folds} below {int(effective_splits)}"
        )
    if evaluation_folds < required_evaluation:
        reasons.append(
            f"{prefix}.class[{label}].evaluation_folds_with_examples="
            f"{evaluation_folds} below {required_evaluation}"
        )
    if minimum_training_rows < int(min_training_rows):
        reasons.append(
            f"{prefix}.class[{label}].min_train_rows="
            f"{minimum_training_rows} below {int(min_training_rows)}"
        )


def _class_fold_support(
    split_records: list[dict[str, Any]],
    *,
    labels: list[str],
    effective_splits: int,
) -> dict[str, dict[str, int | bool]]:
    support: dict[str, dict[str, int | bool]] = {}
    for label in labels:
        train_counts = [
            int(record.get("train_label_counts", {}).get(label) or 0)
            for record in split_records
        ]
        test_counts = [
            int(record.get("test_label_counts", {}).get(label) or 0)
            for record in split_records
        ]
        training_folds = sum(count > 0 for count in train_counts)
        evaluation_folds = sum(count > 0 for count in test_counts)
        support[label] = {
            "total_folds": int(effective_splits),
            "training_folds_with_examples": int(training_folds),
            "evaluation_folds_with_examples": int(evaluation_folds),
            "min_train_rows": int(min(train_counts, default=0)),
            "min_test_rows": int(min(test_counts, default=0)),
            "every_training_fold": training_folds == int(effective_splits),
            "every_evaluation_fold": evaluation_folds == int(
                effective_splits
            ),
        }
    return support


def _calibration_manifest(
    split_records: list[dict[str, Any]],
    *,
    classifier_kind: str,
    calibration_group_column: str,
) -> dict[str, Any]:
    folds = [
        dict(record.get("calibration") or {})
        for record in split_records
    ]
    required = classifier_kind in {"random_forest", "extra_trees"}
    return {
        "required_for_runtime": required,
        "method": "sigmoid" if required else "native_probability",
        "group_column": str(calibration_group_column) if required else "",
        "fold_count": len(folds),
        "every_fold_complete": (
            all(fold.get("status") == "complete" for fold in folds)
            if required
            else True
        ),
        "every_fold_grouped": (
            all(fold.get("grouped") is True for fold in folds)
            if required
            else True
        ),
        "folds": folds,
    }


def metrics_as_dict(metrics: PerAssayMetrics) -> dict[str, Any]:
    return {
        "assay": metrics.assay,
        "training_samples": metrics.training_samples,
        "monoklonal_f1": metrics.monoklonal_f1,
        "macro_f1": metrics.macro_f1,
        "accuracy": metrics.accuracy,
        "balanced_accuracy": metrics.balanced_accuracy,
        "confusion_matrix": metrics.confusion_matrix,
        "classification_report": metrics.classification_report,
        "rare_class_counts": metrics.rare_class_counts,
        "accept_threshold_tau": metrics.accept_threshold_tau,
        "classifier_kind": metrics.classifier_kind,
        "expected_calibration_error": metrics.expected_calibration_error,
        "accepted_coverage": metrics.accepted_coverage,
        "accepted_accuracy": metrics.accepted_accuracy,
        "mean_confidence": metrics.mean_confidence,
    }


def render_review_panel_html(
    validation: GroupedValidationResult,
    *,
    promotion_gate: PromotionGate,
) -> str:
    """Render a local review table; it contains no raw trace or FSA path."""
    metrics = validation.aggregate_metrics
    status = "passes configured gates" if promotion_gate.passed else "candidate only"
    rows = [
        "<!doctype html>",
        "<html lang='en'><head><meta charset='utf-8'>",
        f"<title>Clonality ML review - {html.escape(metrics.assay)}</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#17212b;background:#f7f8fa}",
        "h1{font-size:24px;margin:0 0 8px} .summary{margin:0 0 20px;color:#435160}",
        "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}",
        "th,td{border:1px solid #d9dee5;padding:7px;text-align:left;vertical-align:top}",
        "th{background:#e9edf2;position:sticky;top:0} tr.fp td{background:#fff0f0}",
        "tr.disagree td{background:#fff8e8} .num{text-align:right;font-variant-numeric:tabular-nums}",
        "</style></head><body>",
        f"<h1>{html.escape(metrics.assay)} grouped validation review</h1>",
        (
            "<p class='summary'>"
            f"Status: <strong>{html.escape(status)}</strong> | "
            f"Macro F1: {metrics.macro_f1:.3f} | "
            f"Monoklonal F1: {metrics.monoklonal_f1:.3f} | "
            f"Accepted accuracy: {metrics.accepted_accuracy:.3f} | "
            f"Review rows: {len(validation.review_cases)}"
            "</p>"
        ),
        "<table><thead><tr>",
        "<th>DIT</th><th>Run</th><th>Assay</th><th>Chemist</th><th>Rule</th>",
        "<th>ML</th><th>Confidence</th><th>Fold</th><th>Review reason</th>",
        "</tr></thead><tbody>",
    ]
    for record in validation.review_cases.to_dict(orient="records"):
        css = "fp" if bool(record.get("MonoklonalFalsePositive")) else "disagree"
        cells = [
            record.get("DIT", ""),
            record.get("SourceRunKey", "") or record.get("RunDate", ""),
            record.get("Assay", ""),
            record.get("ChemistLabel", ""),
            record.get("RuleSuggestion", ""),
            record.get("MLSuggestion", ""),
            f"{float(record.get('MLConfidence') or 0.0):.3f}",
            record.get("Fold", ""),
            record.get("ReviewReason", ""),
        ]
        rows.append(
            f"<tr class='{css}'>"
            + "".join(
                f"<td{' class=num' if index in {6, 7} else ''}>"
                f"{html.escape(str(value))}</td>"
                for index, value in enumerate(cells)
            )
            + "</tr>"
        )
    rows.extend(["</tbody></table>", "</body></html>"])
    return "\n".join(rows)


def _prediction_frame(
    dataset: PerAssayDataset,
    *,
    test_idx: np.ndarray,
    fold: int,
    predictions: np.ndarray,
    confidence: np.ndarray,
    probabilities: np.ndarray | None,
    classes: list[str],
    accept_threshold_tau: float,
) -> pd.DataFrame:
    metadata = dataset.rows.iloc[test_idx].reset_index(drop=True).copy()
    output = pd.DataFrame(
        {
            "RowIndex": test_idx.astype(int),
            "Fold": int(fold),
            "IdentityKey": _metadata_column(metadata, "IdentityKey"),
            "DIT": dataset.dit.iloc[test_idx].reset_index(drop=True).astype(str),
            "Assay": dataset.assay,
            "RunDate": _metadata_column(metadata, "RunDate"),
            "SourceRunKey": _metadata_column(metadata, "SourceRunKey"),
            "ChemistLabel": dataset.y.iloc[test_idx].reset_index(drop=True).astype(str),
            "RuleSuggestion": _metadata_column(metadata, "RuleSuggestion"),
            "RuleConfidence": pd.to_numeric(
                _metadata_column(metadata, "RuleConfidence"), errors="coerce"
            ),
            "RuleReviewNeeded": _metadata_column(
                metadata, "RuleReviewNeeded", default=False
            ).map(_truthy),
            "MLSuggestion": predictions.astype(str),
            "MLConfidence": confidence.astype(float),
        }
    )
    output["RuleMLAgree"] = (
        output["RuleSuggestion"].ne("")
        & output["RuleSuggestion"].eq(output["MLSuggestion"])
    )
    output["RuleMLDisagreement"] = (
        output["RuleSuggestion"].ne("")
        & output["RuleSuggestion"].ne(output["MLSuggestion"])
    )
    output["ChemistMLAgree"] = output["ChemistLabel"].eq(output["MLSuggestion"])
    output["MonoklonalFalsePositive"] = (
        output["MLSuggestion"].eq("monoklonal")
        & output["ChemistLabel"].ne("monoklonal")
    )
    output["ReviewReason"] = output.apply(
        lambda row: _review_reason(row, accept_threshold_tau),
        axis=1,
    )
    output["MLReviewNeeded"] = output["ReviewReason"].ne("")
    if probabilities is not None:
        for class_index, label in enumerate(classes):
            if class_index < probabilities.shape[1]:
                output[f"Probability.{label}"] = probabilities[:, class_index]
    return output


def _review_reason(row: pd.Series, threshold: float) -> str:
    reasons: list[str] = []
    if bool(row["MonoklonalFalsePositive"]):
        reasons.append("monoklonal_false_positive")
    if not bool(row["ChemistMLAgree"]):
        reasons.append("chemist_ml_disagreement")
    rule = str(row.get("RuleSuggestion") or "")
    if rule and bool(row["RuleMLDisagreement"]):
        reasons.append("rule_ml_disagreement")
    if float(row["MLConfidence"]) < float(threshold):
        reasons.append("low_confidence")
    if str(row["MLSuggestion"]) in REVIEW_ROUTED_LABELS:
        reasons.append("rare_label_prediction")
    return ";".join(reasons)


def _drift_summary(predictions: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for dimension in ("SourceRunKey", "RunDate"):
        if dimension not in predictions.columns:
            continue
        values = predictions[dimension].fillna("").astype(str).str.strip()
        for value, group in predictions.loc[values.ne("")].groupby(
            values.loc[values.ne("")],
            sort=True,
        ):
            records.append(
                {
                    "Dimension": dimension,
                    "Value": str(value),
                    "Samples": int(len(group)),
                    "Accuracy": float(group["ChemistMLAgree"].mean()),
                    "MeanConfidence": float(group["MLConfidence"].mean()),
                    "RuleDisagreements": int(group["RuleMLDisagreement"].sum()),
                    "MonoklonalFalsePositives": int(
                        group["MonoklonalFalsePositive"].sum()
                    ),
                }
            )
    return pd.DataFrame(records)


def _fold_permutation_importance(
    estimator: Any,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    *,
    fold: int,
    max_features: int,
    repeats: int,
    random_state: int,
) -> list[dict[str, Any]]:
    """Measure shortlisted feature impact on untouched fold rows."""
    max_features = max(0, int(max_features))
    repeats = max(0, int(repeats))
    if max_features == 0 or repeats == 0 or X_test.empty:
        return []
    candidates, screening = _importance_candidates(
        estimator,
        X_test,
        max_features=max_features,
    )
    if not candidates:
        return []

    baseline = balanced_accuracy_score(
        y_test.astype(str),
        np.asarray(estimator.predict(X_test), dtype=str),
    )
    rng = np.random.default_rng(int(random_state))
    records: list[dict[str, Any]] = []
    for column in candidates:
        values = X_test[column].to_numpy(copy=True)
        impacts: list[float] = []
        for _repeat in range(repeats):
            permuted = X_test.copy()
            permuted[column] = values[rng.permutation(len(values))]
            score = balanced_accuracy_score(
                y_test.astype(str),
                np.asarray(estimator.predict(permuted), dtype=str),
            )
            impacts.append(float(baseline - score))
        records.append(
            {
                "Fold": int(fold),
                "Feature": str(column),
                "ScreeningImportance": float(screening.get(column, 0.0)),
                "PermutationImportanceMean": float(np.mean(impacts)),
                "PermutationImportanceStd": float(np.std(impacts)),
                "Repeats": repeats,
            }
        )
    return records


def dit_content_validation_groups(
    dataset: PerAssayDataset,
) -> tuple[pd.Series, dict[str, Any]]:
    if "FsaContentHash" not in dataset.rows.columns:
        raise ValueError(
            "FsaContentHash is required for leakage-safe DIT validation"
        )
    dits = dataset.dit.fillna("").astype(str).str.strip().reset_index(drop=True)
    hashes = (
        dataset.rows["FsaContentHash"]
        .fillna("")
        .astype(str)
        .str.strip()
        .reset_index(drop=True)
    )
    if hashes.eq("").any():
        raise ValueError(
            "FsaContentHash validation requires a non-empty hash for every row"
        )

    unique_dits = list(dict.fromkeys(dits.tolist()))
    parent = {dit: dit for dit in unique_dits}

    def find(value: str) -> str:
        root = value
        while parent[root] != root:
            root = parent[root]
        while parent[value] != value:
            next_value = parent[value]
            parent[value] = root
            value = next_value
        return root

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        keep, merge = sorted((left_root, right_root))
        parent[merge] = keep

    first_dit_by_hash: dict[str, str] = {}
    dits_by_hash: dict[str, set[str]] = {}
    for dit, content_hash in zip(dits, hashes):
        prior = first_dit_by_hash.setdefault(content_hash, dit)
        union(prior, dit)
        dits_by_hash.setdefault(content_hash, set()).add(dit)

    roots = sorted({find(dit) for dit in unique_dits})
    labels = {
        root: f"dit_content_component_{index:06d}"
        for index, root in enumerate(roots, start=1)
    }
    groups = dits.map(lambda dit: labels[find(dit)])
    counts = hashes.value_counts()
    cross_dit_hashes = sum(
        len(hash_dits) > 1 for hash_dits in dits_by_hash.values()
    )
    provenance = {
        "method": "dit_fsa_content_connected_components",
        "content_hash_column": "FsaContentHash",
        "content_hash_coverage": float(hashes.ne("").mean()),
        "row_count": int(len(hashes)),
        "original_dit_groups": int(dits.nunique()),
        "independent_validation_groups": int(groups.nunique()),
        "unique_content_hashes": int(hashes.nunique()),
        "duplicate_content_hashes": int((counts > 1).sum()),
        "cross_dit_duplicate_content_hashes": int(cross_dit_hashes),
        "coalesced_dit_group_count": int(dits.nunique() - groups.nunique()),
    }
    return groups, provenance


def _importance_candidates(
    estimator: Any,
    X: pd.DataFrame,
    *,
    max_features: int,
) -> tuple[list[str], dict[str, float]]:
    columns = [str(column) for column in X.columns]
    native = _native_feature_importance(estimator, expected_size=len(columns))
    if native is None:
        variance = X.var(axis=0, numeric_only=True).reindex(X.columns)
        screening = {
            str(column): float(value) if np.isfinite(value) else 0.0
            for column, value in variance.fillna(0.0).items()
        }
    else:
        screening = {
            str(column): float(native[index])
            for index, column in enumerate(columns)
        }
    ranked = sorted(
        columns,
        key=lambda column: (-screening[column], str(column)),
    )
    return ranked[:max_features], screening


def _native_feature_importance(
    estimator: Any,
    *,
    expected_size: int,
) -> np.ndarray | None:
    direct = getattr(estimator, "feature_importances_", None)
    if direct is not None:
        values = np.asarray(direct, dtype=float)
        if values.shape == (expected_size,):
            return values

    components: list[Any] = []
    calibrated = getattr(estimator, "calibrated_classifiers_", None)
    if calibrated is not None:
        components.extend(
            getattr(item, "estimator", None) for item in calibrated
        )
    named_steps = getattr(estimator, "named_steps", None)
    if isinstance(named_steps, Mapping):
        components.extend(reversed(list(named_steps.values())))

    values = [
        nested
        for component in components
        if component is not None
        for nested in [
            _native_feature_importance(
                component,
                expected_size=expected_size,
            )
        ]
        if nested is not None
    ]
    if not values:
        return None
    return np.mean(np.vstack(values), axis=0)


def _aggregate_feature_importance(
    records: list[dict[str, Any]],
    *,
    effective_splits: int,
) -> pd.DataFrame:
    columns = [
        "Rank",
        "Feature",
        "PermutationImportanceMean",
        "PermutationImportanceStd",
        "ScreeningImportanceMean",
        "FoldsEvaluated",
        "FoldCoverage",
        "PositiveImpactFoldFraction",
    ]
    if not records:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(records)
    aggregated = (
        frame.groupby("Feature", sort=False)
        .agg(
            PermutationImportanceMean=("PermutationImportanceMean", "mean"),
            PermutationImportanceStd=("PermutationImportanceMean", "std"),
            ScreeningImportanceMean=("ScreeningImportance", "mean"),
            FoldsEvaluated=("Fold", "nunique"),
            PositiveImpactFolds=(
                "PermutationImportanceMean",
                lambda values: int((values > 0).sum()),
            ),
        )
        .reset_index()
    )
    aggregated["PermutationImportanceStd"] = (
        aggregated["PermutationImportanceStd"].fillna(0.0)
    )
    aggregated["FoldCoverage"] = (
        aggregated["FoldsEvaluated"] / max(1, int(effective_splits))
    )
    aggregated["PositiveImpactFoldFraction"] = (
        aggregated["PositiveImpactFolds"]
        / aggregated["FoldsEvaluated"].clip(lower=1)
    )
    aggregated = (
        aggregated.sort_values(
            [
                "PermutationImportanceMean",
                "PositiveImpactFoldFraction",
                "Feature",
            ],
            ascending=[False, False, True],
            kind="stable",
        )
        .drop(columns=["PositiveImpactFolds"])
        .reset_index(drop=True)
    )
    aggregated.insert(0, "Rank", np.arange(1, len(aggregated) + 1))
    return aggregated[columns]


def _predict_probabilities(estimator: Any, X: pd.DataFrame) -> np.ndarray | None:
    try:
        values = np.asarray(estimator.predict_proba(X), dtype=float)
    except Exception:
        return None
    return values if values.ndim == 2 and values.shape[0] == len(X) else None


def _estimator_classes(estimator: Any, predictions: np.ndarray) -> list[str]:
    values = getattr(estimator, "classes_", None)
    if values is not None:
        return [str(value) for value in np.asarray(values).tolist()]
    return sorted(set(predictions.astype(str)))


def _prediction_confidence(
    probabilities: np.ndarray | None,
    predictions: np.ndarray,
    classes: list[str],
) -> np.ndarray:
    if probabilities is None:
        return np.zeros(len(predictions), dtype=float)
    class_indexes = {label: index for index, label in enumerate(classes)}
    return np.asarray(
        [
            probabilities[row_index, class_indexes[label]]
            if label in class_indexes
            else float(np.max(probabilities[row_index]))
            for row_index, label in enumerate(predictions.astype(str))
        ],
        dtype=float,
    )


def _metadata_column(
    frame: pd.DataFrame,
    column: str,
    *,
    default: Any = "",
) -> pd.Series:
    if column in frame.columns:
        return frame[column].fillna(default).reset_index(drop=True)
    return pd.Series([default] * len(frame))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "ja"}


__all__ = [
    "GroupedValidationResult",
    "PromotionGate",
    "REVIEW_ROUTED_LABELS",
    "assess_calibration_gate",
    "assess_class_support_gate",
    "assess_promotion_gate",
    "assess_source_run_gate",
    "dit_content_validation_groups",
    "dit_content_grouped_validate",
    "grouped_oof_validate",
    "metrics_as_dict",
    "render_review_panel_html",
    "source_run_grouped_validate",
]
