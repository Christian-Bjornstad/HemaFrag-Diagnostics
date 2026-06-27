# Plan 01 — FLT3 pipeline review

> Branch: `code-cleanup` (off `codex-clonality-ladder-finalize-2026-05-14`).
> Test baseline: `Ran 33 tests, OK` via
> `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests`.
> Reviewer responsibility: **real findings only**.

The FLT3 pipeline is the production-busy surface per
`ObsidianVault/01_Project_Memory.md` (Current Focus: FLT3; clonality
parked).

---

## 1. Architecture summary

- Top-level orchestration in `core/analyses/flt3/pipeline/_legacy.py`
  (6904 lines). Top-level orchestrator `run_pipeline` at line 6818
  builds entries, runs ratio calculation, writes reports.
- Mode routing by env + size-standard tokens: ROX500 → internal
  `GS500ROX` on `DATA4`; LIZ override → `DATA105`. Source:
  `flt3_size_standard_mode()` line 104 in
  `core/analyses/flt3/pipeline/_legacy.py`.
- Strict-Rust opt-in via `core/engine_flags.strict_rust_ladder_enabled`
  (per `ObsidianVault/01_Project_Memory.md` *Hygiene*).
- Review-only / proposal-only GS500ROX ladder start-family priors
  (~29 `_gs500rox_*` helpers) — never auto-pass without narrow review
  band, per `ObsidianVault/01_Project_Memory.md` *FLT3 Learning*.

## 2. File inventory (verbatim `wc -l`)

```
   0  core/analyses/flt3/__init__.py       (empty)
 208  core/analyses/flt3/classification.py
  77  core/analyses/flt3/config.py
 398  core/analyses/flt3/qc_tracker.py
  58  core/analyses/flt3/rox500_exclusions.py
  22  core/analyses/flt3/pipeline/__init__.py
  48  core/analyses/flt3/pipeline/_constants.py
6904  core/analyses/flt3/pipeline/_legacy.py
7715  total
```

## 3. Public-function table (curated)

| Line | Symbol | Role | External callers |
|------|------|------|------|
| 64   | `_flt3_requested_ladder` | env-driven ladder choice | none |
| 78   | `_flt3_uses_liz_ladder` | bool router | none |
| 82   | `_flt3_ladder_only_qc_mode` | scaffold ahead of pipeline | none |
| 91   | `_flt3_legacy_python_ladder_rescue_enabled` | reads `HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE` | none |
| 100  | `_flt3_gs500rox_rust_only_ladder_mode` | env gate | none |
| 104  | `flt3_size_standard_mode` (PUBLIC) | PLA channel contract | `tests/test_flt3_size_standard_contract.py`, `scripts/run_flt3_liz500_qc_all_injections.py`, `gui_qt/tabs/tab_flt3_validation.py` |
| 329  | `_scan_files` | case scan | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 888  | `_calculate_peak_area_fast` | peak-area math | `tests/test_flt3_area_baseline.py` |
| 921  | `_correct_peak_channel_traces` | raw-trace selection | `tests/test_flt3_area_baseline.py` |
| 1004 | `_build_peaks_from_rust_flt3_preview` | preview-peak assembly | `tests/test_flt3_area_baseline.py` |
| 3982-5507 | `_gs500rox_*` (~29 review-band helpers) | review-only priors | `tests/test_flt3_gs500rox_start_family_review.py`, `tests/test_gs500rox_guardrail.py` |
| 5581 | `_build_entry_from_candidate` | entry grouping | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6146 | `_calculate_ratios` | per-entry ratio math | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6177 | `_reportable_itd_mut_rows` | row filter | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6206 | `_summarize_detected_peaks` | summarise peaks | `scripts/run_flt3_liz500_qc_all_injections.py` |
| 6280 | `generate_flt3_peak_report` | write per-run CSV/XLSX/HTML/JSON | called from `run_pipeline` |
| 6708 | `update_flt3_npm1_qc_tracker_workbook` | tracker update | `tests/test_flt3_tracking_output.py` (indirect) |
| 6720 | `update_flt3_qc_trends` | QC trends writer | called from `run_pipeline` |
| 6763 | `generate_flt3_bp_validation_report` | supplementary validation report | none |
| 6818 | `run_pipeline` (PUBLIC) | top-level orchestrator | `gui_qt/tabs/tab_flt3_validation.py`, `scripts/run_flt3_rox500_qc_all_injections.py`, `gui_qt/tabs/tab_archive_runner.py` |

## 4. Intentional tech debt (do not churn)

- `HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE` — opt-in legacy escape
  hatch from Project Memory *FLT3 Architecture*. Keep.
- `HEMAFRAG_STRICT_RUST_LADDER=1` and friends — opt-in strict-Rust
  switch from Project Memory *Hygiene*. Keep.
- 29 `_gs500rox_*` review-band helpers — review-only priors; never
  auto-pass. Per Project Memory *FLT3 Learning* (curated annotation
  evidence) we must NOT loosen them blindly.
- `core/analyses/flt3/rox500_exclusions.py` — manually curated
  source-tracked exclusion tuples
  (`operator_data_review_2026-05-26`,
  `rox_tail_missing_after_3500_review_2026-05-26`, etc.).

## 5. Actionable task list

### Task 1 — Documentation: package docstring for `core/analyses/flt3/__init__.py`
- **Scope**: 1 file, ~20 lines of docstring.
- **Why**: 0-byte `__init__.py`; no contract surface.
- **Acceptance**: `core/analyses/flt3/__init__.py` lists its focused
  submodules in a module docstring.
- **Commit**: `docs(flt3): add package docstring to core/analyses/flt3/__init__.py`
- **Risk**: low.  **Effort**: S.

### Task 2 — Documentation: package docstring for `core/analyses/__init__.py`
- **Scope**: 1 file, ~15 lines.
- **Why**: same as Task 1; documents the `clonality`/`flt3`/`general`
  surface + `shared_pipeline.py`.
- **Acceptance**: docstring in place.
- **Commit**: `docs(analyses): add package docstring to core/analyses/__init__.py`
- **Risk**: low.  **Effort**: S.

### Task 3 — Sub-split: extract report-writing helpers
- **Scope**: 4 functions (`generate_flt3_peak_report` L6280,
  `generate_flt3_bp_validation_report` L6763,
  `update_flt3_npm1_qc_tracker_workbook` L6708,
  `update_flt3_qc_trends` L6720) into `pipeline/_reports.py`.
- **Why**: roughly 600 lines of narrowly-scoped output logic
  separable from the orchestration; reduces monolith.
- **Acceptance**: facade re-exports so external imports still work;
  tests still 33/33.
- **Commit**: `refactor(flt3-pipeline): extract report helpers to _reports.py`
- **Risk**: medium.  **Effort**: M.

### Task 4 — Sub-split: pull out `_gs500rox_review.py`
- **Scope**: lines ~3982-5500 of `pipeline/_legacy.py` (29 GS500ROX
  start-family review helpers) into a dedicated submodule.
- **Why**: this is the single largest cohesive group in the file
  (~1500 lines); explicit separation tracks its role.
- **Acceptance**: facade re-exports; review tests still pass.
- **Commit**: `refactor(flt3-pipeline): extract GS500ROX review helpers to _gs500rox_review.py`
- **Risk**: medium.  **Effort**: L.

### Task 5 — Test gap: end-to-end smoke for `run_pipeline`
- **Scope**: new `tests/test_flt3_run_pipeline_smoke.py` building a
  synthetic FSA-sourced mock and asserting the four report outputs
  exist after `run_pipeline`.
- **Why**: today only individual helper functions have tests;
  no wire-up test for the orchestrator.
- **Acceptance**: tests go 33 → 34.
- **Commit**: `test(flt3): add run_pipeline smoke test with synthetic FSA`
- **Risk**: medium (fixture harness work).  **Effort**: L.

### Task 6 — Hygiene: surface silent ImportError swallows in tab_flt3_validation.py
- **Scope**: the three `try: from scripts.* import *; except: ...` blocks
  in `gui_qt/tabs/tab_flt3_validation.py` (lines ~30-50). Today they
  silently mark features unavailable. Cross-reference: Plan 03 has the
  same pattern in `tab_archive_runner.py`.
- **Why**: user clicking those tabs gets no "feature parked" message.
- **Acceptance**: each swallow emits a one-line `print_warning` or
  the tab shows a parked-feature banner.
- **Commit**: `fix(gui): surface silent ImportError fallback in tab_flt3_validation.py`
- **Risk**: low.  **Effort**: S.

### Task 7 — Snapshot test: lock `flt3_size_standard_mode` shape
- **Scope**: extend `tests/test_flt3_size_standard_contract.py`
  with snapshot assertions for the returned dict shape across
  representative inputs.
- **Why**: Project Memory has multiple bugs rooted in
  ROX500/LIZ500 channel drift; lock the contract.
- **Acceptance**: tests run, dict shapes frozen.
- **Commit**: `test(flt3): snapshot-lock flt3_size_standard_mode shape`
- **Risk**: low.  **Effort**: S.

## 6. Verification

```
$ ls -la /workspace/hemafrag/core/analyses/flt3/
total 36
[output snipped — recorded earlier in the review run]

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

$ grep -n '^def \|^class ' core/analyses/flt3/pipeline/_legacy.py | head -40
$ grep -n '^def \|^class ' core/analyses/flt3/pipeline/_legacy.py | tail -50
[output captured at review time]

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
