"""Tests for core/analyses/clonality/calibration.py."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from core.analyses.clonality.calibration import (
    CalibratedMLPrediction,
    _LADDER_QC_ACCEPTED,
    _forced_review_reasons,
    attach_ml_suggestion_if_enabled,
    is_load_failed,
    load_calibrated_pipeline,
    per_assay_threshold,
    predict_with_rejection,
)


NP_RNG = np.random.default_rng(2026)


def test_per_assay_threshold_known_assay_returns_configured_value():
    assert per_assay_threshold("FR1") == 0.85
    assert per_assay_threshold("TCRG-A") == 0.75
    assert per_assay_threshold("DHJH_D") == 0.92
    assert per_assay_threshold("SL") == 0.95


def test_per_assay_threshold_unknown_assay_returns_default():
    assert per_assay_threshold("not_in_settings") == 0.85
    assert per_assay_threshold("") == 0.85


def test_ladder_qc_accepted_set_includes_ok_and_manual_adjustment():
    assert "ok" in _LADDER_QC_ACCEPTED
    assert "manual_adjustment" in _LADDER_QC_ACCEPTED
    assert "" in _LADDER_QC_ACCEPTED
    assert "fail" not in _LADDER_QC_ACCEPTED
    assert "warning" not in _LADDER_QC_ACCEPTED


def test_forced_review_ladder_qc_fail_returns_reason():
    entry = {
        "assay": "FR1",
        "ladder_qc_status": "fail",
        "ClonalitySuggestion": "monoklonal",
        "control_flag": "",
    }
    reasons = _forced_review_reasons(entry)
    assert any("ladder_qc" in r for r in reasons)


def test_forced_review_ladder_qc_ok_returns_no_reason():
    entry = {
        "assay": "FR1",
        "ladder_qc_status": "ok",
        "ClonalitySuggestion": "monoklonal",
        "control_flag": "",
    }
    assert _forced_review_reasons(entry) == []


def test_forced_review_control_flag_kontroll_avvik_returns_reason():
    entry = {
        "ladder_qc_status": "ok",
        "control_flag": "kontroll_avvik",
        "ClonalitySuggestion": "monoklonal",
    }
    reasons = _forced_review_reasons(entry)
    assert any("control_flag" in r for r in reasons)


def test_forced_review_usikker_review_already_set_returns_reason():
    entry = {
        "ladder_qc_status": "ok",
        "control_flag": "",
        "ClonalitySuggestion": "usikker_review",
    }
    reasons = _forced_review_reasons(entry)
    assert any("qc_teknisk_fail" in r or "usikker_review" in r for r in reasons)


def _make_tiny_rf(n_classes=3, n_samples=200, n_features=10):
    """Build a tiny RandomForest + Calibrated wrapper with known labels."""
    from sklearn.calibration import CalibratedClassifierCV
    X = NP_RNG.uniform(0, 1, size=(n_samples, n_features))
    label_idx = NP_RNG.choice(n_classes, size=n_samples)
    labels = ["monoklonal", "polyklonal", "oligoklonal"][:n_classes]
    y = NP_RNG.choice(labels, size=n_samples)
    base = RandomForestClassifier(n_estimators=20, random_state=42)
    calibrated = CalibratedClassifierCV(base, method="sigmoid", cv=3)
    calibrated.fit(X, y)
    return calibrated, labels


def test_predict_with_rejection_accepts_high_probability():
    calibrated, _ = _make_tiny_rf(n_classes=2)
    n_features = 10
    X = NP_RNG.uniform(0, 1, size=(1, n_features))
    pred = predict_with_rejection(
        calibrated, dict(zip(range(n_features), X[0])),
        assay="FR1", tau=0.20,
        artifact_path="/tmp/test.whl",
    )
    assert pred.accepted
    assert pred.label in ("monoklonal", "polyklonal")
    assert 0.0 < pred.confidence < 1.0
    assert pred.artifact_path == "/tmp/test.whl"


def test_predict_with_rejection_rejects_low_confidence():
    calibrated, _ = _make_tiny_rf()
    n_features = 10
    X = NP_RNG.uniform(0, 1, size=(1, n_features))
    pred = predict_with_rejection(
        calibrated, dict(zip(range(n_features), X[0])),
        assay="FR1", tau=0.99,
    )
    assert not pred.accepted
    assert "prob" in pred.reason
    assert "tau" in pred.reason


def test_predict_with_rejection_outputs_dataclass_to_dict():
    pred = CalibratedMLPrediction(label="monoklonal", confidence=0.92, accepted=True)
    d = pred.to_dict()
    assert d["ClonalityMLSuggestion"] == "monoklonal"
    assert d["ClonalityMLConfidence"] == 0.92
    assert d["ClonalityMLReviewNeeded"] is False
    assert "ClonalityMLModelVersion" in d


def test_load_calibrated_pipeline_returns_load_failed_when_no_model(tmp_path):
    """Empty output_dir -> LoadFailed sentinel."""
    result = load_calibrated_pipeline(
        assay="FR1",
        output_dir=tmp_path,
    )
    assert is_load_failed(result)


def test_attach_ml_suggestion_disabled_leaves_entry_alone():
    """When interpretation.enabled is False, the wrapper is a no-op."""
    settings = {
        "analyses": {"clonality": {"interpretation": {"enabled": False}}}
    }
    entry = {
        "assay": "FR1",
        "ladder_qc_status": "ok",
        "control_flag": "",
        "ClonalitySuggestion": "monoklonal",
    }
    out = attach_ml_suggestion_if_enabled(
        dict(entry), settings=settings, artifact_dir=Path("/tmp/nope"),
    )
    assert out == entry


def test_attach_ml_suggestion_ladder_qc_fail_force_review_no_predict():
    """Forced-review path overrides ML even when interpretation.enabled."""
    settings = {
        "analyses": {"clonality": {"interpretation": {"enabled": True}}}
    }
    entry = {
        "assay": "FR1",
        "ladder_qc_status": "fail",
        "ClonalitySuggestion": "monoklonal",
        "control_flag": "",
        "features": {},
    }
    out = attach_ml_suggestion_if_enabled(
        dict(entry), settings=settings, artifact_dir=Path("/tmp/nope"),
    )
    assert out["ClonalityMLSuggestion"] == "monoklonal"
    assert out["ClonalityMLReviewNeeded"] is True
    assert "ladder_qc" in str(out["ClonalityMLEvidence"])
    assert out["ClonalityMLArtifact"] == ""  # did not try to load


def test_attach_ml_suggestion_with_artifact_load_fails_returns_empty_columns(tmp_path):
    """interpretation.enabled=True but no model artifact -> empty columns."""
    settings = {
        "analyses": {"clonality": {"interpretation": {"enabled": True}}}
    }
    entry = {
        "assay": "FR1",
        "ladder_qc_status": "ok",
        "ClonalitySuggestion": "monoklonal",
        "features": {},
    }
    out = attach_ml_suggestion_if_enabled(
        dict(entry), settings=settings, artifact_dir=tmp_path,
    )
    # Empty strings from load_failed branch:
    assert out["ClonalityMLSuggestion"] == ""
    assert out["ClonalityMLConfidence"] == ""
    assert out["ClonalityMLReviewNeeded"] == ""
    assert out["ClonalityMLArtifact"] == ""


def test_calibration_loader_rejects_unvalidated_roundtrip_artifact(tmp_path):
    """The legacy calibration facade cannot bypass production promotion."""
    import pandas as pd
    from core.analyses.clonality.ml_training import (
        fit_classifier, serialize_model,
    )

    # Build a trained random_forest estimator
    n_samples = 250
    n_features = 5
    X = pd.DataFrame(NP_RNG.uniform(0, 1, size=(n_samples, n_features)),
                      columns=["f0", "f1", "f2", "f3", "f4"])
    y = pd.Series(NP_RNG.choice(["monoklonal", "polyklonal", "oligoklonal"],
                                  size=n_samples))
    estimator = fit_classifier(X, y, kind="random_forest")
    paths = serialize_model(
        estimator,
        label_order=["monoklonal", "polyklonal", "oligoklonal", "_default=8"],
        assay="FR1",
        accept_threshold_tau=0.20,        # accept almost anything
        classifier_kind="random_forest",
        rare_class_counts={"monoklonal": int((y == "monoklonal").sum()),
                            "polyklonal": int((y == "polyklonal").sum())},
        trained_at_utc="2026-06-30T05:00:00Z",
        output_dir=tmp_path,
    )
    joblib_path = paths["joblib"]
    assert joblib_path.exists()
    assert paths["metadata"].exists()

    from core.analyses.clonality.calibration import load_calibrated_pipeline
    loaded = load_calibrated_pipeline(
        assay="FR1", output_dir=tmp_path, classifier_kind="random_forest",
    )
    assert is_load_failed(loaded)
    assert "promotion-eligible v9" in loaded.reason


def test_predict_with_rejection_force_review_ladder_qc_fail_short_circuits():
    """predict_with_rejection must short-circuit on ladder_qc_status='fail'
    BEFORE attempting numeric coercion. Otherwise string-typed metadata
    fields (ladder_qc_status, ClonalitySuggestion, control_flag) crash
    the function even though the entry qualifies for forced review."""
    calibrated, _ = _make_tiny_rf()
    entry = {
        # numeric features (the part the model uses)
        "f0": 0.5, "f1": 0.5, "f2": 0.5, "f3": 0.5, "f4": 0.5,
        # metadata fields that the predict function must skip/short-circuit on
        "ladder_qc_status": "fail",        # string! would crash float()
        "ClonalitySuggestion": "qc_teknisk_fail",
        "control_flag": "kontroll_avvik",
    }
    pred = predict_with_rejection(
        calibrated, entry,
        assay="FR1", tau=0.85,
    )
    assert pred.label == "usikker_review"
    assert pred.accepted is False
    assert "ladder_qc" in pred.reason


def test_predict_with_rejection_handles_uncoercible_feature_values():
    """predict_with_rejection must not crash when feature_row carries
    non-numeric values that cannot be converted to float. They become
    NaN and the imputer handles them; we still produce a prediction."""
    calibrated, _ = _make_tiny_rf()
    entry = {
        "f0": 0.5, "f1": 0.5, "f2": 0.5, "f3": 0.5, "f4": 0.5,
        "f5": "not_a_number",    # would crash float(value) pre-fix
        "f6": None,
        "metadata_str": "ignored",
    }
    pred = predict_with_rejection(
        calibrated, entry,
        assay="FR1", tau=0.20,   # low tau so even mediocre confidence accepts
    )
    # Whether accepted or rejected, the function must NOT raise.
    assert pred.label in ("monoklonal", "monoklonal_pa_poly", "polyklonal", "oligoklonal",
                          "irregulaer", "lite_pcr_produkt",
                          "intet_pcr_produkt", "qc_teknisk_fail",
                          "usikker_review")
