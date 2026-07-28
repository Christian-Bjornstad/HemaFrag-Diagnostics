"""Plan 13 release gates with explicit clinical-review blockers."""
from __future__ import annotations

from typing import Any


PLAN13_RELEASE_GATE_SCHEMA = "hemafrag_plan13_release_gate_v1"


def _gate(
    name: str,
    passed: bool | None,
    detail: str,
    *,
    required_for_performance: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": (
            "pass"
            if passed is True
            else "fail"
            if passed is False
            else "not_evaluated"
        ),
        "detail": detail,
        "required_for_performance": required_for_performance,
    }


def evaluate_plan13_release_gates(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate engineering and clinical gates without assuming approval."""
    unexplained_regressions = evidence.get("unexplained_ladder_regressions")
    manual_attempted = int(evidence.get("manual_rerun_attempted") or 0)
    manual_succeeded = int(evidence.get("manual_rerun_succeeded") or 0)
    expected_entries = evidence.get("expected_report_entries")
    actual_entries = evidence.get("actual_report_entries")
    expected_qc = evidence.get("expected_qc_entries")
    actual_qc = evidence.get("actual_qc_entries")
    area_bias_evaluated = bool(evidence.get("flt3_area_bias_evaluated"))
    area_bias_within_tolerance = evidence.get("flt3_area_bias_within_tolerance")
    changed_interpretations = evidence.get("changed_clinical_interpretations")
    chemist_approved = bool(evidence.get("chemist_review_approved"))
    p95_improvement = evidence.get("p95_improvement_fraction")
    output_parity = evidence.get("performance_output_parity")
    provenance_complete = evidence.get("provenance_complete")
    shadow_reviewed = evidence.get("shadow_evidence_reviewed")

    gates = [
        _gate(
            "zero_unexplained_ladder_regressions",
            (
                unexplained_regressions == 0
                if unexplained_regressions is not None
                else None
            ),
            f"unexplained={unexplained_regressions}",
            required_for_performance=True,
        ),
        _gate(
            "manual_correction_rerun_success",
            (
                manual_attempted > 0
                and manual_succeeded == manual_attempted
            ),
            f"succeeded={manual_succeeded}, attempted={manual_attempted}",
            required_for_performance=True,
        ),
        _gate(
            "report_and_qc_completeness",
            (
                expected_entries is not None
                and expected_qc is not None
                and expected_entries == actual_entries
                and expected_qc == actual_qc
            ),
            (
                f"entries={actual_entries}/{expected_entries}, "
                f"qc={actual_qc}/{expected_qc}"
            ),
            required_for_performance=True,
        ),
        _gate(
            "flt3_area_bias_within_approved_tolerance",
            (
                bool(area_bias_within_tolerance)
                if area_bias_evaluated
                else None
            ),
            (
                "evaluated and within tolerance"
                if area_bias_evaluated and area_bias_within_tolerance
                else "evaluated outside tolerance"
                if area_bias_evaluated
                else "independent FLT3 area-bias study not supplied"
            ),
        ),
        _gate(
            "clinical_interpretation_review",
            (
                True
                if changed_interpretations == 0
                else chemist_approved
                if changed_interpretations is not None
                else None
            ),
            (
                f"changed={changed_interpretations}, "
                f"chemist_approved={chemist_approved}"
            ),
        ),
        _gate(
            "performance_p95_and_output_parity",
            (
                bool(output_parity)
                and p95_improvement is not None
                and float(p95_improvement) > 0.0
            ),
            (
                f"parity={output_parity}, "
                f"p95_improvement={p95_improvement}"
            ),
            required_for_performance=True,
        ),
        _gate(
            "source_engine_model_correction_provenance",
            (
                bool(provenance_complete)
                if provenance_complete is not None
                else None
            ),
            f"complete={provenance_complete}",
            required_for_performance=True,
        ),
        _gate(
            "chemist_review_of_shadow_evidence",
            (
                bool(shadow_reviewed)
                if shadow_reviewed is not None
                else None
            ),
            f"reviewed={shadow_reviewed}",
        ),
    ]
    performance_gates = [
        gate for gate in gates if gate["required_for_performance"]
    ]
    engineering_ready = all(
        gate["status"] == "pass" for gate in performance_gates
    )
    clinical_ready = all(gate["status"] == "pass" for gate in gates)
    return {
        "schema_version": PLAN13_RELEASE_GATE_SCHEMA,
        "engineering_performance_ready": engineering_ready,
        "clinical_algorithm_promotion_ready": clinical_ready,
        "overall_status": (
            "ready"
            if clinical_ready
            else "engineering_ready_clinical_review_blocked"
            if engineering_ready
            else "blocked"
        ),
        "gates": gates,
    }


__all__ = [
    "PLAN13_RELEASE_GATE_SCHEMA",
    "evaluate_plan13_release_gates",
]
