from __future__ import annotations

import json

import pandas as pd

from core.analyses.clonality.ml_data_audit import (
    audit_clonality_ml_data,
    write_clonality_ml_audit,
)
from core.analyses.clonality.ml_data_contract import (
    CHEMIST_LABEL_COLUMN,
    load_tracking_run_table,
)
from scripts.audit_clonality_ml_data import main
from scripts.train_clonality_interpretation_models import (
    _assemble_labelled_df,
    _assemble_labelled_df_with_labels_csv,
)


def _write_tracking_workbook(path, rows):
    frame = pd.DataFrame(rows)
    patient = frame.loc[frame["SampleKind"].eq("patient")].copy()
    control = frame.loc[frame["SampleKind"].eq("control")].copy()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Runs", index=False)
        patient.to_excel(writer, sheet_name="Patient_Runs", index=False)
        control.to_excel(writer, sheet_name="Control_Runs", index=False)


def _rows():
    return [
        {
            "IdentityKey": "id-1",
            "File": "sample1.fsa",
            "SourceRunDir": "run-a",
            "DIT": "26A",
            "Assay": "FR1",
            "SampleKind": "patient",
            "Control": "",
            CHEMIST_LABEL_COLUMN: "monoklonal",
            "ClonalitySuggestion": "polyklonal",
            "LadderR2": 0.999,
            "PeakCount": 3,
        },
        {
            "IdentityKey": "id-2",
            "File": "sample2.fsa",
            "SourceRunDir": "old-machine-path",
            "DIT": "26A",
            "Assay": "IGK",
            "SampleKind": "patient",
            "Control": "",
            CHEMIST_LABEL_COLUMN: "polyklonal",
            "ClonalitySuggestion": "polyklonal",
            "LadderR2": 0.998,
            "PeakCount": 12,
        },
        {
            "IdentityKey": "id-3",
            "File": "missing.fsa",
            "SourceRunDir": "run-b",
            "DIT": "26B",
            "Assay": "FR1",
            "SampleKind": "patient",
            "Control": "",
            CHEMIST_LABEL_COLUMN: "not-a-real-label",
            "ClonalitySuggestion": "monoklonal",
            "LadderR2": None,
            "PeakCount": 0,
        },
        {
            "IdentityKey": "control-1",
            "File": "pk.fsa",
            "SourceRunDir": "run-a",
            "DIT": "",
            "Assay": "FR1",
            "SampleKind": "control",
            "Control": "PK",
            CHEMIST_LABEL_COLUMN: "",
            "ClonalitySuggestion": "polyklonal",
            "LadderR2": 0.999,
            "PeakCount": 5,
        },
        {
            "IdentityKey": "unassigned-1",
            "File": "unassigned.fsa",
            "SourceRunDir": "run-a",
            "DIT": "",
            "Assay": "IKZF1",
            "SampleKind": "unassigned",
            "Control": "",
            CHEMIST_LABEL_COLUMN: "",
            "ClonalitySuggestion": "",
            "LadderR2": 0.999,
            "PeakCount": 1,
        },
        {
            "IdentityKey": "ladder-1",
            "File": "ladder.fsa",
            "SourceRunDir": "run-a",
            "DIT": "26A",
            "Assay": "SL",
            "SampleKind": "patient",
            "Control": "",
            CHEMIST_LABEL_COLUMN: "",
            "ClonalitySuggestion": "",
            "LadderR2": 0.999,
            "PeakCount": 16,
        },
    ]


def test_tracking_loader_prefers_runs_and_excludes_controls(tmp_path):
    workbook = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook, _rows())

    loaded = load_tracking_run_table(workbook)

    assert loaded.primary_sheet == "Runs"
    assert loaded.source_sheets == ("Runs",)
    assert len(loaded.frame) == 3
    assert set(loaded.frame["IdentityKey"]) == {"id-1", "id-2", "id-3"}
    assert CHEMIST_LABEL_COLUMN in loaded.frame.columns


def test_tracking_loader_preserves_unassigned_rows_only_for_full_inventory(tmp_path):
    workbook = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook, _rows())

    model_rows = load_tracking_run_table(workbook)
    all_rows = load_tracking_run_table(
        workbook,
        include_controls=True,
        include_size_ladders=True,
    )

    assert "unassigned-1" not in set(model_rows.frame["IdentityKey"])
    assert set(all_rows.frame["SampleKind"]) == {
        "patient",
        "control",
        "unassigned",
    }
    assert "ladder-1" not in set(model_rows.frame["IdentityKey"])
    assert "ladder-1" in set(all_rows.frame["IdentityKey"])


def test_tracking_loader_preserves_source_rows_for_split_only_workbook(tmp_path):
    workbook = tmp_path / "tracking-split.xlsx"
    frame = pd.DataFrame(_rows())
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        frame.loc[frame["SampleKind"].eq("patient")].to_excel(
            writer,
            sheet_name="Patient_Runs",
            index=False,
        )
        frame.loc[frame["SampleKind"].eq("control")].to_excel(
            writer,
            sheet_name="Control_Runs",
            index=False,
        )

    loaded = load_tracking_run_table(workbook, include_controls=True)
    control = loaded.frame.loc[loaded.frame["SampleKind"].eq("control")].iloc[0]

    assert loaded.primary_sheet == "Patient_Runs"
    assert control["_TrackingSheet"] == "Control_Runs"
    assert control["_TrackingRowNumber"] == 2


def test_trainer_reads_chemist_labels_from_current_runs_sheet(tmp_path):
    workbook = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook, _rows())

    training = _assemble_labelled_df(workbook)

    assert len(training) == 3
    assert training.loc[0, "ClonalitySuggestion"] == "monoklonal"
    assert training.loc[0, CHEMIST_LABEL_COLUMN] == "monoklonal"


def test_trainer_merges_external_chemist_labels_without_column_collision(tmp_path):
    workbook = tmp_path / "tracking.xlsx"
    rows = _rows()
    for row in rows:
        row[CHEMIST_LABEL_COLUMN] = ""
    _write_tracking_workbook(workbook, rows)
    labels_path = tmp_path / "labels.csv"
    pd.DataFrame(
        {
            "IdentityKey": ["id-1", "id-2"],
            "Assay": ["FR1", "IGK"],
            CHEMIST_LABEL_COLUMN: ["monoklonal", "polyklonal"],
        }
    ).to_csv(labels_path, index=False)

    training = _assemble_labelled_df_with_labels_csv(workbook, labels_path)

    assert len(training) == 2
    assert list(training["ClonalitySuggestion"]) == ["monoklonal", "polyklonal"]


def test_audit_reports_paths_labels_groups_and_feature_quality(tmp_path):
    workbook = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook, _rows())
    fsa_root = tmp_path / "fsa"
    (fsa_root / "run-a").mkdir(parents=True)
    (fsa_root / "run-a" / "sample1.fsa").write_bytes(b"fsa-one")
    (fsa_root / "somewhere" / "deep").mkdir(parents=True)
    (fsa_root / "somewhere" / "deep" / "sample2.fsa").write_bytes(b"fsa-two")

    audit = audit_clonality_ml_data(workbook, fsa_root)

    assert audit.report["status"] == "failed"
    assert audit.report["row_count"] == 3
    assert audit.report["resolved_fsa_count"] == 2
    assert audit.report["missing_fsa_count"] == 1
    assert audit.report["grouping"]["multi_row_dit_count"] == 1
    assert audit.report["grouping"]["multi_assay_dit_count"] == 1
    assert {item["code"] for item in audit.report["issues"]} >= {
        "invalid_labels",
        "missing_fsa_files",
    }
    assert set(audit.rows["FsaStatus"]) == {"resolved", "resolved_recursive", "missing"}
    assert {"LadderR2", "PeakCount"}.issubset(set(audit.feature_quality["feature"]))

    paths = write_clonality_ml_audit(audit, tmp_path / "audit")
    assert all(path.exists() for path in paths.values())
    saved = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert saved["missing_fsa_count"] == 1


def test_strict_cli_returns_two_for_blocking_errors(tmp_path):
    workbook = tmp_path / "tracking.xlsx"
    _write_tracking_workbook(workbook, _rows())
    fsa_root = tmp_path / "fsa"
    fsa_root.mkdir()

    result = main(
        [
            "--xls",
            str(workbook),
            "--fsa-root",
            str(fsa_root),
            "--output-dir",
            str(tmp_path / "out"),
            "--strict",
        ]
    )

    assert result == 2
