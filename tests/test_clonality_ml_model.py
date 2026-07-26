"""Tests for ClonalityModelStore — wrapper that loads + caches + predicts
per-assay joblib models living under a model directory of shape
``<model_dir>/<assay>/<classifier>.joblib + metadata.json``.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier

from core.analyses.clonality.ml_model import ClonalityModelStore
from core.analyses.clonality.ml_training import ANNOTATION_CLASSES_ORDER


# --- helpers -------------------------------------------------------------


def _make_meta(*, assay: str, tau: float = 0.80, features: list[str] | None = None) -> dict:
    return {
        "schema_version": "ml_training_pipeline_v2",
        "assay": assay,
        "label_order": list(ANNOTATION_CLASSES_ORDER),
        "accept_threshold_tau": float(tau),
        "classifier_kind": "random_forest",
        "rare_class_counts": {"monoklonal": 50, "polyklonal": 50},
        "trained_at_utc": "2026-07-13T10:00:00Z",
        "feature_columns": features or ["trace_runtime_signal", "f_ratio", "f_share"],
        "trace_feature_schema_version": "clonality_trace_features_v1",
        "deployment_status": "validated",
        "runtime_eligible": True,
        "validation": {
            "strategy": "StratifiedGroupKFold",
            "every_row_oof_once": True,
            "effective_splits": 5,
            "promotion_gate": {"passed": True},
        },
    }


def _train_dummy_model(*, seed: int = 0) -> RandomForestClassifier:
    """Build a tiny pretrained RF on 3 features with 2 labels.

    A Real test fixture would carry accuracy risk; the store tests only
    exercise the load + predict + threshold path, not the classifier
    itself. A small RF that always predicts monoklonal is sufficient.
    """
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(60, 3))
    y = np.array(["monoklonal"] * 30 + ["polyklonal"] * 30)
    clf = RandomForestClassifier(n_estimators=20, random_state=seed, n_jobs=1)
    clf.fit(X, y)
    return clf


def _make_model_dir(tmp_path: Path, assays: list[str]) -> Path:
    """Write a synthetic model folder with one RF per listed assay."""
    for assay in assays:
        assay_dir = tmp_path / assay
        assay_dir.mkdir(parents=True, exist_ok=True)
        clf = _train_dummy_model(seed=abs(hash(assay)) % 1000)
        joblib.dump(clf, assay_dir / "random_forest.joblib")
        # Every-assay default — also drop a DummyClassifier as the fallback
        # so we have at least one joblib we can confirm gets ignored.
        joblib.dump(DummyClassifier(strategy="most_frequent"),
                    assay_dir / "dummy.joblib")
        meta = _make_meta(assay=assay)
        (assay_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


# --- tests ---------------------------------------------------------------


def test_store_returns_empty_when_dir_none(tmp_path):
    store = ClonalityModelStore(model_dir=None)
    assert store.is_enabled("FR1") is False
    assert store.predict("FR1", {"anything": 1}) is None


def test_store_returns_empty_when_dir_missing(tmp_path):
    bogus = tmp_path / "does-not-exist"
    store = ClonalityModelStore(model_dir=bogus)
    assert store.is_enabled("FR1") is False
    assert store.predict("FR1", {}) is None


def test_store_ignores_candidate_model(tmp_path):
    _make_model_dir(tmp_path, ["FR1"])
    metadata_path = tmp_path / "FR1" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["deployment_status"] = "candidate"
    metadata["runtime_eligible"] = False
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    store = ClonalityModelStore(model_dir=tmp_path)

    assert store.is_enabled("FR1") is False
    assert store.predict("FR1", {"f_height": 1.0}) is None


def test_store_ignores_artifact_without_grouped_validation(tmp_path):
    _make_model_dir(tmp_path, ["FR1"])
    metadata_path = tmp_path / "FR1" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["validation"]["every_row_oof_once"] = False
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert ClonalityModelStore(model_dir=tmp_path).is_enabled("FR1") is False


def test_store_ignores_classifier_filename_metadata_mismatch(tmp_path):
    _make_model_dir(tmp_path, ["FR1"])
    metadata_path = tmp_path / "FR1" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["classifier_kind"] = "extra_trees"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert ClonalityModelStore(model_dir=tmp_path).is_enabled("FR1") is False


def test_store_rejects_cohort_model_without_matching_schema(tmp_path):
    _make_model_dir(tmp_path, ["FR1"])
    metadata_path = tmp_path / "FR1" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["feature_columns"].append("cohort_context_available")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert ClonalityModelStore(model_dir=tmp_path).is_enabled("FR1") is False

    metadata["cohort_feature_schema_version"] = "clonality_cohort_features_v1"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert ClonalityModelStore(model_dir=tmp_path).is_enabled("FR1") is True


def test_store_loads_joblib_for_known_assay(tmp_path):
    model_dir = _make_model_dir(tmp_path, ["FR1", "TCRG-A"])
    store = ClonalityModelStore(model_dir=model_dir)

    assert store.is_enabled("FR1") is True
    assert store.is_enabled("TCRGA") is True
    assert store.is_enabled("TCRGB") is False
    assert store.is_enabled("UNKNOWN") is False


def test_store_loads_validated_extra_trees_artifact(tmp_path):
    _make_model_dir(tmp_path, ["FR1"])
    assay_dir = tmp_path / "FR1"
    (assay_dir / "random_forest.joblib").replace(
        assay_dir / "extra_trees.joblib"
    )
    metadata_path = assay_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["classifier_kind"] = "extra_trees"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    store = ClonalityModelStore(model_dir=tmp_path)

    assert store.is_enabled("FR1") is True
    assert store.predict(
        "FR1",
        {
            "trace_runtime_signal": 1.0,
            "f_ratio": 0.5,
            "f_share": 0.3,
        },
    ) is not None


def test_store_predicts_when_runtime_assay_omits_separator(tmp_path):
    model_dir = _make_model_dir(tmp_path, ["TCRG-A"])
    store = ClonalityModelStore(model_dir=model_dir)

    feats = {"f_height": 100, "f_ratio": 0.5, "f_share": 0.3}
    result = store.predict("TCRGA", feats)
    assert result is not None
    assert result["label"] in list(ANNOTATION_CLASSES_ORDER) + [""]


def test_store_caches_after_first_load(tmp_path, monkeypatch):
    model_dir = _make_model_dir(tmp_path, ["FR1"])
    store = ClonalityModelStore(model_dir=model_dir)

    # Patch joblib.load to count invocations via the module import
    import core.analyses.clonality.ml_model as ml_model_mod
    import joblib as _joblib
    load_calls = {"n": 0}
    real_load = _joblib.load

    def counting_load(path):
        load_calls["n"] += 1
        return real_load(path)

    monkeypatch.setattr(ml_model_mod.joblib, "load", counting_load)

    # First call to predict triggers load; second should hit cache
    feats = {"f_height": 100, "f_ratio": 0.5, "f_share": 0.3}
    store.predict("FR1", feats)
    store.predict("FR1", feats)
    assert load_calls["n"] == 1


def test_predict_handles_missing_assay_gracefully(tmp_path):
    model_dir = _make_model_dir(tmp_path, ["FR1"])
    store = ClonalityModelStore(model_dir=model_dir)
    result = store.predict("DHJH_D", {"f_height": 100, "f_ratio": 0.5, "f_share": 0.3})
    assert result is None


def test_predict_returns_label_confidence_after_threshold(tmp_path):
    model_dir = _make_model_dir(tmp_path, ["FR1"])
    store = ClonalityModelStore(model_dir=model_dir)

    feats = {
        "f_height": 100.0,
        "f_ratio": 0.5,
        "f_share": 0.3,
        "peak_count": 5,
        "peak_count_per_channel_DATA1": 3,
        "peak_count_per_channel_DATA2": 2,
        "trace_peak_variance_DATA1": 1.0,
    }
    result = store.predict("FR1", features=feats)
    assert result is not None
    assert "label" in result
    assert "confidence" in result
    assert "review_needed" in result
    assert "model_version" in result
    # Confidence must be a finite probability between 0 and 1
    assert 0.0 <= result["confidence"] <= 1.0
    # Label is one of the canonical class strings
    assert result["label"] in list(ANNOTATION_CLASSES_ORDER) + [""]


# ----- Task 2: feature vector adapter -----------------------------------


def test_flatten_handles_unknown_columns(tmp_path):
    """flattener must pass-through required columns even if missing."""
    df = pd.DataFrame()
    flat_clf = ClonalityModelStore
    # Use the free function
    from core.analyses.clonality.ml_model import flatten_features_for_inference
    out = flatten_features_for_inference(
        {"f_height": 1.0, "f_ratio": 0.5, "f_share": 0.3},
        columns=["f_height", "f_ratio", "f_share", "extra_col"],
    )
    assert list(out.columns) == ["f_height", "f_ratio", "f_share", "extra_col"]
    assert out["f_height"].iloc[0] == 1.0
    assert out["extra_col"].iloc[0] == 0.0  # default to 0.0


def test_flatten_expands_per_channel_dicts():
    """Nested per-channel dicts expand to flat columns with a prefix."""
    from core.analyses.clonality.ml_model import flatten_features_for_inference
    out = flatten_features_for_inference(
        {
            "peak_count_per_channel": {"DATA1": 3, "DATA2": 5},
            "peak_variance_per_channel": {"DATA1": 1.0, "DATA2": 2.0},
            "f_height": 100.0,
        },
        columns=[
            "f_height",
            "trace_peak_count_DATA1",
            "trace_peak_count_DATA2",
            "trace_peak_variance_DATA1",
            "trace_peak_variance_DATA2",
        ],
    )
    assert out["trace_peak_count_DATA1"].iloc[0] == 3
    assert out["trace_peak_count_DATA2"].iloc[0] == 5
    assert out["trace_peak_variance_DATA1"].iloc[0] == 1.0


def test_flatten_expands_dotted_per_channel_columns():
    """Training fixtures also use dotted nested-column names."""
    from core.analyses.clonality.ml_model import flatten_features_for_inference
    out = flatten_features_for_inference(
        {
            "peak_count_per_channel": {"DATA1": 3},
            "mad_per_channel": {"DATA1": 0.12},
        },
        columns=[
            "peak_count_per_channel.DATA1",
            "mad_per_channel.DATA1",
        ],
    )
    assert out["peak_count_per_channel.DATA1"].iloc[0] == 3
    assert out["mad_per_channel.DATA1"].iloc[0] == 0.12


def test_flatten_expands_generic_trace_channel_columns():
    from core.analyses.clonality.ml_model import flatten_features_for_inference

    columns = [
        "trace_dominant_height_raw_per_channel.DATA1",
        "trace_signal_to_noise_per_channel.DATA2",
    ]
    out = flatten_features_for_inference(
        {
            "trace_dominant_height_raw_per_channel": {"DATA1": 1234.0},
            "trace_signal_to_noise_per_channel": {"DATA2": 18.5},
        },
        columns=columns,
    )

    assert out.iloc[0][columns[0]] == 1234.0
    assert out.iloc[0][columns[1]] == 18.5


def test_flatten_coerces_non_numeric_to_numeric():
    from core.analyses.clonality.ml_model import flatten_features_for_inference
    out = flatten_features_for_inference(
        {"f_height": "100", "f_ratio": True, "f_share": None},
        columns=["f_height", "f_ratio", "f_share", "inf"],
    )
    assert out["f_height"].iloc[0] == 100.0
    assert out["f_ratio"].iloc[0] == 1.0
    assert out["f_share"].iloc[0] == 0.0  # None/NaN -> 0.0
