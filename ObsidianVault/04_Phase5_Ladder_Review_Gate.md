# Phase 5 Ladder Review Gate

## Goal

Batch runs should produce analysis results first, then stop before final DIT reporting when ladder fits need review. The operator should get a clear review prompt, inspect/fix the relevant ladders in the app, save manual adjustments, rerun affected files, and only then build final DIT reports.

## Current Position

- Phase 4 is active: Rust ladder fitting now uses ladder-specific defaults, guarded repairs, LIZ reverse-DP, ROX full-span repair, and apex recentering.
- Phase 5 has started in shadow mode: batch runs now write a `ladder_review_gate` bundle when clonality entries contain `review_required`, `missing_ladder`, or ladder QC failure, and Qt shows a non-blocking review popup after batch completion.
- The broad reverse-DP validation completed on `2000` 2025/2026 files with `0` engine errors, `13` backend review flags, `26` soft-fails, and no wrong-ladder calls.
- Real-flow gate test passed on `25OUM12848_tcrgB__260825_F04_H9C0ZJBT.fsa`: shadow generated reports, blocking generated review-bundle/tracking workbook and no HTML.

## Proposed App Flow

1. User runs a normal clonality batch.
2. Backend analyzes all files and writes tracking-ready entries.
3. Backend writes `ASSAY_REPORTS/ladder_review_gate/ladder_review_cases.csv`.
4. If no review cases exist, DIT reports can be generated normally.
5. If review cases exist, Qt shows a popup: `X files need ladder review before DIT reports`.
6. Popup actions:
   - `Open Ladder Review`: opens Ladder Studio with the review bundle loaded.
   - `Build Reports Anyway`: allowed only in shadow mode or with explicit override.
   - `Stop Here`: keeps analysis outputs but skips final DIT report generation.
7. User fixes ladders in the ladder editor and saves `.ladder_adj.json`.
8. App reruns only affected files or reruns the batch/report step.
9. Final DIT reports are generated only when unresolved critical review cases are cleared.

## Data Contract

`ladder_review_cases.csv` should be the shared contract between backend, Qt app, and review tools.

Required fields:
- `full_path`
- `file`
- `source_run_dir`
- `assay`
- `ladder`
- `ladder_qc_status`
- `ladder_review_required`
- `primary_reason`
- `reason_codes`
- `review_summary`
- `linear_max`
- `linear_mean`
- `linear_r2`
- `expected_count`
- `fitted_count`
- `fit_strategy`
- `suggested_action`
- `label`
- `label_note`
- `reviewed_at_utc`
- `adjustment_path`

`full_path` must always point to the original `.fsa`, not the temporary staged symlink. The clonality pipeline stores this as `original_file_path` before staging cleanup.

## Implementation Plan

### Step 1: Shadow Artifact

Implemented first because it is safe and additive. `core.batch.run_batch_jobs(...)` writes a review bundle under the aggregated output folder, but does not block DIT generation yet.

### Step 2: Qt Popup

Implemented in shadow mode. After `TabBatch._on_run_finished(...)`, the app inspects `result["ladder_review_gate"]`. If `review_case_count > 0`, it shows a `QMessageBox` with `Open Ladder Review` and `Continue`.

### Step 3: Bundle Handoff

Implemented first handoff. `gui_qt/tabs/tab_ladder.py` supports `load_review_bundle_from_path(...)`, so the batch popup can switch to Ladder Studio and preload `ladder_review_cases.csv`.

### Step 4: Deferred Report Build

Use existing batch flags:
- `defer_dit_html_reports=True`
- `skip_html_reports=True`
- `tracking_excel_path`

The gated workflow should first run analysis with DIT HTML deferred, then generate final reports after review is complete.

### Step 5: Hard Gate

Hard-gate plumbing is implemented but defaulted off:
- block final DIT HTML when unresolved critical ladder cases exist
- allow override only with explicit user action
- keep missing human-added ladder cases as operator errors, not motor failures

The helper `count_unresolved_review_cases(...)` is implemented for this later gate. A case is considered resolved when `label` is `manual_adjusted` or `reviewed_no_change`.

Current config default:
- `enabled=True`
- `mode=shadow`
- `block_dit_reports=False`
- `allow_continue_anyway=True`

When review-gate is enabled, batch disables streaming DIT generation so the gate can inspect all entries before report generation. When `block_dit_reports=True`, it then skips final DIT HTML if review cases exist. Tracking workbook generation is still allowed.

## Acceptance Criteria

- No change to default results in shadow mode except extra review-gate files.
- Review bundle opens directly in Ladder Studio.
- Manual `.ladder_adj.json` files are picked up on rerun.
- Final DIT reports can be rebuilt after review without rerunning unrelated jobs.
- Broad benchmark remains stable: no engine errors, no wrong-ladder calls, and no regression on known good files.

## Next Work

- Report rebuild after review is now present through Run-tab session finalization: reviewed files are rerun in linked job context, cached session entries are merged, and final DIT/tracking is built from the whole session.
- The finalization button now requires the whole loaded review bundle to be resolved before building final DIT reports. A partially reviewed bundle shows `Finish Ladder Review (N left)` instead of allowing a premature build.
- Next: test one real run-day with shadow popup, review-bundle handoff, manual edits, and `Run Manual Fixes + Build DIT`.
- Then test `block_dit_reports=True` on a copied output folder before using it in routine production.
