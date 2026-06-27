# Plan 01 — FLT3 pipeline review

> Branch: `code-cleanup` (off `codex-clonality-ladder-finalize-2026-05-14`).
> Test baseline: `Ran 33 tests, OK` via
> `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests`.
> Lead reviewer responsibility: **real findings only**.

The FLT3 pipeline is the production-busy surface per
`ObsidianVault/01_Project_Memory.md` (Current Focus: FLT3; clonality
parked). This plan catalogues the current FLT3 surface so future
changes stay surgical and traceable.

---

## 1. Architecture summary

- The FLT3 pipeline is a single Q-style/GS500ROX-LIZ500 ladder-drift
  processor for `.fsa` files: read → fit ladder (hybrid Python +
  Rust `fraggler-cli`) → detect peaks → compute WT/MUT/ITD quant →
  emit per-run CSV/XLSX/HTML/JSON.
- Code is split across `core/analyses/flt3/` as a small set of focused
  modules (`classification.py`, `config.py`, `qc_tracker.py`,
  `rox500_exclusions.py`) and the dominant
  `pipeline/` package whose `_legacy.py` carries the legacy monolithic
  body plus a 162-entry `__all__` for the package facade.
- Mode routing is by env var + size-standard tokens: ROX500 uses
  internal `GS500ROX` on `DATA4`; LIZ override uses `DATA105`
  (`flt3_size_standard_mode()` in `pipeline/_legacy.py:104`).
- The Q-style review tooling is heavily review-only / proposal-only
  per session log: `*_gs500rox_*` review-band gates
  (`simple_shift_review`/`35_earlier_review`/etc.), `start_block_*`,
  `reverse_pair_*`, `late_first_35_right_shift`, `right_shifted_*`.
- Strict-Rust opt-in (`HEMAFRAG_STRICT_RUST_LADDER=1` /
  `HEMAFRAG_RUST_ONLY=1` / `engine.strict_rust_ladder=true`) disables
  the Python ladder fallback (`core/engine_flags.py`). Per
  `ObsidianVault/01_Project_Memory.md`, this is opt-in only.
- Sub-pipeline segments: classification → ladder fitting/selection →
  peak-area resolution → manual-ratio orchestration →
  interpretations → tracker workbook updates → QC trends / NPMI /
  BP-validation reports. Each is a function family, not a directory.
- PCurrent leak surface: a small number of underscore-prefixed
  helper functions imported externally (e.g. `_build_entry_from_candidate`,
  `_calculate_ratios`, `_reportable_itd_mut_rows`, `_scan_files`,
  `_summarize_detected_peaks`, plus the bundle of `_gs500rox_*` names
  the start-family review tests pull). The 162-entry `__all__`
  recorded during the Phase 3 package conversion keeps them reachable.
- External tools that consult this surface:
  - `scripts/run_flt3_rox500_qc_all_injections.py` (ROX500 wrapper)
  - `scripts/run_flt3_liz500_qc_all_injections.py` (LIZ500 wrapper)
  - `gui_qt/tabs/tab_flt3_validation.py` (lazy-import wrapper)
  - `tests/test_flt3_*.py` (8 test files)

---

## 2. File inventory

`core/analyses/flt3/`:

```
total 36
drwxr-xr-x 1 root 512 Jun 27 07:59 .
drwxr-xr-x 1 root 512 Jun 27 07:59 ..
-rw-r--r-- 1 root    0 Jun 27 07:59 __init__.py
drwxr-xr-x 1 root 512 Jun 27 09:58 pipeline
-rw-r--r-- 1 root 6768 Jun 27 07:59 classification.py
-rw-r--r-- 1 root   208 Jun 27 07:59 config.py
-rw-r--r-- 1 root 13629 Jun 27 07:59 qc_tracker.py
-rw-r--r-- 1 root  5385 Jun 27 07:59 rox500_exclusions.py
```

Line counts (verbatim from `wc -l`):

```
   0  core/analyses/flt3/__init__.py        (empty!)
 208  core/analyses/flt3/classification.py
  77  core/analyses/flt3/config.py
 398  core/analyses/flt3/qc_tracker.py
  58  core/analyses/flt3/rox500_exclusions.py
  22  core/analyses/flt3/pipeline/__init__.py
  48  core/analyses/flt3/pipeline/_constants.py
6904  core/analyses/flt3/pipeline/_legacy.py
7715  total
```

---

## 3. Public functions table — `core/analyses/flt3/pipeline/_legacy.py`

File is 6904 lines; 162 top-level definitions (153 underscores + 9
public). Below: public surface plus a curated set of internal helpers
that are externally imported.

| Line | Symbol | Role | External callers |
|------|------|------|------|
| 64   | `_flt3_requested_ladder` | ladder selection from env | none |
| 78   | `_flt3_uses_liz_ladder` | bool router | none |
| 82   | `_flt3_ladder_only_qc_mode` | scaffold ahead of pipeline | none |
| 91   | `_flt3_legacy_python_ladder_rescue_enabled` | reads `HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE` | none |
| 100  | `_flt3_gs500rox_rust_only_ladder_mode` | env gate | none |
| 104  | `flt3_size_standard_mode()` | PLA channel contract function (public) | `tests/test_flt3_size_standard_contract.py`, `scripts/run_flt3_liz500_qc_all_injections.py`, `gui_qt/tabs/tab_flt3_validation.py` |
| ...  | (153 underscore helpers, reviewed in plan) |
| 5581 | `_build_entry_from_candidate` | grouping | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6146 | `_calculate_ratios` | per-entry ratio math | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6177 | `_reportable_itd_mut_rows` | filter rows | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 329  | `_scan_files` | case scan | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6206 | `_summarize_detected_peaks` | summarize | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 888  | `_calculate_peak_area_fast` | peak-area math | tests |
| 921  | `_correct_peak_channel_traces` | raw-trace selection | tests |
| 1004 | `_build_peaks_from_rust_flt3_preview` | preview-peak assembly | tests |
| 4063+ | `_gs500rox_*` review-band helpers (29 fns, lines ~3982-5500) | review-only prior pipeline | `tests/test_flt3_gs500rox_start_family_review.py` and `tests/test_gs500rox_guardrail.py` |
| 6253 | `_interpret_entry` | dispatch (per Project Memory: each assay has `_interpret_<assay>`) | (private, internal use) |
| 6280 | `generate_flt3_peak_report` | writes per-run CSV/XLSX/HTML/JSON | none directly; called from `run_pipeline` |
| 6708 | `update_flt3_npm1_qc_tracker_workbook` | NPMI tracker update | `tests/test_flt3_tracking_output.py` (indirect) |
| 6720 | `update_flt3_qc_trends` | QC trends writer | none directly; called from `run_pipeline` |
| 6763 | `generate_flt3_bp_validation_report` | supplementary validation report | none |
| 6818 | `run_pipeline` | top-level orchestrator | `gui_qt/tabs/tab_flt3_validation.py`, `gui_qt/tabs/tab_archive_runner.py`, `scripts/run_flt3_rox500_qc_all_injections.py` |

---

## 4. Intentional tech debt (called out so we don't churn it)

- **`HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE` legacy flag**
  (`core/analyses/flt3/pipeline/_legacy.py:91`). Per
  `ObsidianVault/01_Project_Memory.md` FLT3 *Architecture*:
  > Python ladder-rescue/template fallback for FLT3 `GS500ROX` is
  > legacy opt-in only via `HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE`.
  Don't delete; keep.
- **Strict-Rust opt-in**
  (`core/engine_flags.py`). Per
  `ObsidianVault/01_Project_Memory.md` *Hygiene*:
  > Strict Rust ladder mode is opt-in with `HEMAFRAG_STRICT_RUST_LADDER=1`
  > …; it disables Python ladder fallback/rescue and clonality
  > multiprocessing so failures surface as skipped/reviewed files under
  > per-file timeout instead of hidden Python rescues.
  Keep.
- **29 `_gs500rox_*` review-band helpers** that exist purely to flag
  review candidates, never to auto-pass. Per FLT3 *Runner* note:
  > ROX500 QC runner supports `--exclude-run-name-contains` …
  > while requiring `3730`.
  Don't turn any of these into PASS gatekeepers without more
  annotation evidence (see plan 04).
- **Review-only `start_family_prior` family.** `pipeline/_legacy.py`
  applies the prior to the fitted ladder but does NOT let it auto-PASS
  unless the row stays inside narrow review-band; per session log
  this is currently narrow on purpose and must not be loosened
  blindly. Don't churn it without explicit annotation unlock.
- **`core/analyses/flt3/rox500_exclusions.py`** contains user-reviewed
  exclusion tuples with provenance strings
  (`operator_data_review_2026-05-26`, etc.). They are intended as a
  manually curated gate; do not auto-extend via ML or heuristics.
- **`core/analyses/flt3/__init__.py` is currently empty** (0 bytes).
  Phase 4 only filled `clonality/__init__.py`. Filling the FLT3 one
  would be cheap documentation hygiene — see Task 1 below.
- **Empty `core/analyses/__init__.py`** and `core/analyses/flt3/__init__.py`
  similarly stubby; same fix available.

---

## 5. Actionable task list (smallest/safest first)

### Task 1 — Documentation: give `flt3/__init__.py` a module docstring

- **Scope**: one file, ~20 lines added.
- **Why**: the directory currently has 0 bytes of package surface;
  a short docstring names the public submodules so new contributors
  see the contract.
- **Acceptance**: `core/analyses/flt3/__init__.py` reads as a
  module docstring listing the focused submodules. Existing tests
  unaffected.
- **Commit draft**:
  `docs(flt3): add package docstring to core/analyses/flt3/__init__.py`
- **Risk**: low.
- **Effort**: S.

### Task 2 — Documentation: give `core/analyses/__init__.py` a docstring

- **Scope**: same as Task 1 but for `core/analyses/`.
- **Why**: same as Task 1.
- **Acceptance**: docstring describing `core/analyses/{clonality, flt3, general}`
  + the shared `core/analyses/shared_pipeline.py`.
- **Commit draft**:
  `docs(analyses): add package docstring to core/analyses/__init__.py`
- **Risk**: low.
- **Effort**: S.

### Task 3 — Sub-split: extract `_legacy_flt3_run_pipeline` from the orchestrator

- **Scope**: currently `run_pipeline` (lines ~6818-end, plus the
  `_calculate_ratios`, `_summarize_detected_peaks`,
  `update_flt3_npm1_qc_tracker_workbook`, `update_flt3_qc_trends`,
  and report-writing functions) appear as separable roles inside one
  flat `_legacy.py`. Pull the report-writing helpers
  (`generate_flt3_peak_report`,
  `generate_flt3_bp_validation_report`,
  `update_flt3_npm1_qc_tracker_workbook`, `update_flt3_qc_trends`)
  into `_reports.py` inside `core/analyses/flt3/pipeline/`.
- **Why**: the four report functions together are ~600 lines and
  don't share local state with the rest; isolating them reduces the
  `_legacy.py` monolith meaningfully.
- **Acceptance**: a new `core/analyses/flt3/pipeline/_reports.py`
  carries those four functions; the `_legacy.py` re-exports them so
  the package facade still works; tests still 33/33.
- **Commit draft**:
  `refactor(flt3-pipeline): extract report-writing helpers to _reports.py`
- **Risk**: medium (touches exports — verify underscore-name consumers
  via `tests/test_flt3_*`).
- **Effort**: M.

### Task 4 — Sub-split: `_gs500rox_review.py` for the 29 review-band helpers

- **Scope**: lines ~3982-5500 of `pipeline/_legacy.py` are pure
  review-only ladder-family helpers; pull them into
  `core/analyses/flt3/pipeline/_gs500rox_review.py`.
- **Why**: the start-family learning code is the single largest
  cohesive group and was the main reason `_legacy.py` is 6904 lines.
- **Acceptance**: `_legacy.py` re-exports every `_gs500rox_*` name so
  the package facade doesn't break (`tests/test_flt3_gs500rox_start_family_review.py`
  and `tests/test_gs500rox_guardrail.py` exercise ~13 of them).
- **Commit draft**:
  `refactor(flt3-pipeline): extract GS500ROX start-family review helpers to _gs500rox_review.py`
- **Risk**: medium.
- **Effort**: L.

### Task 5 — Test gap: cover `run_pipeline` happy-path with synthetic FSA

- **Scope**: a new `tests/test_flt3_run_pipeline_smoke.py` that
  builds a fake `.fsa`-derived `FsaFile`-like mock (or uses a small
  synthetic trace fixture), runs `run_pipeline`, and asserts the
  output files exist and the workbook row count is non-zero.
- **Why**: today the FLT3 surface has no end-to-end test that
  exercises `run_pipeline`. The 8 `test_flt3_*` files cover
  individual helpers.
- **Acceptance**: new test passes; total tests count increases by 1
  to 34; existing tests still pass.
- **Commit draft**:
  `test(flt3): add run_pipeline smoke test with synthetic FSA`
- **Risk**: medium (depends on a fixture harness; the production code
  reads from real files).
- **Effort**: L.

### Task 6 — Hygiene: drop the unused `app.py` if Confirmed dead

- **Scope**: `app.py` at the repo root is 623 B, only referenced by
  `HemaFrag.spec:8` as a PyInstaller data file. If the spec file is
  actually unpacked into the runtime directory but the runtime never
  imports `app.py`, the line in the spec is dead.
- **Why**: Phase 1 left `app.py` and `app_meta.py` because they
  appeared to be imported; combing through `core/` and `gui_qt/` later
  shows no Pyhton imports of `app.py` at all.
- **Acceptance**: `grep -rn '^import app\\b\\|^from app\\b' --include='*.py' .`
  returns zero hits, AND the macOS x86 cross-built distributable
  launches reduce by ~620 B.
- **Commit draft**:
  `chore: drop dead root app.py + spec datas reference`
- **Risk**: medium (touches PyInstaller spec; verify packaging works).
- **Effort**: S.

### Task 7 — Latent issue: surface the silent ImportError swallow in `tab_flt3_validation.py`

- **Scope**: per Session_Log 2026-06-27, `gui_qt/tabs/tab_flt3_validation.py`
  imports three missing scripts under `try`:
  - `scripts/run_flt3_backfill_validation.py` (not present)
  - `scripts/run_flt3_rox500_qc_all_injections.py` (present, but
    imported even before this try).
  - `scripts/run_clonality_yearly` (clonality, not present)
  - `scripts/combine_clonality_yearly_overview` (clonality, not present)
  Each try sets `_FLT3_ARCHIVE_SUPPORT_AVAILABLE = False` and the
  feature is silently unavailable.
- **Why**: a user clicking these tabs gets no visible "feature not
  built yet"; they may instead think the app is broken.
- **Acceptance**: each `try` block restores `ImportError` raised by
  the missing optional import to either (a) log a one-line warning
  via `print_warning`, or (b) display a banner in the tab so the user
  knows the feature is parked. Tasks 2 in plan 03 schedules the
  TabArchiveRunner version of the same fix.
- **Commit draft**:
  `fix(gui): surface the silent ImportError fallback in tab_flt3_validation.py`
- **Risk**: low (additive; defaults unchanged).
- **Effort**: S.

### Task 8 — Test gap: trace-back test for `flt3_size_standard_mode` regression

- **Scope**: `tests/test_flt3_size_standard_contract.py` already
  covers the four corner cases — DATA4 / DATA105 / DATA5 fallback /
  parse failure. Ensure regression: lock the dict shape `{name, internal,
  channel}` to a snapshot test as a defensive measure against future
  silent channel-drift.
- **Why**: per Project Memory, channel drift between ROX500 and LIZ
  was the root cause of multiple bugs.
- **Acceptance**: a new assertion that snapshot-matches the returned
  dict shape for `("test.fsa", "GS500ROX")` and a few other cases.
- **Commit draft**:
  `test(flt3): lock flt3_size_standard_mode return shape with snapshot`
- **Risk**: low.
- **Effort**: S.

---

## Verification (self-check)

Commands run during review prep:

```
$ ls -la /workspace/hemafrag/core/analyses/flt3/
$ wc -l /workspace/hemafrag/core/analyses/flt3/*.py \
         /workspace/hemafrag/core/analyses/flt3/pipeline/*.py

   0  core/analyses/flt3/__init__.py
 208  core/analyses/flt3/classification.py
  77  core/analyses/flt3/config.py
 398  core/analyses/flt3/qc_tracker.py
  58  core/analyses/flt3/rox500_exclusions.py
  22  core/analyses/flt3/pipeline/__init__.py
  48  core/analyses/flt3/pipeline/_constants.py
6904  core/analyses/flt3/pipeline/_legacy.py
7715  total

$ grep -cE '^[A-Z_]+ *=' core/analyses/flt3/pipeline/_constants.py
2

$ grep -n '^def \|^class ' core/analyses/flt3/pipeline/_legacy.py | head -40
$ grep -n '^def \|^class ' core/analyses/flt3/pipeline/_legacy.py | tail -50

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
