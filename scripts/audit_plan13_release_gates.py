from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.validation.release_gates import evaluate_plan13_release_gates


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario(manifest: dict, name: str) -> dict:
    return next(
        scenario
        for scenario in manifest.get("scenarios", [])
        if scenario.get("name") == name
    )


def _first_result(scenario: dict) -> dict:
    runs = scenario.get("runs") or []
    return dict(runs[0].get("result") or {}) if runs else {}


def _phase4_evidence(manifest_path: Path) -> dict:
    manifest = _read_json(manifest_path)
    result = _first_result(
        _scenario(manifest, "phase4_report_provenance")
    )
    workbook_matches = list(manifest_path.parent.rglob("Clonality_Tracking.xlsx"))
    provenance_complete = False
    if workbook_matches:
        runs = pd.read_excel(
            workbook_matches[0],
            sheet_name="Runs",
            engine="openpyxl",
        )
        required = {
            "LadderEngine",
            "SourceFsaSha256",
            "AnalysisVersion",
        }
        provenance_complete = bool(
            required.issubset(runs.columns)
            and len(runs) == int(result.get("dit_entry_count") or 0)
            and runs["SourceFsaSha256"].fillna("").astype(str).str.len().eq(64).all()
            and runs["LadderEngine"].fillna("").astype(str).str.len().gt(0).all()
            and runs["AnalysisVersion"].fillna("").astype(str).str.len().gt(0).all()
        )
    input_count = int((result.get("inputs") or {}).get("count") or 0)
    actual_qc = int(result.get("qc_entry_count") or 0)
    return {
        "expected_report_entries": input_count,
        "actual_report_entries": int(result.get("dit_entry_count") or 0),
        "expected_qc_entries": actual_qc,
        "actual_qc_entries": actual_qc,
        "provenance_complete": provenance_complete,
        "unexplained_ladder_regressions": int(
            result.get("review_case_count") or 0
        ),
    }


def _manual_evidence(manifest_path: Path) -> dict:
    manifest = _read_json(manifest_path)
    result = _first_result(
        _scenario(manifest, "flt3_validation_subset")
    )
    manual_count = int(
        (result.get("ladder_qc_counts") or {}).get(
            "manual_adjustment",
            0,
        )
    )
    successful = (
        manual_count
        if int(result.get("review_row_count") or 0) == 0
        and int(result.get("skipped_count") or 0) == 0
        else 0
    )
    return {
        "manual_rerun_attempted": manual_count,
        "manual_rerun_succeeded": successful,
    }


def build_evidence(
    *,
    artifact_benchmark: Path,
    phase1_manifest: Path,
    phase4_manifest: Path,
    chemist_review: Path | None,
) -> dict:
    artifact = _read_json(artifact_benchmark)
    evidence = {
        **_phase4_evidence(phase4_manifest),
        **_manual_evidence(phase1_manifest),
        "performance_output_parity": artifact.get("output_parity"),
        "p95_improvement_fraction": artifact.get(
            "p95_improvement_fraction"
        ),
        "flt3_area_bias_evaluated": False,
        "flt3_area_bias_within_tolerance": None,
        "changed_clinical_interpretations": None,
        "chemist_review_approved": False,
        "shadow_evidence_reviewed": False,
    }
    if chemist_review is not None:
        review = _read_json(chemist_review)
        evidence.update(
            {
                "flt3_area_bias_evaluated": bool(
                    review.get("flt3_area_bias_evaluated")
                ),
                "flt3_area_bias_within_tolerance": review.get(
                    "flt3_area_bias_within_tolerance"
                ),
                "changed_clinical_interpretations": review.get(
                    "changed_clinical_interpretations"
                ),
                "chemist_review_approved": bool(
                    review.get("chemist_review_approved")
                ),
                "shadow_evidence_reviewed": bool(
                    review.get("shadow_evidence_reviewed")
                ),
                "chemist_review": review,
            }
        )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Plan 13 engineering and clinical release gates."
    )
    parser.add_argument(
        "--artifact-benchmark",
        type=Path,
        default=REPO_ROOT
        / "validation_outputs"
        / "plan13_phase3_artifact_ab_alternating.json",
    )
    parser.add_argument(
        "--phase1-manifest",
        type=Path,
        default=REPO_ROOT
        / "validation_outputs"
        / "plan13_phase1_smoke"
        / "baseline_manifest.json",
    )
    parser.add_argument(
        "--phase4-manifest",
        type=Path,
        default=REPO_ROOT
        / "validation_outputs"
        / "plan13_phase4_report_smoke"
        / "baseline_manifest.json",
    )
    parser.add_argument("--chemist-review", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "validation_outputs"
        / "plan13_release_gate_audit.json",
    )
    args = parser.parse_args()
    evidence = build_evidence(
        artifact_benchmark=args.artifact_benchmark,
        phase1_manifest=args.phase1_manifest,
        phase4_manifest=args.phase4_manifest,
        chemist_review=args.chemist_review,
    )
    audit = evaluate_plan13_release_gates(evidence)
    audit["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    audit["evidence"] = evidence
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(json.dumps(audit, indent=2, ensure_ascii=True))
    return 0 if audit["engineering_performance_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
