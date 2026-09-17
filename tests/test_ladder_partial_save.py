"""Contracts for partial manual ladder mappings and exact trace markers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class _FakeFsa:
    def __init__(self, ladder_steps, ss_peaks, *, trace_length: int = 800):
        self.ladder = "ROX"
        self.expected_ladder_steps = np.asarray(ladder_steps, dtype=float)
        self.ladder_steps = np.asarray(ladder_steps, dtype=float)
        self.size_standard_peaks = np.asarray(ss_peaks, dtype=float)
        self.size_standard = np.zeros(trace_length, dtype=float)
        self.sample_data = np.zeros(trace_length, dtype=float)
        self.file_name = "synthetic.fsa"


def _fake_fit(fsa):
    fsa.fitted_to_model = True
    fsa.sample_data_with_basepairs = pd.DataFrame(
        {
            "time": np.arange(len(fsa.sample_data), dtype=int),
            "basepairs": np.linspace(1.0, 500.0, len(fsa.sample_data)),
        }
    )
    return fsa

def test_exact_trace_sampling_preserves_fractional_x_without_peak_snap():
    from gui_qt.dialogs.ladder_dialog._legacy import sample_raw_trace_at_x

    scan_x, intensity = sample_raw_trace_at_x([0.0, 10.0, 30.0, 5.0], 1.25)

    assert scan_x == pytest.approx(1.25)
    assert intensity == pytest.approx(15.0)


def test_trace_sampling_clamps_only_to_raw_trace_bounds():
    from gui_qt.dialogs.ladder_dialog._legacy import sample_raw_trace_at_x

    assert sample_raw_trace_at_x([4.0, 8.0], -10.0) == (0.0, 4.0)
    assert sample_raw_trace_at_x([4.0, 8.0], 10.0) == (1.0, 8.0)


def test_collision_resolver_reports_every_collocated_identity():
    from gui_qt.dialogs.ladder_dialog._legacy import colliding_candidate_indices

    candidates = pd.DataFrame(
        {
            "time": [99.8, 100.0, 100.2, 104.0],
            "marker_id": ["detected", "manual-a", "manual-b", "far"],
        }
    )

    assert colliding_candidate_indices(candidates, 100.0, tolerance=0.25) == [
        1,
        0,
        2,
    ]


def test_collocated_manual_markers_keep_independent_identities():
    from gui_qt.dialogs.ladder_dialog._legacy import LadderAdjustmentDialog

    dialog = LadderAdjustmentDialog.__new__(LadderAdjustmentDialog)
    dialog.candidates = pd.DataFrame(
        {
            "index": [0],
            "time": [100.0],
            "requested_x": [100.0],
            "intensity": [20.0],
            "source": ["auto"],
            "marker_id": ["detected-100"],
        }
    )
    dialog._manual_candidate_times = []

    first = dialog._insert_manual_candidate(100.0, 20.0, requested_x=100.0)
    second = dialog._insert_manual_candidate(100.0, 20.0, requested_x=100.0)

    assert first != second
    assert dialog.candidates.iloc[first]["source"] == "manual_exact"
    assert dialog.candidates.iloc[first]["marker_id"] != dialog.candidates.iloc[second]["marker_id"]
    assert dialog.candidates.iloc[0]["marker_id"] == "detected-100"

def test_partial_mapping_fits_only_explicit_observed_anchors(monkeypatch):
    import core.analysis._legacy as analysis

    fsa = _FakeFsa([50.0, 100.0, 150.0, 200.0], [100.0, 300.0, 500.0])
    monkeypatch.setattr(analysis, "fit_size_standard_to_ladder", _fake_fit)

    result = analysis.apply_manual_ladder_mapping(
        fsa,
        {
            "mapping": {},
            "mapping_times": {0: 100.0, 2: 300.0, 3: 500.0},
            "manual_candidates": [],
            "review": {"partial_approved": True},
        },
    )

    assert result.best_size_standard.tolist() == [100.0, 300.0, 500.0]
    assert result.ladder_steps.tolist() == [50.0, 150.0, 200.0]
    assert result.expected_ladder_steps.tolist() == [50.0, 100.0, 150.0, 200.0]
    assert result.manual_ladder_mapped_step_indices == [0, 2, 3]
    assert result.manual_ladder_missing_step_indices == [1]
    assert result.ladder_missing_expected_steps == [100.0]
    assert result.ladder_fit_strategy == "manual_partial"
    assert result.ladder_qc_status == "manual_partial_reviewed"
    assert result.ladder_review_required is False


def test_partial_mapping_does_not_extrapolate_trailing_observations(monkeypatch):
    import core.analysis._legacy as analysis

    fsa = _FakeFsa([50.0, 100.0, 150.0, 200.0], [100.0, 200.0, 300.0])
    monkeypatch.setattr(analysis, "fit_size_standard_to_ladder", _fake_fit)

    result = analysis.apply_manual_ladder_mapping(
        fsa,
        {
            "mapping": {},
            "mapping_times": {0: 100.0, 1: 200.0, 2: 300.0},
            "manual_candidates": [],
            "review": {"partial_approved": False},
        },
    )

    assert result.best_size_standard.tolist() == [100.0, 200.0, 300.0]
    assert result.ladder_steps.tolist() == [50.0, 100.0, 150.0]
    assert result.ladder_missing_expected_steps == [200.0]
    assert result.ladder_qc_status == "review_required"
    assert result.ladder_review_required is True


def test_fewer_than_three_explicit_anchors_are_rejected():
    import core.analysis._legacy as analysis

    fsa = _FakeFsa([50.0, 100.0, 150.0], [100.0, 200.0])
    with pytest.raises(ValueError, match="at least three explicitly assigned"):
        analysis.apply_manual_ladder_mapping(
            fsa,
            {
                "mapping": {},
                "mapping_times": {0: 100.0, 1: 200.0},
                "manual_candidates": [],
            },
        )


def test_non_increasing_observed_anchors_are_rejected():
    import core.analysis._legacy as analysis

    fsa = _FakeFsa([50.0, 100.0, 150.0], [100.0, 300.0, 500.0])
    with pytest.raises(ValueError, match="strictly increasing in time"):
        analysis.apply_manual_ladder_mapping(
            fsa,
            {
                "mapping": {},
                "mapping_times": {0: 500.0, 1: 300.0, 2: 100.0},
                "manual_candidates": [],
            },
        )


def test_one_marker_cannot_fit_multiple_steps():
    import core.analysis._legacy as analysis

    fsa = _FakeFsa([50.0, 100.0, 150.0], [100.0, 200.0, 300.0])
    with pytest.raises(ValueError, match="One marker cannot"):
        analysis.apply_manual_ladder_mapping(
            fsa,
            {
                "mapping": {},
                "mapping_times": {0: 100.0, 1: 200.0, 2: 300.0},
                "marker_id_by_step": {0: "same", 1: "same", 2: "third"},
            },
        )


def _dialog_payload(mapping: dict[int, int], times: list[float]) -> dict:
    from gui_qt.dialogs.ladder_dialog._legacy import LadderAdjustmentDialog

    dialog = LadderAdjustmentDialog.__new__(LadderAdjustmentDialog)
    dialog.ladder_steps = np.array([50.0, 100.0, 150.0])
    dialog.mapping = mapping
    dialog._missing_order = "ascending"
    dialog._manual_candidate_times = []
    dialog.candidates = pd.DataFrame(
        {
            "time": times,
            "intensity": [10.0 + index for index in range(len(times))],
            "source": ["auto"] * len(times),
            "marker_id": [f"detected-{index}" for index in range(len(times))],
            "requested_x": times,
        }
    )
    return dialog._build_adjustment_payload()


def test_dialog_payload_records_partial_steps_and_stable_marker_identity():
    payload = _dialog_payload({0: 0, 2: 2}, [10.0, 20.0, 30.0])

    assert payload["partial_mapping"] is True
    assert payload["mapped_step_indices"] == [0, 2]
    assert payload["missing_step_indices"] == [1]
    assert payload["marker_id_by_step"] == {0: "detected-0", 2: "detected-2"}
    assert payload["mapping_times"] == {0: 10.0, 2: 30.0}


def test_dialog_payload_marks_complete_mapping_without_missing_steps():
    payload = _dialog_payload({0: 0, 1: 1, 2: 2}, [10.0, 20.0, 30.0])

    assert payload["partial_mapping"] is False
    assert payload["missing_step_indices"] == []
