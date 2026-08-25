"""Tests for the two-file comparison HTML report."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd


def _fake_entry(assay: str = "TCRgA", dit: str | None = "2026-1234", name: str = "sample.fsa") -> dict:
    """Minimal entry dict shaped like pipeline output, without real FSA decode."""
    fsa = SimpleNamespace(
        file_name=name,
        fsa={
            "DATA1": np.random.randint(100, 500, size=5000).astype(float),
            "DATA2": np.random.randint(100, 5000, size=5000).astype(float),
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
                {
                    "basepairs": [320.0, 345.5, 410.0],
                    "peaks": [1200.0, 8400.0, 900.0],
                    "area": [24000.0, 180000.0, 15000.0],
                }
            )
        },
        "bp_min": 300.0,
        "bp_max": 450.0,
    }


class TestComparisonReport:
    def test_mismatched_assay_raises(self) -> None:
        from core.html_reports.comparison import build_comparison_html_report

        a = _fake_entry(assay="TCRgA")
        b = _fake_entry(assay="TCRbA")

        try:
            build_comparison_html_report(a, b, Path(tempfile.gettempdir()))
            assert False, "Expected ValueError for mismatched assays"
        except ValueError as ex:
            assert "different assays" in str(ex)

    def test_report_written_with_both_files(self) -> None:
        from core.html_reports import comparison as cmp_mod

        outdir = Path(tempfile.mkdtemp(prefix="hf_compare_test_"))
        a = _fake_entry(name="run1_A01.fsa")
        b = _fake_entry(dit="2026-5678", name="run2_B02.fsa")

        # Avoid real plotly figure generation; assert the plumbing around it.
        captured_ymax: dict[str, float] = {}

        def fake_fragment(entry, metrics):
            return "<div class='mock-plot'>plot</div>"

        def fake_group_ymax(entries):
            return 9000.0

        with patch.object(cmp_mod, "_build_report_plot_fragment", side_effect=fake_fragment), \
             patch.object(cmp_mod, "compute_group_ymax_for_entries", side_effect=fake_group_ymax):
            html_path = cmp_mod.build_comparison_html_report(a, b, outdir)

        assert html_path.exists()
        text = html_path.read_text(encoding="utf-8")
        assert "run1_A01.fsa" in text
        assert "run2_B02.fsa" in text
        assert "Sammenligning" in text
        assert "peak-table-comparison" in text
        assert "8400" in text  # peak height from fake data
        assert "</html>" in text

    def test_peak_table_renders_all_peaks(self) -> None:
        from core.html_reports.comparison import _render_peak_table_for_comparison

        entry = _fake_entry()
        html = _render_peak_table_for_comparison(entry, "A")
        assert "345.5" in html
        assert "8400" in html
        assert "180000" in html

    def test_empty_peak_channel_handled(self) -> None:
        from core.html_reports.comparison import _render_peak_table_for_comparison

        entry = _fake_entry()
        entry["peaks_by_channel"]["DATA2"] = pd.DataFrame()
        html = _render_peak_table_for_comparison(entry, "A")
        assert "Ingen peaks" in html


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
