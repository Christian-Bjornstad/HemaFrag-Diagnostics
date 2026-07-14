# Plan: FLT3/NPM1 plot polish (Phase 15)

Branch: `improvement/flt3-npm1-ref-zoom-baseline-2026-07-14`
(off `feat/ml-learning-tab-2026-07-12`)

Date: 2026-07-14 (Lab session pick-up after 5996b1b)

## Context

The FLT3 Plotly panel (`core/plotting_plotly/_legacy.py::build_interactive_peak_plot_for_entry`)
shows the assay trace and the reference-area rectangles, but three things fight the chemist's
mental model when looking at NPM1 in particular:

1. **X-axis is 50-1000 bp** (`bp_min`/`bp_max` from `core/analyses/flt3/config.py`).
   NPM1 wild-type peak sits at 299-301 bp, mutant at 303-305 bp. The 1000 bp range
   loses the relevant hybridisation entirely — the chemist asks to zoom to
   **290-330 bp** to match GeneMapper's NPM1 view.

2. **`_peak_area_half_width_bp(assay='NPM1', label, center_bp)` falls through to `5.0`** (the
   `else` branch at line 395). FLT3-ITD WT uses 2.0 bp, FLT3-D835 WT uses 1.2 bp.
   NPM1's WT/MUT ranges are 2 bp wide, so a 5.0 bp window is **2.5× wider than the whole
   reference range**. The local sideband baseline
   (`_calculate_peak_area_local_baseline`) then samples control levels ~6.25 bp outside the
   peak — picking up the off-centroid asymmetry of the surrounding trace. Result: the
   calculated NPM1 area feels inflated/wrong vs. GeneMapper's reference area.

3. **No visual of "what was integrated"** when a peak is selected. The Plotly figures
   already have click handlers that push peaks into the `peaks[]` list and re-render
   with bigger markers (`redrawPeaks`, lines 1295-1372), but only the *marker* changes
   — the chemist can't see the **integration window** (peak ± half-width) or the **baseline
   line** used to subtract the background.

## Goals

1. Lock the NPM1 plot x-range at **290-330 bp** so the WT (299-301) and MUT (303-305)
   rectangles plus a small sideband margin are all visible.
2. Make `_peak_area_half_width_bp` for NPM1 mirror what GeneMapper uses (1.0 bp for
   both WT and MUT, fall-through otherwise) and let `_calculate_peak_area_local_baseline`
   follow that window so the baseline samples a real sideband.
3. When a click selects a peak in an FLT3 assay (any of FLT3-ITD / FLT3-D835 / NPM1),
   draw a translucent **integration rectangle** over the peak window and a dashed
   **baseline line** under it — visible on the plot for as long as the peak is selected.

## Files touched

- `core/analyses/flt3/config.py` — add `bp_min` and `bp_max` for NPM1 plot window
  (chemists: explicit asssertion that the *plot* x-range rides on a plot-only key, not
  the existing `bp_min`/`bp_max` which are detector ranges; check with chemist).
- `core/analyses/flt3/pipeline/_legacy.py` — `_peak_area_half_width_bp` gains an NPM1
  branch (1.0 bp); `_calculate_peak_area_local_baseline` gains a `min_sideband_floor_bp`
  so the local-baseline denominator does not collapse when half_width is small.
- `core/plotting_plotly/_legacy.py` — when an FLT3 peak is added/selected by the click
  handler, push a `type='rect'` shape onto the Plotly `shapes` array (with `xref='x'`,
  `yref='y'`, `fillcolor` translucently matching the active channel accent) covering
  `[peak.x - half_width, peak.x + half_width]` and a `type='line'` baseline across the
  bottom of that window at the local-baseline y value. Both clear when the peak is removed.
- `core/analyses/flt3/pipeline/_legacy.py` — surface the local-baseline height to JS so
  the baseline line can be drawn at the right RFU. New helper
  `_local_baseline_rfu_at_bp(trace, time_all, bp_all, center_bp, half_width_bp) -> float`
  returning the linspace interpolation at `center_bp` (same math as line 884 of
  `_calculate_peak_area_local_baseline`).
- `core/plotting_plotly/_legacy.py` — pass `local_baseline_rfu` per channel to the JS
  bootstrap alongside `areaWindowBp` / `expectedMutBp` / `expectedWtBp` (already in
  scope there from lines 725-738's `peakHalfWidthBp`). JS side keeps a
  `selectedPeakAreaShape` and a `selectedPeakBaselineShape` reference and rebuilds them
  via `Plotly.relayout` inside `redrawPeaks`.

## Implementation outline (atomic commits)

1. **Atomic 1 — NPM1 zoom window.**
   - `config.py`: add `PLOT_BP_WINDOWS = {"NPM1": (290.0, 330.0)}` (chemist-confirmed value).
   - `_prepare_plot_data(…)` in `_legacy.py`: when `assay_name in PLOT_BP_WINDOWS`,
     force `data["forced_xmin"]` / `data["forced_xmax"]` accordingly so
     `build_interactive_peak_plot_for_entry` keeps using its existing
     `forced_xmin`/`forced_xmax` plumbing at lines 524-528 instead of `bp_min`/`bp_max`.
   - Pure-Python helper test in `tests/test_flt3_npm1_zoom.py` asserting
     `prepare_plot_data` returns the chemistry-confirmed window for `assay_name="NPM1"`
     on a representative entry.
2. **Atomic 2 — NPM1 half-width + sideband fix.**
   - `_peak_area_half_width_bp`: add `if assay == "NPM1": return 1.0` ahead of the `5.0`
     fallback. Same for WT-of-FLT3-ITD-style symmetric labels.
   - `_calculate_peak_area_local_baseline`: ensure `sideband_width = max(half_width_bp * 1.25, 1.5)`
     (was just `half_width_bp * 1.25`, no floor)— without a floor, half_width=1.0
     gives sideband_width=1.25 bp which can sit inside the peak window; floor it.
   - Tests in `tests/test_flt3_npm1_half_width.py` covering: (a) `_peak_area_half_width_bp("NPM1", "WT", 300)`
     returns 1.0, (b) `_calculate_peak_area_local_baseline` on a synthetic 300 bp peak
     does not blow out the sideband past 2.5 bp, (c) the area on the synthetic peak
     with sideband noise floor 50 RFU is within ±5% of the analytic Gaussian integral
     (sanity check, not regression on GeneMapper).
3. **Atomic 3 — Selected-peak area shading on click.**
   - Python: `_local_baseline_rfu_at_bp` helper in `_legacy.py:pip` returns the local
     baseline y at a peak's center_bp (the linspace-interpolation used in
     `_calculate_peak_area_local_baseline`). Pass these as a per-channel dict
     `{"DATA1": 23.4, "DATA2": 19.0, "DATA3": 27.1}` for the JS boot payload when
     peaks are present.
   - Inside `redrawPeaks()` (and the second occurrence at line 1922 for SL), for each
     active peak compute its half-width (mirror `peakHalfWidthBp` JS code), build
     a `shapes` entry `{{type: "rect", x0: x-hw, x1: x+hw, y0: 0, y1: ymax,
     xref: "x", yref: "y", fillcolor: <rgba accent 0.18>, line: {{width: 1, color: accent}}, layer: "above"}}`
     plus a baseline line `{{type: "line", x0: x-hw, x1: x+hw, y0: baseline_rfu, y1: baseline_rfu,
     xref: "x", yref: "y", line: {{width: 1.5, color: accent, dash: "dash"}}, layer: "above"}}`.
     Both feed into `Plotly.relayout(g, {{ shapes: baseShapes.concat(selectedAreaShapes) ... }})`
     — same exact code path, two extra arrays concat'd.
   - Smoke-side ad-hoc verification script (no pytest cover for browser-rendered Plotly):
     generate a one-entry FLT3-NPM1 HTML report, byte-grep `selectedAreaShapes`,
   `baseline_rfu`, `peakHalfWidthBp` to confirm the JS bootstrap has the relevant symbols.
   - Tests in `tests/test_flt3_local_baseline_rfu.py` covering the Python helper.

## Open clarifications (chemist input)

- **A.** Want the 290-330 bp x-limit hard, or do they want it soft (force inside, allow
  zoom out via Plotly autorange when the chemist double-clicks reset)?
  - Hint: probably hard — GeneMapper caps it.
- **B.** NPM1 half-width of `1.0` bp (Gaussian-tight, mirrors what GeneMapper shows)
  vs. wider `1.5`-2.0 bp that visually integrates the shoulders too.
  - Hint: 1.0 bp is the right call to start, but easy to widen if feedback is "still
    too narrow".
- **C.** Shading style: a translucent fill over the integration window (cleaner) or a
  hatched / outlined band (less clutter with other markers)?
  - Hint: translucent fill + dashed baseline wins for at-a-glance interpretability.
- **D.** Stick this in `ObsidianVault/Clonality_ML_Log/as_needed/_todo.md` (one-off
  FLT3 polish) or as a new section under Plan 14?

## Tests + verification before push

- Pure-Python: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_flt3_npm1_zoom.py
  tests/test_flt3_npm1_half_width.py tests/test_flt3_local_baseline_rfu.py -v`
- Suite sanity: `QT_QPA_PLATFORM=offscreen python -m pytest --tb=no -q`
  (target: 406 passed + new tests, 1 skipped, 0 regressions).
- Browser-side: open a generated FLT3-NPM1 report, click a peak, confirm
  (a) shaded rectangle appears over the integration window,
  (b) dashed line draws under it at the local-baseline RFU,
  (c) no console errors,
  (d) clicking off the peak clears the shading.

## Status doc pickup

Add a section to `ObsidianVault/Clonality_ML_Log/_todo.md` with the branch + each
atomic commit SHA on push. Standard cadence: helper + tests + wire + status doc on
the **same commit** (Plan 12 §15 rule).

## Risks / non-risks

- **Non-risk.** Atomics 1+2 are pure-Python and unit-test-pinned. Atomic 3 touches JS
  embedded in `r"""..."""` strings — the `html-report-js-css-editing.md` skill notes
  the lone trap is unreplaced `\\\\n` in escaped literals, which is **not** the area
  we're editing; we are appending new shape entries inside an existing `Plotly.relayout`
  call.
- **Risk.** Selecting more than ~3 peaks would clutter the plot with overlapping
  shading. Mitigation: cap to the most-recently-clicked peak + any pre-existing selected
  WT/MUT pair (typical manual-ratio flow has at most 3 selections anyway).
- **Risk.** FLT3 manual-ratio existing code path in lines 1380-1440 does not re-call
  `redrawPeaks()` for every state transition; new shading has to clear when `peaks[idx].active = !peaks[idx].active`
  toggles. Mitigation: use the same `Plotly.restyle` channel for marker states and
  `Plotly.relayout` for the shapes inside `redrawPeaks` — already the right pattern.
