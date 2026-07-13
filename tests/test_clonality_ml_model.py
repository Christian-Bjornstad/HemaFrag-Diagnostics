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
        "schema_version": "ml_training_pipeline_v1",
        "assay": assay,
        "label_order": list(ANNOTATION_CLASSES_ORDER),
        "accept_threshold_tau": float(tau),
        "classifier_kind": "random_forest",
        "rare_class_counts": {"monoklonal": 50, "polyklonal": 50},
        "trained_at_utc": "2026-07-13T10:00:00Z",
        "feature_columns": features or ["f_height", "f_ratio", "f_share"],
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


def test_store_loads_joblib_for_known_assay(tmp_path):
    model_dir = _make_model_dir(tmp_path, ["FR1", "TCRG-A"])
    store = ClonalityModelStore(model_dir=model_dir)

    assert store.is_enabled("FR1") is True
    assert store.is_enabled("TCRGB") is False
    assert store.is_enabled("UNKNOWN") is False


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
