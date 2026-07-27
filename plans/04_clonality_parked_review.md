# Plan 04 — Clonality (parked) review

> Branch: `code-cleanup` (off \`codex-clonality-ladder-finalize-2026-05-14\`).
> Test baseline: \`Ran 33 tests, OK\` via
> \`QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests\`.
> Reviewer responsibility: **real findings only** — and **HONOR the
> parking constraint strictly**: do not propose behavior changes,
> new interpretation features, or rescoping. The summary says
> clonality is parked; this plan must not park it less.

---

## 1. Architecture summary

- Patient-sample clonality QC pipeline under
  `core/analyses/clonality/` (10 modules, 4590 lines total).
- Public submodules (per the package docstring added in Phase 4):
  `pipeline`, `interpretation`, `classification`, `config`,
  `ladder_review_gate`, `candidate_artifacts`, `feature_artifacts`,
  `tracking_excel`, `tracking_dashboard`, `scoring`.
- `core/analyses/clonality/pipeline.py` (1033 lines) is the main
  orchestrator; reads `.fsa`, runs `classify_fsa`,
  `python_or_rust_qc`, builds clonality QC entries, then triggers
  update of per-run + global Excel workbooks. Live helpers
  detected at the file head include `_scan_files`, `_should_use_multiprocessing`,
  `_rust_worker_batch_mode_available`, `_build_peaks_from_rust_clonality_preview`,
  `_run_analyze_single_file_child`, `_analyze_files`, `run_pipeline`.
- `interpretation.py` (835 lines) holds the
  `clonality_interpretation_v1` schema with `interpretation_enabled`
  / `learning_mode_enabled` toggles (default OFF per Project Memory).
  Interpretation dispatches to `_interpret_<assay>` helpers per
  Project Memory *Clonality v1*.
- `config.py` (340 lines) holds per-assay reference ranges plus the
  `NONSPECIFIC_PEAKS` list.
- Tracking artifacts in `tracking_excel.py` (691 lines) +
  `tracking_dashboard.py` (413 lines) maintain the per-run and
  global Excel workbooks.
- `candidate_artifacts.py` (365 lines) +
  `feature_artifacts.py` (456 lines) hold per-file candidate and
  trace-feature artifact I/O used by interpretation training.

## 2. File inventory (verbatim)

```
   20  core/analyses/clonality/__init__.py
  365  core/analyses/clonality/candidate_artifacts.py
  135  core/analyses/clonality/classification.py
  340  core/analyses/clonality/config.py
  456  core/analyses/clonality/feature_artifacts.py
  835  core/analyses/clonality/interpretation.py
  165  core/analyses/clonality/ladder_review_gate.py
 1033  core/analyses/clonality/pipeline.py
  137  core/analyses/clonality/scoring.py
  413  core/analyses/clonality/tracking_dashboard.py
  691  core/analyses/clonality/tracking_excel.py
 4590  total
```

## 3. Cross-reference map

External consumers (verbatim `grep`):

- `core/analyses/clonality/pipeline.py` is consumed by:
  - `scripts/render_clonality_interpretation_annotation_html.py`
  - `tests/test_clonality_control_smoke.py`
  - `tests/test_clonality_rust_preview_peaks.py`
- `core/analyses/clonality/interpretation.py`:
  - `core/batch.py`
  - `scripts/render_clonality_interpretation_annotation_html.py`
  - `scripts/train_clonality_interpretation_quick_model.py`
  - `tests/test_clonality_interpretation_v1.py`
- `core/analyses/clonality/tracking_excel.py`:
  - `core/batch.py`, `core/clonality_backfill.py`,
    `gui_qt/tabs/tab_batch/_legacy.py`,
    `gui_qt/tabs/tab_ladder/_legacy.py`
  - `tests/test_clonality_interpretation_v1.py`,
    `tests/test_clonality_tracking_output.py`
- `core/analyses/clonality/tracking_dashboard.py`:
  - `core/analyses/flt3/qc_tracker.py` (one lazy import of
    `refresh_clonality_tracking_dashboard`).
- Tests live under `tests/test_clonality_*.py` (8 files, ~1300 lines).

## 4. Intentional tech debt (do not churn — parked)

- `interpretation_v1` is **default OFF** per Project Memory
  *Clonality v1*. Code that powers it (`interpretation_enabled`,
  `learning_mode_enabled`, `_sl_quality_*`, `_interpret_<assay>`,
  `train_clonality_interpretation_quick_model.py`) must stay
  untriggered by default. Touching thresholds here would change
  clinical output, which is exactly what Project Memory forbids.
- `NONSPECIFIC_PEAKS` is a curated reference list (Project Memory
  *Clonality v1*) — do not auto-extend, do not auto-mark unknown
  peaks as nonspecific.
- Per Pipeline *Hygiene* note from Project Memory: clonality
  backfill (one bad `.fsa` blocking the whole night run) uses
  per-file child-process timeout (`analyses.clonality.pipeline.file_timeout_seconds`,
  default 240) and a `core.batch.KNOWN_CLONALITY_BACKFILL_SKIP_FILES`
  allowlist. Don't disable.
- `_interpret_*` helpers per assay are research-quality code paths;
  their outputs (`clonality_interpretation_v1` schema fields) are
  **never** consumed by DIT report text. Don't lift the schema
  into clinical output.

## 5. Actionable task list (structure-only)

### Task 1 — Sub-split: extract `_run_analyze_single_file` plumbing
- **Scope**: clonality/pipeline.py lines 523 (~`_analyze_single_file`)
  through ~`_analyze_files` (~L865) overlap with the same
  `_scan_files` / `_run_analyze_single_file_child` patterns
  shared with FLT3's pipeline. Pull those into
  `core/analyses/clonality/pipeline/_per_file_runner.py`.
- **Why**: shrinks `core/analyses/clonality/pipeline.py` from 1033
  to <700 lines; isolates timeout + known-hang-skip logic.
- **Acceptance**: tests still 33/33; pipeline runs identically.
- **Commit**: `refactor(clonality): extract per-file runner from pipeline.py`
- **Risk**: medium (touches behavior path; no spec change).
  **Effort**: M.

### Task 2 — Sub-split: pull `tracking_dashboard` into `tracking_excel`
- **Scope**: `tracking_dashboard.py` (413 lines) plus
  `tracking_excel.py` (691 lines) both operate on Excel workbooks and
  share `openpyxl`. Pull them into a shared
  `core/analyses/clonality/_workbook_io.py` (low-level helpers) and
  leave the orchestrators slim.
- **Why**: avoid two parallel modules each owning their own
  `load_workbook` / `openpyxl` boilerplate.
- **Acceptance**: facade re-export; tests still 33/33.
- **Commit**: `refactor(clonality): extract Excel workbook helpers`
- **Risk**: low.  **Effort**: M.

### Task 3 — Docstring pass: `_interpret_<assay>` helpers
- **Scope**: each helper in `interpretation.py:605-720` (per
  `_interpret_default`, `_interpret_fr1`, `_interpret_fr2`,
  `_interpret_fr3`, `_interpret_dhjh_d`, `_interpret_dhjh_e`,
  `_interpret_tcrbA`, `_interpret_tcrbC`, `_interpret_igk`).
- **Why**: the policy is documented in Project Memory *Clonality
  v1*; the helpers themselves don't carry that policy in
  docstrings, which makes future review work harder.
- **Acceptance**: each helper has a 2-3 line explanation pinned
  to the per-assay rule from Project Memory.
- **Commit**: `docs(clonality): annotate _interpret_<assay> dispatch rules`
- **Risk**: low (text-only).  **Effort**: S.

### Task 4 — Test gap: cover `KNOWN_CLONALITY_BACKFILL_SKIP_FILES` filter
- **Scope**: today `tests/test_clonality_file_timeout.py` exercises
  the timeout, but the skip-file list itself lacks tests.
- **Why**: ensure additions to the skip list don't break a known-
  good file path.
- **Acceptance**: tests still 33/33 with new tests added (33 -> 35).
- **Commit**: `test(clonality): cover KNOWN_CLONALITY_BACKFILL_SKIP_FILES filter`
- **Risk**: low.  **Effort**: S.

### Task 5 — Test gap: cover `NONSPECIFIC_PEAKS` exclusion logic
- **Scope**: today `clonality` interpretation v1 implementation
  excludes known nonspecific peaks from peak ratios per Project
  Memory *Clonality v1*. There is no test for the exclusion.
- **Why**: this filter is intentional and visible in the
  tracker output; if it regresses, downstream ratios shift.
- **Acceptance**: tests still 33/33 with new tests added.
- **Commit**: `test(clonality): cover NONSPECIFIC_PEAKS exclusion`
- **Risk**: low.  **Effort**: S.

## 6. Verification

```
$ wc -l /workspace/hemafrag/core/analyses/clonality/*.py
   20  core/analyses/clonality/__init__.py
  365  core/analyses/clonality/candidate_artifacts.py
  135  core/analyses/clonality/classification.py
  340  core/analyses/clonality/config.py
  456  core/analyses/clonality/feature_artifacts.py
  835  core/analyses/clonality/interpretation.py
  165  core/analyses/clonality/ladder_review_gate.py
 1033  core/analyses/clonality/pipeline.py
  137  core/analyses/clonality/scoring.py
  413  core/analyses/clonality/tracking_dashboard.py
  691  core/analyses/clonality/tracking_excel.py
 4590  total

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
