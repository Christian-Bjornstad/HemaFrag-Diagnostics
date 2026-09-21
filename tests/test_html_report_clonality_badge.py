"""Regression coverage for retired clonality ML content in HTML reports."""
from __future__ import annotations

from types import SimpleNamespace

import core.html_reports._legacy as html_reports


def test_historical_ml_fields_are_not_rendered_in_new_report(tmp_path, monkeypatch):
    monkeypatch.setattr(
        html_reports,
        "_build_report_plot_fragment",
        lambda *_args, **_kwargs: "<div id='active-peak-editor'>peak editor</div>",
    )
    monkeypatch.setattr(
        html_reports,
        "_resolve_report_display_name",
        lambda _entries: "Klonalitet",
    )
    entry = {
        "fsa": SimpleNamespace(file_name="26OUM00005_FR1_A01.fsa"),
        "file_name": "26OUM00005_FR1_A01.fsa",
        "dit": "26OUM00005",
        "assay": "FR1",
        "primary_peak_channel": "DATA1",
        "ladder": "LIZ500",
        "bp_min": 100,
        "bp_max": 400,
        "ladder_qc_status": "ok",
        "ladder_r2": 0.9999,
        "ClonalitySuggestion": "polyklonal",
        "ClonalityMLSuggestion": "external-ml-monoclonal",
        "ClonalityMLConfidence": 0.97,
        "ClonalityMLChannelResults": [
            {
                "channel": "DATA1",
                "target_name": "historical-channel-target",
                "label": "external-channel-prediction",
                "confidence": 0.96,
            }
        ],
    }

    html_reports.build_dit_html_reports([entry], tmp_path)
    html = (tmp_path / "26OUM00005_Klonalitet_Resultater.html").read_text(
        encoding="utf-8"
    )

    assert "external-ml-monoclonal" not in html
    assert "historical-channel-target" not in html
    assert "external-channel-prediction" not in html
    assert "clonality-ml-badge" not in html
    assert "clonality-channel-ml" not in html
    assert "Skjul for patolog" not in html
    assert "Gjenopprett" not in html
    assert "ClonalityDecisionLog" not in html
    assert "clonality-decisions" not in html

    assert "26OUM00005_FR1_A01.fsa" in html
    assert "active-peak-editor" in html
    assert 'id="peak-data"' in html
    assert 'id="plot-state"' in html
    assert "PeakManager.downloadUpdatedHtml()" in html
    assert "Save Peaks" in html
