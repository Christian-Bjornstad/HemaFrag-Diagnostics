"""Patient-grouped validation and review artifacts for clonality ML."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from core.analyses.clonality.ml_training import (
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


@dataclass
class GroupedValidationResult:
    predictions: pd.DataFrame
    review_cases: pd.DataFrame
    fold_metrics: pd.DataFrame
    drift_summary: pd.DataFrame
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
) -> GroupedValidationResult:
    """Evaluate every row out of fold while keeping each DIT in one fold."""
    unique_groups = int(dataset.dit.nunique())
    effective_splits = min(max(2, int(n_splits)), unique_groups)
    if unique_groups < 2:
        raise ValueError(
            f"assay {dataset.assay!r} has fewer than two unique DIT groups"
        )
    if dataset.y.nunique() < 2:
        raise ValueError(
            f"assay {dataset.assay!r} has fewer than two chemist label classes"
        )

    splitter = StratifiedGroupKFold(
        n_splits=effective_splits,
        shuffle=True,
        random_state=int(random_state),
    )
    prediction_frames: list[pd.DataFrame] = []
    fold_records: list[dict[str, Any]] = []
    split_records: list[dict[str, Any]] = []

    for fold, (train_idx, test_idx) in enumerate(
        splitter.split(dataset.X, dataset.y, groups=dataset.dit),
        start=1,
    ):
        train_groups = set(dataset.dit.iloc[train_idx].astype(str))
        test_groups = set(dataset.dit.iloc[test_idx].astype(str))
        if train_groups & test_groups:
            raise AssertionError("DIT leakage detected in grouped validation")

        estimator = fit_classifier(
            dataset.X.iloc[train_idx],
            dataset.y.iloc[train_idx],
            kind=classifier_kind,
            random_state=int(random_state) + fold - 1,
        )
        X_test = dataset.X.iloc[test_idx]
        y_test = dataset.y.iloc[test_idx].reset_index(drop=True)
        y_pred = np.asarray(estimator.predict(X_test), dtype=str)
        probabilities = _predict_probabilities(estimator, X_test)
        classes = _estimator_classes(estimator, y_pred)
        confidence = _prediction_confidence(probabilities, y_pred, classes)
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
                "TrainDITGroups": int(len(train_groups)),
                "TestDITGroups": int(len(test_groups)),
                "MacroF1": fold_metric.macro_f1,
                "BalancedAccuracy": fold_metric.balanced_accuracy,
                "MonoklonalF1": fold_metric.monoklonal_f1,
                "Accuracy": fold_metric.accuracy,
                "AcceptedAccuracy": fold_metric.accepted_accuracy,
                "AcceptedCoverage": fold_metric.accepted_coverage,
                "ExpectedCalibrationError": (
                    fold_metric.expected_calibration_error
                ),
            }
        )
        split_records.append(
            {
                "fold": fold,
                "train_rows": int(len(train_idx)),
                "test_rows": int(len(test_idx)),
                "train_dit_groups": int(len(train_groups)),
                "test_dit_groups": int(len(test_groups)),
                "test_label_counts": {
                    str(key): int(value)
                    for key, value in y_test.value_counts().sort_index().items()
                },
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
        "group_column": "DIT",
        "requested_splits": int(n_splits),
        "effective_splits": effective_splits,
        "random_state": int(random_state),
        "row_count": dataset.n_samples,
        "unique_dit_groups": unique_groups,
        "every_row_oof_once": True,
        "folds": split_records,
    }
    return GroupedValidationResult(
        predictions=predictions,
        review_cases=review_cases,
        fold_metrics=pd.DataFrame(fold_records),
        drift_summary=_drift_summary(predictions),
        aggregate_metrics=aggregate,
        split_manifest=split_manifest,
    )


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
    groups = int(validation.split_manifest.get("unique_dit_groups") or 0)
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
        reasons.append(f"dit_groups={groups} below {int(min_dit_groups)}")
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
    "assess_promotion_gate",
    "grouped_oof_validate",
    "metrics_as_dict",
    "render_review_panel_html",
]
