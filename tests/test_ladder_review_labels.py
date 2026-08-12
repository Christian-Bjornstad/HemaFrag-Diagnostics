from __future__ import annotations

from core.analyses.clonality.ladder_review_labels import (
    REVIEW_LABEL_POLICIES,
    RERUNNABLE_LABELS,
    RESOLVED_LABELS,
    is_review_fitting_eligible,
    is_review_ml_eligible,
    is_review_rerunnable,
    is_review_resolved,
    review_label_policy,
)


def test_missing_ladder_policy_resolves_but_never_reruns_or_trains():
    label = "excluded_missing_ladder_signal"

    assert is_review_resolved(label)
    assert not is_review_rerunnable(label)
    assert not is_review_fitting_eligible(label)
    assert not is_review_ml_eligible(label)


def test_policy_lookup_normalizes_whitespace_and_case():
    policy = review_label_policy("  EXCLUDED_MISSING_LADDER_SIGNAL  ")

    assert policy == REVIEW_LABEL_POLICIES["excluded_missing_ladder_signal"]
    assert "excluded_missing_ladder_signal" in RESOLVED_LABELS
    assert "excluded_missing_ladder_signal" not in RERUNNABLE_LABELS
