from __future__ import annotations

import json
from pathlib import Path

from core.run_manifest import (
    RUN_MANIFEST_SCHEMA,
    BatchRunManifest,
    jobs_from_run_manifest,
    load_run_manifest,
)
from core.ladder_adjustment_store import (
    load_ladder_adjustment_record,
    save_ladder_adjustment_record,
)


def test_run_manifest_preserves_jobs_adjustments_progress_and_outputs(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB",
        str(tmp_path / "adjustments.sqlite3"),
    )
    patient = tmp_path / "patient.fsa"
    control = tmp_path / "control.fsa"
    patient.write_bytes(b"patient-trace")
    control.write_bytes(b"control-trace")
    output_dir = tmp_path / "reports"
    output_dir.mkdir()

    recorder = BatchRunManifest.create(
        output_dir=output_dir,
        jobs=[
            {
                "name": "patient-job",
                "type": "pipeline",
                "path": tmp_path,
                "files": [patient],
            },
            {
                "name": "QC",
                "type": "qc",
                "path": tmp_path,
                "files": [control],
            },
        ],
        analysis="clonality",
        settings={"qc": {"min_r2_ok": 0.999}},
        execution={"aggregate_dit_reports": True},
    )
    assert recorder.path.is_absolute()
    recorder.record_progress(
        {
            "job_name": "patient-job",
            "phase": "job_start",
            "files_done": 0,
            "files_total": 1,
        }
    )
    recorder.record_progress(
        {
            "job_name": "patient-job",
            "phase": "done",
            "files_done": 1,
            "files_total": 1,
        }
    )

    save_ladder_adjustment_record(patient, {"selected_times": [1, 2, 3]})
    report = output_dir / "DIT_patient.html"
    report.write_text("<html>report</html>", encoding="utf-8")
    workbook = output_dir / "tracking.xlsx"
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Runs"
    sheet.append(["IdentityKey"])
    sheet.append(["patient"])
    book.save(workbook)
    book.close()
    review_dir = output_dir / "ladder_review_gate"
    review_dir.mkdir()
    cases_path = review_dir / "ladder_review_cases.csv"
    cases_path.write_text("file\npatient.fsa\n", encoding="utf-8")

    recorder.finalize(
        result={
            "completed_jobs": ["patient-job", "QC"],
            "failed_jobs": [],
            "dit_report_entries": [
                {"file_name": "patient.fsa"},
                {"file_name": "control.fsa"},
            ],
            "qc_report_entries": [{"file_name": "control.fsa"}],
            "dit_reports_blocked": False,
        },
        aggregate_output_dir=output_dir,
        review_gate={
            "review_case_count": 1,
            "cases_path": str(cases_path),
        },
    )

    payload = load_run_manifest(recorder.path)
    assert payload["schema_version"] == RUN_MANIFEST_SCHEMA
    assert payload["status"] == "completed"
    assert payload["counts"]["expected_input_files"] == 2
    assert payload["counts"]["completed_jobs"] == 2
    assert payload["counts"]["dit_entries"] == 2
    assert payload["counts"]["qc_entries"] == 1
    assert payload["counts"]["patient_entries"] == 1
    assert payload["counts"]["html_artifacts"] == 1
    assert payload["counts"]["workbook_artifacts"] == 1
    assert payload["jobs"][0]["status"] == "completed"
    assert payload["jobs"][0]["files"][0]["sha256"]
    assert payload["jobs"][0]["files"][0]["manual_adjustment"]["sha256"]
    assert payload["outputs"]["review_bundle"]["cases_path"] == str(cases_path)
    assert any(
        artifact["relative_path"] == "DIT_patient.html"
        for artifact in payload["outputs"]["artifacts"]
    )
    workbook_record = next(
        artifact
        for artifact in payload["outputs"]["artifacts"]
        if artifact["relative_path"] == "tracking.xlsx"
    )
    assert workbook_record["sheet_rows"]["Runs"] == 1
    assert list(output_dir.glob(f".{recorder.path.name}.*.tmp")) == []

    recovered = jobs_from_run_manifest(recorder.path)
    assert recovered[0]["files"] == [patient.resolve()]
    assert recovered[1]["type"] == "qc"
    assert recovered[1]["files"] == [control.resolve()]


def test_load_run_manifest_rejects_unknown_schema(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": "future"}), encoding="utf-8")

    try:
        load_run_manifest(path)
    except ValueError as exc:
        assert "future" in str(exc)
    else:
        raise AssertionError("Unknown manifest schema should fail closed.")


def test_run_manifest_records_exact_consumed_manual_adjustment(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB",
        str(tmp_path / "adjustments.sqlite3"),
    )
    patient = tmp_path / "patient.fsa"
    patient.write_bytes(b"patient-trace")
    save_ladder_adjustment_record(patient, {"schema_version": "v2"})
    adjustment_hash = str(
        load_ladder_adjustment_record(patient)["payload_sha256"]
    )
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    recorder = BatchRunManifest.create(
        output_dir=output_dir,
        jobs=[
            {
                "name": "patient",
                "type": "pipeline",
                "path": tmp_path,
                "files": [patient],
            }
        ],
        analysis="clonality",
        settings={},
        execution={},
    )

    recorder.finalize(
        result={
            "completed_jobs": ["patient"],
            "failed_jobs": [],
            "dit_report_entries": [
                {
                    "original_file_path": str(patient),
                    "analysis_provenance": {
                        "manual_adjustment_consumed": True,
                        "manual_adjustment_sha256": adjustment_hash,
                    },
                }
            ],
            "qc_report_entries": [],
        },
        aggregate_output_dir=output_dir,
        review_gate={},
    )

    file_record = load_run_manifest(recorder.path)["jobs"][0]["files"][0]
    assert file_record["manual_adjustment"]["consumed"] is True
    assert (
        file_record["manual_adjustment"]["consumed_sha256"]
        == adjustment_hash
    )
