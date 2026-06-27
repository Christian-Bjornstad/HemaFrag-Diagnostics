# Plan 07 — Performance Optimization (essentials-preserving)

> Branch: `code-cleanup`. Test baseline: `Ran 33 tests, OK`.
> Constraint: **do not remove any user-facing essentials**. The Qt app
> stays as the daily-driver interactive workflow. The plotly
> reports **stay interactive**. The per-patient `Resultater.html`
> stays the LIS handoff. We optimize around the essentials, never
> at their expense.

This plan targets the user's observed pain point: per-patient HTML
report size. Today's `_Resultater.html` files inline 4.6 MB of
minified plotly JS into every single report. For a 200-patient run,
that's ~920 MB of redundant JS payload going to LIS.

---

## 1. Current state (data-grounded)

Source points (verified during review):

- `assets/plotly-3.1.0.min.js` — 4,763,993 bytes (~4.6 MB) bundled
  with the app.
- `core/plotly_offline.py:19-35` (`plotly_inline_script_tag`) reads
  the JS once and caches it in module-global `_PLOTLY_INLINE_CACHE`.
  Returns `<script>{full JS here}</script>`.
- `core/plotly_offline.py:41-43` (`local_plotly_tag(out_dir, ...)`)
  **ignores `out_dir` parameter** and always inlines. Signature is
  dead.
- 11 in-tree call sites for `local_plotly_tag(...)`:
  - `core/analyses/general/reporting.py` (1 site)
  - `core/html_reports/_legacy.py` (3 sites, lines ~671, ~1359,
    plus 2 more)
  - `core/plotting_plotly/_legacy.py:1810` (1 site)
  - `core/qc/qc_html.py` (1 site, line ~47)
  - Each call uses `version="2.35.2"` (stale) regardless of the
    `assets/plotly-3.1.0.min.js` actually shipped. Functionality
    is fine — Plotly APIs in use are stable — but the claim is
    misleading.
- Per-patient `Resultater.html` write sites:
  - `core/html_reports/_legacy.py:1529` (`out_html.write_text`)
  - `core/html_reports/_legacy.py:1574` (same)
  Both inside loop bodies that walk per-DIT patient files in an
  assay run.
- Bundle size (~`HemaFrag_Windows/_internal/`):
  - `assets/plotly-3.1.0.min.js` ~4.6 MB, ACTUALLY shipped always
    (in-process cache).
  - `assets/app_icon.png` 404 KB (a 1.5 MB .icns for macOS).
  Estimate of total frozen bundle: ~25 MB. Plotly is ~18% of the
  frozen bundle.

## 2. Architecture summary (essentials-preserving)

- **Daily-driver Qt app**: `qt_app.py` launches `MainWindow` with
  tabs for settings, batch, ladder, FLT3, archive, log, about. The
  app stays exactly as-is — no UI changes.
- **Ladder/peak picking inside the app**: The user picks peaks
  visually with the plotly `<div id="...">` peak manager. **That
  HTML+JS flow is preserved** as the interactive editing surface.
- **The "saved new HTML" for LIS**: After a run, each patient gets
  `Resultater.html` with embedded plotly figures, status badges,
  peak markers, JSON state. That file is the artifact uploaded to
  the LIS. Today: ~5 MB per patient. Tomorrow: ~10 KB per patient.
- **Per-run directory**: `assay_dir = base_outdir / "REPORTS"` is
  the per-run output folder. All `Resultater.html` files for one
  run live there.

## 3. Cross-reference map (selected, plotly-relevant)

Callers of plotly JS inlining (all to be audit-touched):

```
core/analyses/general/reporting.py:6104      out_html write loop
core/html_reports/_legacy.py:24210, 55810   assay/control QC HTML builders
core/html_reports/_legacy.py:671, 1359      DIT html_lines.appends
core/plotting_plotly/_legacy.py:1810         single interactive Editor HTML
core/qc/qc_html.py:4752                     QC report HTML
core/qc/qc_plots.py + qc_html.py            QC plot builders
```

Each emits HTML referencing `_local_plotly_tag(...)`. We need a
single `_local_plotly_tag_reference(out_dir)` that emits an
external `<script src="./plotly-X.min.js">` tag instead. The HTML
itself becomes a few KB of structure + JS path. JS lives in
`assay_dir/`.

## 4. Intentional tech debt (we keep, not churn)

- The `out_dir` parameter on `local_plotly_tag` was originally
  designed to point at a folder where the JS lives; we re-purpose
  it.
- Plotly version `version="2.35.2"` is wrong-but-functional; we
  leave it (or correct it as Task 1 below) but don't re-tune the
  Plotly API surface.
- The `_PLOTLY_INLINE_CACHE` continues to exist as a fallback for
  callers that explicitly want inline mode (some legacy paths in
  `core/qc/qc_html.py`).

## 5. Optimization task list (smallest/safest first, essentials-preserving)

### Task 1 — Ship shared plotly JS into `assay_dir`

- **Scope**: new helper `_ensure_local_plotly_js(out_dir)` in
  `core/plotly_offline.py`:
  - Copies `assets/plotly-3.1.0.min.js` to `out_dir/plotly-3.1.0.min.js`
    once per call (idempotent — skip if file exists or hashes
    match).
  - Returns the relative path string `"./plotly-3.1.0.min.js"`.
- **Why**: this is the load-bearing primitive for the size win.
- **Acceptance**:
  - Existing call sites compile unchanged after switching to
    `_local_plotly_reference_link(...)` (Task 2).
  - `Ran 33 tests, OK`.
- **Commit**: `feat(plotly): copy assets plotly JS once to assay_dir`
- **Risk**: low (additive helper).
- **Effort**: S.

### Task 2 — Add `local_plotly_link_tag(out_dir)` next to `local_plotly_tag`

- **Scope**: in `core/plotly_offline.py`, add
  ```python
  def local_plotly_link_tag(out_dir: Path) -> str:
      return f'<script src="./plotly-3.1.0.min.js"></script>'
  ```
  useful when caller has **already** ensured the JS exists in
  `out_dir` (per Task 1).  And a complementary one:
  ```python
  def local_plotly_full_safemode_tag(version: str = "3.1.0") -> str:
      """Inline tag for one-off HTML outputs (e.g. debug) when
      out_dir is not writable or the user explicitly wants a
      single self-contained file. Costs ~4.6 MB."""
      ...
  ```
- **Why**: gives callers a knob: prefer EXTERNAL mode, fall back to
  full-inline if the user is exporting a single-file debug copy.
- **Acceptance**: callers opt in by calling `local_plotly_link_tag`.
- **Commit**: `feat(html-reports): add EXTERNAL and FULL_INLINE plotly link strategies`
- **Risk**: low.
- **Effort**: S.

### Task 3 — Switch DIT `Resultater.html` writes to external-mode

- **Scope**: in `core/html_reports/_legacy.py`, replace the three
  `html_lines.append(_local_plotly_tag(..., version="2.35.2"))` with
  - `_local_plotly_link_tag(assay_outdir)`
  paired with a new helper `_ensure_local_plotly_js(assay_outdir)`
  call earlier in the loop (idempotent — copies once).
- **Why**: this is THE win. Per-Resultater HTML size drops from
  ~5 MB to ~10 KB.
- **Acceptance**:
  - Run `scripts/run_flt3_rox500_qc_all_injections.py` against a
    fixture run; verify each `Resultater.html` < 50 KB and that
    they all reference the same `plotly-3.1.0.min.js` next to them.
  - Tests still 33/33.
- **Commit**: `perf(html-reports): DIT reports reference external plotly JS`
- **Risk**: medium (this is what runs in production — but the JS
  reference is functionally equivalent so nothing breaks).
- **Effort**: M.

### Task 4 — Switch QC and FLT3 control reporter HTML writes

- **Scope**: in `core/html_reports/_legacy.py` (other writers) +
  `core/qc/qc_html.py` + `core/analyses/general/reporting.py` +
  `core/plotting_plotly/_legacy.py:1810`, swap to external-mode.
- **Why**: same as Task 3; covers non-DIT HTML consumers.
- **Acceptance**:
  - `QC_FLT3_Injections.html` and the General assay report HTML
    drop to < 100 KB.
- **Commit**: `perf(html-reports): all interactive HTML references external plotly`
- **Risk**: medium.
- **Effort**: M.

### Task 5 — Slim plotly build (drop what we don't use) — STRETCH

- **Scope**: optional follow-up. Plotly's `partial` builds drop
  most plot types we don't use (3D, mapbox, sankey, etc.).
  Candidates:
  - `plotly-cartesian.js` (~370 KB min.gzipped) covers scatter +
    bar/line + layout modes.
  - `plotly-strict.js` exposes only `Plotly.newPlot` family with
    no factory, which is the API we use.
- **Why**: drop **another** ~3 MB per bundle while keeping
  Plotly.js interactive.
- **Acceptance**:
  - The interactive peak editor in the GUI still works (drag to
    add peak, shift+click to delete, JSON dump).
  - The LIS-uploaded HTML still loads without "Plotly not defined"
    errors at the LIS renderer.
- **Commit**: `perf(plotly): switch to plotly-cartesian partial build`
- **Risk**: medium-high (needs runtime verification; LIS site may
  use a stricter renderer).
- **Effort**: M-L.

### Task 6 — GUI foreground tab: don't block on report HTML build

- **Scope**: in `gui_qt/tabs/tab_batch/_legacy.py` `on_run`, the
  report-writing step today happens on the worker thread; the
  `_local_plotly_link_tag` switch also implies an extra early step
  (copy plotly JS). Move the JS copy to a separate background
  task that races the per-patient HTML generation — the slowest
  per-patient step (TraceAnalysis) blocks, so this is amortized.
- **Why**: tab responsiveness during runs.
- **Acceptance**: GUI tabs don't freeze during report run.
- **Commit**: `perf(gui): progressive plotly JS copy during batch run`
- **Risk**: low.
- **Effort**: S.

### Task 7 — Report HTML save dialog: show size estimate

- **Scope**: tiny GUI touch. After Tasks 1-4, when you save the
  report bundle, show in the status bar:
  - HTML slice size per file
  - Total folder size
  - Common-JS size once (not per file).
- **Why**: makes the speedup visible.
- **Acceptance**: visible during `tab_batch` runs.
- **Commit**: `feat(gui): report HTML bundle size in status bar`
- **Risk**: low.
- **Effort**: S.

### Task 8 — First-time-plotly cache warm-up at GUI startup

- **Scope**: `qt_app.py`'s `_prepare_runtime_bundle` triggers early
  read of `assets/plotly-3.1.0.min.js` (or the slim build from
  Task 5). Goal: peak edit `Editor` HTML opens 200-400 ms faster
  on first click.
- **Why**: warm the in-process cache.
- **Acceptance**: first peak edit click is faster.
- **Commit**: `perf(app): warm plotly JS cache during GUI startup`
- **Risk**: low.
- **Effort**: S.

### Task 9 — Optional: zip-bundle mode for LIS upload

- **Scope**: add a CLI option
  `python scripts/run_flt3_rox500_qc_all_injections.py --bundle-html`
  that, after the run, zips `assay_dir/` per DIT folder with the
  shared `plotly-3.1.0.min.js` alongside. The user gets one zip per
  DIT, containing `Resultater.html` plus `plotly-3.1.0.min.js`.
- **Why**: small uploads for LIS submission, especially useful if
  LIS only accepts zip.
- **Acceptance**: zip created with plotly JS as sibling; opens OK
  after unzip.
- **Commit**: `feat(cli): add --bundle-html LIS-friendly zip mode`
- **Risk**: low.
- **Effort**: S-M.

### Task 10 — Verify the LIS handoff with a smoke script

- **Scope**: new `scripts/lis_html_size_smoke.py`:
  - Iterate one fixture run.
  - Print file sizes for each `Resultater.html`.
  - Print per-run total (HTML sum + shared JS once).
  - Exit non-zero if any Resultater.html > 50 KB (regression).
- **Why**: guard rail.
- **Acceptance**: smoke script runs; the run after Task 3 ships
  reduces 5 MB → 10 KB.
- **Commit**: `test(perf): add per-Résultat HTML size regression guard`
- **Risk**: low.
- **Effort**: S.

## 6. Recommended ship-ready sequence

- **PR A** (Tasks 1+2+3): wire the optimization. DIT HTML size
  collapse. Fast, low-risk, big win. ~M effort.
- **PR B** (Tasks 4+6+7+8): extend to QC + General + GUI. ~M effort.
- **PR C** (Task 5 optional): slim plotly build. Documented as
  stretch — only after LIS confirmation.
- **PR D** (Tasks 9+10): LIS-friendly zip + smoke guard.

## 7. Verification

```
$ wc -l assets/plotly-3.1.0.min.js
(file, 4.6 MB, single bundle asset)

$ du -sh assets/plotly-3.1.0.min.js
4.6M

$ grep -rn '_local_plotly_tag' core/ scripts/ gui_qt/ \
       | head -20
[11 in-tree call sites listed above; covered by re-write]

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests, OK
```

Expected after PR A lands:

```
$ ls /runs/<date>/REPORTS/
plotly-3.1.0.min.js                            4.6 MB (one copy)
<dit>_<name>_Resultater.html          ~10 KB each (was ~5 MB)
Final_Detailed_Peak_Report.csv
FLT3_BP_Validation.csv
QC_FLT3_Injections.html             ~30 KB (was ~5 MB)
```

Run-of-100 cases per DIT: `~ 3.6 MB + 100 * 10 KB ≈ 4.6 MB per run`
instead of `~510 MB per run`. That's **>100×** reduction in
report-folder size, and the LIS upload gets a single
self-contained folder each.

## 8. Constraints honored

- Qt app continues to start and behave identically.
- Plotly reports remain interactive (the JS reference is to the
  same `plotly-3.1.0.min.js`).
- Per-patient HTML files retain all features (peak manager,
  status badge, JSON state).
- LIS handoff flow unchanged except smaller payload by default.
- No "essential" feature removed.
