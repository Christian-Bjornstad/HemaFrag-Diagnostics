from __future__ import annotations

import pandas as pd

from core.analyses.clonality.cohort_features import (
    enrich_entries_with_cohort_context,
    enrich_feature_frame_with_cohort_context,
)
from core.analyses.clonality.pipeline import _attach_batch_context_and_ml


def _row(
    identity: str,
    *,
    dit: str = "DIT-1",
    assay: str = "FR1",
    run: str = "run-a",
    bp: float = 325.0,
) -> dict:
    return {
        "IdentityKey": identity,
        "DIT": dit,
        "Assay": assay,
        "SourceRunKey": run,
        "dominant_peak_basepairs": bp,
    }


def test_feature_frame_adds_same_run_replicate_concordance():
    frame = pd.DataFrame(
        [
            _row("first", bp=325.0),
            _row("second", bp=326.0),
            _row("panel", assay="IGK", bp=210.0),
        ]
    )

    enriched = enrich_feature_frame_with_cohort_context(frame)
    first = enriched.set_index("IdentityKey").loc["first"]

    assert first["cohort_patient_entry_count"] == 3
    assert first["cohort_patient_assay_count"] == 2
    assert first["cohort_same_assay_replicate_count"] == 1
    assert first["cohort_replicate_nearest_delta_bp"] == 1.0
    assert first["cohort_replicate_within_2bp_fraction"] == 1.0
    assert first["cohort_replicate_concordant"] == 1


def test_feature_frame_does_not_mix_source_runs():
    frame = pd.DataFrame(
        [
            _row("first", run="run-a", bp=325.0),
            _row("second", run="run-b", bp=325.5),
        ]
    )

    enriched = enrich_feature_frame_with_cohort_context(frame)

    assert enriched["cohort_patient_entry_count"].tolist() == [1.0, 1.0]
    assert enriched["cohort_same_assay_replicate_count"].tolist() == [0.0, 0.0]


def test_feature_frame_requires_run_provenance_and_excludes_controls():
    missing_run = _row("missing-run", run="")
    patient = _row("patient")
    control = {
        **_row("control", bp=325.5),
        "SampleKind": "control",
    }

    enriched = enrich_feature_frame_with_cohort_context(
        pd.DataFrame([missing_run, patient, control])
    ).set_index("IdentityKey")

    assert enriched.loc["missing-run", "cohort_context_available"] == 0
    assert enriched.loc["patient", "cohort_patient_entry_count"] == 1
    assert enriched.loc["patient", "cohort_same_assay_replicate_count"] == 0
    assert enriched.loc["control", "cohort_context_available"] == 0


def test_entry_enrichment_updates_runtime_and_rule_feature_maps():
    entries = [
        {
            "file_name": "first.fsa",
            "dit": "DIT-1",
            "assay": "FR1",
            "source_run_dir": r"C:\raw\run-a",
            "clonality_interpretation": {
                "features": {"dominant_peak_basepairs": 325.0}
            },
        },
        {
            "file_name": "second.fsa",
            "dit": "DIT-1",
            "assay": "FR1",
            "source_run_dir": r"C:\raw\run-a",
            "clonality_interpretation": {
                "features": {"dominant_peak_basepairs": 326.0}
            },
        },
    ]

    enriched = enrich_entries_with_cohort_context(entries)

    for entry in enriched:
        assert entry["features"]["cohort_context_available"] == 1
        assert entry["features"]["cohort_same_assay_replicate_count"] == 1
        assert (
            entry["clonality_interpretation"]["features"][
                "cohort_replicate_concordant"
            ]
            == 1
        )


def test_batch_pipeline_attaches_ml_after_context(monkeypatch):
    entries = [
        {
            "file_name": "first.fsa",
            "dit": "DIT-1",
            "assay": "FR1",
            "source_run_dir": "run-a",
            "features": {"dominant_peak_basepairs": 325.0},
        },
        {
            "file_name": "second.fsa",
            "dit": "DIT-1",
            "assay": "FR1",
            "source_run_dir": "run-a",
            "features": {"dominant_peak_basepairs": 326.0},
        },
    ]
    observed = []

    def attach(entry):
        observed.append(entry["features"]["cohort_same_assay_replicate_count"])
        entry["ml_attached"] = True
        return entry

    monkeypatch.setattr(
        "core.analyses.clonality.pipeline.attach_ml_prediction_if_enabled",
        attach,
    )

    result = _attach_batch_context_and_ml(entries)

    assert observed == [1, 1]
    assert all(entry["ml_attached"] for entry in result)
