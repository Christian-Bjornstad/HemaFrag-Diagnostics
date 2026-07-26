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
        "trace_peak_count_raw_per_channel.DATA1",
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
                "trace_peak_count_raw_per_channel.DATA1": peak_count,
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


def test_build_per_assay_datasets_normalizes_assay_filter_spelling():
    df = _synth_combined(n_per_assay={"TCRG-A": 24})
    df["Assay"] = "TCRgA"

    out = build_per_assay_datasets(
        df,
        include_assays=["TCRG-A"],
        min_samples_per_assay=20,
    )

    assert set(out) == {"TCRgA"}


def test_build_per_assay_datasets_drops_unlabelled_rows_and_uses_numeric_features_only():
    df = _synth_combined(n_per_assay={"FR1": 12})
    df.loc[0, "ClonalitySuggestion"] = ""
    df["File"] = [f"sample-{index}.fsa" for index in range(len(df))]
    df["ClonalityConfidence"] = 0.99
    df["ClonalityMLConfidence"] = 0.98
    out = build_per_assay_datasets(df, min_samples_per_assay=10)
    ds = out["FR1"]
    assert ds.n_samples == 11
    assert "File" not in ds.X.columns
    assert "ClonalityConfidence" not in ds.X.columns
    assert "ClonalityMLConfidence" not in ds.X.columns


def test_build_per_assay_datasets_rejects_unknown_chemist_label():
    df = _synth_combined(n_per_assay={"FR1": 12})
    df.loc[0, "ClonalitySuggestion"] = "definitely_clonal"
    with pytest.raises(ValueError, match="unknown clonality training labels"):
        build_per_assay_datasets(df, min_samples_per_assay=10)


def test_build_per_assay_datasets_rejects_ladder_only_features():
    frame = pd.DataFrame(
        {
            "DIT": [f"DIT-{index}" for index in range(12)],
            "Assay": ["FR1"] * 12,
            "ClonalitySuggestion": ["monoklonal", "polyklonal"] * 6,
            "LadderR2": [0.999] * 12,
        }
    )
    with pytest.raises(ValueError, match="no raw FSA trace features"):
        build_per_assay_datasets(frame, min_samples_per_assay=10)


def test_per_assay_dataset_rare_class_counts_non_empty_for_FR1():
    df = _synth_combined()
    out = build_per_assay_datasets(df, min_samples_per_assay=100)
    counts = out["FR1"].rare_class_counts
    assert "monoklonal" in counts
    assert counts["monoklonal"] >= 1


def test_per_assay_dataset_reports_independent_class_support():
    df = _synth_combined(n_per_assay={"FR1": 24})
    df["ClonalitySuggestion"] = ["monoklonal", "polyklonal"] * 12
    df["SourceRunKey"] = [f"run-{index % 3}" for index in range(len(df))]

    dataset = build_per_assay_datasets(
        df,
        min_samples_per_assay=20,
    )["FR1"]

    assert dataset.class_support["monoklonal"] == {
        "rows": 12,
        "unique_dit_groups": 12,
        "unique_source_run_groups": 3,
        "rows_missing_source_run": 0,
    }
    assert dataset.class_support["polyklonal"]["unique_dit_groups"] == 12


def test_build_per_assay_datasets_deduplicates_identical_trace_votes():
    df = _synth_combined(n_per_assay={"FR1": 12})
    df["FsaContentHash"] = [f"hash-{index}" for index in range(len(df))]
    df["SourceRunKey"] = "run-a"
    df.loc[1, "FsaContentHash"] = df.loc[0, "FsaContentHash"]
    df.loc[1, "ClonalitySuggestion"] = df.loc[0, "ClonalitySuggestion"]

    dataset = build_per_assay_datasets(
        df,
        min_samples_per_assay=10,
    )["FR1"]

    assert dataset.n_samples == 11
    assert dataset.data_provenance["raw_row_count"] == 12
    assert dataset.data_provenance["unique_trace_row_count"] == 11
    assert dataset.data_provenance["duplicate_rows_removed"] == 1
    assert dataset.data_provenance[
        "cross_dit_duplicate_content_hashes"
    ] == 1


def test_build_per_assay_datasets_rejects_conflicting_duplicate_labels():
    df = _synth_combined(n_per_assay={"FR1": 12})
    df["FsaContentHash"] = [f"hash-{index}" for index in range(len(df))]
    df.loc[0, "ClonalitySuggestion"] = "monoklonal"
    df.loc[1, "ClonalitySuggestion"] = "polyklonal"
    df.loc[1, "FsaContentHash"] = df.loc[0, "FsaContentHash"]

    with pytest.raises(ValueError, match="conflicting chemist labels"):
        build_per_assay_datasets(df, min_samples_per_assay=10)


def test_build_per_assay_datasets_rejects_conflicting_duplicate_runs():
    df = _synth_combined(n_per_assay={"FR1": 12})
    df["FsaContentHash"] = [f"hash-{index}" for index in range(len(df))]
    df["SourceRunKey"] = "run-a"
    df.loc[1, "FsaContentHash"] = df.loc[0, "FsaContentHash"]
    df.loc[1, "ClonalitySuggestion"] = df.loc[0, "ClonalitySuggestion"]
    df.loc[1, "SourceRunKey"] = "run-b"

    with pytest.raises(ValueError, match="conflicting source runs"):
        build_per_assay_datasets(df, min_samples_per_assay=10)


def test_minimum_samples_is_applied_after_trace_deduplication():
    df = _synth_combined(n_per_assay={"FR1": 10})
    df["FsaContentHash"] = [f"hash-{index}" for index in range(len(df))]
    df.loc[1, "FsaContentHash"] = df.loc[0, "FsaContentHash"]
    df.loc[1, "ClonalitySuggestion"] = df.loc[0, "ClonalitySuggestion"]

    assert build_per_assay_datasets(
        df,
        min_samples_per_assay=10,
    ) == {}


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


def test_fit_classifier_extra_trees_predicts_labels():
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    train_idx, test_idx = group_shuffle_split_by_dit(
        ds.X,
        ds.y,
        ds.dit,
        random_state=12345,
    )

    estimator = fit_classifier(
        ds.X.iloc[train_idx],
        ds.y.iloc[train_idx],
        kind="extra_trees",
    )

    assert len(estimator.predict(ds.X.iloc[test_idx])) == len(test_idx)
    assert estimator.predict_proba(ds.X.iloc[test_idx[:3]]).shape[0] == 3


def test_fit_classifier_uses_grouped_calibration_without_patient_overlap():
    row_count = 36
    X = pd.DataFrame(
        {
            "trace_runtime_signal": np.linspace(0.0, 1.0, row_count),
            "trace_peak_count_raw_per_channel.DATA1": (
                [2.0, 12.0] * (row_count // 2)
            ),
        }
    )
    y = pd.Series(["monoklonal", "polyklonal"] * (row_count // 2))
    groups = pd.Series([f"DIT-{index:03d}" for index in range(row_count)])

    estimator = fit_classifier(
        X,
        y,
        kind="random_forest",
        calibration_groups=groups,
        calibration_group_column="DITContentComponent",
    )
    calibration = estimator.hemafrag_calibration_

    assert calibration["status"] == "complete"
    assert calibration["strategy"] == "StratifiedGroupKFold"
    assert calibration["grouped"] is True
    assert calibration["every_group_held_out_once"] is True
    for train_idx, test_idx in estimator.cv:
        assert set(groups.iloc[train_idx]).isdisjoint(
            set(groups.iloc[test_idx])
        )


def test_fit_classifier_skips_calibration_when_class_has_too_few_groups():
    X = pd.DataFrame(
        {
            "trace_runtime_signal": np.linspace(0.0, 1.0, 24),
            "trace_peak_count_raw_per_channel.DATA1": [2.0] * 12
            + [12.0] * 12,
        }
    )
    y = pd.Series(["monoklonal"] * 12 + ["polyklonal"] * 12)
    groups = pd.Series(
        ["mono-a", "mono-b"] * 6 + ["poly-a", "poly-b"] * 6
    )

    estimator = fit_classifier(
        X,
        y,
        kind="random_forest",
        calibration_groups=groups,
    )

    assert estimator.hemafrag_calibration_["status"] == "skipped"
    assert "minimum_class_calibration_groups=2 below 3" in (
        estimator.hemafrag_calibration_["reason"]
    )


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
    assert m.accepted_coverage == 0.0
    assert m.accepted_accuracy == 0.0
    assert m.expected_calibration_error == 0.0
    # Confusion matrix: rows=predicted, cols=true
    assert isinstance(m.confusion_matrix, list)
    assert all(isinstance(row, list) for row in m.confusion_matrix)


def test_per_assay_metrics_reports_confidence_calibration_and_coverage():
    y_true = pd.Series(["monoklonal", "polyklonal", "monoklonal", "polyklonal"])
    y_pred = pd.Series(["monoklonal", "polyklonal", "polyklonal", "polyklonal"])
    confidence = [0.95, 0.90, 0.80, 0.60]

    metrics = per_assay_metrics(
        y_true,
        y_pred,
        y_prob=None,
        prediction_confidence=confidence,
        classes=["monoklonal", "polyklonal"],
        assay="FR1",
        training_samples=4,
        rare_class_counts={"monoklonal": 2, "polyklonal": 2},
        accept_threshold_tau=0.85,
    )

    assert metrics.accepted_coverage == 0.5
    assert metrics.accepted_accuracy == 1.0
    assert metrics.mean_confidence == pytest.approx(0.8125)
    assert 0.0 <= metrics.expected_calibration_error <= 1.0


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
    assert meta["runtime_versions"]["python"]
    assert meta["runtime_versions"]["scikit_learn"]

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


def test_serialize_model_persists_validation_and_deployment_metadata(tmp_path):
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    estimator = fit_classifier(
        ds.X,
        ds.y,
        kind="random_forest",
    )
    paths = serialize_model(
        estimator,
        label_order=list(ANNOTATION_CLASSES_ORDER),
        assay="FR1",
        accept_threshold_tau=0.85,
        classifier_kind="random_forest",
        rare_class_counts=ds.rare_class_counts,
        output_dir=tmp_path,
        extra_metadata={
            "deployment_status": "candidate",
            "runtime_eligible": False,
            "validation": {"strategy": "StratifiedGroupKFold"},
        },
    )

    meta = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    assert meta["deployment_status"] == "candidate"
    assert meta["runtime_eligible"] is False
    assert meta["validation"]["strategy"] == "StratifiedGroupKFold"


def test_serialize_model_rejects_reserved_metadata_override(tmp_path):
    df = _synth_combined()
    ds = build_per_assay_datasets(df, min_samples_per_assay=100)["FR1"]
    estimator = fit_classifier(ds.X, ds.y, kind="random_forest")

    with pytest.raises(ValueError, match="reserved keys"):
        serialize_model(
            estimator,
            label_order=list(ANNOTATION_CLASSES_ORDER),
            assay="FR1",
            accept_threshold_tau=0.85,
            classifier_kind="random_forest",
            rare_class_counts=ds.rare_class_counts,
            output_dir=tmp_path,
            extra_metadata={"assay": "TCRG-A"},
        )
