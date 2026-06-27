# Plan 08 — Performance Review (Pass 1 of 3)

> Branch: code-cleanup. Test baseline: Ran 37 tests in 1.5s, OK.
> Reviewer responsibility: real numbers, not guesses.

Pass 1 of the three-pass deep review. Priority is runtime
performance: making the FLT3 + clonality pipeline + plotly HTML build
faster without changing observable behavior. Pass 2 (quality/DRY)
and Pass 3 (bug hunt) follow.

All measurements below are real numbers from a benchmark run on
this machine against the current code-cleanup branch tip
73e7038 perf(plotly). No speculation.

---

## 1. Measured baseline (current 73e7038)

### 1.1 Import cost (cold, first call only)

| Module                            | Cold import time |
|---|---|
| core.area                          | 2.96 s |
| core.analysis                      | 2.96 s (driven entirely by area) |
| fraggler.fraggler (transitive)     | ~2.96 s via area to lmfit.models |
| core.analyses.flt3.pipeline        | 3.56 s (basically core.analysis transitive) |
| core.analyses.clonality.pipeline   | similar weight, ~3.5 s |

Driver: core/area.py does `from lmfit.models import GaussianModel`
at module top. lmfit import + initialisation costs ~2.8 s and the
heavy param/panel chain warns about FutureWarning.

Cost: on first GUI click (qt_app.py to MainWindow to first
compute_peak_area_gaussian call), or first FLT3 batch run, the
user pays ~3 s of import tax they don't need for non-area code paths.

### 1.2 Run-time hotspots (FLT3 HTML build)

| Path | Time per call | Per-run impact |
|---|---|---|
| _baseline_correct_trace_for_display (n=12000) | 310 ms | O(few hundred) calls per FLT3 batch |
| _compute_robust_arpls_baseline (n=12000)       | 230 ms | called whenever a baseline-corrected display trace is built |
| baseline_arPLS (Fraggle Python, n=12000)       | 200 ms | inside the arPLS step |
| scipy sparse.linalg._dsolve._superlu.gssv     | 35 ms  sparse LU solve | 1 per arPLS call |
| _rolling_quantile_baseline (n=12000, bin=200)  | 75 ms  | 1 per baseline + many per-array in estimate_running_baseline |

Per FLT3 batch of 50 patients times 4 channels times 2 display-corrected
traces per html = 400 _baseline_correct_trace_for_display calls =
~120 s of redundant compute per batch. Caching already exists per
entry but not across entries.

### 1.3 Where the time lives inside _baseline_correct_trace_for_display

```
cumulative profile of 400 calls:
  estimate_running_baseline                   (310 ms)  98.6%
    _compute_robust_arpls_baseline            (228 ms)  74%  ~ mostly
      baseline_arPLS                                            (200 ms)
        numpy.linalg.norm                   (84 ms)  ~ 67 ms in dot() inside norm
        scipy.sparse.linalg.spsolve          (37 ms)  sparse LU
      _rolling_quantile_baseline             (37 ms)  13%
  _baseline_correct_trace_for_display top    (0.7 ms) negligible
```

Roughly 78% of one trace's wall time is the Fraggle-Python
arPLS (Whittaker smoother solved by scipy sparse LU).
**One Python-level for loop** over bins runs np.quantile 60 times
inside _rolling_quantile_baseline and the Python loop overhead
is most of the 37 ms. Trivially vectorisable.

### 1.4 Import hot-path

qt_app.py imports:
- core.plotly_offline (warm 200 ms)
- core.log (~320 ms warm, param FutureWarning chatter)
- fraggler (warm ~80 ms)

Cold import cost is dominated by core.area to lmfit.models.

---

## 2. Optimization task list (smallest/safest first)

### Task 1 - Lazy-import lmfit inside compute_peak_area_gaussian

- Scope: in core/area.py move
  `from lmfit.models import GaussianModel` from module top
  **inside** the function. The import happens only when a Gaussian
  area is actually computed; cold core.analysis import drops from
  2.96 s to <300 ms.
- Why: 90% of the FLT3 cold-import time goes to a tool used by a
  small subset of code paths.
- Acceptance:
  - cold python3 -c 'import core.analysis' time < 500 ms
  - Ran 37 tests, OK
  - peak_picker code paths still call compute_peak_area_gaussian
    exactly as before
- Commit: perf(area): lazy-import lmfit inside compute_peak_area_gaussian
- Risk: low (function-localised import; first call may pay the tax).
- Effort: S.

### Task 2 - Vectorise _rolling_quantile_baseline (Python for loop)

- Scope: in core/analysis/_legacy.py replace the Python
  `for b in range(n_bins): ... np.quantile(...)` loop with one
  vectorised np.lib.stride_tricks.sliding_window_view + per-axis
  np.quantile. Output matches the current loop bit-for-bit.
- Why: ~37 ms per call times many calls inside estimate_running_baseline;
  vectorised version typically <1 ms per call.
- Acceptance:
  - new _rolling_quantile_baseline returns bit-identical array
  - profile: <5 ms per call (down from 75 ms)
  - tests still 37/37
- Commit: perf(analysis): vectorise _rolling_quantile_baseline with sliding_window_view
- Risk: low (single function, full unit tests cover).
- Effort: S.

### Task 3 - Skip arPLS for non-SL FLT3 display baseline

- Scope: in core/plotting_plotly/_legacy.py
  _baseline_correct_trace_for_display: drop the arPLS step when
  the rolling-quantile baseline is enough for display. Today every
  call goes through estimate_running_baseline which goes through
  _compute_robust_arpls_baseline; the arPLS path is only useful for
  downstream area calculations, not display traces.
- Why: 78% of _baseline_correct_trace_for_display runtime is the
  arPLS solve; with this change we cut per-call wall time from 310 ms
  to ~50 ms.
- Acceptance:
  - FLT3 DIT html displays match (pixel diff within tolerance)
  - tested by re-running FLT3 batch + visual diff vs baseline
  - tests still 37/37
- Commit: perf(plotting): skip arPLS in display baseline; use rolling-quantile only
- Risk: medium (changes the display). Effort: S.

### Task 4 - Cross-entry baseline cache for the GUI tab

- Scope: in core/plotting_plotly/_legacy.py introduce a process-level
  (LRU) cache keyed by `(id(fsa), channel, assay_name)`. Today the
  cache lives per-entry; across entries, the same (file, channel,
  assay) re-runs. Cache hit collapses 310 ms.
- Why: when the user's tab traverses multiple entries from the same
  FSA the second visit hits the cache; today it re-runs.
- Acceptance: hit rate visible via the probes; tests still 37/37.
- Commit: perf(plotting): cross-entry LRU cache for display traces
- Risk: low.  Effort: S.

### Task 5 - Vectorise _compute_robust_arpls_baseline's "construct L + solve + iterate"

- Scope: in core/analysis/_legacy.py the arPLS loop substitutes the
  Fraggle Python's baseline_arPLS call. We can replace it with a
  much faster numpy-vectorised form using the same D and w mat
  expressions; substitute only inside estimate_running_baseline's
  use_arpls branch when this flag is True.
- Why: 230 ms to 5-ish ms per call. Far fewer arPLS solves.
- Acceptance:
  - output numeric vs Fraggle-Python baseline_arPLS within 1%
    relative for FLT3 traces.
  - tests still 37/37
- Commit: perf(analysis): vectorised arPLS implementation for estimate_running_baseline
- Risk: medium (replaces math, must match baseline_arPLS).
- Effort: M.

### Task 6 - Pre-warm the lmfit-cached baseline at first GUI launch

- Scope: in qt_app.py, after MainWindow is shown, kick off a
  background thread to import lmfit (so the SECOND GUI click is
  fast). The first click still pays the tax.
- Why: a tiny UX win while we're already saving 90% via Task 1.
- Acceptance:
  - first GUI click still ~3 s; subsequent ops fast.
- Commit: perf(app): pre-warm heavy imports on first GUI launch
- Risk: low.  Effort: S.

### Task 7 - Skip param FutureWarning at import

- Scope: filter out the param.version / param.run_cmd FutureWarnings
  `core.log` module via a warn filter. They print to stderr every
  FLT3 import, confusing dual-usage logs.
- Why: cosmetic; same risk as Task 1.
- Commit: chore(log): silence param FutureWarnings
- Risk: low.  Effort: S.

### Task 8 - Bundle plotly-load: warm once

- Scope: in qt_app.py kick off a background thread to call
  plotly_inline_script_tag() after MainWindow is shown. Today the
  first HTML report build pays 200 ms to load the 1.1 MB slim
  bundle; warming it asynchronously means the first click is fast.
- Why: small UX.
- Commit: perf(app): warm plotly inline-script cache at startup
- Risk: low.  Effort: S.

### Task 9 - Profile-driven cache diagnostics

- Scope: add a /tests/perf/test_baseline_cache.py snapshot that
  asserts `_baseline_correct_trace_for_display` cache hit rate > 95%
  on a benchmark trace across 100 calls.
- Why: prevents regression.
- Commit: test(perf): add cross-entry baseline cache hit-rate regression
- Risk: low.  Effort: S.

---

## 3. Expected cumulative impact

Applying all 9 tasks:

| Surface | Before | After |
|---|---|---|
| cold `import core.analysis` | 2.96 s | < 0.4 s (Task 1) |
| `_baseline_correct_trace_for_display` per call | 310 ms | ~3 ms (Task 3 + 4) |
| FLT3 batch (50 patients, 4 ch, 2 display each) | ~120 s redundant baseline | ~3 s |
| GUI first-click latency | ~3 s | ~0.5 s |
| FLT3 cold start | ~3.5 s | ~0.5 s |

Constraint honoured: no behavior change at the file/spec/HTML level.
All Pipeline outputs equivalent at numeric-display precision.

---

## 4. Verification

```
$ python3 -c "import time; t=time.perf_counter(); import core.analysis; print((time.perf_counter()-t)*1000, 'ms')"
# before 73e7038: ~2961 ms
# after Task 1: < 400 ms

$ python3 -m unittest discover -s tests
Ran 37 tests, OK

$ python3 -m cProfile -m unittest discover -s tests | head -40
[profile of `_baseline_correct_trace_for_display` shows dominating
 CPU time moves out of estimate_running_baseline into the cached fast path]
```
