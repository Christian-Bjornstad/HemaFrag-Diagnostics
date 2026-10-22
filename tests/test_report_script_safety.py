"""Report source names and saved annotations must remain data in HTML."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import subprocess
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


class _ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.ids = []
        self._script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "script":
            self._script = []

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None


def _entry(name="sample.fsa", assay="synthetic"):
    scans = np.arange(100)
    trace = np.full(100, 100.0)
    return {
        "fsa": SimpleNamespace(
            file_name=name, fsa={"DATA1": trace},
            sample_data_with_basepairs=pd.DataFrame({"time": scans, "basepairs": scans}),
        ),
        "assay": assay, "ladder": "ROX", "group": "sample", "analysis_type": "standard",
        "primary_peak_channel": "DATA1", "trace_channels": ["DATA1"],
        "bp_min": 1.0, "bp_max": 99.0, "peaks_by_channel": {"DATA1": pd.DataFrame()},
    }


@pytest.mark.parametrize("builder", ["patient", "qc", "batch"])
def test_plot_filenames_cannot_terminate_script_elements(builder):
    from core.plotting_plotly import _legacy as plots
    from core.qc.qc_plots import build_interactive_peak_plot_for_entry_qc
    from core.qc.qc_rules import QCRules

    entry = _entry('sample"</script><script>globalThis.injected = true</script>.fsa')
    if builder == "patient":
        fragment = plots.build_interactive_peak_plot_for_entry(entry)
    elif builder == "qc":
        fragment = build_interactive_peak_plot_for_entry_qc(entry, QCRules())
    else:
        fragment = plots.build_interactive_assay_batch_plot_html([entry], "Synthetic")
    parser = _ReportParser()
    parser.feed(fragment)
    # The batch builder also includes the trusted, bundled Plotly script.
    assert len(parser.scripts) == (2 if builder == "batch" else 1)
    executable = parser.scripts[-1]
    # Every generated editor script must compile, including its source metadata.
    subprocess.run(
        ["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'));"],
        input=executable, text=True, encoding="utf-8", check=True,
    )


def test_batch_editor_id_survives_apostrophe_in_source_name():
    from core.plotting_plotly._legacy import build_interactive_assay_batch_plot_html

    fragment = build_interactive_assay_batch_plot_html([_entry("O'Brien.fsa")], "Synthetic")
    parser = _ReportParser()
    parser.feed(fragment)
    div_id = re.search(r'var divId = "([^"]+)";', parser.scripts[-1]).group(1)
    assert div_id in parser.ids


def test_flt3_overview_ids_survive_apostrophe_in_source_name():
    from core.html_reports._legacy import _render_file_summary_table

    entry = _entry("O'Brien.fsa", "FLT3-ITD")
    lines = []
    _render_file_summary_table([entry], lines)
    parser = _ReportParser()
    parser.feed("\n".join(lines))
    assert "overview_ratio_O'Brien_fsa" in parser.ids


@pytest.mark.parametrize("marker_id", ["literal$&", "literal$`", "</script><script>injected()</script>"])
def test_saving_peaks_preserves_literal_json_without_replacement_expansion(marker_id):
    from core.html_reports._legacy import _build_peak_manager_script

    manager = _build_peak_manager_script().removeprefix("\n<script>").removesuffix("</script>\n")
    script = """
const nodes = {'peak-data':{textContent:'{}'}, 'plot-state':{textContent:'{}'}};
global.window = {};
global.document = {
  querySelectorAll: () => [], getElementById: id => nodes[id],
  title: 'synthetic', createElement: () => ({click: () => {}}),
  documentElement: {get outerHTML() {
    return '<html>' + Object.entries(nodes).map(([id, node]) =>
      '<script id="' + id + '" type="application/json">' + node.textContent + '</script>').join('') + '</html>';
  }}
};
let saved;
global.Blob = class {constructor(parts) {saved = parts.join('');}};
global.URL = {createObjectURL: () => 'blob:synthetic', revokeObjectURL: () => {}};
""" + manager + """
window.PeakManager.registerPlot('plot', {getPeaks: () => [{marker_id: MARKER_ID}]});
window.PeakManager.downloadUpdatedHtml();
console.log(saved);
""".replace("MARKER_ID", json.dumps(marker_id))
    completed = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True, encoding="utf-8")
    parser = _ReportParser()
    parser.feed(completed.stdout)
    assert json.loads(parser.scripts[0]) == {"plot": [{"marker_id": marker_id}]}


def test_saving_before_all_editors_mount_retains_unmounted_saved_peaks():
    from core.html_reports._legacy import _build_peak_manager_script

    manager = _build_peak_manager_script().removeprefix("\n<script>").removesuffix("</script>\n")
    saved = {"slow": {"peaks": [{"x": 123.5}]}, "ready": {"peaks": [{"x": 456.0}]}}
    script = (
        "global.window = {}; global.document = {getElementById: () => ({textContent: "
        + json.dumps(json.dumps(saved)) + "})};\n" + manager
        + "window.PeakManager.registerPlot('ready', {getPeakData: () => ({peaks: []})});\n"
        + "console.log(JSON.stringify(window.PeakManager.getAllPeakData()));"
    )
    completed = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(completed.stdout) == {"slow": saved["slow"], "ready": {"peaks": []}}


def test_saving_before_plots_mount_retains_saved_zoom_ranges():
    from core.html_reports._legacy import _build_plotly_reflow_script

    manager = _build_plotly_reflow_script().removeprefix("\n<script>").removesuffix("</script>\n")
    saved = {"slow": {"xaxis_range": [100, 200], "yaxis_range": [0, 500]}}
    script = (
        "global.window = {addEventListener: () => {}};\n"
        "global.document = {addEventListener: () => {}, getElementById: () => ({textContent: "
        + json.dumps(json.dumps(saved)) + "})};\n" + manager
        + "console.log(JSON.stringify(window.ReportPlotManager.getAllStates()));"
    )
    completed = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(completed.stdout) == saved


@pytest.mark.parametrize("assay,expected", [("SL", 20.0), ("synthetic", 5.0)])
def test_manual_area_window_is_initialized_after_assay_name(assay, expected):
    from core.plotting_plotly._legacy import build_interactive_peak_plot_for_entry

    fragment = build_interactive_peak_plot_for_entry(_entry(assay=assay))
    parser = _ReportParser()
    parser.feed(fragment)
    bootstrap = parser.scripts[0].split("  var initialPlotState =", 1)[0]
    script = (
        "global.window = {}; global.document = {getElementById: () => ({})};\n"
        + bootstrap
        + "console.log(areaWindowBp);})();"
    )
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout) == expected
