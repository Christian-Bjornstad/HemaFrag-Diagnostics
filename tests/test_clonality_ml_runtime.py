"""Tests for ``core.analyses.clonality.ml_runtime`` — the runtime hook."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.dummy import DummyClassifier

from core.analyses.clonality import ml_runtime
from core.analyses.clonality.ml_runtime import (
    attach_ml_prediction_if_enabled,
    is_ml_enabled,
    ml_model_dir_for_settings,
    reset_model_store_cache,
)


# --- fixtures ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with a clean model-store cache."""
    reset_model_store_cache()
    yield
    reset_model_store_cache()


def _make_model_dir(p: Path) -> Path:
    (p / "FR1").mkdir(parents=True, exist_ok=True)
    X = np.zeros((20, 3))
    y = np.array(["monoklonal"] * 10 + ["polyklonal"] * 10)
    clf = DummyClassifier(strategy="most_frequent").fit(X, y)
    joblib.dump(clf, p / "FR1" / "random_forest.joblib")
    joblib.dump(clf, p / "FR1" / "dummy.joblib")
    (p / "FR1" / "metadata.json").write_text(
        json.dumps({
            "schema_version": "ml_training_pipeline_v6",
            "assay": "FR1",
            "label_order": ["monoklonal", "polyklonal"],
            "accept_threshold_tau": 0.80,
            "classifier_kind": "random_forest",
            "rare_class_counts": {},
            "trained_at_utc": "",
            "feature_columns": ["trace_runtime_signal", "dominant_to_second_ratio", "dominant_height_share"],
            "trace_feature_schema_version": "clonality_trace_features_v1",
            "deployment_status": "validated",
            "runtime_eligible": True,
            "training_rows": 20,
            "training_data_provenance": {
                "method": "per_assay_fsa_content_hash_v1",
                "raw_row_count": 20,
                "unique_trace_row_count": 20,
                "duplicate_rows_removed": 0,
                "content_hash_coverage": 1.0,
                "conflicting_label_content_hashes": 0,
                "conflicting_source_run_content_hashes": 0,
            },
            "training_class_support": {
                "monoklonal": {
                    "rows": 10,
                    "unique_dit_groups": 10,
                    "unique_source_run_groups": 3,
                    "rows_missing_source_run": 0,
                },
                "polyklonal": {
                    "rows": 10,
                    "unique_dit_groups": 10,
                    "unique_source_run_groups": 3,
                    "rows_missing_source_run": 0,
                },
            },
            "validation": {
                "strategy": "StratifiedGroupKFold",
                "group_column": "DITContentComponent",
                "every_row_oof_once": True,
                "effective_splits": 5,
                "row_count": 20,
                "unique_groups": 20,
                "group_provenance": {
                    "method": "dit_fsa_content_connected_components",
                    "content_hash_coverage": 1.0,
                },
                "class_support_gate": {"passed": True},
                "class_fold_support": {
                    "monoklonal": {
                        "total_folds": 5,
                        "training_folds_with_examples": 5,
                        "evaluation_folds_with_examples": 5,
                        "min_train_rows": 8,
                    },
                    "polyklonal": {
                        "total_folds": 5,
                        "training_folds_with_examples": 5,
                        "evaluation_folds_with_examples": 5,
                        "min_train_rows": 8,
                    },
                },
                "promotion_gate": {"passed": True},
                "source_run_stress": {
                    "status": "complete",
                    "strategy": "StratifiedGroupKFold",
                    "group_column": "SourceRunKey",
                    "every_row_oof_once": True,
                    "effective_splits": 3,
                    "row_count": 20,
                    "unique_groups": 3,
                    "class_fold_support": {
                        "monoklonal": {
                            "total_folds": 3,
                            "training_folds_with_examples": 3,
                            "evaluation_folds_with_examples": 3,
                            "min_train_rows": 6,
                        },
                        "polyklonal": {
                            "total_folds": 3,
                            "training_folds_with_examples": 3,
                            "evaluation_folds_with_examples": 3,
                            "min_train_rows": 6,
                        },
                    },
                    "promotion_gate": {"passed": True},
                },
            },
        }),
        encoding="utf-8",
    )
    return p


def _settings_with_dir(model_dir: Path) -> dict:
    return {
        "analyses": {
            "clonality": {
                "interpretation": {
                    "enabled": True,
                    "model_path": str(model_dir),
                }
            }
        }
    }


# --- tests ---------------------------------------------------------------


def test_is_ml_enabled_when_dir_set(tmp_path):
    _make_model_dir(tmp_path)
    settings = _settings_with_dir(tmp_path)
    assert is_ml_enabled(settings) is True
    assert ml_model_dir_for_settings(settings) == tmp_path


def test_is_ml_enabled_rejects_candidate_artifact(tmp_path):
    _make_model_dir(tmp_path)
    metadata_path = tmp_path / "FR1" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["deployment_status"] = "candidate"
    metadata["runtime_eligible"] = False
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert is_ml_enabled(_settings_with_dir(tmp_path)) is False


def test_is_ml_disabled_when_dir_missing_setting(tmp_path):
    settings = {"analyses": {"clonality": {"interpretation": {}}}}
    assert is_ml_enabled(settings) is False
    assert ml_model_dir_for_settings(settings) is None


def test_is_ml_disabled_when_interpretation_toggle_is_off(tmp_path):
    _make_model_dir(tmp_path)
    settings = _settings_with_dir(tmp_path)
    settings["analyses"]["clonality"]["interpretation"]["enabled"] = False

    assert is_ml_enabled(settings) is False
    assert ml_model_dir_for_settings(settings) is None


def test_is_ml_disabled_when_dir_does_not_exist(tmp_path):
    settings = _settings_with_dir(tmp_path / "nope")
    assert is_ml_enabled(settings) is False


def test_attach_is_noop_when_settings_off(tmp_path):
    """Without ``model_path`` set, no ML columns are stamped on entry."""
    entry = {"assay": "FR1", "sample_kind": "patient"}
    settings = {"analyses": {"clonality": {"interpretation": {}}}}
    out = attach_ml_prediction_if_enabled(entry)
    # Original entry untouched
    assert "ClonalityMLSuggestion" not in out
    # Idempotent in the sense of not altering unrelated fields
    assert out.get("assay") == "FR1"


def test_attach_does_not_crash_on_bad_features(tmp_path):
    """Even on a pathological entry, this must not raise."""
    _make_model_dir(tmp_path)
    settings = _settings_with_dir(tmp_path)
    # monkeypatch the global APP_SETTINGS via ml_model_dir_for_settings shim
    monkeypatch = pytest.MonkeyPatch()
    import core.analyses.clonality.ml_runtime as rt_mod
    monkeypatch.setattr(rt_mod, "ml_model_dir_for_settings",
                        lambda _=None: tmp_path)
    try:
        # entry that lacks both 'assay' and features
        bad_entry = {"features": {"not_a_real_feature": 1}}
        out = attach_ml_prediction_if_enabled(bad_entry)
        assert isinstance(out, dict)
        # ML suggestion should be empty since assay='UNKNOWN'
        assert out.get("ClonalityMLSuggestion", "") == ""
    finally:
        monkeypatch.undo()


def test_attach_stamps_ml_columns_when_assay_known(tmp_path):
    _make_model_dir(tmp_path)
    settings = _settings_with_dir(tmp_path)
    import core.analyses.clonality.ml_runtime as rt_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rt_mod, "ml_model_dir_for_settings",
                        lambda _=None: tmp_path)
    try:
        entry = {
            "assay": "FR1",
            "sample_kind": "patient",
            "ClonalitySuggestion": "polyklonal",
            "ClonalityConfidence": 0.66,
            "ClonalityReviewNeeded": False,
            "features": {
                "trace_runtime_signal": 100.0,
                "dominant_to_second_ratio": 0.5,
                "dominant_height_share": 0.3,
            },
        }
        out = attach_ml_prediction_if_enabled(entry)
        assert out.get("ClonalityMLSuggestion") in {"monoklonal", "polyklonal"}
        assert 0.0 <= float(out.get("ClonalityMLConfidence", -1)) <= 1.0
        assert out.get("ClonalityMLReviewNeeded") in {True, False}
        # Model version stamped
        assert out.get("ClonalityMLModelVersion") == "ml_training_pipeline_v6"
        assert out.get("ClonalityMLThreshold") == 0.8
        assert out.get("ClonalityMLEvidence")
    finally:
        monkeypatch.undo()


def test_attach_recomputes_full_features_when_raw_trace_fields_are_missing(
    tmp_path,
    monkeypatch,
):
    _make_model_dir(tmp_path)
    import core.analyses.clonality.ml_runtime as rt_mod

    monkeypatch.setattr(
        rt_mod,
        "ml_model_dir_for_settings",
        lambda _=None: tmp_path,
    )
    calls = []

    def full_features(_entry):
        calls.append(True)
        return {
            "sample_kind": "patient",
            "trace_runtime_signal": 100.0,
            "dominant_to_second_ratio": 0.5,
            "dominant_height_share": 0.3,
        }

    monkeypatch.setattr(
        "core.analyses.clonality.interpretation.features_from_entry",
        full_features,
    )
    entry = {
        "assay": "FR1",
        "sample_kind": "patient",
        "ClonalitySuggestion": "monoklonal",
        "features": {"dominant_to_second_ratio": 0.5},
    }

    out = attach_ml_prediction_if_enabled(entry)

    assert calls == [True]
    assert out["ClonalityMLSuggestion"] == "monoklonal"


def test_attach_refuses_prediction_when_raw_trace_is_unavailable(
    tmp_path,
    monkeypatch,
):
    _make_model_dir(tmp_path)
    import core.analyses.clonality.ml_runtime as rt_mod

    monkeypatch.setattr(
        rt_mod,
        "ml_model_dir_for_settings",
        lambda _=None: tmp_path,
    )
    monkeypatch.setattr(
        "core.analyses.clonality.interpretation.features_from_entry",
        lambda _entry: {
            "sample_kind": "patient",
            "trace_available_channel_count": 0,
        },
    )
    entry = {
        "assay": "FR1",
        "sample_kind": "patient",
        "ClonalitySuggestion": "monoklonal",
        "features": {},
    }

    out = attach_ml_prediction_if_enabled(entry)

    assert out["ClonalityMLSuggestion"] == ""
    assert out["ClonalityMLReviewNeeded"] is True
    assert out["ClonalityMLEvidence"] == "trace_features_unavailable"


def test_attach_refuses_cohort_model_without_batch_context():
    class CohortStore:
        def required_feature_columns(self, _assay):
            return [
                "trace_runtime_signal",
                "cohort_context_available",
            ]

        def predict(self, _assay, _features):
            raise AssertionError("prediction must not run without cohort context")

    entry = {
        "assay": "FR1",
        "sample_kind": "patient",
        "features": {"trace_runtime_signal": 100.0},
    }

    out = ml_runtime._do_attach(entry, CohortStore())

    assert out["ClonalityMLSuggestion"] == ""
    assert out["ClonalityMLReviewNeeded"] is True
    assert out["ClonalityMLEvidence"] == "cohort_context_unavailable"


def test_attach_keeps_batch_context_when_recomputing_trace_features(monkeypatch):
    observed = {}

    class CohortStore:
        def required_feature_columns(self, _assay):
            return [
                "trace_runtime_signal",
                "cohort_context_available",
            ]

        def predict(self, _assay, features):
            observed.update(features)
            return {
                "label": "monoklonal",
                "confidence": 0.9,
                "threshold_tau": 0.8,
                "review_needed": False,
                "model_version": "test",
            }

    monkeypatch.setattr(
        "core.analyses.clonality.interpretation.features_from_entry",
        lambda _entry: {
            "trace_runtime_signal": 100.0,
            "cohort_context_available": 0,
        },
    )
    entry = {
        "assay": "FR1",
        "sample_kind": "patient",
        "features": {"cohort_context_available": 1},
    }

    ml_runtime._do_attach(entry, CohortStore())

    assert observed["trace_runtime_signal"] == 100.0
    assert observed["cohort_context_available"] == 1


def test_attach_excludes_control_when_kind_is_only_in_features(tmp_path):
    _make_model_dir(tmp_path)
    import core.analyses.clonality.ml_runtime as rt_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        rt_mod,
        "ml_model_dir_for_settings",
        lambda _=None: tmp_path,
    )
    try:
        entry = {
            "assay": "FR1",
            "features": {
                "sample_kind": "control",
                "trace_runtime_signal": 100.0,
                "dominant_to_second_ratio": 2.0,
                "dominant_height_share": 0.7,
            },
        }
        out = attach_ml_prediction_if_enabled(entry)
        assert out["ClonalityMLSuggestion"] == ""
        assert out["ClonalityMLConfidence"] == ""
    finally:
        monkeypatch.undo()


def test_attach_marks_review_when_disagreement(tmp_path):
    """Rule=polyklonal + ML=monoklonal ⇒ review_needed=True."""
    _make_model_dir(tmp_path)
    import core.analyses.clonality.ml_runtime as rt_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rt_mod, "ml_model_dir_for_settings",
                        lambda _=None: tmp_path)
    try:
        # Build a real RF so we can force the prediction
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        X = np.array([
            [50.0, 0.9, 0.7], [120.0, 1.0, 0.6], [60.0, 0.8, 0.5],
            [40.0, 0.85, 0.7], [10.0, 0.95, 0.8],
            [1.0, 0.6, 0.1], [2.0, 0.5, 0.1], [3.0, 0.55, 0.1],
            [4.0, 0.45, 0.05], [5.0, 0.7, 0.05],
        ])
        y = np.array(["monoklonal"] * 5 + ["polyklonal"] * 5)
        clf = RandomForestClassifier(n_estimators=20, random_state=0).fit(X, y)
        # Overwrite fixture joblib with this one
        joblib.dump(clf, tmp_path / "FR1" / "random_forest.joblib")

        # Force the predict to be 'monoklonal' (point 0) when rule is polyklonal
        entry = {
            "assay": "FR1",
            "sample_kind": "patient",
            "ClonalitySuggestion": "polyklonal",
            "ClonalityConfidence": 0.66,
            "ClonalityReviewNeeded": False,
            "features": {
                "trace_runtime_signal": 50.0,
                "dominant_to_second_ratio": 0.9,
                "dominant_height_share": 0.7,
            },
        }
        out = attach_ml_prediction_if_enabled(entry)
        # ML should be monoklonal for this point (high ratio + share => strong)
        assert out["ClonalityMLSuggestion"] == "monoklonal"
        # Disagreement ⇒ review flag flipped true
        assert out["ClonalityMLReviewNeeded"] is True
    finally:
        monkeypatch.undo()
