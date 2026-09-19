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
