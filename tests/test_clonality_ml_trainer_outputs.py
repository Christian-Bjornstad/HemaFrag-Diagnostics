from __future__ import annotations

import json

import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier

from core.analyses.clonality.ml_data_contract import CHEMIST_LABEL_COLUMN
from core.analyses.clonality.ml_model import ClonalityModelStore
from scripts.train_clonality_interpretation_models import (
    _per_assay_threshold_default,
    main,
)


def _inputs(tmp_path):
    tracking_rows = []
    feature_rows = []
    for index in range(36):
        label = "monoklonal" if index % 2 == 0 else "polyklonal"
        identity = f"id-{index:03d}"
        dit = f"DIT-{index:03d}"
        tracking_rows.append(
            {
                "IdentityKey": identity,
                "DIT": dit,
                "Assay": "FR1",
                "SampleKind": "patient",
                "Control": "",
                CHEMIST_LABEL_COLUMN: label,
            }
        )
        feature_rows.append(
            {
                "FeatureDatasetVersion": "clonality_ml_feature_dataset_v2",
                "TraceFeatureSchemaVersion": "clonality_trace_features_v1",
                "CohortFeatureSchemaVersion": "clonality_cohort_features_v1",
                "IdentityKey": identity,
                "FsaSourceHash": f"source-{index}",
                "FsaContentHash": f"content-{index}",
                "DIT": dit,
                "Assay": "FR1",
                "SourceRunKey": f"run-{index % 3}",
                "RunDate": f"2026-07-{1 + index % 3:02d}",
                CHEMIST_LABEL_COLUMN: label,
                "RuleSuggestion": (
                    label if index % 7 else "usikker_review"
                ),
                "RuleConfidence": 0.8,
                "RuleReviewNeeded": index % 7 == 0,
                "cohort_context_available": 1,
                "cohort_patient_entry_count": 1,
                "cohort_patient_assay_count": 1,
                "cohort_panel_completeness": 1.0 / 12.0,
                "cohort_same_assay_entry_count": 1,
                "cohort_same_assay_replicate_count": 0,
                "cohort_replicate_bp_observation_count": 0,
                "trace_dominant_area_share_raw_per_channel.DATA1": (
                    0.9 if label == "monoklonal" else 0.2
                ),
                "trace_peak_count_raw_per_channel.DATA1": (
                    2.0 if label == "monoklonal" else 12.0
                ),
            }
        )
    workbook = tmp_path / "tracking.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(tracking_rows).to_excel(writer, sheet_name="Runs", index=False)
    features = tmp_path / "features.csv"
    pd.DataFrame(feature_rows).to_csv(features, index=False)
    return workbook, features


def _fast_fit(
    X,
    y,
    *,
    kind,
    random_state,
    calibration_groups=None,
    calibration_group_column="DITContentComponent",
):
    del kind
    estimator = RandomForestClassifier(
        n_estimators=20,
        random_state=random_state,
        n_jobs=1,
    ).fit(X, y)
    estimator.hemafrag_calibration_ = {
        "status": "complete",
        "required_for_runtime": True,
        "method": "sigmoid",
        "strategy": "StratifiedGroupKFold",
        "group_column": calibration_group_column,
        "grouped": True,
        "folds": 3,
        "unique_groups": int(pd.Series(calibration_groups).nunique()),
        "minimum_train_class_rows": 4,
        "minimum_test_class_rows": 2,
        "every_group_held_out_once": True,
        "reason": "",
    }
    return estimator


def test_threshold_lookup_normalizes_assay_spelling():
    assert _per_assay_threshold_default("TCRgA") == 0.75


def _run(
    tmp_path,
    monkeypatch,
    *,
    promote,
    gate_value="0.5",
    classifier_kind="random_forest",
    extra_args=(),
):
    workbook, features = _inputs(tmp_path)
    output = tmp_path / ("promoted" if promote else "candidate")
    monkeypatch.setattr(
        "scripts.train_clonality_interpretation_models.fit_classifier",
        _fast_fit,
    )
    monkeypatch.setattr(
        "core.analyses.clonality.ml_validation.fit_classifier",
        _fast_fit,
    )
    args = [
        "--xls",
        str(workbook),
        "--features-csv",
        str(features),
        "--output-dir",
        str(output),
        "--date",
        "2026-07-26",
        "--min-samples",
        "20",
        "--validation-folds",
        "3",
        "--classifier-kind",
        classifier_kind,
        "--min-dit-groups",
        "20",
        "--min-core-class-dit-groups",
        "10",
        "--min-macro-f1",
        gate_value,
        "--min-monoklonal-f1",
        gate_value,
        "--min-monoklonal-precision",
        gate_value,
    ]
    args.extend(extra_args)
    if promote:
        args.append("--promote-if-passes")
    return main(args), output


def test_trainer_writes_candidate_and_local_review_artifacts(tmp_path, monkeypatch):
    exit_code, output = _run(tmp_path, monkeypatch, promote=False)

    assert exit_code == 0
    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["schema_version"] == "ml_training_pipeline_v8"
    assert metadata["deployment_status"] == "candidate"
    assert metadata["runtime_eligible"] is False
    assert metadata["training_rows"] == 36
    assert metadata["training_data_provenance"]["raw_row_count"] == 36
    assert metadata["training_data_provenance"][
        "duplicate_rows_removed"
    ] == 0
    assert metadata["training_class_support"]["monoklonal"][
        "unique_dit_groups"
    ] == 18
    assert metadata["validation"]["every_row_oof_once"] is True
    assert metadata["validation"]["group_column"] == "DITContentComponent"
    assert metadata["validation"]["group_provenance"][
        "content_hash_coverage"
    ] == 1.0
    assert (
        metadata["validation"]["feature_importance"]["method"]
        == "held_out_permutation_balanced_accuracy"
    )
    assert metadata["validation"]["feature_importance"]["top_features"]
    assert metadata["validation"]["source_run_stress"]["status"] == "complete"
    assert metadata["validation"]["source_run_stress"]["promotion_gate"][
        "passed"
    ] is True
    assert metadata["validation"]["class_support_gate"]["passed"] is True
    assert metadata["validation"]["calibration_gate"]["passed"] is True
    assert metadata["validation"]["calibration"][
        "every_fold_grouped"
    ] is True
    assert metadata["validation"]["source_run_stress"]["calibration"][
        "every_fold_complete"
    ] is True
    assert metadata["final_fit_calibration"]["status"] == "complete"
    assert (
        metadata["final_fit_calibration"]["strategy"]
        == "StratifiedGroupKFold"
    )
    assert metadata["validation"]["class_fold_support"]["monoklonal"][
        "evaluation_folds_with_examples"
    ] >= 2
    assert ClonalityModelStore(model_dir=output).is_enabled("FR1") is False

    report_dir = output / "reports" / "2026-07-26"
    predictions = pd.read_csv(report_dir / "predictions_FR1.csv")
    assert len(predictions) == 36
    assert predictions["RowIndex"].nunique() == 36
    assert (report_dir / "review_cases_FR1.csv").is_file()
    assert (report_dir / "review_panel_FR1.html").is_file()
    assert (report_dir / "drift_FR1.csv").is_file()
    assert (report_dir / "feature_importance_FR1.csv").is_file()
    assert (report_dir / "source_run_predictions_FR1.csv").is_file()
    assert (report_dir / "source_run_metrics_FR1.json").is_file()
    assert (report_dir / "source_run_splits_FR1.json").is_file()
    assert (report_dir / "splits_FR1.json").is_file()


def test_trainer_explicitly_promotes_only_gate_passing_model(tmp_path, monkeypatch):
    exit_code, output = _run(tmp_path, monkeypatch, promote=True)

    assert exit_code == 0
    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["deployment_status"] == "validated"
    assert metadata["runtime_eligible"] is True
    assert metadata["validation"]["promotion_gate"]["passed"] is True
    assert ClonalityModelStore(model_dir=output).is_enabled("FR1") is True


def test_trainer_blocks_explicit_promotion_when_gate_fails(tmp_path, monkeypatch):
    exit_code, output = _run(
        tmp_path,
        monkeypatch,
        promote=True,
        gate_value="1.01",
    )

    assert exit_code == 2
    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["deployment_status"] == "candidate"
    assert metadata["runtime_eligible"] is False
    assert metadata["validation"]["promotion_gate"]["passed"] is False
    assert metadata["validation"]["promotion_gate"]["reasons"]
    assert ClonalityModelStore(model_dir=output).is_enabled("FR1") is False


def test_trainer_blocks_promotion_when_class_support_is_too_low(
    tmp_path,
    monkeypatch,
):
    exit_code, output = _run(
        tmp_path,
        monkeypatch,
        promote=True,
        extra_args=("--min-core-class-dit-groups", "100"),
    )

    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    support_gate = metadata["validation"]["class_support_gate"]

    assert exit_code == 2
    assert support_gate["passed"] is False
    assert any(
        "class_support[monoklonal].unique_dit_groups=18 below 100"
        in reason
        for reason in support_gate["reasons"]
    )
    assert metadata["runtime_eligible"] is False


def test_trainer_blocks_promotion_when_one_dit_share_is_too_high(
    tmp_path,
    monkeypatch,
):
    exit_code, output = _run(
        tmp_path,
        monkeypatch,
        promote=True,
        extra_args=("--max-class-dit-row-fraction", "0.01"),
    )

    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    support_gate = metadata["validation"]["class_support_gate"]

    assert exit_code == 2
    assert support_gate["passed"] is False
    assert any(
        "max_dit_row_fraction=0.056 above 0.010" in reason
        for reason in support_gate["reasons"]
    )


def test_trainer_refuses_existing_model_output_directory(tmp_path, monkeypatch):
    exit_code, output = _run(tmp_path, monkeypatch, promote=False)
    assert exit_code == 0
    workbook, features = _inputs(tmp_path)

    with pytest.raises(FileExistsError, match="fresh directory"):
        main(
            [
                "--xls",
                str(workbook),
                "--features-csv",
                str(features),
                "--output-dir",
                str(output),
                "--min-samples",
                "20",
                "--classifier-kind",
                "random_forest",
            ]
        )


def test_trainer_auto_compares_baselines_and_selects_candidate(
    tmp_path,
    monkeypatch,
):
    exit_code, output = _run(
        tmp_path,
        monkeypatch,
        promote=False,
        classifier_kind="auto",
    )

    assert exit_code == 0
    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    selection = metadata["validation"]["model_selection"]
    assert selection["requested_classifier_kind"] == "auto"
    assert selection["selected_classifier_kind"] == "random_forest"
    assert metadata["validation"]["feature_importance"]["top_features"] == []
    assert metadata["validation"]["source_run_stress"]["status"] == "deferred"
    assert {
        row["classifier_kind"] for row in selection["candidates"]
    } == {"random_forest", "extra_trees"}
    assert sum(bool(row["selected"]) for row in selection["candidates"]) == 1
    report_dir = output / "reports" / "2026-07-26"
    assert (report_dir / "model_comparison_FR1.json").is_file()
    assert (report_dir / "model_comparison_FR1.csv").is_file()


def test_trainer_rejects_auto_selection_for_direct_promotion(tmp_path):
    workbook, features = _inputs(tmp_path)

    with pytest.raises(ValueError, match="comparison-only"):
        main(
            [
                "--xls",
                str(workbook),
                "--features-csv",
                str(features),
                "--output-dir",
                str(tmp_path / "auto-promote"),
                "--classifier-kind",
                "auto",
                "--promote-if-passes",
            ]
        )


def test_trainer_rejects_calibration_support_below_runtime_floor(tmp_path):
    with pytest.raises(ValueError, match="cannot be below 6"):
        main(
            [
                "--xls",
                str(tmp_path / "missing.xlsx"),
                "--min-class-training-rows-per-fold",
                "5",
            ]
        )


def test_trainer_blocks_promotion_when_source_runs_cannot_be_held_out(
    tmp_path,
    monkeypatch,
):
    workbook, features = _inputs(tmp_path)
    feature_frame = pd.read_csv(features)
    feature_frame["SourceRunKey"] = "only-run"
    feature_frame.to_csv(features, index=False)
    output = tmp_path / "single-run"
    monkeypatch.setattr(
        "scripts.train_clonality_interpretation_models.fit_classifier",
        _fast_fit,
    )
    monkeypatch.setattr(
        "core.analyses.clonality.ml_validation.fit_classifier",
        _fast_fit,
    )

    exit_code = main(
        [
            "--xls",
            str(workbook),
            "--features-csv",
            str(features),
            "--output-dir",
            str(output),
            "--date",
            "2026-07-26",
            "--min-samples",
            "20",
            "--validation-folds",
            "3",
            "--classifier-kind",
            "random_forest",
            "--min-dit-groups",
            "20",
            "--min-macro-f1",
            "0.5",
            "--min-monoklonal-f1",
            "0.5",
            "--min-monoklonal-precision",
            "0.5",
            "--promote-if-passes",
        ]
    )

    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    assert exit_code == 2
    assert metadata["deployment_status"] == "candidate"
    assert metadata["runtime_eligible"] is False
    assert metadata["validation"]["source_run_stress"]["status"] == "failed"
    assert "fewer than two unique SourceRunKey groups" in metadata[
        "validation"
    ]["source_run_stress"]["error"]
    assert metadata["validation"]["promotion_gate"]["passed"] is False
