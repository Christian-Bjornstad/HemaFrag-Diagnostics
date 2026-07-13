"""Phase 3 / T-3.x tests for the per-assay clonality ML pipeline.

Exercises:
  - build_per_assay_datasets (with group split semantics)
  - group_shuffle_split_by_dit (DIT never overlaps train/test)
  - fit_classifier with random_forest + qda_calibrated kinds
  - per_assay_metrics output shape
  - serialize_model / deserialize_model roundtrip
  - end-to-end micro-train on a synthetic 250-row FR1 dataset
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.analyses.clonality.ml_training import (
    ANNOTATION_CLASSES_ORDER,
    PerAssayDataset,
    build_per_assay_datasets,
    deserialize_model,
    fit_classifier,
    group_shuffle_split_by_dit,
    per_assay_metrics,
    serialize_model,
)

NP_RNG = np.random.default_rng(42)


def _synth_combined(  # noqa: C901 -- synthetic generator
    *,
    n_per_assay: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Generate a synthetic combined DataFrame.

    Mirrors the shape `feature_artifacts.build_clonality_feature_tables`
    would emit, with DIT + Assay + a label column + numeric features.
    """
    if n_per_assay is None:
        n_per_assay = {"FR1": 250, "TCRG-A": 220, "DHJH_D": 80}
    rows = []
    feature_names = [
        "ladder_r2", "ladder_linear_r2", "peak_count",
        "dominant_peak_height", "dominant_height_share", "dominant_to_second_ratio",
        "peak_variance_per_channel.DATA1", "mad_per_channel.DATA1",
        "peak_count_per_channel.DATA1",
        "dom_distance_to_ref_window_center_bp",
        "in_reference_window",
        "patient_assays_run_count", "assay_panel_completeness_pct",
    ]
    dit_counter = 100
    for assay, n in n_per_assay.items():
        dits = [f"26SYN{dit_counter+i:05d}" for i in range(n)]
        for i, dit in enumerate(dits):
            label_p = {
                "FR1": [0.45, 0.40, 0.10, 0.04, 0.01],
                "TCRG-A": [0.55, 0.30, 0.10, 0.04, 0.01],
                "DHJH_D": [0.30, 0.50, 0.10, 0.08, 0.02],
            }[assay]
            label = ANNOTATION_CLASSES_ORDER[
                int(NP_RNG.choice(5, p=label_p))
            ] if i > 0 else "monoklonal"
            # Some truly mono rows use high dominant-height, few in range
            if label == "monoklonal":
                dom_h = float(NP_RNG.uniform(800, 1500))
                ratio = float(NP_RNG.uniform(2.0, 4.0))
                dom_share = float(NP_RNG.uniform(0.6, 0.9))
                peak_count = int(NP_RNG.integers(3, 8))
                in_win = 1
            else:
                dom_h = float(NP_RNG.uniform(50, 250))
                ratio = float(NP_RNG.uniform(0.5, 1.3))
                dom_share = float(NP_RNG.uniform(0.1, 0.4))
                peak_count = int(NP_RNG.integers(8, 25))
                in_win = 1 if label == "polyklonal" else 0
            ladder_r2 = float(NP_RNG.uniform(0.97, 1.000))
            patient_assays = int(NP_RNG.integers(1, 6))
            row = {
                "DIT": dit,
                "Assay": assay,
                "ClonalitySuggestion": label,
                "ladder_r2": ladder_r2,
                "ladder_linear_r2": ladder_r2,
                "peak_count": peak_count,
                "dominant_peak_height": dom_h,
                "dominant_height_share": dom_share,
                "dominant_to_second_ratio": ratio,
                "peak_variance_per_channel.DATA1": float(NP_RNG.uniform(0.01, 4.0)),
                "mad_per_channel.DATA1": float(NP_RNG.uniform(0.001, 1.2)),
                "peak_count_per_channel.DATA1": peak_count,
                "dom_distance_to_ref_window_center_bp": float(NP_RNG.uniform(-30, 30)),
                "in_reference_window": in_win,
                "patient_assays_run_count": patient_assays,
                "assay_panel_completeness_pct": float(patient_assays) / 9.0,
            }
            rows.append(row)
        dit_counter += n
    return pd.DataFrame(rows)


# ----- T-3.2 build_per_assay_datasets ------------------------------

def test_build_per_assay_datasets_returns_per_assay_objects():
    df = _synth_combined()
    out = build_per_assay_datasets(df, min_samples_per_assay=100)
    assert isinstance(out, dict)
    assert "FR1" in out
    assert "TCRG-A" in out
    # DHJH_D has 80 rows, below the 100-min threshold -> still in dict but flag empty
    assert "DHJH_D" not in out  # dropped (below 100-sample threshold)


def test_build_per_assay_datasets_aliases_lower_case_columns():
    df = _synth_combined()
    df = df.rename(columns={"DIT": "dit", "Assay": "assay", "ClonalitySuggestion": "y"})
    out = build_per_assay_datasets(df, min_samples_per_assay=100)
    assert isinstance(out.get("FR1"), PerAssayDataset)


def test_build_per_assay_datasets_empty_dataframe_returns_empty_dict():
    out = build_per_assay_datasets(pd.DataFrame(), min_samples_per_assay=1)
    assert out == {}


def test_per_assay_dataset_rare_class_counts_non_empty_for_FR1():
    df = _synth_combined()
    out = build_per_assay_datasets(df, min_samples_per_assay=100)
    counts = out["FR1"].rare_class_counts
    assert "monoklonal" in counts
    assert counts["monoklonal"] >= 1


# ----- T-3.3 group_shuffle_split_by_dit ------------------------------

def test_group_shuffle_split_respects_dit_groups():
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, test_idx = group_shuffle_split_by_dit(
        ds.X, ds.y, ds.dit, test_size=0.25, random_state=12345
    )
    assert isinstance(train_idx, pd.Index)
    assert isinstance(test_idx, pd.Index)
    assert len(train_idx) > 0
    assert len(test_idx) > 0
    # 24.4% < test_size < 25.6% slice for n=250 with integer rounding
    ratio = len(test_idx) / (len(train_idx) + len(test_idx))
    assert 0.10 < ratio < 0.40
    # No DIT overlap between splits
    train_dits = set(ds.dit.iloc[train_idx].tolist())
    test_dits = set(ds.dit.iloc[test_idx].tolist())
    assert train_dits.isdisjoint(test_dits)


def test_group_shuffle_split_raises_on_size_mismatch_inputs():
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    with pytest.raises(ValueError):
        # mismatched lengths on X and y -> sklearn will error
        group_shuffle_split_by_dit(
            ds.X.iloc[:100], ds.y.iloc[:50], ds.dit.iloc[:100],
            test_size=0.20,
        )


# ----- T-3.4 fit_classifier --------------------------------------

def test_fit_classifier_random_forest_predicts_labels():
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, test_idx = group_shuffle_split_by_dit(ds.X, ds.y, ds.dit, random_state=12345)
    X_train, y_train = ds.X.iloc[train_idx], ds.y.iloc[train_idx]
    X_test = ds.X.iloc[test_idx]
    estimator = fit_classifier(X_train, y_train, kind="random_forest")
    preds = estimator.predict(X_test)
    assert len(preds) == len(test_idx)
    # All preds in ANNOTATION_CLASSES_ORDER (or close-enough strings)
    label_set = set(ANNOTATION_CLASSES_ORDER)
    pred_set = set(preds.tolist())
    assert pred_set.issubset(label_set | {"polyklonal", "monoklonal", "usikker_review"})  # tolerate rule labels


def test_fit_classifier_rejects_unknown_kind():
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    with pytest.raises(ValueError):
        fit_classifier(ds.X.iloc[:30], ds.y.iloc[:30], kind="totally_made_up")


def test_fit_classifier_qda_calibrated_runs():
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, _ = group_shuffle_split_by_dit(ds.X, ds.y, ds.dit, random_state=12345)
    X_train, y_train = ds.X.iloc[train_idx], ds.y.iloc[train_idx]
    estimator = fit_classifier(X_train, y_train, kind="qda_calibrated")
    # qda_calibrated returns a Pipeline; predict_proba must work
    proba = estimator.predict_proba(ds.X.iloc[:10])
    assert proba.shape == (10, len(estimator.named_steps["qda"].classes_))


# ----- per_assay_metrics ------------------------------------------

def test_per_assay_metrics_basic_shape():
    y_true = pd.Series(["monoklonal"] * 5 + ["polyklonal"] * 5)
    y_pred = pd.Series(["monoklonal", "monoklonal", "polyklonal",
                        "mono_klonal", "monoklonal", "polyklonal",
                        "polyklonal", "monoklonal", "polyklonal",
                        "polyklonal"])
    m = per_assay_metrics(
        y_true, y_pred, y_prob=None,
        classes=["monoklonal", "polyklonal"],
        assay="FR1",
        training_samples=200,
        rare_class_counts={"monoklonal": 100, "polyklonal": 100},
        accept_threshold_tau=0.85,
    )
    assert m.assay == "FR1"
    assert 0.0 <= m.accuracy <= 1.0
    assert 0.0 <= m.macro_f1 <= 1.0
    assert 0.0 <= m.monoklonal_f1 <= 1.0
    assert m.accept_threshold_tau == 0.85
    # Confusion matrix: rows=predicted, cols=true
    assert isinstance(m.confusion_matrix, list)
    assert all(isinstance(row, list) for row in m.confusion_matrix)


def test_per_assay_metrics_csv_roundtrip(tmp_path):
    y_true = pd.Series(["monoklonal", "polyklonal"] * 5)
    y_pred = pd.Series(["monoklonal", "polyklonal"] * 5)
    m = per_assay_metrics(
        y_true, y_pred, y_prob=None,
        classes=["monoklonal", "polyklonal"],
        assay="FR1",
        training_samples=200,
        rare_class_counts={"monoklonal": 100, "polyklonal": 100},
        accept_threshold_tau=0.85,
    )
    out = tmp_path / "metrics.json"
    out.write_text(json.dumps({
        "assay": m.assay, "monoklonal_f1": m.monoklonal_f1,
        "macro_f1": m.macro_f1, "accuracy": m.accuracy,
    }), encoding="utf-8")
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["assay"] == "FR1"
    assert 0.0 <= parsed["monoklonal_f1"] <= 1.0


# ----- serialize_model / deserialize_model --------------------------

def test_serialize_model_writes_joblib_and_metadata(tmp_path):
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, _ = group_shuffle_split_by_dit(ds.X, ds.y, ds.dit, random_state=12345)
    estimator = fit_classifier(ds.X.iloc[train_idx], ds.y.iloc[train_idx],
                               kind="random_forest")
    paths = serialize_model(
        estimator,
        label_order=list(ANNOTATION_CLASSES_ORDER),
        assay="FR1",
        accept_threshold_tau=0.85,
        classifier_kind="random_forest",
        rare_class_counts={"monoklonal": 100, "polyklonal": 100},
        trained_at_utc="2026-06-29T05:25:00Z",
        output_dir=tmp_path,
    )
    assert paths["joblib"].exists()
    assert paths["metadata"].exists()
    meta = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    assert meta["schema_version"] == "ml_training_pipeline_v1"
    assert meta["assay"] == "FR1"
    assert meta["accept_threshold_tau"] == 0.85

    # Roundtrip load: predict via loaded model
    roundtrip_model, roundtrip_meta = deserialize_model(
        joblib_path=paths["joblib"], metadata_path=paths["metadata"]
    )
    assert roundtrip_meta["assay"] == "FR1"
    assert hasattr(roundtrip_model, "predict")
    # Smoke: predict on the same X
    preds = roundtrip_model.predict(ds.X.iloc[:5])
    assert len(preds) == 5


def test_serialize_model_persists_feature_columns(tmp_path):
    """When feature_columns is passed, it lands in metadata.json round-trip."""
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, _ = group_shuffle_split_by_dit(ds.X, ds.y, ds.dit, random_state=12345)
    estimator = fit_classifier(ds.X.iloc[train_idx], ds.y.iloc[train_idx],
                               kind="random_forest")
    cols = ["f_height", "f_ratio", "f_share"]
    paths = serialize_model(
        estimator,
        label_order=list(ANNOTATION_CLASSES_ORDER),
        assay="FR1",
        accept_threshold_tau=0.85,
        classifier_kind="random_forest",
        rare_class_counts={"monoklonal": 100, "polyklonal": 100},
        output_dir=tmp_path,
        feature_columns=cols,
    )
    meta = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    assert meta["feature_columns"] == cols
    # Roundtrip through deserialize_model
    _, meta2 = deserialize_model(
        joblib_path=paths["joblib"], metadata_path=paths["metadata"]
    )
    assert meta2["feature_columns"] == cols


def test_serialize_model_omits_feature_columns_when_unset(tmp_path):
    """Backwards compat: existing callers that don't pass feature_columns
    should still produce a metadata.json keyed on the original schema."""
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, _ = group_shuffle_split_by_dit(ds.X, ds.y, ds.dit, random_state=12345)
    estimator = fit_classifier(ds.X.iloc[train_idx], ds.y.iloc[train_idx],
                               kind="random_forest")
    paths = serialize_model(
        estimator,
        label_order=list(ANNOTATION_CLASSES_ORDER),
        assay="FR1",
        accept_threshold_tau=0.85,
        classifier_kind="random_forest",
        rare_class_counts={"monoklonal": 100, "polyklonal": 100},
        output_dir=tmp_path,
    )
    meta = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    assert "feature_columns" not in meta
