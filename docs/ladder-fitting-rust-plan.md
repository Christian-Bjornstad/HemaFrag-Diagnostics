# Rust Ladder-Fitting Performance, Quality, and Fallback Plan

Status: Executed through Rust-owned bounded rescue; partial-anchor Tier C remains a guarded follow-up
Scope: ROX400HD and LIZ500_250 ladder fitting
Primary implementation: `fraggler-v2/crates/fraggler-core/src/primitives.rs`
Runtime integration: `core/rust_bridge/_legacy.py` and `core/analysis/_legacy.py`

## Execution outcome (2026-07-30)

Implemented and verified:

- Manifest-driven deterministic benchmark runner with engine-stage timings and optional manual-gold comparison.
- Removed the redundant second full LIZ fit.
- Reused duplicate LIZ peak detection and peak-feature lookup work.
- Fixed three ladder-rescue paths that incorrectly sourced candidates from the biological sample trace.
- Added conservative bounded-first LIZ search with an exact-search audit mode.
- Added conservative early acceptance that skips the large repair cascade only for strong, complete LIZ fits.
- Added Rust-native reduced-pool and relaxed-beam rescue tiers with serialized `search_tier` metadata.
- Added a non-waivable baseline-noise review gate. Selected anchors now expose baseline-like, cleaner-neighbor, and strong-baseline counts.
- Added a Python-bridge guardrail that refuses downstream ladder hydration when two or more selected anchors have strong baseline-noise signatures. Saved manual adjustments remain usable.
- Added a capped full-pool beam audit mode (`HEMAFRAG_LADDER_AUDIT_CAPPED_FULL_POOL_BEAM=1`). It remains shadow-only because it changed five unreviewed anchor sets.
- Made Rust-owned ladder selection the default. Legacy Python anchor selection is now an explicit emergency compatibility mode via `HEMAFRAG_ENABLE_PYTHON_LADDER_FALLBACK=1`.
- Propagated the Rust search tier into application result entries and analysis provenance.

Release-gate results:

| Gate | Result |
|---|---:|
| Release corpus | 75 files: 50 LIZ, 25 ROX |
| Anchor changes versus the preceding targeted-repair build | 0 / 75 |
| LIZ engine median | 28.3 ms |
| LIZ engine p95 | 101.0 ms |
| LIZ end-to-end median | 73.8 ms |
| LIZ end-to-end p95 | 146.8 ms |
| ROX engine median | 18.9 ms |
| ROX engine p95 | 26.8 ms |
| Release-corpus review results | 1 LIZ, 0 ROX |
| Manual gold | 2 exact matches; 1 match within one scan |
| Determinism | Passed |
| Rust tests | 91 passed, 1 intentionally ignored |
| Full Python application/regression suite | 519 passed, 3 skipped |

The original LIZ baseline was 1.74 seconds mean on the initial five-file sample. The release corpus now meets the proposed sub-150 ms median and sub-400 ms p95 engine targets with wide margin.

One item is intentionally not marked complete: synthesizing a partial anchor-to-base-pair assignment when Rust cannot establish a trustworthy full sequence. Returning a guessed partial sizing model could contaminate downstream clinical sizing. The implemented production behavior instead exhausts bounded Rust rescue, preserves explicit tier/review metadata for valid full fits, and reports an explicit failure when no hydratable Rust result exists. It never silently substitutes Python anchors. A future partial Tier C should be added only with reviewed partial-fit gold fixtures and UI/report support that prevents downstream automatic interpretation.

## 1. Objective

Improve ladder fitting so that:

- LIZ500_250 approaches ROX400HD runtime without sacrificing fit quality.
- Known difficult ladders require fewer manual corrections.
- Every accepted fit has explicit, inspectable confidence and QC evidence.
- Rust owns both the primary algorithm and the operational fallback path.
- Python remains available as an optional reference/shadow implementation, not the normal fallback.
- Results remain deterministic and reproducible.

The work must be delivered incrementally. Output-preserving performance changes come first, followed by correctness fixes, algorithm improvements, and finally fallback-policy changes.

## 2. Current measured baseline

A small real-data benchmark was run against ten 2026 clonality FSA files using the release Rust CLI.

| Ladder | Files | Mean runtime | Observed range | Expected steps |
|---|---:|---:|---:|---:|
| LIZ500_250 | 5 | 1.74 s | 1.13–2.54 s | 16 |
| ROX400HD | 5 | 70 ms | 65–84 ms | 21 |

This is approximately a 25× runtime difference. The difference is not caused by LIZ having more expected ladder steps; it has fewer.

The ROX measurement includes CLI and artifact overhead. In-process measurements can be lower, which is consistent with observed ROX runtimes around 20 ms.

### Evidence from candidate evaluation

Several ROX files estimated roughly one million possible combinations but evaluated only 192 bounded beam finalists and completed in approximately 65–84 ms.

One LIZ file also evaluated only 192 beam finalists but took approximately 1.13 seconds. This shows that the fixed LIZ repair and rescue work is a major cost independent of the initial beam size.

Other LIZ examples evaluated between roughly 4,000 and 51,000 combinations and took 1.27–2.54 seconds.

## 3. Root causes identified

### 3.1 Redundant full LIZ execution

`build_ladder_fit_preview_with_arbiter` calculates an initial fit and then performs a final fit with `allow_visual_start_repair = true`.

The visual-start repair is ROX-specific. LIZ therefore repeats its deterministic fitting and repair pipeline without receiving the intended benefit of the second pass.

Relevant location:

- `fraggler-v2/crates/fraggler-core/src/primitives.rs`
- `build_ladder_fit_preview_with_arbiter`
- Current final-preview call near line 3206

This is the safest first optimization because the second LIZ calculation should be removable without changing its output.

### 3.2 LIZ performs multiple broad and exact searches

The LIZ path may execute:

- The original candidate-pool search.
- A filtered candidate-pool search.
- Exact reruns for suspicious fits.
- Tail-augmented candidates.
- Blob-oriented candidates.
- Broad candidates.
- Local anchor-grid augmentation.
- Weak-anchor-grid augmentation.
- Apex recentering.
- Multiple family and local repair routines.

Important current bounds include:

- Beam width: 192.
- Beam final cap: 4,096.
- Maximum candidate combinations: 2,000,000.
- LIZ exact-rerun maximum: 600,000.

The expensive paths are conditionally triggered, but a large repair sequence is still evaluated after candidate selection.

### 3.3 Sequential repair cascade

`select_best_combination` calls many specialized repair functions in sequence. Most functions return quickly when the ladder type or trigger does not match, but the LIZ-specific sequence still contains numerous overlapping searches and repeated scoring.

Relevant location:

- `fraggler-v2/crates/fraggler-core/src/primitives.rs`
- `select_best_combination`, currently near line 15660

The repair pipeline does not have a strong early-accept boundary for an already trustworthy initial LIZ fit.

### 3.4 Likely wrong-trace correctness defect

Three LIZ rescue blocks perform corrected-trace generation and candidate detection from `sample_trace`:

- Near line 3934.
- Near line 4054.
- Near line 4100.

These blocks are part of ladder-candidate rescue. They should use `ladder_trace`, not the biological sample channel.

Potential consequences:

- Sample peaks can enter the ladder candidate pool.
- Results can depend on sample-channel biology rather than only the size standard.
- A mathematically smooth but physically incorrect ladder may be selected.
- Some manually corrected cases may originate from cross-channel contamination.

The use of `sample_trace` remains correct when fitting the final sizing model and mapping sample peaks. Only ladder peak detection/rescue should be changed to `ladder_trace`.

### 3.5 Operational fallback still reaches Python

The runtime currently has Rust transport fallbacks:

1. In-process native wheel.
2. Persistent Rust worker where supported.
3. Standalone Rust CLI.

However, when Rust produces no accepted/hydratable ladder result, the analysis layer can still fall back to Python ladder fitting unless strict Rust mode is enabled.

Relevant locations:

- `core/rust_bridge/_legacy.py::run_ladder_fit_hybrid`
- `core/analysis/_legacy.py::analyse_fsa_liz`
- `core/analysis/_legacy.py::analyse_fsa_rox`

Transport fallback and algorithm fallback must be treated separately:

- Transport fallback answers: “How do we run Rust?”
- Algorithm fallback answers: “What does Rust do when its primary fit is uncertain?”

The target architecture keeps the existing Rust transport chain and adds a complete Rust-native algorithm fallback chain.

## 4. Target architecture

### Tier A: Fast Rust fit

Use a bounded, template-aware candidate graph/beam:

- Expected ladder gap pattern.
- Scan-time domain.
- Peak height and prominence.
- Local baseline and peak purity.
- Monotonicity.
- Polynomial/spline residuals.
- Start and tail plausibility.

Keep more than one finalist so confidence can include the margin between the best and second-best candidates.

Tier A should accept only when all high-confidence gates pass.

### Tier B: Robust Rust rescue

Run only if Tier A is incomplete, low-confidence, or fails a specific QC rule.

Possible Tier B components:

- Alternative baseline-correction lanes.
- Wider but still bounded beam.
- Template-constrained local anchor substitution.
- Targeted start, middle, or tail repair selected from reason codes.
- Limited exact search only when the candidate space is small enough.

Every Tier B operation must have an explicit work budget.

### Tier C: Partial Rust fit requiring review

If a full high-confidence ladder cannot be recovered:

- Return the best usable monotonic Rust fit.
- Preserve the expected ladder definition.
- Explicitly report missing/unresolved steps.
- Provide selected anchors and rejected alternatives.
- Mark the result as mandatory review.
- Do not silently treat the result as a normal full fit.

This tier should allow the user to repair a small number of anchors rather than restarting from an unrelated Python result.

### Optional Python shadow

Python may run when explicitly enabled for:

- Development comparison.
- Release validation.
- Diagnosing disagreements.
- Producing parity statistics.

Python shadow output must not replace Rust output automatically in production.

## 5. Execution plan

## Phase 0 — Baseline preservation and observability

Goal: Make performance and behavior measurable before changing the algorithm.

### Tasks

- [ ] Add a reproducible ladder benchmark command or script.
- [ ] Support explicit input manifests so the same files are used between runs.
- [ ] Record total Rust ladder time separately from ABIF parsing, reporting, and process startup.
- [ ] Add timings for:
  - [ ] Channel selection and ABIF extraction.
  - [ ] Baseline correction per lane.
  - [ ] Peak detection and candidate merging.
  - [ ] Initial combination generation.
  - [ ] Combination scoring.
  - [ ] Exact reruns.
  - [ ] Broad/blob/tail rescue lanes.
  - [ ] Each repair family or repair category.
  - [ ] Final sizing-model construction.
  - [ ] Review assessment.
- [ ] Record:
  - [ ] Candidate-pool size.
  - [ ] Estimated combinations.
  - [ ] Evaluated combinations.
  - [ ] Beam width/finalist count.
  - [ ] Selected tier.
  - [ ] Repair actions attempted and accepted.
  - [ ] Final selected scan indices.
  - [ ] QC metrics.
  - [ ] Best-versus-second-best score margin.
  - [ ] Review reason codes.
- [ ] Ensure instrumentation can be disabled or has negligible production overhead.
- [ ] Freeze baseline outputs for the initial validation corpus.

### Deliverables

- Benchmark runner.
- Machine-readable JSON or CSV results.
- Baseline summary split by ladder and difficulty group.
- Frozen anchor/QC output for regression comparison.

### Exit gate

- The benchmark is deterministic across repeated runs.
- Every major LIZ search stage has visible timing.
- Baseline anchor identities can be compared automatically.

## Phase 1 — Validation and gold corpus

Goal: Measure quality using representative real files, not only synthetic unit tests.

### Corpus groups

- [ ] Normal high-confidence ROX400HD.
- [ ] Normal high-confidence LIZ500_250.
- [ ] LIZ files with dense early blobs.
- [ ] LIZ files with weak 35/50 bp anchors.
- [ ] LIZ files with weak middle triplets.
- [ ] LIZ files with weak or split tail peaks.
- [ ] Candidate-space-capped files.
- [ ] High-curvature or poor-linear-trend files.
- [ ] Files that previously required manual adjustment.
- [ ] Files where Rust and Python disagree.
- [ ] Negative/invalid size-standard traces.

### Gold hierarchy

Use the strongest available truth source in this order:

1. Saved manual ladder correction reviewed by a user.
2. Explicitly reviewed ladder anchor annotation.
3. Accepted historical result with strong QC and visual confirmation.
4. Stable consensus between multiple algorithm versions.

Automatic QC alone is not sufficient truth for difficult cases.

### Tasks

- [ ] Locate and export all available manual ladder adjustments.
- [ ] Preserve source-file hashes rather than relying only on paths.
- [ ] Store expected ladder, expected channel, selected scans, and review notes.
- [ ] Stratify the larger 2026 data collection by assay and difficulty.
- [ ] Create a smaller fast development set and a larger release set.
- [ ] Keep the release set independent from threshold tuning where possible.

### Exit gate

- All known manually corrected files are represented.
- Both ladder types and major failure modes are covered.
- Gold records are versioned and reproducible.

## Phase 2 — Safe output-preserving performance patch

Goal: Remove unnecessary work without intentionally changing fitted anchors.

### Tasks

- [ ] Skip the second/final full preview for LIZ when the only changed option is ROX visual-start repair.
- [ ] Preserve the second pass for ROX400HD where required.
- [ ] Compute guarded, quantile, morphological, SNIP, and other corrected traces at most once per file/lane.
- [ ] Reuse corrected traces across LIZ rescue paths.
- [ ] Reuse peak-feature maps instead of rebuilding identical `BTreeMap` values.
- [ ] Avoid rebuilding identical filtered candidate pools.
- [ ] Avoid recalculating identical scores and sizing models for unchanged anchor sequences.
- [ ] Add regression tests proving selected LIZ anchors and QC values remain bit-identical for this phase.

### Expected result

Removing the redundant full LIZ pass should provide a material improvement immediately. A rough expectation is a 35–50% LIZ runtime reduction, subject to instrumentation results.

### Exit gate

- Exact selected-anchor equality against the Phase 0 baseline.
- No QC or review-status changes.
- Deterministic output.
- Statistically meaningful LIZ runtime improvement.

## Phase 3 — Wrong-trace correctness fix

Goal: Ensure every ladder candidate comes from the ladder/size-standard channel.

### Tasks

- [ ] Replace ladder-rescue use of `sample_trace` with `ladder_trace` at all identified locations.
- [ ] Audit every peak-candidate function call for channel ownership.
- [ ] Introduce clearer parameter naming or types to prevent future channel confusion.
- [ ] Consider a `LadderSignals` structure containing raw and corrected ladder lanes.
- [ ] Keep `sample_trace` only for sample mapping after ladder anchors are selected.

### Tests

- [ ] Construct a sample channel with strong peaks absent from the ladder channel.
- [ ] Prove those peaks cannot become ladder anchors.
- [ ] Change sample-channel biology while keeping the ladder trace fixed.
- [ ] Prove the fitted ladder anchors remain identical.
- [ ] Verify sizing/sample mapping can still change appropriately after the ladder is fixed.
- [ ] Run all real difficult LIZ files through before/after comparison.

### Exit gate

- No accepted anchor is sourced only from the sample channel.
- Gold-set agreement is non-inferior.
- Any changed real-data fit is reviewed and explained.

## Phase 4 — High-confidence fast acceptance

Goal: Stop after the initial bounded fit when further repair work is unlikely to improve correctness.

### Candidate acceptance inputs

- Full expected step count.
- Strict monotonic scan ordering.
- No duplicate scan indices.
- Scan-domain plausibility.
- First and last anchor plausibility.
- Linear trend R².
- Linear mean and maximum absolute error.
- Final spline/polynomial mean and maximum error.
- Curvature.
- Gap-template deviation.
- Peak height/prominence consistency.
- Baseline-like or foot-like peak count.
- Candidate-generation capped status.
- Best-versus-second-best score margin.

### Tasks

- [ ] Implement a ladder-specific confidence assessment.
- [ ] Separate “QC good” from “candidate identity unambiguous.”
- [ ] Require both for fast acceptance.
- [ ] Emit confidence level and individual reason codes.
- [ ] Add an audit mode that continues rescue after fast acceptance and reports whether rescue would have changed the result.
- [ ] Use audit data to tune conservative thresholds.

### Safety rule

Do not accept solely because a polynomial has excellent residuals. A shifted or biologically implausible anchor family can also fit a smooth curve.

### Exit gate

- Fast-accepted gold files match reviewed anchors.
- Audit mode shows negligible beneficial changes after fast acceptance.
- False acceptance does not increase.

## Phase 5 — Failure-directed repair pipeline

Goal: Replace the unconditional LIZ repair chain with targeted, bounded work.

### Failure categories

- Early/start-family ambiguity.
- Blob-contaminated start.
- Weak 35/50 bp anchors.
- Middle-triplet outlier.
- Weak/baseline-like individual anchor.
- Tail-pair split or missing tail.
- Broad global mismatch.
- Candidate space capped.
- High residual without obvious local defect.

### Tasks

- [ ] Map every existing LIZ repair function to one or more failure categories.
- [ ] Remove duplicate repair calls.
- [ ] Establish an explicit order within each category.
- [ ] Run only categories indicated by diagnostics.
- [ ] Add per-category candidate and time budgets.
- [ ] Keep a global per-file work budget.
- [ ] Stop when a repair reaches high-confidence acceptance.
- [ ] Compare candidates through one central deterministic arbiter.
- [ ] Require material improvement, not only tiny score changes.
- [ ] Preserve the original candidate as a finalist for regression protection.

### Refactoring target

The final code should express policy centrally rather than embedding policy across many independent repair functions.

Suggested concepts:

- `FitDiagnostics`
- `FailureReason`
- `RepairTier`
- `SearchBudget`
- `FitCandidate`
- `FitConfidence`
- `CandidateArbiter`

### Exit gate

- Existing repair capabilities remain covered by tests.
- Duplicate/untriggered work is eliminated.
- Quality is non-inferior on the gold and release corpora.
- LIZ p95 runtime improves materially.

## Phase 6 — Rust-native robust fallback

Goal: Remove Python as the normal algorithm fallback.

### Tier A implementation

- [ ] Bounded primary candidate search.
- [ ] Ladder-template-aware beam state.
- [ ] Maintain top K distinct candidate families.
- [ ] Produce confidence and diagnostics.

### Tier B implementation

- [ ] Generate alternative ladder lanes once.
- [ ] Use a wider but hard-bounded beam.
- [ ] Select targeted repair categories.
- [ ] Permit exact enumeration only below a configured bound.
- [ ] Enforce maximum candidate and time budgets.
- [ ] Preserve deterministic ordering and tie-breaking.

### Tier C implementation

- [ ] Support partial monotonic anchor assignment.
- [ ] Record exactly which expected steps are missing.
- [ ] Fit only when the retained anchors support a stable model.
- [ ] Mark the result as mandatory review.
- [ ] Expose nearby alternatives for manual correction.
- [ ] Ensure downstream analysis cannot mistake the result for a full automatic fit.

### Returned metadata

Every Rust result should expose:

- Ladder kind.
- Size-standard channel.
- Fallback/search tier.
- Selected scan indices.
- Expected base pairs.
- Missing steps.
- Candidate-pool and search counts.
- Accepted repairs.
- QC metrics.
- Confidence level.
- Confidence/review reason codes.
- Best-versus-second-best margin.
- Per-stage timing.

### Exit gate

- All valid gold files produce either:
  - A correct accepted full Rust fit, or
  - A usable Rust review result with explicit uncertainty.
- Rust failure does not silently turn into a Python-selected ladder.

## Phase 7 — Runtime fallback-policy migration

Goal: Make Rust the operational source of truth while retaining safe deployment controls.

### Desired runtime order

1. In-process Rust wheel.
2. Persistent Rust worker.
3. Standalone Rust CLI.
4. Rust Tier A/B/C algorithm result.
5. Explicit failure/review if Rust cannot provide a usable result.

Python shadow is separate and optional.

### Tasks

- [ ] Distinguish Rust transport failure from Rust low-confidence fit.
- [ ] Do not rerun the same Rust algorithm through multiple transports after a valid low-confidence result.
- [ ] Add a setting for Python shadow comparison.
- [ ] Store Rust/Python disagreements without replacing the Rust result.
- [ ] Add telemetry for transport and algorithm fallback tiers.
- [ ] Update strict-Rust behavior and messages to reflect Tier C review results.
- [ ] Update tests that currently expect automatic Python fallback.
- [ ] Keep a temporary emergency compatibility flag during rollout.

### Exit gate

- Default production processing never silently changes from Rust anchors to Python anchors.
- Failures and review-required results are explicit.
- The compatibility switch is documented and removable.

## Phase 8 — Verification and release gates

### Correctness tests

- [ ] Ladder-size definitions match between Rust and Python configuration.
- [ ] Channel selection is correct for every supported assay.
- [ ] Anchor indices are strictly increasing.
- [ ] Expected base pairs are strictly increasing.
- [ ] No duplicate anchors.
- [ ] No sample-only peak can become a ladder anchor.
- [ ] Complete and partial fits are distinguishable.
- [ ] Review flags survive bridge hydration and reporting.

### Determinism tests

- [ ] Repeated same-process runs.
- [ ] Fresh-process runs.
- [ ] Wheel versus worker versus CLI.
- [ ] Different worker counts.
- [ ] Debug and release builds where practical.

### Regression tests

- [ ] Exact selected-anchor comparison.
- [ ] Manual-gold agreement.
- [ ] QC comparison.
- [ ] Review-status comparison.
- [ ] Downstream base-pair mapping comparison.
- [ ] Clonality/FLT3 output smoke tests.

### Performance tests

Report separately:

- In-process engine-only ladder time.
- Full Rust primitive-analysis time.
- Worker transport time.
- CLI cold-start time.
- Batch throughput.

Report median, p90, p95, p99, maximum, and timeout count by ladder and difficulty group.

### Proposed release gates

Quality gates:

- Zero unexplained regressions against manually corrected gold anchors.
- No increase in known false automatic acceptances.
- Manual correction rate must not increase.
- Review-required rate must not increase unless new reviews expose previously silent incorrect fits.
- Downstream sizing changes must be traceable to reviewed ladder improvements.

Performance gates:

- Initial goal: LIZ median below 150 ms in-process.
- Initial goal: LIZ p95 below 400 ms in-process.
- No meaningful ROX regression.
- No unbounded search path.
- No production timeouts in the release corpus.

These runtime targets may be revised after Phase 0 establishes precise engine-only measurements.

## 6. Testing strategy

### Rust unit tests

Add focused tests near the primitive ladder implementation for:

- Duplicate-pass avoidance.
- Trace ownership.
- Confidence assessment.
- Failure classification.
- Repair routing.
- Search budgets.
- Candidate arbitration.
- Partial fit representation.
- Deterministic tie-breaking.

### Rust integration tests

Use manifest-driven real or de-identified fixture sets where repository policy permits. Verify serialized engine contracts as well as internal structures.

### Python bridge tests

Cover:

- Full accepted Rust fit hydration.
- Tier B fit hydration.
- Tier C partial/review fit hydration.
- Rust transport failure.
- Optional Python shadow mode.
- Absence of automatic Python replacement.
- Metadata propagation into tracking and reports.

### Application tests

Verify:

- Manual ladder UI displays missing and alternative anchors.
- Review gate recognizes Tier C.
- Tracking workbooks retain tier, confidence, and reasons.
- Reports do not claim a partial ladder is complete.
- Existing manual adjustments still load and apply.

## 7. Benchmark design

### Development benchmark

A small, fast set used continuously:

- At least 10 normal ROX files.
- At least 10 normal LIZ files.
- At least 10 difficult LIZ files covering different failure categories.
- Every available manual gold case if the set remains small enough.

### Release benchmark

A larger stratified sample from the available 2026 collection:

- Assay-balanced.
- Ladder-balanced where possible.
- Instrument/run-date diversity.
- Duplicate injections tracked separately.
- Difficulty strata based on baseline metrics and review reasons.

### Benchmark identity

Each result must include:

- Source SHA-256.
- File name for human inspection.
- Ladder and channel.
- Engine version/commit.
- Build profile.
- Runtime surface: wheel, worker, or CLI.
- Selected anchors and QC digest.

## 8. Data and privacy

- Do not commit patient-identifying FSA file names or paths into public fixtures.
- Prefer source hashes and de-identified fixture IDs.
- Keep local benchmark manifests outside version control if they contain sensitive paths.
- Commit only synthetic or explicitly approved de-identified test data.
- Manual-review notes must be sanitized before inclusion in repository fixtures.

## 9. Rollout strategy

### Stage 1: Instrumentation only

Collect baseline timing and quality data without changing decisions.

### Stage 2: Output-preserving optimization

Deploy redundant-pass removal and caching after exact-output regression checks.

### Stage 3: Shadow correctness and confidence

Run corrected trace ownership, confidence scoring, and targeted repairs in shadow comparison mode.

### Stage 4: Rust fallback shadow

Produce Tier A/B/C decisions but retain current operational behavior while disagreements are reviewed.

### Stage 5: Rust-owned production fallback

Make Rust Tier A/B/C operational. Keep Python shadow and emergency compatibility settings temporarily.

### Stage 6: Remove compatibility fallback

Remove or disable the automatic Python ladder fallback after the release corpus and real production monitoring pass.

## 10. Implementation order

Execute work in this order:

1. Phase 0 benchmark and observability.
2. Phase 1 validation/gold corpus.
3. Phase 2 output-preserving speed patch.
4. Phase 3 wrong-trace correctness fix.
5. Phase 4 confidence-based fast acceptance.
6. Phase 5 failure-directed repairs.
7. Phase 6 Rust-native fallback tiers.
8. Phase 7 runtime fallback-policy migration.
9. Phase 8 full verification and release.

Do not combine Phase 2 and Phase 3 into one unreviewed result comparison. Phase 2 should first prove that the performance optimization is output-preserving. Phase 3 can then intentionally change incorrect rescue behavior with isolated evidence.

## 11. Definition of done

The project is complete when:

- [ ] LIZ fitting meets the agreed median and p95 targets.
- [ ] ROX performance and quality are not regressed.
- [ ] All manually corrected gold cases pass or produce justified review results.
- [ ] Ladder candidate generation never uses the biological sample trace.
- [ ] High-confidence fits avoid unnecessary repair searches.
- [ ] Difficult fits use bounded, targeted Rust rescue.
- [ ] Rust can return an explicit usable partial/review fit.
- [ ] Python is not the automatic operational ladder fallback.
- [ ] Wheel, worker, and CLI produce deterministic equivalent results.
- [ ] Reports and tracking expose tier, confidence, missing steps, and reason codes.
- [ ] Unit, integration, bridge, application, and real-data release gates pass.
- [ ] Runtime and quality changes are documented with before/after benchmark results.

## 12. Progress log

Update this section as phases are completed.

| Date | Phase | Change | Quality result | Performance result | Decision |
|---|---|---|---|---|---|
| 2026-07-30 | Investigation | Mapped LIZ/ROX paths and benchmarked 5 real files per ladder | No source changes | LIZ 1.74 s mean; ROX 70 ms mean | Plan approved for execution |
| 2026-07-30 | 0–3 | Added benchmark/timings, removed duplicate work, fixed ladder-trace ownership | No anchor changes on 20-file comparison; sample-trace independence test added | LIZ median reduced by about 70% after safe patch | Accepted |
| 2026-07-30 | 4–5 | Added bounded acceptance, exact audit, and targeted repair fast path | Targeted versus full-repair audit: 0/75 anchor changes | LIZ engine median 28–33 ms across final audits | Accepted |
| 2026-07-30 | 6–7 | Added reduced-pool/relaxed-beam Rust rescue, search-tier provenance, Rust-owned runtime policy | 0/75 final anchor changes; manual gold 2 exact and 1 within one scan | LIZ engine median 28.3 ms, p95 101.0 ms | Accepted; guessed partial Tier C deferred |
| 2026-07-30 | 8 | Ran Rust contract/unit tests and the full Python application/regression suite | 90 Rust tests and 518 Python tests passed; 3 Python tests skipped | No ROX regression observed | Ready for application-level user acceptance |
| 2026-07-30 | Baseline guard | Made strong baseline-noise signatures non-waivable, exposed signal-quality counts, and rejected hydration at two strong-baseline anchors | 0/75 production anchor changes; full-repair audit 0/75 changes; manual gold unchanged; one existing difficult LIZ review is now blocked from downstream hydration | LIZ engine median 29.7 ms, p95 97.9 ms | Accepted |
| 2026-07-30 | Full-pool beam audit | Tested bounded full-pool beam instead of candidate-pool thinning | Changed 5/75 unreviewed anchor sets; reduced the difficult file baseline count from 12 to 10 but did not eliminate the concern | Lower p95/max but slightly higher median | Kept audit-only pending reviewed gold |
