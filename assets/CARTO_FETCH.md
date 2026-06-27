# Slim plotly bundle refresh procedure

This directory ships two plotly bundles:

- `plotly-3.1.0.min.js`: legacy **full** plotly 3.1.0, ~4.6 MB.
  Kept for any HTML writer that needs 3D scenes, mapbox, finance,
  gl2d, mesh, etc.  Used by `core/plotly_offline.full_inline_script_tag`.
- `plotly-3.1.0-basic.min.js`: **slim** plotly-basic build (~1.1 MB).
  Used by `core/plotly_offline.plotly_inline_script_tag` and by all
  per-patient `Resultater.html` writers.

Why slim? Our HTML report uses only `Plotly.newPlot`, `Plotly.relayout`,
`Scatter` traces and `plotly_click` handlers (verified by `grep` across
`core/html_reports/_legacy.py`, `core/plotting_plotly/_legacy.py`,
`core/qc/qc_html.py`, `core/qc/qc_plots.py`, `core/analyses/general/reporting.py`).
The full bundle is overkill.

## Refreshing the slim bundle

Run:

```bash
python scripts/refresh_slim_plotly.py
```

That script downloads the canonical basic partial from unpkg and
runs the symbol assertions from `tests/test_html_report_size.py` —
the budget cap (1.5 MB) and the API coverage checks (`.newPlot`,
`.relayout`, `plotly_click`).

## Manual refresh

If `scripts/refresh_slim_plotly.py` is unavailable or unpkg is
blocked:

```bash
curl -sSL -o assets/plotly-3.1.0-basic.min.js \
     https://unpkg.com/plotly.js-basic-dist-min/plotly-basic.min.js
wc -c assets/plotly-3.1.0-basic.min.js
# expected: ~1.1 MB (1_115_927 bytes)
```

The slim build does NOT bundle `plotly_cartesian` partials separately
— vendor updates should bump to whatever `plotly.js-basic-dist-min`
shipped at that date.

## Pin behavior

The asset filename embeds **"plotly-3.1.0"** for documentation; the
content is whatever `.min.js` ships from unpkg at vendor-update time.
After any vendor bump:

1. Run `python scripts/refresh_slim_plotly.py` (or manual download).
2. Run the test suite; the API-coverage check in
   `tests/test_html_report_size.py` will fail loudly if a vendor
   update regressed the basic bundle.
3. Manually verify the slim bundle still serves `newPlot` /
   `relayout` by opening a fixture `Resultater.html` in a browser.
