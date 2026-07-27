# Plan 07 — Performance Optimization (essentials-preserving, self-contained HTML)

> Branch: `code-cleanup`. Test baseline: `Ran 33 tests, OK`.
> Constraint (revised after user feedback 2026-06-27):
> **Each per-patient `Resultater.html` MUST remain a single self-contained
> file. The LIS upload is one HTML file per patient; sibling dependencies
> (a separate `plotly-3.1.0.min.js` next to it) are not acceptable. We do
> not externalize the JS — we shrink it instead, and remove the rest of
> the redundancy from inside one HTML.**

This plan targets the user's primary pain: per-patient HTML report
size. Today's `_Resultater.html` files inline 4.6 MB of minified
plotly JS into every single report. For a 200-patient run, that's
~920 MB of redundant JS payload going to LIS.

We keep the essentials:
- Qt app stays the daily-driver interactive workflow.
- Plotly HTML reports stay interactive.
- Per-patient `Resultater.html` files stay **ONE FILE EACH**, fully
  self-contained, no sibling dependencies.

## 1. Current state (data-grounded)

- `assets/plotly-3.1.0.min.js` — 4,763,993 bytes (~4.6 MB) bundled.
- `core/plotly_offline.py:19-35` (`plotly_inline_script_tag`) reads
  the JS once into `_PLOTLY_INLINE_CACHE`, emits inline `<script>`.
- 11 in-tree call sites for `local_plotly_tag(...)` (all use
  `version="2.35.2"` regardless of `assets/plotly-3.1.0.min.js`
  lying on disk).
- Production HTML trace inventory:
  - Trace types: **only `go.Scatter`** (verified by grep across
    `core/html_reports/_legacy.py`, `core/plotting_plotly/_legacy.py`,
    `core/qc/qc_html.py`, `core/qc/qc_plots.py`,
    `core/analyses/general/reporting.py`).
  - JS methods: **`Plotly.newPlot`, `Plotly.relayout`** (verified).
  - Event handlers: `plotly_click` + our own DOM click+resize.
  - No `make_subplots`, no `add_subplot`, no animations.
- Per-patient `Resultater.html` write sites:
  - `core/html_reports/_legacy.py:1529` (`out_html.write_text`).
  - `core/html_reports/_legacy.py:1574` (same).

## 2. Architecture summary

- The plotly **full** bundle (`plotly-3.1.0.min.js`) is overkill: it
  ships 3D, mapbox, sankey, finance, mesh, gl2d scenes, animation
  runtime, etc. — none of which is used.
- The plotly **basic** bundle (`plotly.js-basic-dist-min`) is a
  curated subset that includes `Scatter`, basic layout, click
  handlers, `newPlot`, `relayout`, `purge`, plots house-keeping.
  Download from unpkg: 1,115,881 bytes (~1.1 MB) — **75% smaller**.
- The plotly **cartesian** bundle is 1,420,800 bytes — covers all
  2D cartesian layouts including bar with some extras; not needed
  for our `Scatter`-only use case but available if needed.
- Verified at review time on the sandbox that the plotly-basic
  bundle exposes `Plotly.newPlot`, `Plotly.relayout`, `Plotly.react`,
  `Plotly.purge`, `Plotly.Plots`, and the `plotly_click` handler —
  all features we use. No 3D/glMatrix code.

## 3. Cross-reference map (selected, plotly-relevant)

Callers of plotly JS inlining that must be updated:

```
core/analyses/general/reporting.py:6104      out_html write loop
core/html_reports/_legacy.py:24210, 55810   assay/control QC HTML builders
core/html_reports/_legacy.py:671, 1359      DIT html_lines.appends
core/html_reports/_legacy.py:1529, 1574     per-patient write sites
core/plotting_plotly/_legacy.py:1810         single interactive Editor HTML
core/qc/qc_html.py:4752                     QC report HTML
```

After PR-A these all use the slim inlined `plotly-basic.min.js`.

## 4. Intentional tech debt (we keep, not churn)

- The `version="2.35.2"` parameter on `local_plotly_tag` is wrong-but-
  functional; it won't change unless we update the major API; we
  pin to the slim bundle and re-document.
- Some helpers in `core/qc/qc_html.py` may still need the full
  bundle if they use features outside basic. Task 7 below audits
  this before switching residue.

## 5. Optimization task list (smallest/safest first, essentials-preserving)

### Task 1 — Download `plotly-basic` slim build into assets

- **Scope**: new `assets/plotly-3.1.0-basic.min.js` downloaded from
  `https://unpkg.com/plotly.js-basic-dist-min/plotly-basic.min.js`
  (v3.1.0). 1.1 MB.
- **Why**: machine the slim build; this is the load-bearing
  primitive for the size win.
- **Acceptance**:
  - File exists at `assets/plotly-3.1.0-basic.min.js`. Size 1.1 MB.
  - Reproduction recipe recorded in `assets/CARTO_FETCH.md` for
    future vendor updates.
- **Commit**: `assets: add slim plotly-basic build (~1.1 MB)`
- **Risk**: low.
- **Effort**: S.

### Task 2 — Slim `plotly_inline_script_tag` to use the basic build

- **Scope**: in `core/plotly_offline.py`, rename the cache to
  `_PLOTLY_BASIC_JS_CACHE`, read `assets/plotly-3.1.0-basic.min.js`,
  emit `<script>{slim JS}</script>`. Old `plotly-3.1.0.min.js`
  stays on disk but is no longer the inline asset.
- **Why**: every `Resultater.html` gets the slim JS inline.
- **Acceptance**:
  - `plotly_inline_script_tag()` returns 1.1 MB string.
  - Stale `assets/plotly-3.1.0.min.js` removed (or moved to
    `assets/legacy/`).
  - Ran 33 tests, OK.
- **Commit**: `perf(plotly): switch inline script to plotly-basic slim build`
- **Risk**: medium (could break per-HTML features; covered by Task 7
  feature audit).
- **Effort**: S.

### Task 3 — Deduplicate HTML/CSS scaffolding across Resultater.html files

- **Scope**: per-report `Resultater.html` today inlines a large
  chunk of CSS (`REPORT_STYLE` ~8 KB) and an HTML scaffold.
  CSS is small; the real win is one schema per file. Keep the
  inlining; just verify no-op CSS is removed.
- **Why**: minor (8 KB × 100 patients = 0.8 MB), but worth doing
  while we're already touching every file.
- **Acceptance**:
  - `REPORT_STYLE` minify pass via cssmin (or manual).
  - Tests still pass.
- **Commit**: `perf(html-reports): minify REPORT_STYLE inline CSS`
- **Risk**: low.
- **Effort**: S.

### Task 4 — `Plotly.relayout`/`newPlot` runtime verification on slim build

- **Scope**: a new manual test in
  `tests/test_html_report_fragment_cache.py` (or new file) that
  builds a small fig and confirms `Plotly.newPlot` + `Plotly.relayout`
  APIs exist in the slim bundle by ingesting the slim JSON we ship
  in `assets/`.
- **Why**: enforce the slim-build-feature invariant. A future
  vendor update that breaks `relayout` would be caught here.
- **Acceptance**:
  - New test passes; 33 → 34 tests.
  - Both `newPlot` and `relayout` substring matches verified.
- **Commit**: `test(plotly): assert slim build exposes our APIs`
- **Risk**: low.
- **Effort**: S.

### Task 5 — Size regression guard

- **Scope**: a unit test in `tests/test_html_report_size.py`:
  - Generate one minimal `Resultater.html` fixture.
  - Assert file size is < 1.5 MB (after Tasks 1–3 land) instead of
    the current ~5 MB.
  - Tests fail if every new vendor update of `plotly-basic` is
    larger than the budget.
- **Why**: this is the lever that prevents the win from regressing.
- **Acceptance**:
  - 33 → 34 (or 35) tests.
  - Failure message points at `assets/plotly-3.1.0-basic.min.js`.
- **Commit**: `test(html-reports): regression guard for per-patient HTML size`
- **Risk**: low (test-only).
- **Effort**: S.

### Task 6 — Vendor-update flow

- **Scope**: `assets/CARTO_FETCH.md` documents how to refresh the
  slim build with `curl` (or `pip install plotly` for syncing plots
  min.js backend). Add a `scripts/refresh_slim_plotly.py` that
  downloads and validates the bundle (size budget, substring API
  presence).
- **Why**: prevents future drift.
- **Acceptance**:
  - Script runs, prints OK/FAIL.
  - Document updated.
- **Commit**: `chore(plotly): vendor-update script + CARTO_FETCH.md`
- **Risk**: low.
- **Diff**: S.

### Task 7 — Feature audit: which HTML writers need full vs slim

- **Scope**: a script (or notebook) that walks each of the 6 HTML
  outputs (`plotting_plotly/_legacy.py`, `html_reports/_legacy.py`,
  `qc/qc_html.py`, `qc/qc_plots.py`, `general/reporting.py`,
  `qc/qc_main.py`) and confirms each only uses features that
  `plotly-basic` supports.
- **Why**: a feature that requires 3D, mesh, mapbox, finance, or
  gl2d would not work with the slim bundle; we must upgrade that
  specific call site to the full bundle only.
- **Acceptance**:
  - Each output category passes the audit (or is moved to
    full-inline mode).
- **Commit**: `chore(html-reports): audit each writer against slim build`
- **Risk**: low (audit-only).
- **Effort**: M.

### Task 8 — Optional micro-win: trim per-patient scaffolding further

- **Scope**: after Tasks 1–3 land, profile the per-patient HTML
  with a real dataset. Probably not worth it — try Task 5 first
  and see if size budget is comfortable.
- **Why**: tail-end optimisation.
- **Acceptance**: optional.
- **Commit**: deferred.
- **Risk**: low.
- **Effort**: M.

## 6. Recommended ship-ready sequence

- **PR A** (Tasks 1+2+3): switch to slim inline plotly + minify CSS.
  Per-patient HTML drops from ~5 MB to ~1.2 MB. ~S+M effort, low
  risk (verified by Tasks 4+7).
- **PR B** (Tasks 4+5+6): tests + vendor-update script. ~S effort.
- **PR C** (Task 7): feature audit (which callsites drift back to
  full whenever needed). ~M effort.
- Optional **PR D** (Task 8): further trimming if PR-A is not small
  enough; deferred until measured.

## 7. Verification

```
$ wc -c assets/plotly-3.1.0.min.js
4763993
$ wc -c assets/plotly-3.1.0-basic.min.js    # after PR A
1115881
$ du -sh assets/

$ grep -rn '_local_plotly_tag' core/ scripts/ gui_qt/ \
       | head -10
[callsites unchanged; all switched to slim mode internally]

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests, OK
# After PR B:
Ran 35 tests, OK
```

Expected after PR A lands (per `Resultater.html`):

| File | Before | After |
|---|---|---|
| Slim inline plotly JS | 4.6 MB | 1.1 MB |
| CSS + scaffolding | ~50 KB | ~50 KB (unchanged) |
| Per-figure JSON + peak data | ~10 KB | ~10 KB |
| **Total per patient** | **~4.7 MB** | **~1.2 MB** |
| Run of 100 patients | ~470 MB | ~120 MB |

Expected after PR C + self-test budget (Task 5 threshold):

| | Target | Per patient |
|---|---|---|
| Hard cap | 1.5 MB | enforces slim build |

(Note: the user-supplied LIS workflow requires per-patient
self-contained HTML — no external sibling files. This plan
preserves that constraint by keeping the JS inline and **shrinking
the bundle instead of externalizing it**.)

## 8. Constraints honored

- Qt app continues to start and behave identically.
- Plotly reports remain interactive (the slim bundle supports
  `newPlot`, `relayout`, `click` — all features we use).
- Per-patient HTML remains a **single self-contained file**, suitable
  for direct LIS upload with no sibling files.
- Per-patient feature set unchanged (peak manager, status badges,
  JSON state).
- LIS handoff contract unchanged except smaller payload by default.
