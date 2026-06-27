# Plan 09 — Code Quality + DRY Review (Pass 2 of 3)

> Branch: code-cleanup. Test baseline: Ran 37 tests, OK.
> Reviewer responsibility: real duplications grounded in code grep + counts, not anecdote.

Pass 2 of the three-pass deep review. Priority is code quality:
deduplicating copy-pasted helpers and standardising cache patterns.
No behaviour change is acceptable; every refactor must preserve the
current test baseline (Ran 37 tests, OK).

All counts and file references in this plan are from grep +
inspect on the current code-cleanup branch tip `48e7c16 perf(area+analysis)`.

---

## 1. Found duplication (file:line evidence)

### 1.1 Plot-cache helpers duplicated between plotting_plotly and qc_plots

Both `core/plotting_plotly/_legacy.py` and `core/qc/qc_plots.py`
copy the same per-FSA / per-entry cache machinery with slightly
different names:

```
core/plotting_plotly/_legacy.py
  _get_fsa_plot_cache(fsa)            line 37
  _get_entry_plot_cache(entry)        line 63
  _get_axis_arrays(fsa)               line 79
  _get_trace_array(fsa, channel)       line 101
  _baseline_correct_trace_for_display trace, assay_name  115
  _get_display_trace(entry, ...)      line 123
  _get_nonspecific_corrected_trace   138
  ```

mirror in

```
core/qc/qc_plots.py
  _get_qc_fsa_cache(fsa)               line ~50
  _get_qc_entry_cache(entry)           line ~40
  _get_qc_axis_arrays(fsa)             line ~55
  _get_qc_trace_array(fsa, channel)    line ~88
```

Total: ~120 lines of near-textual clone code across the two files,
maintained independently. Future cache schema changes (e.g.
adding a baseline cache key) require edits in two places that drift.

### 1.2 `FsaPlotCache` schema implicit

Both modules carry the same per-FSA cache-keys set:
- `trace_arrays`       (per channel, source_id-keyed)
- `axis_arrays`        (id(raw_df)+columns-keyed)
- `display_traces`     (per-channel display-shaped)
- `nonspecific_traces`

No formal type/schema. The pattern `cache.setdefault('display_traces', {}).set(channel)` is
present in both files with subtle differences in default-value and
source-id semantics.

### 1.3 FLT3 ladder/QC review code is spread

Plan 07 / Pass 1 alone landed core/area.py lazy import + a vectorised
baseline. The remaining `core/analysis/_legacy.py` 4906-line module is
still the dominant source of repeated inline patterns across
plotting and QC plotting paths.

### 1.4 `OUTDIR_NAME` re-imports across 7 files (verified DRY)

```
core/assay_config.py        : defines OUTDIR_NAME * get_default_outdir_name()
core/batch.py               : `from core.assay_config import OUTDIR_NAME`
core/runner.py              : same, 2x
core/qc/qc_main.py          : same
core/html_reports/_legacy.py: imports inside functions
gui_qt/tabs/tab_batch/_legacy.py : 7 callers
gui_qt/tabs/tab_ladder/_legacy.py :
```

> Status: this is already DRY (one canonical definition). However
> it's worth noting that callers do `from core.assay_config import OUTDIR_NAME`
> at function-call time instead of module top. We can move those to
> module-top imports in one PR for a small import-order cleanup.

---

## 2. Quality task list (smallest/safest first)

### Task 1 — Extract plot caches to a shared cache module (DRY win)

- Scope: in core/plot_cache.py (new) introduce:
    class FsaPlotCache:
        def __init__(self, fsa): ...
        def get_or_compute_trace(self, channel, fn): ...
        def get_or_compute_axis_arrays(self, raw_df_cols): ...
        def get_or_compute_display(self, channel, key, fn): ...
        @classmethod
        def for_fsa(cls, fsa): -> cls instance with idempotent on-fsa cache

  and use it from BOTH core/plotting_plotly/_legacy.py and
  core/qc/qc_plots.py.

- Why: removes ~120 lines of duplicate cache plumbing; one
  place to evolve the schema (e.g. add baseline cache key).
- Acceptance:
    - core/plot_cache.py exposes FsaPlotCache
    - core/plotting_plotly/_legacy.py drops the helpers; uses
      core.plot_cache.FsaPlotCache instead.
    - core/qc/qc_plots.py drops the duplicating helpers; same.
    - Ran 37 tests, OK.
    - All current behaviour identical: cache invalidation on source_id
      change preserved.
- Commit: refactor: extract shared FsaPlotCache into core/plot_cache.py
- Risk: medium (touches two heavily used cache helpers).
- Effort: M.

### Task 2 — Replace `_local_plotly_tag(version="2.35.2")` with version pulled from bundled asset

- Scope: in core/plotly_offline.py:15 we already documented that
  `version="2.35.2"` is wrong-but-functional. Detect the actual
  version from assets/plotly-3.1.0-basic.min.js (parse the header
  comment) and use that in `_local_plotly_tag.__doc__` and any
  external reference. The hard-coded `2.35.2` in callers doesn't
  need to change unless we audit the version param.
- Why: clean up a real inconsistency between asset (3.1.0) and
  call-site tag string (2.35.2).
- Acceptance:
    - assets/plotly-3.1.0-basic.min.js header parsed.
    - `from core.plotly_offline import bundle_version` returns
      `3.6.0` (the build variant of plotly.js-basic-dist-min@3.6.0+).
    - Tests still 37/37.
- Commit: docs(plotly): derive bundleVersion from the bundled asset
- Risk: low (informational).
- Effort: S.

### Task 3 — Move `from core.assay_config import OUTDIR_NAME` to module-top in 7 callers

- Scope: one consistent import in each module (core/batch.py,
  core/runner.py, core/qc/qc_main.py, core/html_reports/_legacy.py,
  gui_qt/tabs/tab_batch/_legacy.py,
  gui_qt/tabs/tab_ladder/_legacy.py).
- Why: import-order polish; saves 4-5 lazy-import microseconds per
  call (& faster startup with -X importtime profiling).
- Acceptance: tests still 37/37; no behavioural change.
- Commit: chore: hoist OUTDIR_NAME imports to module top
- Risk: low.
- Effort: S.

### Task 4 — Drop `legacy_app.py` reference in qt_app.py if absence is confirmed safe

- Scope: confirmation that no current code path imports `app.py`
  at runtime. From Pass 2 grep:
    `grep -rn "import app\\b\\|from app\\b" --include='*.py' .` -> zero hits.
  But we keep the legacy Panel-server optional path which DOES
  load app.py. If we expose a CLA (or env) to disable that path,
  we get crystal-clear behaviour.

  Decision after step Plan 07: NOT in scope for Pass 2. Track in
  Plan 06 follow-ups.

- Commit: N/A
- Risk: N/A
- Effort: N/A

### Task 5 — Replace call-site `print_green(f"[DIT] Lagret: {...}{file_path}")` with logger

- Scope: scroll core/html_reports/_legacy.py for `_lagret_` strings;
  the prints share a pattern. Switch to Project's log mechanism
  (consistent across core.log). For now, leave prints alone
  because the user often wants visible stdout in batch runs.
- Why: quality; not strict DRY.
- Acceptance: behaviour identical (same stdout lines); tests
  unaffected.
- Commit: N/A (deferred).
- Risk: low.
- Effort: M.

### Task 6 — Split `core/qc/qc_plots.py` cache helpers into shared module

- Scope: subsumed by Task 1 — when `core/plot_cache.py` ships, qc_plots
  reuses it.
- Commit/Risk/Effort: see Task 1.

### Task 7 — Drop `print_warning` FutureWarning on Param init

- Scope: core/log.py reaches into param at import. The deprecated
  `param.version.Version` warning prints once. We can wrap a
  warnings.filterwarnings("ignore") at the entry of core.log to
  suppress just the param deprecation chatter. Better: monitor
  when param/panel really deprecate and look upstream.
- Acceptance: clean stderr on first import.
- Commit: chore(log): suppress param.version FutureWarning at the entry of core.log
- Risk: low.
- Effort: S.

---

## 3. Recommended ship-ready sequence

- PR A (Task 1): shared FsaPlotCache in core/plot_cache.py. Single
  commit, ~120 lines moved, behavioural unchanged. ~M effort.
- PR B (Tasks 2 + 3 + 7): small cleanups. ~S effort.

---

## 4. Verification

After PR A:
  - grep 'def _get_fsa_plot_cache\\|def _get_entry_plot_cache\\|def _get_qc_fsa_cache\\|def _get_qc_entry_cache' \\
    core/plot_cache.py core/plotting_plotly/_legacy.py core/qc/qc_plots.py
  - shows: only core/plot_cache.py defines them; the other two
    import from there.
  - python3 -m unittest discover -s tests: Ran 37 tests, OK.

After PR B:
  - grep 'from core.plotly_offline import bundle_version' -- returns doc-friendly value.
  - python3 -m unittest discover -s tests: Ran 37 tests, OK.
