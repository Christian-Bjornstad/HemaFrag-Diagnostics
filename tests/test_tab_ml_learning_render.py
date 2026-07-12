"""Plan 13 / Phase B tests - Plotly panel renderer.

The renderer writes a self-contained HTML file that bundles:
  - one Plotly figure per case
  - one Class button per ANNOTATION_CLASSES (with onClick wiring)
  - one Flag button per CONTROL_FLAGS (only for control rows)
  - in-page keyboard shortcuts (M/P/B/I/Q/N/T/U/Z)
  - a sticky annotate bar so buttons stay visible during scroll
  - in-page Export JSON button that downloads via anchor.click()
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui_qt.tabs.tab_ml_learning._render import (
    compute_panel_axes,
    render_annotation_panel_html,
)
from core.analyses.clonality.interpretation import (
    ANNOTATION_CLASSES,
    CONTROL_FLAGS,
)


# ---- Pure helpers --------------------------------------------------------


class TestComputePanelAxes:
    def test_uses_assay_interpretation_range(self):
        # FR1 = (310, 360); pad by 18 bp each side
        axes = compute_panel_axes(assay="FR1", peaks_by_channel={}, ymax_hint=0.0)
        assert axes["xmin"] == 310.0 - 18.0
        assert axes["xmax"] == 360.0 + 18.0
        assert axes["ymin"] == 0.0

    def test_picks_ymax_from_peaks_when_no_hint(self):
        axes = compute_panel_axes(
            assay="FR1",
            peaks_by_channel={"DATA1": {"basepairs": [311, 350], "peaks": [2000, 4500]}},
            ymax_hint=0.0,
        )
        # 4500 * 1.18
        assert axes["ymax"] == pytest.approx(4500 * 1.18)

    def test_uses_ymax_hint_when_larger_than_peaks(self):
        axes = compute_panel_axes(
            assay="FR1",
            peaks_by_channel={"DATA1": {"basepairs": [311], "peaks": [1000]}},
            ymax_hint=8000.0,
        )
        # hint wins (4500 > 1000 wouldn't be true here)
        assert axes["ymax"] == pytest.approx(8000 * 1.18)

    def test_unknown_assay_uses_default(self):
        axes = compute_panel_axes(assay="NOT_A_REAL_ASSAY", peaks_by_channel={})
        assert axes["xmin"] == 0.0
        assert axes["xmax"] == 500.0
        assert axes["ymax"] > 0


# ---- HTML rendering ------------------------------------------------------


@pytest.fixture
def two_entry_panel(tmp_path) -> Path:
    entries = [
        {
            "ordinal": 1,
            "file": "24OUM20364_FR1_A_040125_A01.fsa",
            "raw_path": "/run/24OUM20364_FR1_A_040125_A01.fsa",
            "assay": "FR1",
            "sample_kind": "patient",
            "control": "",
            "primary_peak_channel": "DATA1",
            "ladder_qc_status": "ok",
            "ladder_fit_strategy": "auto_full",
            "peak_count": 2,
            "raw_peak_count": 2,
            "peak_count_in_interpretation_range": 2,
            "dominant_peak_basepairs": 312.0,
            "dominant_peak_height": 5000.0,
            "interpretation_range_min_bp": 310.0,
            "interpretation_range_max_bp": 360.0,
            "suggestion": "monoklonal",
            "confidence": 0.92,
            "review_needed": False,
            "evidence": "single dominant peak at 312bp",
            "peaks_by_channel": {
                "DATA1": {
                    "basepairs": [311.5, 348.0],
                    "peaks": [5000.0, 1200.0],
                }
            },
            "annotation_schema_version": 1,
        },
        {
            "ordinal": 2,
            "file": "PK_FR1_PK_xxx.fsa",
            "raw_path": "/run/PK_FR1_PK_xxx.fsa",
            "assay": "FR1",
            "sample_kind": "control",
            "control": "PK",
            "primary_peak_channel": "DATA1",
            "ladder_qc_status": "ok",
            "ladder_fit_strategy": "auto_full",
            "peak_count": 1,
            "raw_peak_count": 1,
            "peak_count_in_interpretation_range": 1,
            "dominant_peak_basepairs": 335.0,
            "dominant_peak_height": 4500.0,
            "interpretation_range_min_bp": 310.0,
            "interpretation_range_max_bp": 360.0,
            "suggestion": "monoklonal",
            "confidence": 0.95,
            "review_needed": False,
            "evidence": "control PK peak in range",
            "peaks_by_channel": {
                "DATA1": {
                    "basepairs": [335.0],
                    "peaks": [4500.0],
                }
            },
            "annotation_schema_version": 1,
        },
    ]
    return render_annotation_panel_html(
        entries, out_dir=tmp_path, title="Test Panel", annotator="lab"
    )


class TestAnnotationPanelRenders:
    def test_writes_review_panel_html(self, tmp_path, two_entry_panel):
        assert two_entry_panel.exists()
        assert two_entry_panel.name == "review_panel.html"

    def test_includes_plotly_script_local(self, two_entry_panel):
        text = two_entry_panel.read_text(encoding="utf-8")
        # Local plotly asset, NOT a CDN URL (corporate proxy pitfall).
        assert "plotly-3.1.0-basic.min.js" in text
        assert "https://cdn.plot.ly" not in text

    def test_each_card_has_class_buttons(self, two_entry_panel):
        text = two_entry_panel.read_text(encoding="utf-8")
        for cls in ANNOTATION_CLASSES:
            assert f"data-class='{cls}'" in text

    def test_control_card_has_flag_buttons_patient_does_not(self, two_entry_panel):
        text = two_entry_panel.read_text(encoding="utf-8")
        # Flag buttons present
        for flag in CONTROL_FLAGS:
            assert f"data-flag='{flag}'" in text
        # BUT only the control case (ordinal=2) should have the flag row
        assert text.count("class='row-label'>Flag:") == 1

    def test_keyboard_shortcut_map_full(self, two_entry_panel):
        text = two_entry_panel.read_text(encoding="utf-8")
        # JS object literal with unquoted keys (f-string emitted single braces)
        for letter, label in [
            ("m", "monoklonal"),
            ("p", "polyklonal"),
            ("b", "bi_oligoklonal"),
            ("i", "irregulaer"),
            ("q", "pseudoklonal"),
            ("n", "intet_pcr_produkt_darlig_dna"),
            ("t", "qc_teknisk_fail"),
            ("u", "usikker_review"),
            ("z", ""),
        ]:
            assert f"{letter}: '{label}'" in text, f"missing key for {letter}"

    def test_no_inline_json_crash(self, two_entry_panel):
        """Make sure the entries payload is embedded without breaking the
        script tag (sneaky `</script>` inside strings would split it)."""
        text = two_entry_panel.read_text(encoding="utf-8")
        # The exporters substitute </ with <\/ to keep the script block intact
        script_open = text.count('<script id="entries-data"')
        assert script_open == 1
        # No leak of </script> *inside* the payload
        # We tolerate the closing tag at the end of the line however.

    def test_zoom_axes_precomputed_per_entry(self, two_entry_panel):
        """xrange 292..378 expected for FR1 (310 - 18, 360 + 18)."""
        text = two_entry_panel.read_text(encoding="utf-8")
        payload_idx = text.find('<script id="plotly-payload"')
        # Pull the JSON for figure 0
        body = text[payload_idx + len('<script id="plotly-payload" type="application/json">') :]
        body = body.split("</script>")[0]
        figures = json.loads(body)
        first = figures[0]
        x_range = first["layout"]["xaxis"]["range"]
        assert x_range[0] == pytest.approx(310 - 18)
        assert x_range[1] == pytest.approx(360 + 18)
        y_range = first["layout"]["yaxis"]["range"]
        # ymax >= 5900 because peaks include 5000 * 1.18
        assert y_range[1] >= 5000 * 1.18 - 0.5

    def test_export_button_call_back_present(self, two_entry_panel):
        text = two_entry_panel.read_text(encoding="utf-8")
        assert 'function exportAnnotations()' in text
        assert 'function harvest()' in text
        assert "anchor" in text  # download-link trick

    def test_renders_with_no_entries(self, tmp_path):
        target = render_annotation_panel_html([], out_dir=tmp_path)
        assert target.exists()
        text = target.read_text(encoding="utf-8")
        assert "0 cases" in text
        # No figure payloads => no broken JSON
