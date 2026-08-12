from core.validation.release_gates import evaluate_plan13_release_gates


def _evidence() -> dict:
    return {
        "unexplained_ladder_regressions": 0,
        "manual_rerun_attempted": 1,
        "manual_rerun_succeeded": 1,
        "expected_report_entries": 22,
        "actual_report_entries": 22,
        "expected_qc_entries": 14,
        "actual_qc_entries": 14,
        "flt3_area_bias_evaluated": True,
        "flt3_area_bias_within_tolerance": True,
        "changed_clinical_interpretations": 0,
        "chemist_review_approved": False,
        "performance_output_parity": True,
        "p95_improvement_fraction": 0.10,
        "provenance_complete": True,
        "shadow_evidence_reviewed": True,
    }


def test_release_gates_pass_complete_evidence():
    result = evaluate_plan13_release_gates(_evidence())

    assert result["engineering_performance_ready"] is True
    assert result["clinical_algorithm_promotion_ready"] is True
    assert result["overall_status"] == "ready"


def test_release_gates_keep_clinical_changes_blocked_without_review():
    evidence = _evidence()
    evidence["flt3_area_bias_evaluated"] = False
    evidence["changed_clinical_interpretations"] = None
    evidence["shadow_evidence_reviewed"] = False

    result = evaluate_plan13_release_gates(evidence)

    assert result["engineering_performance_ready"] is True
    assert result["clinical_algorithm_promotion_ready"] is False
    assert result["overall_status"] == "engineering_ready_clinical_review_blocked"
    statuses = {gate["name"]: gate["status"] for gate in result["gates"]}
    assert statuses["flt3_area_bias_within_approved_tolerance"] == "not_evaluated"
    assert statuses["clinical_interpretation_review"] == "not_evaluated"
    assert statuses["chemist_review_of_shadow_evidence"] == "fail"
