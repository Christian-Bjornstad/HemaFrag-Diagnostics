"""Native guesses must not replace the ladder requested by the analysis."""
from types import SimpleNamespace

import numpy as np
import pytest

from core.rust_bridge import _legacy as bridge


@pytest.mark.parametrize(
    ("ladder", "channel", "native_ladder", "native_channel"),
    [
        ("ROX400HD", "DATA4", "LIZ500_250", "DATA4"),
        ("LIZ500_250", "DATA5", "LIZ500_250", "DATA4"),
        ("GS500ROX", "DATA4", "GS500ROX", "DATA105"),
        ("GS500ROX", "DATA4", None, "DATA4"),
        ("GS500ROX", "DATA4", "GS500ROX", None),
        ("GS500ROX", "DATA4", "", "DATA4"),
        ("GS500ROX", "DATA4", "GS500ROX", ""),
    ],
)
def test_native_ladder_contract_mismatch_requires_review(
    monkeypatch, ladder, channel, native_ladder, native_channel
):
    from fraggler.ladders import LADDERS

    fsa = SimpleNamespace(
        file_name="sample.fsa",
        ladder=ladder,
        size_standard_channel=channel,
        ladder_steps=LADDERS[ladder]["sizes"].copy(),
    )
    original_steps = fsa.ladder_steps.copy()
    payload = {
        "ladder": native_ladder,
        "size_standard_channel_guess": native_channel,
        "ladder_review_assessment": {"suggested_review": False, "reason_codes": []},
        "ladder_fit_preview": {
            "best_scan_indices": [1300, 1400, 1500],
            "sizing_model": {"predicted_ladder_basepairs": [35, 50, 75]},
        },
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    monkeypatch.setattr(bridge, "_validate_rust_anchor_selection", lambda *_args: (True, ""))
    monkeypatch.setattr(bridge, "_normalized_size_standard_trace_for_fsa", lambda *_args: np.array([]))
    monkeypatch.setattr(bridge, "_apply_rust_sizing_model_to_fsa", lambda value, *_args: value)

    assert bridge._apply_rust_result_to_fsa(fsa, payload) is None
    assert np.array_equal(fsa.ladder_steps, original_steps)
    assert fsa.ladder_review_required is True
    assert "rust_ladder_contract_mismatch" in fsa.rust_review_reason_codes
    assert fsa.rust_ladder_review_assessment["suggested_review"] is True
