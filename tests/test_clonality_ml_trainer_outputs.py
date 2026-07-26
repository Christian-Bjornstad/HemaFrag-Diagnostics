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
                "FeatureDatasetVersion": "clonality_ml_feature_dataset_v1",
                "TraceFeatureSchemaVersion": "clonality_trace_features_v1",
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


def _fast_fit(X, y, *, kind, random_state):
    del kind
    return RandomForestClassifier(
        n_estimators=20,
        random_state=random_state,
        n_jobs=1,
    ).fit(X, y)


def test_threshold_lookup_normalizes_assay_spelling():
    assert _per_assay_threshold_default("TCRgA") == 0.75


def _run(tmp_path, monkeypatch, *, promote, gate_value="0.5"):
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
        "--min-dit-groups",
        "20",
        "--min-macro-f1",
        gate_value,
        "--min-monoklonal-f1",
        gate_value,
        "--min-monoklonal-precision",
        gate_value,
    ]
    if promote:
        args.append("--promote-if-passes")
    return main(args), output


def test_trainer_writes_candidate_and_local_review_artifacts(tmp_path, monkeypatch):
    exit_code, output = _run(tmp_path, monkeypatch, promote=False)

    assert exit_code == 0
    metadata = json.loads(
        (output / "FR1" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["schema_version"] == "ml_training_pipeline_v2"
    assert metadata["deployment_status"] == "candidate"
    assert metadata["runtime_eligible"] is False
    assert metadata["training_rows"] == 36
    assert metadata["validation"]["every_row_oof_once"] is True
    assert ClonalityModelStore(model_dir=output).is_enabled("FR1") is False

    report_dir = output / "reports" / "2026-07-26"
    predictions = pd.read_csv(report_dir / "predictions_FR1.csv")
    assert len(predictions) == 36
    assert predictions["RowIndex"].nunique() == 36
    assert (report_dir / "review_cases_FR1.csv").is_file()
    assert (report_dir / "review_panel_FR1.html").is_file()
    assert (report_dir / "drift_FR1.csv").is_file()
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
            ]
        )
