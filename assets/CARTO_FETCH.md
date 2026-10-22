# Offline Plotly assets

HemaFrag embeds these local scripts into generated HTML reports:

| File | Actual upstream version | Use |
|---|---|---|
| `plotly-3.1.0.min.js` | 3.1.0 | Full runtime for reports that require it |
| `plotly-3.1.0-basic.min.js` | 3.6.0 | Smaller basic runtime used by patient reports |

The basic asset keeps its historical filename for compatibility. Its header
contains the actual upstream version. Both files retain upstream MIT notices.

To refresh the basic asset, deliberately change `PLOTLY_BASIC_VERSION` in
`../scripts/refresh_slim_plotly.py`, review upstream changes, then run from the
repository root:

```powershell
python scripts/refresh_slim_plotly.py
python -m pytest -q tests/test_html_report_size.py tests/test_html_peak_editor_interactions.py
```

The downloader uses a versioned URL and runs size/API checks with the same Python
interpreter. Inspect the asset header and verify an edited report after saving
and reopening before committing a vendor update. No asset download is needed
when running HemaFrag or opening a generated report.
