"""Tests for the Compare tab redesign: multi-file/patient selection,
group comparison report, and ladder-review handoff payload."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd


def _fake_entry(assay: str = "TCRgA", dit: str | None = "2026-1234", name: str = "sample.fsa") -> dict:
    fsa = SimpleNamespace(
        file_name=name,
        fsa={
            "DATA1": np.random.randint(100, 500, size=2000).astype(float),
            "DATA2": np.random.randint(100, 5000, size=2000).astype(float),
        },
    )
    return {
        "fsa": fsa,
        "file_name": name,
        "assay": assay,
        "group": "TCRg",
        "ladder": "ROX",
        "dit": dit,
        "primary_peak_channel": "DATA2",
        "trace_channels": ["DATA1", "DATA2"],
        "peaks_by_channel": {
            "DATA2": pd.DataFrame(
                {"basepairs": [320.0, 345.5], "peaks": [1200.0, 8400.0], "area": [24000.0, 180000.0]}
            )
        },
        "bp_min": 300.0,
        "bp_max": 450.0,
    }


def _review_entry(name: str = "bad_ladder.fsa") -> dict:
    e = _fake_entry(name=name)
    e["analysis_status"] = "ladder_review_only"
    e["ladder_review_required"] = True
    return e


class TestGroupComparisonReport:
    def test_empty_entries_raises(self) -> None:
        from core.html_reports.comparison import build_group_comparison_html_report

        try:
            build_group_comparison_html_report([], Path(tempfile.gettempdir()))
            assert False, "Expected ValueError for empty entries"
        except ValueError as ex:
            assert "No analysis entries" in str(ex)

    def test_multi_file_report_written(self) -> None:
        from core.html_reports import comparison as cmp_mod

        outdir = Path(tempfile.mkdtemp(prefix="hf_groupcmp_test_"))
        entries = [
            _fake_entry(name="26OUM00001_run1_A01.fsa"),
            _fake_entry(dit="2026-1235", name="26OUM00001_run2_B02.fsa"),
            _fake_entry(assay="FR1", dit="2026-1236", name="26OUM00001_FR1_C03.fsa"),
        ]

        with patch.object(cmp_mod, "_build_report_plot_fragment", return_value="<div class='mock-plot'>p</div>"), \
             patch.object(cmp_mod, "compute_group_ymax_for_entries", return_value=9000.0):
            html_path = cmp_mod.build_group_comparison_html_report(entries, outdir)

        assert html_path.exists()
        text = html_path.read_text(encoding="utf-8")
        assert "3 filer" in text
        # Assay sections in first-seen order
        assert "TCRgA (2 filer)" in text
        assert "FR1 (1 filer)" in text
        for name in ("run1_A01.fsa", "run2_B02.fsa", "FR1_C03.fsa"):
            assert name in text
        assert "</html>" in text

    def test_shared_ymax_within_assay_section(self) -> None:
        """compute_group_ymax_for_entries must be called once per assay group."""
        from core.html_reports import comparison as cmp_mod

        outdir = Path(tempfile.mkdtemp(prefix="hf_groupcmp_ymax_"))
        calls: list[list[str]] = []

        def fake_ymax(entries):
            calls.append([e["file_name"] for e in entries])
            return 8000.0

        entries = [
            _fake_entry(name="a.fsa"),
            _fake_entry(name="b.fsa"),
            _fake_entry(assay="FR1", name="c.fsa"),
        ]
        with patch.object(cmp_mod, "_build_report_plot_fragment", return_value="x"), \
             patch.object(cmp_mod, "compute_group_ymax_for_entries", side_effect=fake_ymax):
            cmp_mod.build_group_comparison_html_report(entries, outdir)

        assert len(calls) == 2
        assert sorted(calls[0]) == ["a.fsa", "b.fsa"]
        assert calls[1] == ["c.fsa"]


class TestReviewPayload:
    def test_build_review_payload_writes_bundle(self) -> None:
        from gui_qt.tabs.tab_compare_worker import CompareWorker

        outdir = Path(tempfile.mkdtemp(prefix="hf_cmp_payload_"))
        worker = CompareWorker.__new__(CompareWorker)  # no Qt init needed
        worker._outdir = outdir

        entry = _review_entry("Positiv_kontroll_bad.fsa")
        payload = worker._build_review_payload([entry])

        assert payload is not None
        assert payload["count"] == 1
        assert "Positiv_kontroll_bad.fsa" in payload["file_names"]
        bundle = Path(payload["bundle_dir"])
        assert (bundle / "ladder_review_cases.csv").exists()
        csv_text = (bundle / "ladder_review_cases.csv").read_text(encoding="utf-8")
        assert "Positiv_kontroll_bad.fsa" in csv_text


class TestPatientGrouping:
    def test_group_files_by_patient_used_for_tree(self) -> None:
        """The tab groups via core.batch.group_files_by_patient (batch parity)."""
        from core.batch import group_files_by_patient

        tmp = Path(tempfile.mkdtemp(prefix="hf_cmp_patients_"))
        files = []
        for stem in (
            "26OUM00001_A01", "26OUM00001_B02", "26OUM00007_A05",
            "Positiv_kontroll_P1", "Negativ_kontroll_N1",
        ):
            p = tmp / f"{stem}.fsa"
            p.write_bytes(b"")
            files.append(p)

        grouped = group_files_by_patient(files, r"\d{2}OUM\d{5}")
        assert len(grouped["26OUM00001"]) == 2
        assert len(grouped["26OUM00007"]) == 1
        assert {f.name for f in grouped["QC"]} == {
            "Positiv_kontroll_P1.fsa", "Negativ_kontroll_N1.fsa"
        }


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
