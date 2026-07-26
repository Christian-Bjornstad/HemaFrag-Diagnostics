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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import inspect
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
from sklearn.naive_bayes import GaussianNB
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

from core.analyses.clonality.ml_data_contract import (
    CHEMIST_LABEL_COLUMN,
    is_trace_feature,
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
    "ClonalityMLReviewNeeded",
    "ClonalityMLModelVersion",
}

__all__ = [
    "ANNOTATION_CLASSES_ORDER",
    "build_per_assay_datasets",
    "group_shuffle_split_by_dit",
    "fit_classifier",
    "per_assay_metrics",
    "serialize_model",
    "deserialize_model",
    "PerAssayDataset",
    "PerAssayMetrics",
]


@dataclass
class PerAssayDataset:
    """Built once per assay, used by every fold.

    X: pd.DataFrame, shape (n_samples, n_features), all numeric.
    y: pd.Series of str, length n_samples.
    dit: pd.Series of str, length n_samples, used for group split.
    assay: str -- the assay tube (e.g., "FR1").
    n_samples: int -- populated post-init from len(X).
    rare_class_counts: dict[str, int] -- ANNOTATION_CLASSES -> row counts.
    """

    X: pd.DataFrame
    y: pd.Series
    dit: pd.Series
    assay: str
    rare_class_counts: dict[str, int] = field(default_factory=dict)
    n_samples: int = 0

    def __post_init__(self) -> None:
        if self.n_samples == 0:
            self.n_samples = int(len(self.X))


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


def _annotation_sort_key(name: str) -> int:
    try:
        return ANNOTATION_CLASSES_ORDER.index(name)
    except ValueError:
        return len(ANNOTATION_CLASSES_ORDER)


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
    if not any(is_trace_feature(column) for column in feature_cols):
        raise ValueError(
            "no raw FSA trace features were available for training; "
            "refusing to fit a ladder/QC-only clonality model"
        )

    out: dict[str, PerAssayDataset] = {}
    for assay_name, group in combined_df.groupby(assay_col, sort=True):
        if pd.isna(assay_name):
            continue
        if include_assays is not None and str(assay_name) not in include_assays:
            continue
        if len(group) < min_samples_per_assay:
            continue
        X_num = _ensure_numeric_X(group[feature_cols]).reset_index(drop=True)
        y_series = group[label_col].astype(str).reset_index(drop=True)
        dit_series = group[dit_col].astype(str).reset_index(drop=True)
        counts = group[label_col].value_counts().to_dict()
        out[str(assay_name)] = PerAssayDataset(
            X=X_num,
            y=y_series,
            dit=dit_series,
            assay=str(assay_name),
            n_samples=len(group),
            rare_class_counts={str(k): int(v) for k, v in counts.items()},
        )
    return out


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
) -> Any:
    """Fit a per-assay classifier.

    kind:
      - 'random_forest': RandomForestClassifier(n_estimators=400,
        class_weight='balanced'), wrapped in CalibratedClassifierCV
        (Platt scaling).
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
    if kind not in {"random_forest", "qda_calibrated"}:
        raise ValueError(f"unknown classifier kind: {kind!r}")
    X_train = _ensure_numeric_X(X_train)
    y_train = y_train.astype(str)
    if kind == "random_forest":
        base = RandomForestClassifier(
            n_estimators=400,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        # Minimum per-class count for 3-fold CV.
        class_counts = y_train.value_counts()
        min_class_count = int(class_counts.min()) if len(class_counts) else 0
        if min_class_count >= 6:
            try:
                calibrated = CalibratedClassifierCV(
                    estimator=base, method="sigmoid", cv=3
                )
            except TypeError:
                calibrated = CalibratedClassifierCV(
                    base_estimator=base, method="sigmoid", cv=3
                )
            calibrated.fit(X_train, y_train)
            return calibrated
        # Tiny dataset -- skip Platt scaling, just return raw RF.
        base.fit(X_train, y_train)
        return base
    qda = _build_qda_or_nb_fallback(X_train, y_train)
    return qda


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
    )


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
    }
    if feature_columns is not None:
        metadata["feature_columns"] = [str(c) for c in feature_columns]
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
