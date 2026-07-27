# Plan 06 — Tests & hygiene review

> Branch: `code-cleanup` (off \`codex-clonality-ladder-finalize-2026-05-14\`).
> Test baseline: \`Ran 33 tests, OK\` via
> \`QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests\`.
> Reviewer responsibility: **real findings only**.

This plan covers the test surface and post-`code-cleanup` workspace
hygiene — where we are after 13 commits on `code-cleanup`.

---

## 1. Architecture summary

- Test runner: stdlib `unittest discover -s tests`, plus
  `pytest` available (CI uses unittest only). 18 test files
  total. 2581 lines of test code.
- All tests run headless via `QT_QPA_PLATFORM=offscreen`.
- Coverage is **NOT** configured (no `coverage.py` integration);
  this plan proposes optional coverage.
- CI workflow runs only **2** of the 18 test files
  (`tests/test_ladder_review_gate.py`,
   `tests/test_water_filter.py`); the rest run only locally.

## 2. Test inventory (verbatim)

```
   77  tests/test_batch_latest_run_filter.py
   59  tests/test_clonality_control_smoke.py
   67  tests/test_clonality_file_timeout.py
  472  tests/test_clonality_interpretation_v1.py
  188  tests/test_clonality_rust_preview_peaks.py
   41  tests/test_clonality_rust_worker_mode.py
  137  tests/test_clonality_tracking_output.py
   88  tests/test_flt3_area_baseline.py
  548  tests/test_flt3_gs500rox_start_family_review.py
  151  tests/test_flt3_rox500_runner_filters.py
   57  tests/test_flt3_size_standard_contract.py
  156  tests/test_flt3_tracking_output.py
  151  tests/test_gs500rox_guardrail.py
   42  tests/test_html_report_fragment_cache.py
  171  tests/test_ladder_review_gate.py
  108  tests/test_rust_result_cache.py
   51  tests/test_strict_rust_ladder_mode.py
   17  tests/test_water_filter.py
 2581  total
```

Largest test files:
- `test_flt3_gs500rox_start_family_review.py` (548 lines) — the
  GS500ROX start-family learning assertions.
- `test_clonality_interpretation_v1.py` (472 lines) — interpretation
  v1 dispatch tests.

## 3. Test coverage gaps (cross-reference with Plans 01-05)

- **Plan 01 — FLT3 pipeline**: no end-to-end smoke for
  `run_pipeline` (Plan 01 Task 5).
- **Plan 02 — Analysis + Rust**: `_validate_rust_anchor_selection`
  family-boundary cases (Plan 02 Task 6).
- **Plan 03 — Plotting + GUI**: `tab_archive_runner.py` /
  `tab_flt3_validation.py` ImportError fallback behavior
  (Plan 03 Task 2 + Plan 01 Task 6); `html_reports` empty/stale/missing
  cases (Plan 03 Task 6).
- **Plan 04 — Clonality**: `KNOWN_CLONALITY_BACKFILL_SKIP_FILES`
  filter (Plan 04 Task 4); `NONSPECIFIC_PEAKS` exclusion logic
  (Plan 04 Task 5).
- **Plan 05 — Scripts & packaging**: CI coverage is partial — only
  two test files. Cross-referenced by Plan 05 Tasks 1-3.

Beyond what's in plans 01-05:
- **No Python lint / type-check** in CI today (no ruff/flake8/mypy).
  Optional.
- **No coverage tool** integrated.

## 4. Intentional tech debt (do not churn)

- Windows-runtime: no CI covers the Windows path. The repo relies
  on developer-side packaging experiments. Treat as known gap.
- Freeze-runtime (`_internal/`, PyInstaller bundle): no CI runs
  against the bundled artefact. Known gap.
- Project Memory *Hygiene* logging policy (1-3 bullets per session)
  is observable in `ObsidianVault/02_Session_Log.md` but not
  enforced automatically. Treat as policy, not test.

## 5. Actionable task list (smallest/safest first)

### Task 1 — CI: run the full unittest discover
- **Scope**: change `python3 -m unittest tests/test_ladder_review_gate.py
  tests/test_water_filter.py` → `python3 -m unittest discover -s tests`.
- **Why**: every Phase-1-7 commit passed locally; CI never exercised
  the full set. Cross-reference Plan 05 Task 3.
- **Acceptance**: CI runs all 33 tests on each push / PR.
- **Commit**: `ci: run full unittest discover in CI`
- **Risk**: low.  **Effort**: S.

### Task 2 — CI: add `QT_QPA_PLATFORM=offscreen` env
- **Scope**: the macOS-latest CI runner defaults vary. Set
  `QT_QPA_PLATFORM=offscreen` per Job.
- **Why**: make the headless Qt test path reproducible on runners.
- **Acceptance**: tests run on CI without a display.
- **Commit**: `ci: pin QT_QPA_PLATFORM=offscreen in CI test step`
- **Risk**: low.  **Effort**: S.

### Task 3 — Update CI py_compile targets after Phase 5/6
- **Scope**: see Plan 05 Task 1/2.
- **Why**: today CI py_compile references old file paths.
- **Acceptance**: full module set compiles in CI.
- **Commit**: `ci: enumerate package files in py_compile step`
- **Risk**: low.  **Effort**: S.

### Task 4 — Hygiene: check leftover `__pycache__` from sandbox runs
- **Scope**: `git status` before commit; the new
  code-cleanup branch state has `find . -name __pycache__` cleaned
  each verify step. Add a `scripts/clean_pycache.sh` or
  documentation note.
- **Why**: hygiene.
- **Acceptance**: caches absent from git history.
- **Commit**: `chore: document __pycache__ cleanup step in CLEANUP_PLAYBOOK.md`
- **Risk**: low.  **Effort**: S.

### Task 5 — Hygiene: check for orphan .py files outside packages
- **Scope**: today every original `.py` file in the Phase 5/6 scope
  became a package. Verify there are no stragglers.
- **Why**: drift detector.
- **Acceptance**: a smoke test asserts every `.py` under
  `core/*` and `gui_qt/tabs/*` lives inside a package
  (has `__init__.py` in its directory).
- **Commit**: `chore: add package-layout lint script`
- **Risk**: low.  **Effort**: S.

### Task 6 — Hygiene: reconcile `app_meta.py` with PyInstaller spec
- **Scope**: cross-reference app_meta.py usage:
  `from app_meta import APP_NAME, APP_VERSION` in
  `gui_qt/about_content.py`, `gui_qt/main_window.py`; `HemaFrag.spec`
  references it indirectly via `app.py`. Document and pin
  `APP_VERSION` semver.
- **Why**: cross-check that frozen Windows builds carry the
  correct metadata.
- **Acceptance**: APP_VERSION bumped via documented workflow.
- **Commit**: `docs: document APP_VERSION bump workflow in memory.md`
- **Risk**: low.  **Effort**: S.

### Task 7 — Stretch: coverage tooling
- **Scope**: optional `coverage.py` integration. Run
  `coverage run -m unittest discover -s tests`, output report;
  add to CI as a non-blocking report step.
- **Why**: Plans 01-04 add more tests; coverage is the natural
  metric.
- **Acceptance**: coverage report generated locally.
- **Commit**: `ci: add coverage measurement workflow`
- **Risk**: low.  **Effort**: M.

## 6. Verification

```
$ ls /workspace/hemafrag/tests/test_*.py | wc -l
18

$ wc -l /workspace/hemafrag/tests/test_*.py | tail -1
  2581  total

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
