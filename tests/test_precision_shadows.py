from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import numpy as np

from core.precision import (
    evaluate_artifact_shadow,
    evaluate_baseline_detection_shadow,
    evaluate_ladder_confidence_shadow,
)
from core.precision.artifact_shadow import ARTIFACT_SHADOW_SCHEMA
from core.precision.baseline_shadow import BASELINE_SHADOW_SCHEMA, _airpls_baseline
from core.precision.ladder_confidence_shadow import LADDER_CONFIDENCE_SHADOW_SCHEMA


def _synthetic_fsa() -> SimpleNamespace:
    length = 900
    scans = np.asarray([100, 160, 230, 305, 390, 480, 585, 700], dtype=float)
    sizes = np.asarray([35, 50, 75, 100, 139, 160, 200, 250], dtype=float)
    x = np.arange(length, dtype=float)
    channels: dict[str, np.ndarray] = {}
    for channel_index in range(1, 5):
        trace = 20.0 + (0.005 * x)
        for peak_index, scan in enumerate(scans):
            height = 1000.0 - (35.0 * peak_index)
            trace += height * np.exp(-0.5 * ((x - scan) / 2.0) ** 2)
        channels[f"DATA{channel_index}"] = trace.copy()
    channels["DATA1"][450] += 20000.0
    channels["DATA2"][450] += 1800.0
    channels["DATA3"][300:303] = 32000.0
    channels["DATA4"] += 2500.0 * np.exp(-0.5 * ((x - 60.0) / 18.0) ** 2)
    candidates = np.sort(np.concatenate([scans, scans[1:-1] + 8.0]))
    return SimpleNamespace(
        fsa=channels,
        size_standard_channel="DATA4",
        sample_channel="DATA1",
        size_standard=channels["DATA4"].copy(),
        sample_data=channels["DATA1"].copy(),
        size_standard_peaks=candidates,
        best_size_standard=scans.copy(),
        ladder_steps=sizes.copy(),
        expected_ladder_steps=sizes.copy(),
        min_size_standard_height=100,
        min_distance_between_peaks=5,
    )


def test_ladder_confidence_shadow_is_deterministic_bounded_and_read_only():
    fsa = _synthetic_fsa()
    before = deepcopy(fsa.__dict__)

    first = evaluate_ladder_confidence_shadow(fsa, top_k=4)
    second = evaluate_ladder_confidence_shadow(fsa, top_k=4)

    assert first == second
    assert first["schema_version"] == LADDER_CONFIDENCE_SHADOW_SCHEMA
    assert first["promotion_eligible"] is False
    assert len(first["top_k"]) <= 4
    assert len(first["anchor_evidence"]) == len(fsa.ladder_steps)
    assert first["runtime_selected_rank"] is not None
    for name, value in before.items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(getattr(fsa, name), value)
        elif isinstance(value, dict):
            for key, array in value.items():
                np.testing.assert_array_equal(getattr(fsa, name)[key], array)
        else:
            assert getattr(fsa, name) == value


def test_artifact_shadow_reports_candidates_without_diagnosing_them():
    result = evaluate_artifact_shadow(_synthetic_fsa(), signal_limit_rfu=30000.0)

    assert result["schema_version"] == ARTIFACT_SHADOW_SCHEMA
    assert result["promotion_eligible"] is False
    assert result["channels"]["DATA3"]["saturation_candidate"] is True
    assert result["pull_up_candidate_count"] >= 1
    assert result["ladder_tail"]["missing_high_end_ladder_candidate"] is False
    assert result["warnings"]["candidates_are_not_diagnoses"] is True


def test_airpls_and_baseline_bakeoff_are_finite_and_use_current_reference():
    x = np.arange(600, dtype=float)
    trace = 10.0 + (0.02 * x)
    trace += 800.0 * np.exp(-0.5 * ((x - 180.0) / 3.0) ** 2)
    trace += 500.0 * np.exp(-0.5 * ((x - 420.0) / 4.0) ** 2)

    airpls = _airpls_baseline(trace)
    result = evaluate_baseline_detection_shadow(
        trace,
        min_height=50.0,
        min_distance=5,
    )

    assert np.all(np.isfinite(airpls))
    assert result["schema_version"] == BASELINE_SHADOW_SCHEMA
    assert result["promotion_eligible"] is False
    assert result["reference_method"] == "current_guarded_arpls"
    assert result["methods"]["current_guarded_arpls"]["reference_peak_recall"] == 1.0
    assert result["warnings"]["quantitative_area_trace_must_remain_separate"] is True
