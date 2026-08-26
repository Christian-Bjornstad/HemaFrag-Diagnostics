"""Regression tests for save_ladder_adjustment with NumPy-array inputs.

Ladder Studio previews carry ``expected_ladder_steps``/``ladder_steps``
as numpy arrays; the old ``(expected_steps_raw or [])`` idiom raised
ValueError ("truth value of an array ... is ambiguous"), which surfaced
to the user as "The ladder correction was not saved".
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ladder_adjustment_io import save_ladder_adjustment


def _make_fsa(tmp_path: Path, expected, ladder) -> MagicMock:
    fsa = MagicMock()
    path = tmp_path / "case.fsa"
    path.write_bytes(b"fake-fsa-bytes")
    fsa.file = str(path)
    fsa.expected_ladder_steps = expected
    fsa.ladder_steps = ladder
    for attr in (
        "analysis_id",
        "assay",
        "assay_name",
        "ladder",
        "rust_size_standard_channel",
        "size_standard_channel",
    ):
        setattr(fsa, attr, "")
    return fsa


_PAYLOAD = {"mapping": {0: 1}, "mapping_times": {0: 12.5}, "manual_candidates": []}


@pytest.mark.parametrize(
    "expected,ladder",
    [
        (np.array([100.0, 200.0, 300.0]), np.array([100.0, 200.0, 300.0])),
        (np.arange(50, 500, 50), None),
        (None, np.array([100.0, 200.0])),
        (None, None),
        ([100.0, 200.0], [100.0, 200.0]),
        ([], []),
    ],
    ids=["numpy-both", "numpy-expected-none-ladder", "none-expected-numpy-ladder", "both-none", "plain-lists", "empty"],
)
def test_save_survives_array_and_list_step_inputs(tmp_path, expected, ladder):
    fsa = _make_fsa(tmp_path, expected, ladder)
    saved = save_ladder_adjustment(fsa, _PAYLOAD)
    assert saved is not None and Path(saved).exists()


def test_saved_record_carries_expected_bp_from_numpy_steps(tmp_path):
    fsa = _make_fsa(
        tmp_path,
        np.array([100.0, 200.0, 300.0]),
        np.array([100.0, 200.0, 300.0]),
    )
    save_ladder_adjustment(fsa, _PAYLOAD)

    from core.ladder_adjustment_store import load_ladder_adjustment_record

    record = load_ladder_adjustment_record(Path(fsa.file), ladder="", size_standard_channel="")
    peaks = record["payload"]["selected_peaks"]
    assert peaks[0]["expected_bp"] == pytest.approx(100.0)
