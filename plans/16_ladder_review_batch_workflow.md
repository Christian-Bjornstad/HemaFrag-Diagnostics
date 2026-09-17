# Ladder Review Batch Workflow

## Scope

This work joins two operator workflows in the existing Run tab without adding a second persistence format:

1. Run an explicitly selected set of `.fsa` files, retain only analysis entries that actually require manual ladder review in the existing `ladder_review_cases.csv` bundle, open that queue in Ladder Studio, then rerun corrected linked jobs and compare the review files/results.
2. Stop an active batch safely and responsively without terminating worker threads, losing completed outputs, dropping review cases, or reporting unprocessed work as successful.

## Existing contracts to preserve

- `core.batch.generate_jobs` remains the single scanner/grouping path for folders and individual FSA paths.
- `core.batch.run_batch_jobs` remains the batch executor and writes the existing `hemafrag_batch_run_manifest_v1` ledger.
- `write_ladder_review_gate` remains the only review-queue writer; its CSV contains only entries whose ladder flags/status require review.
- Ladder Studio consumes the existing review bundle and persists its existing annotations/adjustment provenance.
- Review reruns remain linked to the parent manifest and rebuild reports from the preserved session cohort.
- Archive Runner continues discovering the same `ladder_review_cases.csv` bundles; no new queue database or sidecar convention is introduced.

## Implementation

### Operator-selected files and review workflow

- Permit individual `.fsa` paths for every analysis in the Run tab, matching `generate_jobs` capability.
- Keep the scanned job table as the explicit run selection boundary.
- Add a persistent review-workflow action area on Run that shows the exact review-only queue count and offers:
  - Open Review Queue in Ladder Studio.
  - Rerun corrected linked jobs and rebuild final reports using the existing session/parent-manifest path.
  - Load the queue files into Compare so failures and corrected results can be rerun side by side.
- Keep review rows visible until Ladder Studio resolves or excludes them; never infer review from generic job failure.

### Cooperative cancellation

- Add a caller-owned `threading.Event` cancellation token to `run_batch_jobs`.
- Schedule only up to the concurrency limit at a time. Once cancellation is requested, schedule no new jobs.
- Let active work stop only at safe cooperative boundaries/progress callbacks; never terminate a thread.
- Preserve entries and outputs from jobs that completed before cancellation.
- Still write a review bundle from completed entries so ladder-review cases are not lost.
- Skip final aggregate report publication for an incomplete cohort.
- Return and manifest explicit `cancelled`, `cancelled_jobs`, and `unprocessed_jobs` state. Completed, failed, cancelled, and unprocessed states are mutually honest; cancellation is never success.
- Keep the Qt Run tab responsive: Stop requests cancellation, immediately updates status, disables repeated Stop, and restores controls when the worker returns.

## Safety invariants

- A cancelled or never-started job is never listed as completed and never shown as successful.
- A partially completed run has a finalized manifest with cancellation status and per-job states.
- Completed job outputs and provenance remain on disk.
- Review entries discovered in completed work are written to the standard review bundle even when the overall run is cancelled.
- Final DIT aggregation is not published for a cancelled/incomplete cohort.
- Cancellation is cooperative only; no `terminate`, thread kill, or unsafe interruption is used.

## Verification

- Behavior regression: cancellation while one job is active prevents later scheduling, preserves the completed subset, records cancelled/unprocessed jobs, and finalizes the manifest honestly.
- Behavior regression: review bundle queue contains only entries requiring ladder correction and remains available after cancellation.
- Focused tests for the two contracts above.
- Headless Qt smoke: select explicit files, scan, start a controlled batch, request Stop, observe usable controls and honest row states; load the emitted review queue into Ladder Studio/Compare handoff paths.

## Ladder Studio precision and review-state workstream

This workstream is independent of the batch-cancellation implementation above. It hardens how an operator places ladder markers, persists partial mappings, and carries the result through reruns and generated editors.

### Phase L1 — Additive persisted marker contract

- Use `hemafrag_ladder_adjustment_v3` as the canonical write schema while continuing to normalize legacy unversioned, v1, and v2 payloads.
- Persist a stable identity for every marker together with the exact requested trace x, sampled intensity, source kind, assigned ladder step, and candidate index where one exists.
- Persist the expected, mapped, and missing ladder-step indices explicitly. `partial_mapping` is derived from those sets, not inferred from array length.
- Keep legacy index mappings readable, but normalize them at the persistence boundary so analysis code consumes one contract.

### Phase L2 — Exact placement and collision-safe editing

- Exact-marker mode preserves the operator's requested x. Fractional x values sample the raw trace deterministically by linear interpolation; only trace bounds may clamp the request.
- Two markers may occupy the same or nearby x positions and must retain distinct stable identities.
- A collision never silently toggles, replaces, or deletes a marker. The operator must choose a named existing marker, create a separate marker, or cancel.
- Reassigning a step or moving one marker between steps requires explicit confirmation.
- Deletion is distance-bounded and requires confirmation of the identified target.

### Phase L3 — Partial mapping semantics

- Fit only the observed anchors the operator assigned. Never synthesize missing anchors by interpolation or extrapolation.
- Require at least three strictly ordered anchors for a partial fit, with unique marker identities and monotonic expected sizes and trace positions.
- An unapproved partial mapping remains `review_required`.
- A partial mapping becomes rerunnable only after the operator explicitly approves it in Ladder Studio. It remains visibly `manual_partial_reviewed`, records its missing steps, and is not relabeled as a complete manual fit.
- Operator-approved partial fits remain ineligible for automatic ML training/acceptance.

### Phase L4 — Downstream provenance and generated editors

- Carry schema version, adjustment hash, stable marker identities, mapped/missing indices, partial status, and operator approval into analysis provenance, tracking output, dashboards, and report badges.
- Preserve the same marker contract in the interactive assay and QC HTML editors. Saved HTML must round-trip marker identity and exact requested x without narrowing an object payload to legacy x/y arrays.
- Existing array-only saved HTML remains loadable.

### Phase L5 — Guarded Rust rescue diagnostics and private-corpus gate

- Keep rescue search deterministic, budget bounded, and subject to the existing arbiter improvement margins; do not relax detection, QC, or acceptance thresholds.
- Emit an auditable arbiter record for each completed rescue: incumbent score, selected score, selected-over-incumbent improvement, required improvement, whether selection changed, runner-up margin, candidate count, expansions, and watchdog state.
- The diagnostic fields support a paired baseline/candidate benchmark on the private clinical corpus; they do not by themselves establish fewer manual fits.
- Before any rescue/arbiter behavior change is promoted, run the baseline and candidate on the same immutable, ladder-stratified private corpus. Promotion requires no newly wrong automatic ladder acceptance, no loss of currently correct accepted fits, deterministic repeat results, and a measured reduction in manual-review cases. Any threshold change is out of scope and requires a separate validated decision.
- Until that private-corpus gate passes, report the Rust work as diagnostic instrumentation only and make no claim that manual review has been reduced.

## Ladder safety invariants

- Marker identity, not rounded x or DataFrame row position, is the assignment key.
- Exact requested x survives save/load/rerun; plotting or trace sampling never rewrites it to a nearby detected peak.
- Missing ladder steps remain explicitly missing in persisted data, fit inputs, provenance, and operator-visible status.
- Partial approval is explicit, auditable, and distinct from complete-fit approval.
- Rerunning an operator-approved partial mapping does not re-open generic review solely because steps are missing; independent non-waivable QC failures may still require review.
- Legacy payload compatibility is additive: old readers are not simulated, and new readers never reinterpret a schema-only object as an integer-index mapping.
- Clinical performance claims require measured private-corpus evidence. Synthetic tests prove determinism and safety boundaries only.

## Ladder verification

- Focused Python regression tests cover legacy normalization, v3 round-trip, stable identities, exact fractional placement, same-x collisions, partial-fit anchor boundaries, monotonicity, approval state, and rerun provenance.
- Focused Rust tests cover deterministic bounded rescue behavior and the auditable promotion/non-promotion diagnostic record.
- Headless Qt smoke opens Ladder Studio with a synthetic trace, places distinct exact markers, assigns them, and observes a partial payload with exact x and stable identities.
- Browser smoke opens generated Plotly editor HTML, exercises collision choices and bounded deletion, and verifies the saved peak object retains stable identity and exact requested x.
- Full Python and Rust suites remain the final integration gate; private-corpus benchmarking remains a separate required clinical-validation gate.
