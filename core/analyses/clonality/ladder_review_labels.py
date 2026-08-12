"""Central policy for labels written to ladder-review CSV bundles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewLabelPolicy:
    resolved: bool
    rerunnable: bool
    fitting_eligible: bool
    ml_eligible: bool


REVIEW_LABEL_POLICIES = {
    "manual_adjusted": ReviewLabelPolicy(True, True, True, True),
    "reviewed_no_change": ReviewLabelPolicy(True, True, True, True),
    "excluded_missing_ladder_signal": ReviewLabelPolicy(True, False, False, False),
}

_UNRECOGNIZED_LABEL_POLICY = ReviewLabelPolicy(False, False, False, False)

RESOLVED_LABELS = {
    label for label, policy in REVIEW_LABEL_POLICIES.items() if policy.resolved
}
RERUNNABLE_LABELS = {
    label for label, policy in REVIEW_LABEL_POLICIES.items() if policy.rerunnable
}


def review_label_policy(label: str | None) -> ReviewLabelPolicy:
    """Return the policy for a raw CSV label, defaulting to unresolved."""
    normalized = str(label or "").strip().casefold()
    return REVIEW_LABEL_POLICIES.get(normalized, _UNRECOGNIZED_LABEL_POLICY)


def is_review_resolved(label: str | None) -> bool:
    return review_label_policy(label).resolved


def is_review_rerunnable(label: str | None) -> bool:
    return review_label_policy(label).rerunnable


def is_review_fitting_eligible(label: str | None) -> bool:
    return review_label_policy(label).fitting_eligible


def is_review_ml_eligible(label: str | None) -> bool:
    return review_label_policy(label).ml_eligible
