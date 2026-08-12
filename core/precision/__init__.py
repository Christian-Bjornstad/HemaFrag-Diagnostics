"""Offline precision experiments that never alter runtime analysis calls."""

from core.precision.artifact_shadow import evaluate_artifact_shadow
from core.precision.baseline_shadow import evaluate_baseline_detection_shadow
from core.precision.ladder_confidence_shadow import evaluate_ladder_confidence_shadow
from core.precision.sizing_shadow import evaluate_anchor_leave_one_out

__all__ = [
    "evaluate_anchor_leave_one_out",
    "evaluate_artifact_shadow",
    "evaluate_baseline_detection_shadow",
    "evaluate_ladder_confidence_shadow",
]
