from __future__ import annotations

import json

import pandas as pd
import pytest

from core.analyses.clonality.ml_data_contract import CHEMIST_LABEL_COLUMN
from core.analyses.clonality.ml_readiness import (
    assess_clonality_label_readiness,
    write_clonality_label_readiness,
)
from scripts.assess_clonality_ml_readiness import main


def _cohort(
    *,
    rows_per_class: int = 100,
    labeled: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tracking_rows = []
    feature_rows = []
    labels = ("monoklonal", "polyklonal")
    ordinal = 0
    for label in labels:
        for index in range(rows_per_class):
            ordinal += 1
            identity = f"id-{ordinal}"
            dit = f"26P{index:03d}"
            run = f"run-{index % 10}"
            tracking_rows.append(
                {
                    "IdentityKey": identity,
                    "DIT": dit,
                    "Assay": "FR1",
                    "SampleKind": "patient",
                    "Control": "",
                    CHEMIST_LABEL_COLUMN: label if labeled else "",
                }
            )
            feature_rows.append(
                {
                    "IdentityKey": identity,
                    "DIT": dit,
                    "Assay": "FR1",
                    "SourceRunKey": run,
                    "FsaContentHash": f"hash-{ordinal}",
                    "trace_feature": float(ordinal),
                }
            )
    return pd.DataFrame(tracking_rows), pd.DataFrame(feature_rows)


def _write_workbook(path, tracking: pd.DataFrame) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        tracking.to_excel(writer, sheet_name="Runs", index=False)


def test_readiness_reports_awaiting_labels_without_using_rules():
    tracking, features = _cohort(labeled=False)

    readiness = assess_clonality_label_readiness(tracking, features)

    assert readiness.report["status"] == "awaiting_labels"
    assert readiness.report["labeled_rows"] == 0
    assert readiness.report["candidate_ready_assay_count"] == 0
    assay = readiness.assays.iloc[0]
    assert assay["Status"] == "awaiting_labels"
    assert "required_class=monoklonal absent" in assay["CandidateBlockers"]


def test_readiness_passes_static_candidate_and_promotion_support():
    tracking, features = _cohort()

    readiness = assess_clonality_label_readiness(tracking, features)

    assert readiness.report["status"] == "promotion_preflight_ready"
    assert readiness.report["candidate_ready_assay_count"] == 1
    assert readiness.report["promotion_preflight_ready_assay_count"] == 1
    assay = readiness.assays.iloc[0]
    assert bool(assay["CandidateReady"]) is True
    assert bool(assay["PromotionPreflightReady"]) is True
    observed = readiness.classes.loc[readiness.classes["Observed"]]
    assert set(observed["ChemistLabel"]) == {"monoklonal", "polyklonal"}
    assert observed["StaticPromotionSupportPass"].all()


def test_readiness_blocks_single_class_and_low_support():
    tracking, features = _cohort(rows_per_class=8)
    tracking.loc[
        tracking[CHEMIST_LABEL_COLUMN].eq("polyklonal"),
        CHEMIST_LABEL_COLUMN,
    ] = ""

    readiness = assess_clonality_label_readiness(
        tracking,
        features,
        min_samples=10,
    )

    assay = readiness.assays.iloc[0]
    assert bool(assay["CandidateReady"]) is False
    assert "required_class=polyklonal absent" in assay["CandidateBlockers"]
    assert readiness.report["status"] == "not_ready"


def test_readiness_is_reported_per_interpretation_unit():
    tracking = pd.DataFrame(
        [
            {
                "IdentityKey": f"id-{index}",
                "DIT": f"26-{index}",
                "Assay": "IGK",
                "ClonalityChemistLabel_DATA1": (
                    "monoklonal" if index % 2 == 0 else "polyklonal"
                ),
                "ClonalityChemistLabel_DATA2": (
                    "polyklonal" if index % 2 == 0 else "monoklonal"
                ),
            }
            for index in range(4)
        ]
    )
    features = pd.DataFrame(
        [
            {
                "IdentityKey": f"id-{index}",
                "Assay": "IGK",
                "InterpretationUnit": unit,
                "Channel": channel,
                "TargetName": target,
                "SourceRunKey": f"run-{index % 2}",
                "FsaContentHash": f"hash-{index}",
            }
            for index in range(4)
            for unit, channel, target in (
                ("IGK_JK5", "DATA1", "Jk5"),
                ("IGK_JK1_4", "DATA2", "Jk1-4"),
            )
        ]
    )

    readiness = assess_clonality_label_readiness(
        tracking,
        features,
        min_samples=2,
        validation_folds=2,
        source_run_validation_folds=2,
        min_dit_groups=2,
        min_class_dit_groups=1,
        min_core_class_dit_groups=1,
        min_class_source_run_groups=1,
        min_class_evaluation_folds=1,
        min_class_training_rows_per_fold=1,
        max_class_dit_row_fraction=1.0,
    )

    assert set(readiness.assays["Assay"]) == {"IGK_JK5", "IGK_JK1_4"}
    assert readiness.report["available_rows"] == 8
    assert readiness.report["labeled_rows"] == 8


def test_readiness_rejects_conflicting_content_hash_labels():
    tracking, features = _cohort(rows_per_class=6)
    features.loc[features.index[-1], "FsaContentHash"] = features.loc[
        features.index[0],
        "FsaContentHash",
    ]
    features.loc[features.index[-1], "SourceRunKey"] = features.loc[
        features.index[0],
        "SourceRunKey",
    ]

    with pytest.raises(ValueError, match="conflicting chemist labels"):
        assess_clonality_label_readiness(
            tracking,
            features,
            min_samples=10,
        )


def test_readiness_cli_writes_aggregate_artifacts(tmp_path):
    tracking, features = _cohort(labeled=False)
    workbook = tmp_path / "tracking.xlsx"
    feature_path = tmp_path / "features.csv"
    output = tmp_path / "readiness"
    _write_workbook(workbook, tracking)
    features.to_csv(feature_path, index=False)

    result = main(
        [
            "--xls",
            str(workbook),
            "--features-csv",
            str(feature_path),
            "--output-dir",
            str(output),
        ]
    )

    assert result == 0
    report = json.loads(
        (output / "clonality_label_readiness.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "awaiting_labels"
    assert (output / "clonality_assay_readiness.csv").exists()
    assert (output / "clonality_class_support.csv").exists()
