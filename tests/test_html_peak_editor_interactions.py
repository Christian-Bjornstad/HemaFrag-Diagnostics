from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.plotting_plotly._legacy import TRACE_MARKER_RUNTIME_JS


@pytest.mark.parametrize("saved_payload, expected_ids", [
    ({}, ["detected"]),
    ({"plot": {}}, ["detected"]),
    ({"plot": {"peaks": []}}, []),
    ({"plot": []}, []),
    ({"plot": {"peaks": [{"peak_id": "saved"}]}}, ["saved"]),
    ({"plot": [{"peak_id": "legacy"}]}, ["legacy"]),
])
@pytest.mark.parametrize("legacy_manager", [False, True])
def test_peak_restore_preserves_saved_empty_selection(saved_payload, expected_ids, legacy_manager):
    report_source = Path("core/html_reports/_legacy.py").read_text(encoding="utf-8")
    manager_start = report_source.index("window.PeakManager = {")
    manager_end = report_source.index("\n};", manager_start) + len("\n};")
    editor_source = Path("core/plotting_plotly/_legacy.py").read_text(encoding="utf-8")
    restore_start = editor_source.index("    var peaks = [];")
    restore_end = editor_source.index("    peaks = peaks.map(", restore_start)
    restore = editor_source[restore_start:restore_end].replace("{{", "{").replace("}}", "}")
    script = (
        "global.window = {};\n"
        "const divId = 'plot';\n"
        "const initialPeaks = [{peak_id: 'detected'}];\n"
        f"const saved = {json.dumps(saved_payload)};\n"
        "global.document = {getElementById: () => ({textContent: JSON.stringify(saved)})};\n"
        + report_source[manager_start:manager_end] + "\n"
        + ("delete window.PeakManager.hasInitialPeakDataForPlot;\n" if legacy_manager else "")
        + restore
        + "console.log(JSON.stringify(peaks.map(p => p.peak_id)));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == expected_ids


def test_html_peak_delete_is_immediate_when_close_and_silent_when_far():
    script = f"""
global.window = {{
  confirm: function() {{ throw new Error('confirmation dialog opened'); }},
  alert: function() {{ throw new Error('alert dialog opened'); }}
}};
eval({json.dumps(TRACE_MARKER_RUNTIME_JS)});
const marker = {{marker_id: 'peak-a', x: 100.0}};
console.log(JSON.stringify([
  window.HemaFragTraceMarkers.confirmDelete(marker, 0.2, 0.4),
  window.HemaFragTraceMarkers.confirmDelete(marker, 0.8, 0.4)
]));
"""

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [True, False]


def test_wt_selection_keeps_latest_peak_per_channel_on_restore_and_click():
    source = Path("core/plotting_plotly/_legacy.py").read_text(encoding="utf-8")
    start = source.index("    function cloneSelection(")
    end = source.index("    var peaks = [];", start)
    selection_functions = source[start:end].replace("{{", "{").replace("}}", "}")
    start = source.index('        table.addEventListener("change",')
    end = source.index('        table.addEventListener("click",', start)
    change_handler = source[start:end].replace("{{", "{").replace("}}", "}")
    script = """
const peaks = [
  {peak_id:'blue-old',source_channel:'DATA1',active:true},
  {peak_id:'green',source_channel:'DATA2',active:true},
  {peak_id:'blue-new',source_channel:'DATA1',active:true}
];
function findPeakById(id) {return peaks.find(p => p.peak_id === id);}
function renderFlt3CandidateTable() {}
function redrawPeaks() {}
let onChange;
const table = {addEventListener: (event, callback) => {onChange = callback;}};
""" + selection_functions + """
let manualSelection = cloneSelection({wt_peak_ids:['blue-old','green','blue-new']});
const restored = manualSelection.wt_peak_ids.slice();
""" + change_handler + """
onChange({target:{type:'checkbox',checked:true,dataset:{role:'wt',peakId:'blue-old'}}});
const changed = manualSelection.wt_peak_ids.slice();
onChange({target:{type:'checkbox',checked:false,dataset:{role:'wt',peakId:'blue-old'}}});
const unresolved = cloneSelection({wt_peak_ids:['missing']}).wt_peak_ids;
console.log(JSON.stringify([restored,changed,manualSelection.wt_peak_ids,unresolved]));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [["green", "blue-new"], ["green", "blue-old"], ["green"], ["missing"]]


def test_flt3_distance_uses_only_explicit_peaks_and_concise_units():
    from pathlib import Path

    source = Path("core/plotting_plotly/_legacy.py").read_text(encoding="utf-8")
    start = source.index("    function bpDistanceText(")
    end = source.index("    function updateRatioCards(", start)
    functions = source[start:end].replace("{{", "{").replace("}}", "}")
    script = functions + """
const peaks = [
  {peak_id: 'wt', source_channel: 'DATA1', x: 330, active: true},
  {peak_id: 'mut', source_channel: 'DATA1', x: 339, active: true}
];
const manualSelection = {wt_peak_ids: [], mutant_peak_ids: ['mut']};
const assayName = 'FLT3-ITD';
const manualTraceChannels = ['DATA1'];
function channelLabel(ch) { return ch; }
function peakAreaForSourceChannel(p) { return 100; }
function peakIdFor(p) { return p.peak_id; }
function findPeakById(id) { return peaks.find(p => p.peak_id === id); }
function inferredWtByChannel() { return {DATA1: peaks[0]}; }
const unselected = selectionSummary().distanceText;
manualSelection.wt_peak_ids = ['wt'];
const selected = selectionSummary().distanceText;
peaks[1].x = 338;
const nonCodon = selectionSummary().distanceText;
peaks[0].active = false;
const removedWt = selectionSummary().distanceText;
console.log(JSON.stringify([unselected, selected, nonCodon, removedWt]));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(result.stdout) == ["—", "DATA1: +9.0 bp (3 kodoner)", "DATA1: +8.0 bp", "—"]
