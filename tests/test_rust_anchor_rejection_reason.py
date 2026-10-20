from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest


@pytest.mark.parametrize(
    ("prior_codes", "prior_primary", "prior_summary"),
    [
        ([], None, "Rust ladder fit looks internally consistent."),
        (["poor_linear_liz_fit"], "poor_linear_liz_fit", "Existing Rust diagnostic."),
    ],
)
def test_python_anchor_rejection_preserves_actual_reason_for_review(
    prior_codes, prior_primary, prior_summary,
):
    from core.analysis._legacy import _mark_rust_ladder_rejection_for_review
    from core.rust_bridge._legacy import _apply_rust_result_to_fsa

    fsa = SimpleNamespace(
        file_name="rejected-liz.fsa",
        ladder="LIZ500_250",
        expected_ladder_steps=np.asarray([35.0, 50.0, 75.0]),
        ladder_steps=np.asarray([35.0, 50.0, 75.0]),
    )
    result = {
        "ladder_review_assessment": {
            "suggested_review": bool(prior_codes),
            "reason_codes": list(prior_codes),
            "primary_reason": prior_primary,
            "summary": prior_summary,
        },
        "ladder_fit_preview": {
            "best_scan_indices": [100, 300, 200],
            "sizing_model": {
                "predicted_ladder_basepairs": [35.0, 50.0, 75.0],
            },
        },
    }

    assert _apply_rust_result_to_fsa(fsa, result) is None

    reason = "anchors are not strictly increasing"
    assert fsa.rust_review_primary_reason == reason
    assert fsa.rust_review_reason_codes == [*prior_codes, "rust_anchor_validation_failed"]
    assert reason in fsa.rust_review_summary
    assert prior_summary in fsa.rust_review_summary
    assessment = fsa.rust_ladder_review_assessment
    assert assessment["suggested_review"] is True
    assert assessment["primary_reason"] == reason
    assert assessment["reason_codes"] == fsa.rust_review_reason_codes
    assert assessment["summary"] == fsa.rust_review_summary

    review = _mark_rust_ladder_rejection_for_review(fsa, "LIZ")
    assert review.ladder_review_required is True
    assert review.ladder_qc_status == "review_required"
    assert review.analysis_status == "ladder_review_only"
    assert review.rust_review_primary_reason == reason
    assert review.best_size_standard.size == 0
    assert review.ladder_steps.size == 0
    assert review.sample_data_with_basepairs is None
    assert review.ladder_model is None
