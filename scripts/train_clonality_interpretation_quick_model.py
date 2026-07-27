from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.analyses.clonality.interpretation import (
    ANNOTATION_CLASSES,
    ANNOTATION_SCHEMA_VERSION,
    MODEL_VERSION,
    annotation_export_rows_to_frame,
)


NUMERIC_FEATURES = [
    "ladder_r2",
    "ladder_linear_r2",
    "ladder_linear_mean_residual_bp",
    "ladder_linear_max_residual_bp",
    "raw_peak_count",
    "peak_count",
    "peak_count_in_interpretation_range",
    "peak_count_outside_interpretation_range",
    "dominant_peak_basepairs",
    "outside_interpretation_height_share",
    "interpretation_range_min_bp",
    "interpretation_range_max_bp",
    "dominant_peak_height",
    "second_peak_height",
    "dominant_to_second_ratio",
    "dominant_height_share",
    "total_peak_height",
    "dominant_peak_area",
    "total_peak_area",
    "dominant_area_share",
    "rust_preview_top_score",
    "rust_preview_top_clonal_groups",
    "rust_preview_top_dominant_ratio",
    "tracking_marker_count",
    "tracking_marker_hits",
    "tracking_marker_misses",
    "sl_total_area",
    "sl_100_percent",
    "sl_200_percent",
    "sl_300_percent",
    "sl_400_percent",
    "sl_600_percent",
    "sl_fragmented_percent",
]

TRACE_NUMERIC_PREFIXES = ("trace_", "replicate_")
NON_NUMERIC_PREFIX_FEATURES = {
    "trace_primary_channel",
    "trace_channels_evaluated",
    "trace_reference_ranges_bp",
    "replicate_peak_basepairs",
}

CATEGORICAL_FEATURES = [
    "assay",
    "ladder",
    "primary_peak_channel",
    "sample_kind",
    "control",
    "control_bucket",
    "ladder_qc_status",
    "sl_quality_class",
]


def read_annotations(path: Path) -> pd.DataFrame:
    path = Path(path).expanduser()
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return annotation_export_rows_to_frame(payload)
    return pd.read_csv(path).fillna("")


def build_training_frame(annotation_path: Path, feature_path: Path | None = None) -> pd.DataFrame:
    annotations = read_annotations(annotation_path)
    if annotations.empty:
        return annotations
    annotations = annotations.copy()
    annotations["label"] = annotations.get("label", "").fillna("").astype(str).str.strip()
    annotations = annotations[annotations["label"].isin(ANNOTATION_CLASSES)].copy()

    if feature_path is not None and Path(feature_path).exists():
        features = pd.read_csv(feature_path).fillna("")
        if "raw_path" in annotations.columns and "raw_path" in features.columns:
            overlap = [col for col in features.columns if col not in annotations.columns or col == "raw_path"]
            annotations = annotations.merge(features[overlap], on="raw_path", how="left", suffixes=("", "_feature"))

    for column in NUMERIC_FEATURES:
        if column not in annotations.columns:
            annotations[column] = 0.0
        annotations[column] = pd.to_numeric(annotations[column], errors="coerce").fillna(0.0)
    for column in _trace_numeric_columns(annotations):
        annotations[column] = pd.to_numeric(annotations[column], errors="coerce").fillna(0.0)
    for column in CATEGORICAL_FEATURES:
        if column not in annotations.columns:
            annotations[column] = ""
        annotations[column] = annotations[column].fillna("").astype(str)
    return annotations


def train_quick_model(annotation_path: Path, out_dir: Path, feature_path: Path | None = None, random_state: int = 42) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = build_training_frame(annotation_path, feature_path)
    trace_numeric_features = _trace_numeric_columns(frame)
    numeric_features = NUMERIC_FEATURES + trace_numeric_features
    feature_columns = numeric_features + CATEGORICAL_FEATURES
    (out_dir / "feature_columns.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                "numeric": NUMERIC_FEATURES,
                "trace_numeric": trace_numeric_features,
                "categorical": CATEGORICAL_FEATURES,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "annotation_path": str(annotation_path),
        "feature_path": str(feature_path) if feature_path else "",
        "rows": int(len(frame)),
        "label_counts": frame["label"].value_counts().to_dict() if "label" in frame.columns else {},
        "trained": False,
        "reason": "",
    }

    if frame.empty or frame["label"].nunique() < 2:
        report["reason"] = "Need at least two annotated classes to train."
        _write_empty_outputs(out_dir, report)
        return report

    label_counts = frame["label"].value_counts()
    can_stratify = bool(label_counts.min() >= 2 and len(frame) >= max(6, len(label_counts) * 2))
    if len(frame) < 4:
        report["reason"] = "Too few annotated rows for a useful train/test split."
        _write_empty_outputs(out_dir, report)
        return report

    x = frame[feature_columns].copy()
    y = frame["label"].astype(str)
    test_size = 0.25 if len(frame) >= 20 else 0.4
    group_split = False
    if "patient_id" in frame.columns:
        groups = _training_groups(frame)
        if groups.nunique() >= 2 and len(frame) >= 8:
            splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
            train_idx, test_idx = next(splitter.split(x, y, groups=groups))
            x_train = x.iloc[train_idx].copy()
            x_test = x.iloc[test_idx].copy()
            y_train = y.iloc[train_idx].copy()
            y_test = y.iloc[test_idx].copy()
            group_split = True
        else:
            group_split = False

    if not group_split:
        stratify = y if can_stratify else None
        x_train, x_test, y_train, y_test = train_test_split(
            x,
            y,
            test_size=test_size,
            random_state=random_state,
            stratify=stratify,
        )

    model = Pipeline(
        steps=[
            (
                "features",
                ColumnTransformer(
                    transformers=[
                        ("num", "passthrough", NUMERIC_FEATURES),
                        ("trace", "passthrough", trace_numeric_features),
                        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
                    ]
                ),
            ),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=250,
                    min_samples_leaf=2,
                    random_state=random_state,
                    class_weight="balanced_subsample",
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    pred = model.predict(x_test)
    labels = sorted(y.unique())
    matrix = confusion_matrix(y_test, pred, labels=labels)
    pd.DataFrame(matrix, index=labels, columns=labels).to_csv(out_dir / "confusion_matrix.csv")

    preview = frame[["raw_path", "file", "label"]].copy() if {"raw_path", "file", "label"}.issubset(frame.columns) else frame[["label"]].copy()
    preview["prediction"] = model.predict(x)
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(x)
        preview["prediction_confidence"] = np.max(probabilities, axis=1)
    preview.to_csv(out_dir / "prediction_preview.csv", index=False)

    model_path = out_dir / "model.joblib"
    joblib.dump(
        {
            "model_version": MODEL_VERSION,
            "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
            "feature_columns": feature_columns,
            "numeric_features": numeric_features,
            "trace_numeric_features": trace_numeric_features,
            "categorical_features": CATEGORICAL_FEATURES,
            "model": model,
        },
        model_path,
    )
    report.update(
        {
            "trained": True,
            "model_path": str(model_path),
            "train_rows": int(len(x_train)),
            "test_rows": int(len(x_test)),
            "stratified_split": bool(can_stratify),
            "group_split": bool(group_split),
            "classification_report": classification_report(y_test, pred, labels=labels, output_dict=True, zero_division=0),
        }
    )
    (out_dir / "label_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _trace_numeric_columns(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    columns = []
    for column in frame.columns:
        if not any(str(column).startswith(prefix) for prefix in TRACE_NUMERIC_PREFIXES):
            continue
        if column in NUMERIC_FEATURES or column in CATEGORICAL_FEATURES:
            continue
        if column in NON_NUMERIC_PREFIX_FEATURES:
            continue
        columns.append(str(column))
    return sorted(columns)


def _training_groups(frame: pd.DataFrame) -> pd.Series:
    patient = frame.get("patient_id", pd.Series([""] * len(frame), index=frame.index)).fillna("").astype(str).str.strip()
    raw_path = frame.get("raw_path", pd.Series([""] * len(frame), index=frame.index)).fillna("").astype(str)
    file_name = frame.get("file", pd.Series([""] * len(frame), index=frame.index)).fillna("").astype(str)
    return patient.where(patient.str.len() > 0, raw_path.where(raw_path.str.len() > 0, file_name))


def _write_empty_outputs(out_dir: Path, report: dict[str, Any]) -> None:
    pd.DataFrame().to_csv(out_dir / "confusion_matrix.csv")
    pd.DataFrame().to_csv(out_dir / "prediction_preview.csv", index=False)
    (out_dir / "label_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a quick offline clonality interpretation model.")
    parser.add_argument("--annotations", type=Path, required=True, help="Annotation JSON or CSV exported from the HTML panel.")
    parser.add_argument("--features", type=Path, default=None, help="Optional feature_rows.csv from the HTML panel.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()
    report = train_quick_model(
        annotation_path=args.annotations.expanduser(),
        feature_path=args.features.expanduser() if args.features else None,
        out_dir=args.out_dir.expanduser(),
        random_state=args.random_state,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
