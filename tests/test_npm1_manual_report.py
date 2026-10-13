
import json
import subprocess
from pathlib import Path

from test_npm1_manual_review import npm1_entry


def test_npm1_plot_shades_protocol_bands_below_trace_and_scales_full_window():
    from core.plotting_plotly._legacy import (
        _create_plotly_figure,
        _get_display_trace,
        _prepare_plot_data,
    )

    entry = npm1_entry()
    entry["fsa"].fsa["DATA3"][390] = 9000  # 290 bp, outside the expected bands.
    figure, ymax, _count = _create_plotly_figure(_prepare_plot_data(entry))
    bands = [shape for shape in figure.layout.shapes if shape.type == "rect"]
    assert [(shape.x0, shape.x1) for shape in bands] == [(300, 301), (304, 306)]
    assert all(shape.layer == "below" for shape in bands)
    assert all(shape.fillcolor == "rgba(250,204,21,0.24)" for shape in bands)
    assert ymax == _get_display_trace(entry, "DATA3", "NPM1")[390]
    assert figure.data[0].line.color == "#111827"


def test_npm1_summary_never_shows_stale_ratio_or_automatic_call():
    from core.html_reports._legacy import (
        _build_flt3_summary_table,
        _render_file_summary_table,
    )

    entry = npm1_entry()
    assert _build_flt3_summary_table(entry) == ""
    lines = []
    _render_file_summary_table([entry], lines)
    html = "\n".join(lines)
    assert "Manuell peakmarkering" in html
    assert "Ratio" not in html
    assert "20000" not in html
    assert "Positiv" not in html


def test_npm1_editor_starts_without_markers_or_ratio_controls():
    from core.plotting_plotly._legacy import build_interactive_peak_plot_for_entry

    entry = npm1_entry()
    html = build_interactive_peak_plot_for_entry(entry)
    assert 'var initialPeaks = [];' in html
    assert '"range":[280.0,320.0]' in html
    assert "Klikk" in html and "Shift" in html
    assert 'data-channel-choice=' not in html
    assert '<th>Peak Størrelse (bp)</th><th>Høyde (RFU)</th><th>Area</th>' in html
    assert '_flt3_ratio_cards" style=' not in html


def test_npm1_control_report_has_manual_status_and_no_ratio_table(tmp_path):
    from core.analyses.flt3.pipeline import _legacy as pipeline
    from core.html_reports._legacy import build_flt3_qc_html_report

    entry = npm1_entry()
    entry["group"] = "reactive_control"
    pipeline._calculate_ratios([entry])
    row = pipeline._build_control_qc_row(entry)
    path = build_flt3_qc_html_report([entry], [row], tmp_path)
    html = path.read_text(encoding="utf-8")
    assert "Manuell vurdering" in html
    assert "<th>Ratio</th>" not in html
    assert "<th>WT area</th>" not in html
    assert "<th>Bestatt</th>" not in html
    assert "window.PeakManager =" in html
    assert 'onclick="PeakManager.downloadUpdatedHtml()"' in html
    assert "Positiv NPM1" not in html
    assert '"range":[280.0,320.0]' in html


def test_npm1_saved_marker_payload_excludes_legacy_ratio_roles():
    source = Path("core/plotting_plotly/_legacy.py").read_text(encoding="utf-8")
    start = source.index("    function updatePeakManagerRegistration()")
    end = source.index("    function peakAreaForSourceChannel(", start)
    registration = source[start:end].replace("{{", "{").replace("}}", "}")
    script = """
const assayName = 'NPM1', divId = 'npm1';
const peaks = [{x:300.5,y:4000,area:20000,source_kind:'manual_exact'}, {x:305,y:1000,area:5000,source_kind:'manual_exact'}];
const manualSelection = {enabled:true,wt_peak_ids:['old-wt'],mutant_peak_ids:['old-mut']};
function ensurePeakIds() {}
global.window = {PeakManager:{plots:{},registerPlot:(id,plot)=>window.PeakManager.plots[id]=plot}};
""" + registration + "console.log(JSON.stringify(window.PeakManager.plots[divId].getPeakData()));"
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)
    assert list(payload) == ["peaks"]
    assert [peak["x"] for peak in payload["peaks"]] == [300.5, 305]
