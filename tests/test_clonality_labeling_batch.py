from __future__ import annotations

import json

import pandas as pd

from core.analyses.clonality.labeling_batch import (
    build_clonality_labeling_batch,
    merge_clonality_labeling_batch,
    write_clonality_labeling_batch,
)
from core.analyses.clonality.ml_data_contract import CHEMIST_LABEL_COLUMN
from core.labeling.labeling_session import LabelingSession


def _tracking_rows() -> pd.DataFrame:
    rows = []
    ordinal = 0
    for assay in ("FR1", "IGK", "TCRgA"):
        for index in range(8):
            ordinal += 1
            rows.append(
                {
                    "IdentityKey": f"id-{ordinal}",
                    "DIT": f"26P{index:02d}",
                    "Assay": assay,
                    "File": f"sample-{ordinal}.fsa",
                    "SourceRunDir": f"run-{index % 4}",
                    "SampleKind": "patient",
                    "Control": "",
                    "Well": f"A{index + 1:02d}",
                    CHEMIST_LABEL_COLUMN: (
                        "monoklonal" if assay == "FR1" and index == 0 else ""
                    ),
                    "ClonalitySuggestion": (
                        "monoklonal" if index % 3 == 0 else "polyklonal"
                    ),
                    "ClonalityReviewNeeded": bool(index % 2),
                }
            )
    return pd.DataFrame(rows)


def _feature_rows(tracking: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ordinal, row in tracking.reset_index(drop=True).iterrows():
        rows.append(
            {
                "IdentityKey": row["IdentityKey"],
                "DIT": row["DIT"],
                "Assay": row["Assay"],
                "SourceRunKey": row["SourceRunDir"],
                "RuleSuggestion": row["ClonalitySuggestion"],
                "RuleConfidence": 0.45 + (ordinal % 5) * 0.1,
                "RuleReviewNeeded": row["ClonalityReviewNeeded"],
                "trace_feature_a": float(ordinal),
                "trace_feature_b": float((ordinal * ordinal) % 17),
                "constant_feature": 1.0,
            }
        )
    return pd.DataFrame(rows)


def _write_tracking(path, frame: pd.DataFrame) -> None:
    patient = frame.loc[frame["SampleKind"].eq("patient")].copy()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Runs", index=False)
        patient.to_excel(writer, sheet_name="Patient_Runs", index=False)


def test_labeling_batch_is_deterministic_balanced_and_unlabeled():
    tracking = _tracking_rows()
    features = _feature_rows(tracking)

    first = build_clonality_labeling_batch(
        tracking,
        features,
        batch_id="pilot-1",
        per_assay=3,
        max_rows=8,
        review_fraction=0.65,
        random_state=123,
    )
    second = build_clonality_labeling_batch(
        tracking,
        features,
        batch_id="pilot-1",
        per_assay=3,
        max_rows=8,
        review_fraction=0.65,
        random_state=123,
    )

    assert list(first.rows["IdentityKey"]) == list(second.rows["IdentityKey"])
    assert len(first.rows) == 8
    assert first.rows["Assay"].nunique() == 3
    assert first.rows.groupby("Assay").size().max() == 3
    assert "id-1" not in set(first.rows["IdentityKey"])
    assert first.rows[CHEMIST_LABEL_COLUMN].eq("").all()
    assert first.rows["ClonalitySuggestion"].ne("").all()
    assert first.manifest["rule_suggestions_used_as_labels"] is False
    assert first.manifest["selection_feature_count"] == 2


def test_labeling_batch_workbook_loads_in_existing_gui_session(tmp_path):
    tracking = _tracking_rows()
    features = _feature_rows(tracking)
    batch = build_clonality_labeling_batch(
        tracking,
        features,
        batch_id="pilot-1",
        per_assay=2,
        max_rows=6,
    )
    output = tmp_path / "pilot.xlsx"

    paths = write_clonality_labeling_batch(
        batch,
        output,
        source_workbook=tmp_path / "source.xlsx",
        source_features=tmp_path / "features.csv",
    )
    session = LabelingSession(excel_path=str(output))
    session.load()

    assert session.total_count == 6
    assert session.unlabeled_count == 6
    assert {sample.assay for sample in session.samples} == {"FR1", "IGK", "TCRgA"}
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["selected_rows"] == 6
    assert manifest["rule_suggestions_used_as_labels"] is False
    with pd.ExcelFile(output, engine="openpyxl") as workbook:
        assert {
            "Runs",
            "Patient_Runs",
            "Batch_Summary",
            "Rule_Summary",
            "Batch_Metadata",
        }.issubset(workbook.sheet_names)


def test_merge_labeling_batch_adds_safe_labels_and_preserves_conflicts(tmp_path):
    target = _tracking_rows().head(4).copy()
    target[CHEMIST_LABEL_COLUMN] = ["", "", "monoklonal", ""]
    target_path = tmp_path / "target.xlsx"
    _write_tracking(target_path, target)

    batch = target.copy()
    batch[CHEMIST_LABEL_COLUMN] = [
        "polyklonal",
        "bi_oligoklonal",
        "polyklonal",
        "",
    ]
    batch_path = tmp_path / "batch.xlsx"
    _write_tracking(batch_path, batch)

    report = merge_clonality_labeling_batch(batch_path, target_path)

    assert report["labels_written"] == 2
    assert report["conflict_count"] == 1
    runs = pd.read_excel(target_path, sheet_name="Runs", engine="openpyxl")
    patients = pd.read_excel(
        target_path,
        sheet_name="Patient_Runs",
        engine="openpyxl",
    )
    assert list(runs[CHEMIST_LABEL_COLUMN].fillna("")) == [
        "polyklonal",
        "bi_oligoklonal",
        "monoklonal",
        "",
    ]
    assert list(patients[CHEMIST_LABEL_COLUMN].fillna("")) == list(
        runs[CHEMIST_LABEL_COLUMN].fillna("")
    )

    overwrite = merge_clonality_labeling_batch(
        batch_path,
        target_path,
        allow_overwrite=True,
    )
    assert overwrite["labels_written"] == 1
    assert overwrite["labels_unchanged"] == 2
    assert overwrite["conflict_count"] == 0
    updated = pd.read_excel(target_path, sheet_name="Runs", engine="openpyxl")
    assert updated.loc[2, CHEMIST_LABEL_COLUMN] == "polyklonal"


def test_merge_labeling_batch_dry_run_does_not_write(tmp_path):
    target = _tracking_rows().head(1).copy()
    target[CHEMIST_LABEL_COLUMN] = ""
    target_path = tmp_path / "target.xlsx"
    _write_tracking(target_path, target)
    batch = target.copy()
    batch[CHEMIST_LABEL_COLUMN] = "monoklonal"
    batch_path = tmp_path / "batch.xlsx"
    _write_tracking(batch_path, batch)

    report = merge_clonality_labeling_batch(
        batch_path,
        target_path,
        dry_run=True,
    )

    assert report["labels_written"] == 1
    unchanged = pd.read_excel(target_path, sheet_name="Runs", engine="openpyxl")
    assert unchanged[CHEMIST_LABEL_COLUMN].fillna("").eq("").all()


def test_merge_labeling_batch_adds_missing_target_label_column(tmp_path):
    target = _tracking_rows().head(1).drop(columns=[CHEMIST_LABEL_COLUMN])
    target_path = tmp_path / "target.xlsx"
    _write_tracking(target_path, target)
    batch = target.copy()
    batch[CHEMIST_LABEL_COLUMN] = "monoklonal"
    batch_path = tmp_path / "batch.xlsx"
    _write_tracking(batch_path, batch)

    report = merge_clonality_labeling_batch(batch_path, target_path)

    assert report["labels_written"] == 1
    updated = pd.read_excel(target_path, sheet_name="Runs", engine="openpyxl")
    assert updated.loc[0, CHEMIST_LABEL_COLUMN] == "monoklonal"
