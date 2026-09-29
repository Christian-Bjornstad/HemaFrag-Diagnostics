"""Rust ladder rejections require review before aggregated DIT publication."""

from __future__ import annotations

import copy
import csv
from pathlib import Path
from unittest.mock import patch

from config import APP_SETTINGS
from core.batch import run_batch_jobs


def test_rejected_alternate_blocks_dit_even_with_shadow_mode(tmp_path, monkeypatch):
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "flt3")
    analyses = copy.deepcopy(APP_SETTINGS.get("analyses", {}))
    analyses.setdefault("flt3", {}).setdefault("batch", {})["ladder_review_gate"] = {
        "enabled": True,
        "mode": "shadow",
        "block_dit_reports": False,
    }
    monkeypatch.setitem(APP_SETTINGS, "analyses", analyses)

    selected_file = tmp_path / "26OUM00000_ITD_B05.fsa"
    rejected_file = tmp_path / "26OUM00000_ITD_A05.fsa"
    selected_file.write_bytes(b"selected")
    rejected_file.write_bytes(b"rejected")
    selected_entry = {
        "original_file_path": str(selected_file),
        "file_name": selected_file.name,
        "assay": "FLT3-ITD",
        "ladder": "GS500ROX",
        "ladder_qc_status": "ok",
        "dit": "26OUM00000",
        "_alternate_ladder_review_entries": [{
            "original_file_path": str(rejected_file),
            "file_name": rejected_file.name,
            "assay": "FLT3-ITD",
            "ladder": "GS500ROX",
            "ladder_qc_status": "review_required",
            "ladder_review_required": True,
            "ladder_review_reason_codes": ["rust_ladder_fit_rejected"],
        }],
    }
    jobs = [{
        "name": "26OUM00000",
        "type": "pipeline",
        "path": None,
        "files": [selected_file, rejected_file],
    }]

    with (
        patch("core.batch.run_pipeline_job_collect", return_value=[selected_entry]),
        patch("core.html_reports.build_dit_html_reports") as build_reports,
    ):
        result = run_batch_jobs(
            jobs=jobs,
            output_base=tmp_path / "output",
            out_folder_tmpl="ASSAY_REPORTS",
            outfile_html_tmpl="QC_REPORT_{name}.html",
            excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
            pipeline_scope="all",
            assay_filter="",
            aggregate_dit_reports=True,
            continue_on_error=False,
            aggregate_outdir_name="reports",
            max_workers=1,
            defer_tracking_workbook_refresh=True,
            defer_dit_html_reports=False,
        )

    assert result["dit_reports_blocked"] is True
    gate = result["ladder_review_gate"]
    assert gate["mode"] == "blocking"
    assert gate["block_reason"] == "rejected_ladder_requires_review"
    assert gate["rejected_ladder_case_count"] == 1
    with Path(gate["cases_path"]).open(encoding="utf-8", newline="") as handle:
        cases = list(csv.DictReader(handle))
    assert [case["full_path"] for case in cases] == [str(rejected_file)]
    build_reports.assert_not_called()


def test_review_gate_write_failure_stops_report_publication(tmp_path, monkeypatch):
    monkeypatch.setitem(APP_SETTINGS, "active_analysis", "flt3")
    analyses = copy.deepcopy(APP_SETTINGS.get("analyses", {}))
    analyses.setdefault("flt3", {}).setdefault("batch", {})["ladder_review_gate"] = {
        "enabled": True,
        "mode": "shadow",
        "block_dit_reports": False,
    }
    monkeypatch.setitem(APP_SETTINGS, "analyses", analyses)
    source = tmp_path / "26OUM00000_ITD_A05.fsa"
    source.write_bytes(b"sample")
    entry = {
        "original_file_path": str(source),
        "file_name": source.name,
        "assay": "FLT3-ITD",
        "ladder": "GS500ROX",
        "ladder_qc_status": "review_required",
        "ladder_review_required": True,
        "ladder_review_reason_codes": ["rust_ladder_fit_rejected"],
    }
    with (
        patch("core.batch.run_pipeline_job_collect", return_value=[entry]),
        patch(
            "core.analyses.clonality.ladder_review_gate.write_ladder_review_gate",
            side_effect=OSError("network denied"),
        ),
        patch("core.html_reports.build_dit_html_reports") as build_reports,
    ):
        result = run_batch_jobs(
            jobs=[{"name": "26OUM00000", "type": "pipeline", "path": None, "files": [source]}],
            output_base=tmp_path / "output",
            out_folder_tmpl="ASSAY_REPORTS",
            outfile_html_tmpl="QC_REPORT_{name}.html",
            excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
            pipeline_scope="all",
            assay_filter="",
            aggregate_dit_reports=True,
            continue_on_error=True,
            aggregate_outdir_name="reports",
            max_workers=1,
            defer_tracking_workbook_refresh=True,
            defer_dit_html_reports=False,
        )

    assert result["dit_reports_blocked"] is True
    assert "ladder review gate" in result["failed_jobs"]
    build_reports.assert_not_called()
