"""core/analyses/clonality/ml_training.py

Plan 11 / Phase 3 — per-assay clonality training helpers. Pure
functions; no module globals; no side effects. The CLI driver
`scripts/train_clonality_interpretation_models.py` uses these; the
tests module `tests/test_clonality_interpretation_ml.py` exercises
them; Phase-4 calibration wraps them.

Public surface (re-exported via __all__):
    build_per_assay_datasets
    group_shuffle_split_by_dit
    fit_classifier
    per_assay_metrics
    serialize_model
    deserialize_model
    ANNOTATION_CLASSES_ORDER
"""

from __future__ import annotations

import inspect
import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
from sklearn.naive_bayes import GaussianNB
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from core.analyses.clonality.ml_data_contract import (
    CHEMIST_LABEL_COLUMN,
    is_raw_trace_feature,
)


# Frozen label order. Training pipeline always produces a PerAssayMetrics
# dict keyed on these. Caller may extend this list once chemist signs
# off on a new annotation class.
ANNOTATION_CLASSES_ORDER: tuple[str, ...] = (
    "monoklonal",
    "polyklonal",
    "bi_oligoklonal",
    "irregulaer",
    "pseudoklonal",
    "intet_pcr_produkt_darlig_dna",
    "qc_teknisk_fail",
    "usikker_review",
)
RUNTIME_MODEL_SCHEMA_VERSION = "ml_training_pipeline_v8"
TREE_CLASSIFIER_KINDS = {"random_forest", "extra_trees"}
CALIBRATION_FOLDS = 3
CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT = 2

DEFAULT_NON_FEATURE_COLUMNS = {
    "Month",
    "IdentityKey",
    "File",
    "SourceRunDir",
    "SourceRunKey",
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
    "RawPath",
    "FeatureDatasetVersion",
    "TraceFeatureSchemaVersion",
    "CohortFeatureSchemaVersion",
    "FsaSourceHash",
    "FsaContentHash",
    CHEMIST_LABEL_COLUMN,
    "RuleSuggestion",
    "RuleConfidence",
    "RuleReviewNeeded",
    "RuleEvidence",
    "RuleVersion",
    "ClonalityInterpretationEnabled",
    "ClonalitySuggestion",
    "ClonalityConfidence",
    "ClonalityReviewNeeded",
    "ClonalityEvidence",
    "ClonalitySLQualityClass",
    "ClonalitySLQualityPhrase",
    "ClonalityModelVersion",
    "ClonalityMLSuggestion",
    "ClonalityMLConfidence",
    "ClonalityMLThreshold",
    "ClonalityMLReviewNeeded",
    "ClonalityMLEvidence",
    "ClonalityMLModelVersion",
}

__all__ = [
    "ANNOTATION_CLASSES_ORDER",
    "RUNTIME_MODEL_SCHEMA_VERSION",
    "build_per_assay_datasets",
    "group_shuffle_split_by_dit",
    "fit_classifier",
    "per_assay_metrics",
    "serialize_model",
    "deserialize_model",
    "PerAssayDataset",
    "PerAssayMetrics",
    "summarize_class_support",
]


def summarize_class_support(
    y: pd.Series,
    dit: pd.Series,
    rows: pd.DataFrame,
) -> dict[str, dict[str, int | float]]:
    """Count independent patient and run support for every observed label."""
    labels = pd.Series(y).fillna("").astype(str).str.strip().reset_index(drop=True)
    dits = pd.Series(dit).fillna("").astype(str).str.strip().reset_index(drop=True)
    metadata = pd.DataFrame(rows).reset_index(drop=True)
    if len(labels) != len(dits) or len(labels) != len(metadata):
        raise ValueError("class support inputs must have identical row counts")
    if "SourceRunKey" in metadata.columns:
        source_runs = (
            metadata["SourceRunKey"]
            .fillna("")
            .astype(str)
            .str.strip()
            .reset_index(drop=True)
        )
    else:
        source_runs = pd.Series([""] * len(labels), dtype=str)

    support: dict[str, dict[str, int | float]] = {}
    for label in sorted(set(labels.loc[labels.ne("")])):
        mask = labels.eq(label)
        label_runs = source_runs.loc[mask]
        dit_counts = dits.loc[mask & dits.ne("")].value_counts()
        dit_rows = int(dit_counts.sum())
        max_dit_rows = int(dit_counts.max()) if not dit_counts.empty else 0
        effective_dits = (
            float(dit_rows**2 / np.square(dit_counts.to_numpy()).sum())
            if dit_rows
            else 0.0
        )
        support[label] = {
            "rows": int(mask.sum()),
            "unique_dit_groups": int(len(dit_counts)),
            "effective_dit_groups": effective_dits,
            "max_rows_per_dit": max_dit_rows,
            "max_dit_row_fraction": (
                float(max_dit_rows / dit_rows) if dit_rows else 0.0
            ),
            "unique_source_run_groups": int(
                label_runs.loc[label_runs.ne("")].nunique()
            ),
            "rows_missing_source_run": int(label_runs.eq("").sum()),
        }
    return support


@dataclass
class PerAssayDataset:
    """Built once per assay, used by every fold.

    X: pd.DataFrame, shape (n_samples, n_features), all numeric.
    y: pd.Series of str, length n_samples.
    dit: pd.Series of str, length n_samples, used for group split.
    assay: str -- the assay tube (e.g., "FR1").
    n_samples: int -- populated post-init from len(X).
    rare_class_counts: dict[str, int] -- ANNOTATION_CLASSES -> row counts.
    class_support: per-label independent DIT/run and repeat-concentration
        evidence computed after content deduplication.
    """

    X: pd.DataFrame
    y: pd.Series
    dit: pd.Series
    assay: str
    rare_class_counts: dict[str, int] = field(default_factory=dict)
    class_support: dict[str, dict[str, int | float]] = field(
        default_factory=dict
    )
    data_provenance: dict[str, Any] = field(default_factory=dict)
    n_samples: int = 0
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __post_init__(self) -> None:
        if self.n_samples == 0:
            self.n_samples = int(len(self.X))
        if not self.class_support and len(self.rows) == self.n_samples:
            self.class_support = summarize_class_support(
                self.y,
                self.dit,
                self.rows,
            )


@dataclass
class PerAssayMetrics:
    """Per-assay metric triplet used by Phase-3 reporting."""

    assay: str
    training_samples: int
    monoklonal_f1: float
    macro_f1: float
    accuracy: float
    balanced_accuracy: float
    confusion_matrix: list[list[int]]
    classification_report: dict[str, dict[str, float]]
    rare_class_counts: dict[str, int]
    accept_threshold_tau: float
    classifier_kind: str = "random_forest"
    expected_calibration_error: float = 0.0
    accepted_coverage: float = 0.0
    accepted_accuracy: float = 0.0
    mean_confidence: float = 0.0


def _annotation_sort_key(name: str) -> int:
    try:
        return ANNOTATION_CLASSES_ORDER.index(name)
    except ValueError:
        return len(ANNOTATION_CLASSES_ORDER)


def _assay_key(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .upper()
    )


def _ensure_numeric_X(X: pd.DataFrame) -> pd.DataFrame:
    """Coerce non-numeric columns to numeric via factorize.

    Tolerated inputs: numeric, bool, NaN, +/-inf.
    Anything else gets factorized (categorical -> int) so the
    classifier sees only float64.
    """
    if not isinstance(X, pd.DataFrame):
        X = pd.DataFrame(X)
    out = X.copy()
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_numeric_dtype(series):
            out[col] = pd.to_numeric(series, errors="coerce")
        elif pd.api.types.is_bool_dtype(series):
            out[col] = series.astype(float)
        else:
            codes, _ = pd.factorize(series.astype(str), use_na_sentinel=True)
            out[col] = codes.astype(float)
    out = out.replace([np.inf, -np.inf], np.nan).astype(float)
    return out


def build_per_assay_datasets(
    combined_df: pd.DataFrame,
    *,
    feature_cols: Sequence[str] | None = None,
    label_col: str = "ClonalitySuggestion",
    dit_col: str = "DIT",
    assay_col: str = "Assay",
    include_assays: Sequence[str] | None = None,
    min_samples_per_assay: int = 200,
) -> dict[str, PerAssayDataset]:
    """Split a feature-DataFrame into per-assay PerAssayDataset entries.

    combined_df: expected columns (or aliases):
        - <feature_cols>: numeric features (or anything coercible via _ensure_numeric_X)
        - DIT (alias: 'dit'): patient identifier
        - Assay (alias: 'assay')
        - ClonalitySuggestion (alias: 'label' or 'y'): one of ANNOTATION_CLASSES_ORDER

    Returns dict[assay_name -> PerAssayDataset].  Assays with < min_samples_per_assay
    rows are DROPPED -- we don't ship low-N models.
    """
    if combined_df.empty:
        return {}

    renames: dict[str, str] = {}
    if "dit" in combined_df.columns and dit_col not in combined_df.columns:
        renames["dit"] = dit_col
    if "assay" in combined_df.columns and assay_col not in combined_df.columns:
        renames["assay"] = assay_col
    if "y" in combined_df.columns and label_col not in combined_df.columns:
        renames["y"] = label_col
    if renames:
        combined_df = combined_df.rename(columns=renames)

    if assay_col not in combined_df.columns:
        raise KeyError(f"column {assay_col!r} not in dataframe")
    if label_col not in combined_df.columns:
        raise KeyError(f"column {label_col!r} not in dataframe")
    if dit_col not in combined_df.columns:
        raise KeyError(f"column {dit_col!r} not in dataframe")

    labels = combined_df[label_col].fillna("").astype(str).str.strip()
    combined_df = combined_df.loc[labels.ne("")].copy()
    combined_df[label_col] = labels.loc[labels.ne("")]
    invalid_labels = sorted(
        set(combined_df[label_col].unique()) - set(ANNOTATION_CLASSES_ORDER)
    )
    if invalid_labels:
        raise ValueError(
            "unknown clonality training labels: {}".format(", ".join(invalid_labels))
        )
    missing_dit = combined_df[dit_col].fillna("").astype(str).str.strip().eq("")
    if missing_dit.any():
        raise ValueError(
            f"{int(missing_dit.sum())} labelled row(s) have no {dit_col}; "
            "grouped validation would leak patients"
        )

    if feature_cols is None:
        feature_cols = [
            c for c in combined_df.columns
            if c not in DEFAULT_NON_FEATURE_COLUMNS
            and c not in (label_col, dit_col, assay_col)
            and (
                pd.api.types.is_numeric_dtype(combined_df[c])
                or pd.api.types.is_bool_dtype(combined_df[c])
            )
        ]
    feature_cols = [c for c in feature_cols if c in combined_df.columns]
    if not feature_cols:
        raise ValueError("no numeric feature columns were available for training")
    if not any(is_raw_trace_feature(column) for column in feature_cols):
        raise ValueError(
            "no raw FSA trace features were available for training; "
            "refusing to fit a ladder/QC-only clonality model"
        )

    out: dict[str, PerAssayDataset] = {}
    include_assay_keys = (
        {_assay_key(value) for value in include_assays}
        if include_assays is not None
        else None
    )
    for assay_name, group in combined_df.groupby(assay_col, sort=True):
        if pd.isna(assay_name):
            continue
        if (
            include_assay_keys is not None
            and _assay_key(assay_name) not in include_assay_keys
        ):
            continue
        group, data_provenance = _deduplicate_content_rows(
            group,
            label_col=label_col,
            dit_col=dit_col,
            assay_name=str(assay_name),
        )
        if len(group) < min_samples_per_assay:
            continue
        X_num = _ensure_numeric_X(group[feature_cols]).reset_index(drop=True)
        y_series = group[label_col].astype(str).reset_index(drop=True)
        dit_series = group[dit_col].astype(str).reset_index(drop=True)
        counts = group[label_col].value_counts().to_dict()
        reset_group = group.reset_index(drop=True)
        out[str(assay_name)] = PerAssayDataset(
            X=X_num,
            y=y_series,
            dit=dit_series,
            assay=str(assay_name),
            n_samples=len(group),
            rare_class_counts={str(k): int(v) for k, v in counts.items()},
            data_provenance=data_provenance,
            rows=reset_group,
            class_support=summarize_class_support(
                y_series,
                dit_series,
                reset_group,
            ),
        )
    return out


def _deduplicate_content_rows(
    group: pd.DataFrame,
    *,
    label_col: str,
    dit_col: str,
    assay_name: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw_count = int(len(group))
    if "FsaContentHash" not in group.columns:
        return group.copy(), {
            "method": "per_assay_fsa_content_hash_v1",
            "raw_row_count": raw_count,
            "unique_trace_row_count": raw_count,
            "duplicate_rows_removed": 0,
            "content_hash_coverage": 0.0,
            "duplicate_content_hashes": 0,
            "cross_dit_duplicate_content_hashes": 0,
            "conflicting_label_content_hashes": 0,
            "conflicting_source_run_content_hashes": 0,
        }

    working = group.copy()
    hashes = (
        working["FsaContentHash"].fillna("").astype(str).str.strip()
    )
    working["_TrainingContentHash"] = hashes
    nonempty = working.loc[hashes.ne("")]
    grouped_hashes = nonempty.groupby("_TrainingContentHash", sort=False)
    label_counts = grouped_hashes[label_col].nunique(dropna=False)
    conflicting_labels = int((label_counts > 1).sum())
    if conflicting_labels:
        raise ValueError(
            f"assay {assay_name!r} has {conflicting_labels} FSA content "
            "hash(es) with conflicting chemist labels"
        )

    conflicting_runs = 0
    if "SourceRunKey" in working.columns:
        run_values = working["SourceRunKey"].fillna("").astype(str).str.strip()
        working["_TrainingSourceRunKey"] = run_values
        run_counts = (
            working.loc[hashes.ne("")]
            .groupby("_TrainingContentHash", sort=False)[
                "_TrainingSourceRunKey"
            ]
            .nunique()
        )
        conflicting_runs = int((run_counts > 1).sum())
        if conflicting_runs:
            raise ValueError(
                f"assay {assay_name!r} has {conflicting_runs} FSA content "
                "hash(es) assigned to conflicting source runs"
            )

    hash_counts = hashes.loc[hashes.ne("")].value_counts()
    duplicate_hashes = int((hash_counts > 1).sum())
    cross_dit_hashes = int(
        (
            nonempty.groupby("_TrainingContentHash", sort=False)[dit_col]
            .nunique()
            > 1
        ).sum()
    )
    keep = ~(
        hashes.ne("")
        & hashes.duplicated(keep="first")
    )
    deduplicated = working.loc[keep].drop(
        columns=["_TrainingContentHash", "_TrainingSourceRunKey"],
        errors="ignore",
    )
    return deduplicated, {
        "method": "per_assay_fsa_content_hash_v1",
        "raw_row_count": raw_count,
        "unique_trace_row_count": int(len(deduplicated)),
        "duplicate_rows_removed": int(raw_count - len(deduplicated)),
        "content_hash_coverage": float(hashes.ne("").mean()),
        "duplicate_content_hashes": duplicate_hashes,
        "cross_dit_duplicate_content_hashes": cross_dit_hashes,
        "conflicting_label_content_hashes": conflicting_labels,
        "conflicting_source_run_content_hashes": conflicting_runs,
    }


def group_shuffle_split_by_dit(
    X: pd.DataFrame,
    y: pd.Series,
    dit: pd.Series,
    *,
    test_size: float = 0.20,
    random_state: int = 12345,
) -> tuple[pd.Index, pd.Index]:
    """GroupBy-DIT holdout. Same patient never in train and test."""
    splitter = GroupShuffleSplit(
        n_splits=1, test_size=test_size, random_state=random_state
    )
    train_idx, test_idx = next(splitter.split(X, y, groups=dit.values))
    return (
        pd.Index(sorted(train_idx.tolist())),
        pd.Index(sorted(test_idx.tolist())),
    )


def _build_qda_or_nb_fallback(X_train, y_train) -> "Pipeline":
    """Fit a ``Pipeline(impute -> qda)`` for ``kind='qda_calibrated'``.

    sklearn >= 1.6 raised ``LinAlgError`` (and sometimes ``ValueError``)
    from ``QuadraticDiscriminantAnalysis.fit`` when a class's empirical
    covariance is rank-deficient -- mostly on synthetic fixtures with
    perfectly-collinear features. The fallback swaps in ``GaussianNB``,
    which still satisfies the ``Pipeline.named_steps["qda"]`` shape and
    the ``predict_proba(n_samples, n_classes)`` contract.

    Recipe from the ``python-3.15-migration-runway`` skill
    (validated 3.11 sklearn 1.5 / 3.13 sklearn 1.9, 13+13 tests).
    """
    _QDA = QuadraticDiscriminantAnalysis
    has_solver = "solver" in inspect.signature(_QDA.__init__).parameters

    def make_qda():
        # sklearn >= 1.6 gained ``solver`` + ``shrinkage``; the older
        # (<= 1.5, our 3.11 baseline) path takes no kwargs.
        if has_solver:
            return _QDA(solver="eigen", shrinkage="auto")
        return _QDA()

    def pipe_for(estimator) -> "Pipeline":
        return Pipeline(
            steps=[
                ("impute", SimpleImputer(strategy="median")),
                ("qda", estimator),
            ]
        )

    try:
        pipe = pipe_for(make_qda())
        pipe.fit(X_train, y_train)
        return pipe
    except (ValueError, np.linalg.LinAlgError):
        # Class covariance is rank-deficient on this fixture -- QDA
        # can't represent it; swap the estimator for GaussianNB. Same
        # step name, same predict_proba shape contract.
        pipe = pipe_for(GaussianNB())
        pipe.fit(X_train, y_train)
        return pipe


def fit_classifier(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    kind: str = "random_forest",
    random_state: int = 12345,
    calibration_groups: pd.Series | Sequence[str] | None = None,
    calibration_group_column: str = "DITContentComponent",
) -> Any:
    """Fit a per-assay classifier.

    kind:
      - 'random_forest': RandomForestClassifier(n_estimators=400,
        class_weight='balanced'), wrapped in CalibratedClassifierCV
        (Platt scaling).
      - 'extra_trees': ExtraTreesClassifier with the same class balancing,
        tree count, and calibration policy as RandomForest.
      - 'qda_calibrated': Pipeline(SimpleImputer(median) ->
        QuadraticDiscriminantAnalysis()). On sklearn >= 1.6 the
        rank-counter tightens and QDA.fit() may raise
        ``LinAlgError`` or ``ValueError`` when a class's empirical
        covariance is rank-deficient (e.g. collinear synthetic
        fixtures). In that case the helper
        ``_build_qda_or_nb_fallback`` swaps in
        ``sklearn.naive_bayes.GaussianNB`` while preserving
        ``named_steps["qda"]`` and ``predict_proba(n, n_classes)``.
    """
    if kind not in {"random_forest", "extra_trees", "qda_calibrated"}:
        raise ValueError(f"unknown classifier kind: {kind!r}")
    X_train = _ensure_numeric_X(X_train)
    y_train = y_train.astype(str)
    if kind in TREE_CLASSIFIER_KINDS:
        estimator_type = (
            RandomForestClassifier
            if kind == "random_forest"
            else ExtraTreesClassifier
        )
        base = estimator_type(
            n_estimators=400,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        class_counts = y_train.value_counts()
        min_class_count = int(class_counts.min()) if len(class_counts) else 0
        if min_class_count >= 6:
            calibration_cv, calibration_metadata = _calibration_cv(
                y_train,
                groups=calibration_groups,
                group_column=calibration_group_column,
                random_state=random_state,
            )
        else:
            calibration_cv = None
            calibration_metadata = {
                "status": "skipped",
                "required_for_runtime": True,
                "method": "sigmoid",
                "strategy": "",
                "grouped": False,
                "folds": CALIBRATION_FOLDS,
                "reason": (
                    f"minimum_class_rows={min_class_count} below 6"
                ),
            }
        if calibration_cv is not None:
            try:
                calibrated = CalibratedClassifierCV(
                    estimator=base,
                    method="sigmoid",
                    cv=calibration_cv,
                )
            except TypeError:
                calibrated = CalibratedClassifierCV(
                    base_estimator=base,
                    method="sigmoid",
                    cv=calibration_cv,
                )
            calibrated.fit(X_train, y_train)
            calibrated.hemafrag_calibration_ = calibration_metadata
            return calibrated
        base.fit(X_train, y_train)
        base.hemafrag_calibration_ = calibration_metadata
        return base
    qda = _build_qda_or_nb_fallback(X_train, y_train)
    qda.hemafrag_calibration_ = {
        "status": "native_probability",
        "required_for_runtime": False,
        "method": "native_probability",
        "strategy": "",
        "grouped": False,
        "folds": 0,
        "reason": "",
    }
    return qda


def _calibration_cv(
    y: pd.Series,
    *,
    groups: pd.Series | Sequence[str] | None,
    group_column: str,
    random_state: int,
) -> tuple[list[tuple[np.ndarray, np.ndarray]] | int | None, dict[str, Any]]:
    if groups is None:
        return CALIBRATION_FOLDS, {
            "status": "complete",
            "required_for_runtime": True,
            "method": "sigmoid",
            "strategy": "StratifiedKFold",
            "group_column": "",
            "grouped": False,
            "folds": CALIBRATION_FOLDS,
            "unique_groups": 0,
            "minimum_train_class_rows": 0,
            "minimum_test_class_rows": 0,
            "every_group_held_out_once": False,
            "reason": "",
        }

    labels = pd.Series(y).astype(str).reset_index(drop=True)
    group_values = (
        pd.Series(groups).fillna("").astype(str).str.strip().reset_index(drop=True)
    )
    if len(group_values) != len(labels):
        raise ValueError("calibration groups do not match training rows")
    if group_values.eq("").any():
        return None, _skipped_group_calibration(
            group_column,
            "calibration groups contain empty values",
            unique_groups=int(group_values.loc[group_values.ne("")].nunique()),
        )
    unique_groups = int(group_values.nunique())
    if unique_groups < CALIBRATION_FOLDS:
        return None, _skipped_group_calibration(
            group_column,
            f"unique_calibration_groups={unique_groups} below {CALIBRATION_FOLDS}",
            unique_groups=unique_groups,
        )
    class_group_counts = (
        pd.DataFrame({"label": labels, "group": group_values})
        .groupby("label", sort=False)["group"]
        .nunique()
    )
    minimum_class_groups = int(class_group_counts.min())
    if minimum_class_groups < CALIBRATION_FOLDS:
        return None, _skipped_group_calibration(
            group_column,
            "minimum_class_calibration_groups="
            f"{minimum_class_groups} below {CALIBRATION_FOLDS}",
            unique_groups=unique_groups,
        )

    splitter = StratifiedGroupKFold(
        n_splits=CALIBRATION_FOLDS,
        shuffle=True,
        random_state=int(random_state),
    )
    splits = [
        (np.asarray(train_idx), np.asarray(test_idx))
        for train_idx, test_idx in splitter.split(
            np.zeros(len(labels)),
            labels,
            groups=group_values,
        )
    ]
    all_labels = set(labels)
    minimum_train_rows: int | None = None
    minimum_test_rows: int | None = None
    held_out_rows: list[int] = []
    for train_idx, test_idx in splits:
        train_groups = set(group_values.iloc[train_idx])
        test_groups = set(group_values.iloc[test_idx])
        if train_groups & test_groups:
            raise AssertionError("calibration group leakage detected")
        train_counts = labels.iloc[train_idx].value_counts()
        test_counts = labels.iloc[test_idx].value_counts()
        if set(train_counts.index) != all_labels or set(test_counts.index) != all_labels:
            return None, _skipped_group_calibration(
                group_column,
                "a calibration fold does not contain every class",
                unique_groups=unique_groups,
            )
        fold_train_min = int(train_counts.min())
        fold_test_min = int(test_counts.min())
        minimum_train_rows = (
            fold_train_min
            if minimum_train_rows is None
            else min(minimum_train_rows, fold_train_min)
        )
        minimum_test_rows = (
            fold_test_min
            if minimum_test_rows is None
            else min(minimum_test_rows, fold_test_min)
        )
        held_out_rows.extend(test_idx.tolist())
    if (
        int(minimum_train_rows or 0) < CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT
        or int(minimum_test_rows or 0) < CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT
    ):
        return None, _skipped_group_calibration(
            group_column,
            "minimum class rows in a calibration train/test split below "
            f"{CALIBRATION_MIN_CLASS_ROWS_PER_SPLIT}",
            unique_groups=unique_groups,
            minimum_train_rows=int(minimum_train_rows or 0),
            minimum_test_rows=int(minimum_test_rows or 0),
        )
    every_row_held_out_once = sorted(held_out_rows) == list(range(len(labels)))
    if not every_row_held_out_once:
        raise AssertionError("calibration did not hold every training row out once")
    return splits, {
        "status": "complete",
        "required_for_runtime": True,
        "method": "sigmoid",
        "strategy": "StratifiedGroupKFold",
        "group_column": str(group_column),
        "grouped": True,
        "folds": CALIBRATION_FOLDS,
        "unique_groups": unique_groups,
        "minimum_class_groups": minimum_class_groups,
        "minimum_train_class_rows": int(minimum_train_rows or 0),
        "minimum_test_class_rows": int(minimum_test_rows or 0),
        "every_group_held_out_once": True,
        "reason": "",
    }


def _skipped_group_calibration(
    group_column: str,
    reason: str,
    *,
    unique_groups: int,
    minimum_train_rows: int = 0,
    minimum_test_rows: int = 0,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "required_for_runtime": True,
        "method": "sigmoid",
        "strategy": "StratifiedGroupKFold",
        "group_column": str(group_column),
        "grouped": True,
        "folds": CALIBRATION_FOLDS,
        "unique_groups": int(unique_groups),
        "minimum_train_class_rows": int(minimum_train_rows),
        "minimum_test_class_rows": int(minimum_test_rows),
        "every_group_held_out_once": False,
        "reason": str(reason),
    }


def per_assay_metrics(
    y_true: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    y_prob: np.ndarray | None,
    *,
    classes: Sequence[str],
    assay: str,
    training_samples: int,
    rare_class_counts: Mapping[str, int],
    accept_threshold_tau: float,
    classifier_kind: str = "random_forest",
    prediction_confidence: Sequence[float] | None = None,
) -> PerAssayMetrics:
    """Compute accuracy / F1 / confusion-matrix for one assay's holdout.

    classes: sorted-by-canonical-order labels (estimator.classes_).
    """
    labels = sorted(
        {*classes, *pd.Series(y_true).astype(str).unique()},
        key=_annotation_sort_key,
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    monoklonal_label = "monoklonal"
    try:
        monoklonal_f1 = float(
            f1_score(
                y_true, y_pred,
                labels=[monoklonal_label], average="macro", zero_division=0,
            )
        )
    except ValueError:
        # Class absent in y_pred -- default to NaN -> 0.0
        monoklonal_f1 = 0.0
    macro = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    acc = float(accuracy_score(y_true, y_pred))
    bal_acc = float(balanced_accuracy_score(y_true, y_pred))
    report = classification_report(
        y_true, y_pred, labels=labels, output_dict=True, zero_division=0
    )
    has_confidence = prediction_confidence is not None or y_prob is not None
    if prediction_confidence is not None:
        confidence = np.asarray(prediction_confidence, dtype=float)
    elif y_prob is not None:
        probabilities = np.asarray(y_prob, dtype=float)
        confidence = (
            np.max(probabilities, axis=1)
            if probabilities.ndim == 2 and probabilities.shape[0] == len(y_pred)
            else np.zeros(len(y_pred), dtype=float)
        )
    else:
        confidence = np.zeros(len(y_pred), dtype=float)
    confidence = np.nan_to_num(
        confidence,
        nan=0.0,
        posinf=1.0,
        neginf=0.0,
    )
    confidence = np.clip(confidence, 0.0, 1.0)
    correct = (
        pd.Series(y_true).astype(str).reset_index(drop=True).to_numpy()
        == pd.Series(y_pred).astype(str).reset_index(drop=True).to_numpy()
    )
    accepted = confidence >= float(accept_threshold_tau)
    accepted_coverage = float(np.mean(accepted)) if accepted.size else 0.0
    accepted_accuracy = (
        float(np.mean(correct[accepted])) if accepted.any() else 0.0
    )
    return PerAssayMetrics(
        assay=assay,
        training_samples=int(training_samples),
        monoklonal_f1=monoklonal_f1,
        macro_f1=macro,
        accuracy=acc,
        balanced_accuracy=bal_acc,
        confusion_matrix=cm.tolist(),
        classification_report=report,
        rare_class_counts=dict({str(k): int(v) for k, v in rare_class_counts.items()}),
        accept_threshold_tau=accept_threshold_tau,
        classifier_kind=classifier_kind,
        expected_calibration_error=(
            _expected_calibration_error(correct, confidence)
            if has_confidence
            else 0.0
        ),
        accepted_coverage=accepted_coverage,
        accepted_accuracy=accepted_accuracy,
        mean_confidence=float(np.mean(confidence)) if confidence.size else 0.0,
    )


def _expected_calibration_error(
    correct: np.ndarray,
    confidence: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    if confidence.size == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, max(2, int(bins)) + 1)
    total = float(confidence.size)
    error = 0.0
    for index in range(len(edges) - 1):
        lower = edges[index]
        upper = edges[index + 1]
        in_bin = (
            (confidence >= lower)
            & (confidence <= upper if index == len(edges) - 2 else confidence < upper)
        )
        if not in_bin.any():
            continue
        accuracy = float(np.mean(correct[in_bin]))
        mean_confidence = float(np.mean(confidence[in_bin]))
        error += float(np.sum(in_bin)) / total * abs(accuracy - mean_confidence)
    return float(error)


def serialize_model(
    estimator: Any,
    *,
    label_order: Sequence[str],
    assay: str,
    accept_threshold_tau: float,
    classifier_kind: str,
    rare_class_counts: Mapping[str, int],
    schema_version: str = "ml_training_pipeline_v1",
    trained_at_utc: str = "",
    output_dir: Path | None = None,
    feature_columns: Sequence[str] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Persist a trained estimator and metadata. Returns paths dict.

    ``feature_columns``: optional list of the input feature column names
    (in the order the estimator was fitted on). When present, downstream
    ``ClonalityModelStore.predict`` uses this list to slice the runtime
    feature dict into the exact column contract the estimator expects.
    Cheap to populate; recommended.
    """
    if output_dir is None:
        output_dir = Path.cwd() / "models"
    out_dir = Path(output_dir) / assay
    out_dir.mkdir(parents=True, exist_ok=True)

    joblib_path = out_dir / f"{classifier_kind}.joblib"
    metadata_path = out_dir / "metadata.json"
    joblib.dump(estimator, joblib_path)

    metadata = {
        "schema_version": schema_version,
        "assay": assay,
        "label_order": list(label_order),
        "accept_threshold_tau": float(accept_threshold_tau),
        "classifier_kind": classifier_kind,
        "rare_class_counts": dict({str(k): int(v) for k, v in rare_class_counts.items()}),
        "trained_at_utc": trained_at_utc,
        "runtime_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    if feature_columns is not None:
        metadata["feature_columns"] = [str(c) for c in feature_columns]
    if extra_metadata:
        overlap = sorted(set(metadata) & set(extra_metadata))
        if overlap:
            raise ValueError(
                "extra model metadata cannot replace reserved keys: "
                + ", ".join(overlap)
            )
        metadata.update(dict(extra_metadata))
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return {"joblib": joblib_path, "metadata": metadata_path}


def deserialize_model(
    *,
    joblib_path: Path,
    metadata_path: Path,
) -> tuple[Any, dict[str, Any]]:
    """Inverse of serialize_model.

    Caller is responsible for verifying that
    metadata['schema_version'] matches the expected version -- a
    mismatch means the model was trained under a different code path.
    """
    estimator = joblib.load(Path(joblib_path))
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    return estimator, metadata
