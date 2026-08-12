from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.analyses.clonality.ml_data_contract import CHEMIST_LABEL_COLUMN
from core.analyses.clonality.ml_feature_dataset import (
    TraceFeatureDataset,
    build_clonality_trace_feature_dataset,
    load_resumable_feature_artifact,
    write_clonality_trace_feature_artifact,
)
from scripts.train_clonality_interpretation_models import _assemble_trace_feature_df


def _entry(path, assay="FR1"):
    bp = np.linspace(100.0, 400.0, 3001)
    time = np.arange(bp.size)
    trace = (
        100.0
        + 2.0 * np.sin(bp / 9.0)
        + 1200.0 * np.exp(-0.5 * ((bp - 325.0) / 0.9) ** 2)
        + 500.0 * np.exp(-0.5 * ((bp - 342.0) / 1.1) ** 2)
    )
    fsa = SimpleNamespace(
        sample_data_with_basepairs=pd.DataFrame(
            {"time": time, "basepairs": bp}
        ),
        fsa={"DATA1": trace, "DATA4": np.zeros_like(trace)},
        size_standard_channel="DATA4",
        file=path,
        file_name=path.name,
    )
    return {
        "fsa": fsa,
        "file_name": path.name,
        "original_file_path": str(path),
        "assay": assay,
        "bp_min": 100.0,
        "bp_max": 400.0,
        "trace_channels": ["DATA1"],
        "primary_peak_channel": "DATA1",
        "peaks_by_channel": {
            "DATA1": pd.DataFrame(
                {
                    "basepairs": [325.0, 342.0],
                    "peaks": [1300.0, 600.0],
                    "keep": [True, True],
                }
            )
        },
        "ladder_qc_status": "ok",
        "ladder_review_required": False,
        "ladder_r2": 0.999,
    }


def _dual_channel_entry(path):
    entry = _entry(path, assay="IGK")
    data1 = entry["fsa"].fsa["DATA1"]
    data2 = (
        80.0
        + 500.0 * np.exp(
            -0.5
            * (
                (
                    entry["fsa"].sample_data_with_basepairs["basepairs"].to_numpy()
                    - 205.0
                )
                / 1.2
            )
            ** 2
        )
    )
    entry["fsa"].fsa["DATA2"] = data2
    entry["trace_channels"] = ["DATA1", "DATA2"]
    entry["peaks_by_channel"]["DATA2"] = pd.DataFrame(
        {
            "basepairs": [205.0],
            "peaks": [580.0],
            "keep": [True],
        }
    )
    return entry


def _audit_rows(tmp_path):
    first = tmp_path / "sample1.fsa"
    second = tmp_path / "sample2.fsa"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    return pd.DataFrame(
        [
            {
                "IdentityKey": "id-1",
                "FsaSourceHash": "hash-1",
                "DIT": "26A",
                "Assay": "FR1",
                "SourceRunDir": r"C:\private\raw\run-a",
                "RunDate": "2026-07-26",
                "Well": "A01",
                "File": first.name,
                "ResolvedFsaPath": str(first),
                "FsaStatus": "resolved",
                CHEMIST_LABEL_COLUMN: "monoklonal",
            },
            {
                "IdentityKey": "id-2",
                "FsaSourceHash": "hash-2",
                "DIT": "26B",
                "Assay": "FR1",
                "SourceRunDir": "run-a",
                "RunDate": "2026-07-26",
                "Well": "A02",
                "File": second.name,
                "ResolvedFsaPath": str(second),
                "FsaStatus": "resolved",
                CHEMIST_LABEL_COLUMN: "polyklonal",
            },
        ]
    )


def test_build_feature_dataset_exports_flat_trace_features_without_raw_paths(tmp_path):
    rows = _audit_rows(tmp_path)
    checkpoints = []

    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
        checkpoint_every=1,
        checkpoint_callback=lambda value: checkpoints.append(len(value.features)),
    )

    assert len(dataset.features) == 2
    assert dataset.errors.empty
    assert dataset.processed_count == 2
    assert "trace_peak_count_raw_per_channel.SELECTED" in dataset.features.columns
    assert "trace_signal_to_noise_per_channel.SELECTED" in dataset.features.columns
    assert dataset.features["FsaContentHash"].str.len().eq(64).all()
    assert dataset.features["FeatureDatasetVersion"].eq(
        "clonality_ml_feature_dataset_v4_channel"
    ).all()
    assert dataset.features["CohortFeatureSchemaVersion"].eq(
        "clonality_cohort_features_v1"
    ).all()
    assert dataset.features["cohort_context_available"].eq(1).all()
    assert "ResolvedFsaPath" not in dataset.features.columns
    assert "SourceRunDir" not in dataset.features.columns
    assert dataset.features.loc[0, "SourceRunKey"] == "run-a"
    assert list(dataset.features[CHEMIST_LABEL_COLUMN]) == [
        "monoklonal",
        "polyklonal",
    ]
    assert checkpoints[-1] == 2


def test_feature_dataset_resume_skips_matching_schema_and_source(tmp_path):
    rows = _audit_rows(tmp_path)
    first = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    calls = []
    resumed = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: calls.append(path),
        existing_features=first.features,
    )

    assert calls == []
    assert resumed.processed_count == 0
    assert resumed.skipped_existing_count == 2
    assert len(resumed.features) == 2


def test_feature_dataset_resume_prunes_rows_outside_current_audit(tmp_path):
    rows = _audit_rows(tmp_path)
    first = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    stale = first.features.iloc[[0]].copy()
    stale["IdentityKey"] = "stale-id"
    existing = pd.concat([first.features, stale], ignore_index=True)

    resumed = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: pytest.fail(f"unexpected analysis: {path}"),
        existing_features=existing,
    )

    assert resumed.skipped_existing_count == 2
    assert set(resumed.features["IdentityKey"]) == {"id-1", "id-2"}


def test_feature_dataset_resume_reprocesses_changed_fsa_content(tmp_path):
    rows = _audit_rows(tmp_path)
    first = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    original_hashes = dict(
        zip(first.features["IdentityKey"], first.features["FsaContentHash"])
    )
    (tmp_path / "sample1.fsa").write_bytes(b"changed")
    calls = []

    resumed = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: calls.append(path) or _entry(path),
        existing_features=first.features,
    )

    assert calls == [tmp_path / "sample1.fsa"]
    assert resumed.processed_count == 1
    assert resumed.skipped_existing_count == 1
    assert len(resumed.features) == 2
    changed = resumed.features.set_index("IdentityKey").loc["id-1", "FsaContentHash"]
    assert changed != original_hashes["id-1"]


def test_feature_dataset_records_assay_mismatch_as_error(tmp_path):
    rows = _audit_rows(tmp_path).head(1)

    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path, assay="IGK"),
    )

    assert dataset.features.empty
    assert len(dataset.errors) == 1
    assert "assay mismatch" in dataset.errors.iloc[0]["Error"]


def test_dual_channel_feature_dataset_is_long_form_and_channel_local(tmp_path):
    path = tmp_path / "igk.fsa"
    path.write_bytes(b"igk")
    rows = pd.DataFrame(
        [
            {
                "IdentityKey": "igk-id",
                "FsaSourceHash": "source",
                "DIT": "26IGK",
                "Assay": "IGK",
                "SourceRunDir": "run-a",
                "RunDate": "2026-07-29",
                "Well": "A01",
                "File": path.name,
                "ResolvedFsaPath": str(path),
                "FsaStatus": "resolved",
                "ClonalityChemistLabel": "irregulaer",
                "ClonalityChemistLabel_DATA1": "polyklonal",
                "ClonalityChemistLabel_DATA2": "monoklonal",
            }
        ]
    )

    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=_dual_channel_entry,
    )

    assert dataset.processed_count == 1
    assert len(dataset.features) == 2
    assert set(dataset.features["InterpretationUnit"]) == {
        "IGK_JK5",
        "IGK_JK1_4",
    }
    assert set(dataset.features["ClonalityChemistLabel"]) == {
        "polyklonal",
        "monoklonal",
    }
    assert not any(
        column.endswith(".DATA1") or column.endswith(".DATA2")
        for column in dataset.features.columns
    )
    assert "trace_peak_count_raw_per_channel.SELECTED" in dataset.features


def test_write_feature_artifact_has_provenance_and_no_raw_trace_claim(tmp_path):
    rows = _audit_rows(tmp_path)
    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    output = tmp_path / "artifact"
    paths = write_clonality_trace_feature_artifact(
        dataset,
        output,
        workbook_path=tmp_path / "tracking.xlsx",
        fsa_root=tmp_path,
        audit_report={"status": "review", "issues": []},
    )

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["contains_raw_traces"] is False
    assert manifest["features_contain_local_raw_paths"] is False
    assert manifest["manifest_contains_local_paths"] is True
    assert manifest["row_count"] == 2
    assert manifest["trace_feature_count"] > 0
    assert manifest["settings_fingerprint"]

    resumed = load_resumable_feature_artifact(output)
    assert len(resumed) == 2


def test_load_resumable_feature_artifact_accepts_empty_checkpoint(tmp_path):
    output = tmp_path / "artifact"
    write_clonality_trace_feature_artifact(
        TraceFeatureDataset(
            features=pd.DataFrame(),
            errors=pd.DataFrame(),
            processed_count=0,
            skipped_existing_count=0,
        ),
        output,
        workbook_path=tmp_path / "tracking.xlsx",
        fsa_root=tmp_path,
    )

    assert load_resumable_feature_artifact(output).empty


def test_load_resumable_feature_artifact_migrates_v2_derived_fields(tmp_path):
    rows = _audit_rows(tmp_path)
    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    output = tmp_path / "artifact"
    paths = write_clonality_trace_feature_artifact(
        dataset,
        output,
        workbook_path=tmp_path / "tracking.xlsx",
        fsa_root=tmp_path,
    )
    legacy = pd.read_csv(paths["features"])
    legacy["FeatureDatasetVersion"] = "clonality_ml_feature_dataset_v2"
    legacy["ref_window_coverage_fraction"] = 0.0
    legacy["in_reference_window"] = 0
    legacy["patient_assays_run_count"] = 0
    legacy.to_csv(paths["features"], index=False)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["dataset_version"] = "clonality_ml_feature_dataset_v2"
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    migrated = load_resumable_feature_artifact(output)

    assert migrated["FeatureDatasetVersion"].eq(
        "clonality_ml_feature_dataset_v4_channel"
    ).all()
    assert migrated["patient_assays_run_count"].eq(
        migrated["cohort_patient_assay_count"]
    ).all()


def test_load_resumable_feature_artifact_rejects_changed_settings(tmp_path):
    rows = _audit_rows(tmp_path)
    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    output = tmp_path / "artifact"
    paths = write_clonality_trace_feature_artifact(
        dataset,
        output,
        workbook_path=tmp_path / "tracking.xlsx",
        fsa_root=tmp_path,
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["settings_fingerprint"] = "stale"
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="different clonality settings"):
        load_resumable_feature_artifact(output)


def test_trainer_refreshes_labels_from_workbook_by_identity_and_assay(tmp_path):
    rows = _audit_rows(tmp_path)
    dataset = build_clonality_trace_feature_dataset(
        rows,
        analyze_file=lambda path: _entry(path),
    )
    feature_path = tmp_path / "features.csv"
    dataset.features.to_csv(feature_path, index=False)

    tracking = pd.DataFrame(
        {
            "IdentityKey": ["id-1", "id-2"],
            "DIT": ["26A", "26B"],
            "Assay": ["FR1", "FR1"],
            "SampleKind": ["patient", "patient"],
            "Control": ["", ""],
            CHEMIST_LABEL_COLUMN: ["polyklonal", "monoklonal"],
        }
    )
    workbook = tmp_path / "tracking.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        tracking.to_excel(writer, sheet_name="Runs", index=False)

    training = _assemble_trace_feature_df(workbook, feature_path)

    assert list(training["ClonalitySuggestion"]) == [
        "polyklonal",
        "monoklonal",
    ]
    assert "RuleConfidence" in training.columns
