from __future__ import annotations

import json
import subprocess

from core.plotting_plotly._legacy import TRACE_MARKER_RUNTIME_JS


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
