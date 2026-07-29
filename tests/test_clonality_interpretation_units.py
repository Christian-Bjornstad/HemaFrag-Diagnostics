from __future__ import annotations

import pandas as pd

from core.analyses.clonality.interpretation_units import (
    channel_labels_from_row,
    channel_local_numeric_features,
    interpretation_units_for_assay,
)
from core.analyses.clonality.ml_training import build_per_assay_datasets


def test_dual_channel_assays_have_two_semantic_units():
    for assay in ("IGK", "TCRbA", "TCRbB", "TCRbC", "TCRgA", "TCRgB"):
        units = interpretation_units_for_assay(assay)
        assert len(units) == 2
        assert {unit.channel for unit in units} == {"DATA1", "DATA2"}
        assert len({unit.unit_id for unit in units}) == 2
        assert all(unit.target_name for unit in units)


def test_channel_projection_excludes_other_channel_and_combined_morphology():
    features = {
        "trace_peak_count_raw_per_channel": {
            "DATA1": 2,
            "DATA2": 17,
        },
        "trace_signal_to_noise_per_channel": {
            "DATA1": 8.5,
            "DATA2": 1.2,
        },
        "trace_total_peak_count_all_channels": 19,
        "dominant_peak_height": 4000,
        "ladder_r2": 0.9998,
        "cohort_context_available": 1,
    }

    projected = channel_local_numeric_features(features, "DATA1")

    assert projected["trace_peak_count_raw_per_channel.SELECTED"] == 2
    assert projected["trace_signal_to_noise_per_channel.SELECTED"] == 8.5
    assert "trace_total_peak_count_all_channels" not in projected
    assert "dominant_peak_height" not in projected
    assert not any("DATA2" in column for column in projected)
    assert projected["ladder_r2"] == 0.9998
    assert projected["cohort_context_available"] == 1


def test_legacy_label_migrates_only_for_single_channel_assay():
    single = channel_labels_from_row(
        {"ClonalityChemistLabel": "monoklonal"},
        "FR1",
    )
    dual = channel_labels_from_row(
        {"ClonalityChemistLabel": "monoklonal"},
        "IGK",
    )

    assert single == {"DATA1": "monoklonal"}
    assert dual == {"DATA1": "", "DATA2": ""}


def test_training_builds_one_dataset_per_interpretation_unit():
    frame = pd.DataFrame(
        {
            "IdentityKey": [f"id-{index}" for index in range(8)],
            "FsaContentHash": [f"hash-{index}" for index in range(8)],
            "DIT": [f"26-{index}" for index in range(8)],
            "Assay": ["IGK"] * 8,
            "InterpretationUnit": [
                "IGK_JK5",
                "IGK_JK5",
                "IGK_JK5",
                "IGK_JK5",
                "IGK_JK1_4",
                "IGK_JK1_4",
                "IGK_JK1_4",
                "IGK_JK1_4",
            ],
            "ClonalitySuggestion": [
                "monoklonal",
                "polyklonal",
                "monoklonal",
                "polyklonal",
                "monoklonal",
                "polyklonal",
                "monoklonal",
                "polyklonal",
            ],
            "trace_signal.SELECTED": list(range(8)),
        }
    )

    datasets = build_per_assay_datasets(
        frame,
        min_samples_per_assay=4,
    )

    assert set(datasets) == {"IGK_JK5", "IGK_JK1_4"}
    assert all(dataset.n_samples == 4 for dataset in datasets.values())
