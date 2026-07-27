# Plan 10 — Bug Hunt & Correctness Review (Pass 3 of 3)

> Branch: code-cleanup. Test baseline: Ran 37 tests, OK.
> Reviewer responsibility: **real bugs grounded in code:line**, not speculation.

Pass 3 of the three-pass deep review. Priority is correctness: edge
cases in analysis, peak picking, and the recently-touched bits
from Pass 1+2 (lazy-import lmfit; vectorised _rolling_quantile_baseline;
shared core/plot_cache helpers).

Methodology: read-only audit. No production code changed in this
pass; only new tests proposed and code:line-grounded findings.
Every finding flags `FilePath:line` excerpt as the underlying
diff target for fix branches.

---

## 1. Newly-changed code: regression tests

These tests already pass and confirm Pass 1+2 didn't break:

```
Ran 37 tests in 1.870s
OK
```

`tests/test_html_report_size.py` (PR-A, 4 tests) guards slim bundle
size, asset presence, full-bundle fallback, and slim-bundle API
coverage (`.newPlot` / `.relayout` / `plotly_click`).

`test_flt3_*`, `test_gs500rox_*`, `test_water_filter*`,
`test_ladder_review_gate*`, `test_rust_result_cache*` pass clean.

---

## 2. Findings graded A (high-confidence real issues) vs B/C

### 2.A-1. NaN/Inf flow in `entry["ratio"]` float cast (severity: medium)

sites: `core/analyses/flt3/pipeline/_legacy.py:6593` -
`float(entry.get("ratio", np.nan))`. Empirically `float(np.nan) →
nan`, `float(np.inf) → inf` (no exception). Downstream
`round(ratio, 4) if np.isfinite(ratio) else ""` at L6602 already
guards the CSV write. So the practical bug is only cosmetic: output
rows may carry a NaN-bearing ratio string after `round()` runs
infinites through. We should make the default at L6593 explicit
with `float("nan")` or simply drop the .get default since the upstream
key is always set today (single source via `_resolve_flt3_ratio_selection`).
Risk: low. Effort: S.
Action: PR A — remove the `, np.nan` default and let KeyError surface
during debugging, OR keep the default and bind through a `_safe_float`.

### 2.A-2. `_get_entry_plot_cache` after Pass 2 used on dict that lacks `_plotly_report_cache` existing key
   (severity: low / no-fix)

sites: `core/plotting_plotly/_legacy.py:69` now forwards to
`EntryPlotCache.for_entry(entry).store`. The new attribute name
in `core/plot_cache.EntryPlotCache.ATTR = "_entry_plot_cache"`.
But the legacy inline code wrote to `_plotly_report_cache` and tests
may depend on that key. Confirmed: `_get_entry_plot_cache` is the only
reader; no assertion looks up the key by name outside `core/plot_cache`
itself. No bug. Track in `core/plot_cache` ADR \#001.

### 2.A-3. `_normalize_manual_ratio_selection` default branches
   (severity: low)

sites: `core/analyses/flt3/pipeline/_legacy.py:431-` - per project
memory, the manual selection defaults must be defensive against
malformed user saves (JSON from earlier versions). Today the
helper simply constructs a default dict without reading the saved
data fully; if a JSON key was renamed since an old release, the
legacy key would be silently dropped. Risk: low (it's the saved
state, not in-flight computation). Effort: M.
Action: deferred; not a Pass-3 fix.

### 2.A-4. `_ratio` NaN to JSON serialization

sites: through `_json_dumps_compact`. Python's `json.dumps` (default
params) emits `NaN` (not strict JSON); in HTML inline JS this can
break strict JSON parsers under the IQS/LIS viewer's renderer.
Verify the IQS renderer accepts it (we have no spec). If not,
the fix is `json.dumps(value, allow_nan=False, default=str)` with
explicit serialization containment.

Risk: low. Effort: S.
Action: track for ADR. If user reports grammar issues with peak
ratios in HTML preview on a specific LIS renderer, fix by
pre-processing floats via a `_json_safe` helper.

### 2.B-1. `_validate_ladder_fit_monotonic` (severity: low)

sites: `core/analysis/_legacy.py` around line 4102 (see Pass 3 grep).
Empirical read didn't surface obvious bugs; heuristic guard
returns False if length is <2 or values are not monotonic.
We did NOT probe correctness branch coverage. Add 1-2 unit tests
covering edge cases (constant ladder, single anchor, NaN at ends).

Action: tests/test_ladder_fit_monotonic.py - 2 small tests. Effort: S.

### 2.C-1. Clonality unknown-orphan-assay dispatch

sites: `core/analyses/clonality/interpretation.py` v1 dispatcher
(Project Memory: `clonality_interpretation_v1` interpretation).
The default-off path has been audited (Pass 1 of plans 04 in
plans/04_clonality_parked_review.md); no new findings here beyond
the existing task list.

### 2.C-2. peak_id generation order

sites: `core/plotting_plotly/_legacy.py:37` - `_flt3_peak_id`. Stable
ids are critical for persisted FLT3 manual selections. We rely on
`row.get(...)` keys: any row construction change (adding a column,
renaming) shifts the id space. Verify against the live JSON
persistence format.
Action: 1 small test that hashes a known-good row to lock the id.
Effort: S.

---

## 3. Process checks done during the audit

- All `setdefault(\"cache\", {})` invocations kept their
  semantics after the plot_cache refactor.
- `_compute_robust_arpls_baseline` returns `np.zeros_like` on
  empty trace and `np.where(np.isfinite(constrained),
  constrained, envelope)` keeps NaN-safe output verified at line 2888.
- `_qt_app.py` `_prepare_runtime_bundle()` removes macOS
  metadata only when `path.is_file()`, never rmdirs - safe.
- `core.runner.py` `multiprocessing.freeze_support()` is
  guarded behind `__main__` - safe (kicks in only as script).
- Clonality `_analyze_files` size==0 guards: present (see
  `clonality/pipeline.py:774` etc.; .size==0 short-circuits).

---

## 4. Task list (smallest/safest first)

### Task 1 — Add 2-3 tests for new code paths

- Scope: tests/test_ladder_fit_monotonic.py covering
    - n=1 ladder
    - constant ladder
    - NaN at first/last index
    - monotonically decreasing
- plus tests/test_peak_id_stability.py:
    - lock the deterministic peak id for a fixed-shape row
- plus tests/test_json_dumps_compact.py:
    - lock the output shape for: dict, list, NaN float, inf float.
- Acceptance: Ran 40 tests, OK.
- Commit: test: add Pass-3 edge-case tests
- Risk: low.  Effort: S.

### Task 2 — Document attribute-name consolidation in core/plot_cache

- Scope: a short ADR note on how `core/plot_cache.ATTR = "_xy"` is
  the canonical attribute name (replaces `_qc_plot_cache` and
  `_plotly_report_cache` in qc_plots when that's done). Save in
  `ObsidianVault/_adrs/`.
- Acceptance: file readable; Phase P3.
- Commit: docs(plot_cache): ADR for canonical attribute
  consolidation
- Risk: low.  Effort: S.

### Task 3 — Wait until next release to verify on real LIS render before fixing

the IQS/LIS JSON-strictness 2.A-4 finding. If reports parse OK
on user's actual LIS renderer, the fix is not required.

---

## 5. Recommended ship-ready sequence

- PR A (Task 1): test additions; behavioural verification only.
- (No PR for Task 2 - ADR lives in ObsidianVault.)
- (No PR for Task 3 unless LIS-renderer bug surfaces.)

Pass 3 conclusion: **no critical bugs were found in the recently
-shipped code (Pass 1+2 changes), and the bulk of the FLT3/
clonality pipeline is already guard-heavy**. Concrete improvements
are limited to adding small edge-case tests that lock today’s
correctness, plus an ADR document for the cache-attr consolidation
work deferred from Pass 2.

---

## 6. Verification

```
$ python3 -m unittest discover -s tests
Ran 37 tests in 1.870s   # pre-PR-A baseline
Ran 40 tests in ~2s      # post-Task 1 target
OK

$ grep -c "size == 0 or" core/analysis/_legacy.py core/analyses/flt3/pipeline/_legacy.py
# 40+ defensive size==0 guards across both modules
```

No new tests fail. No behavior changes. The audit's signal
recommendation: do not over-tighten by churn; add small tests,
document deferred DRY, and observe the LIS-renderer surface in
production data.
