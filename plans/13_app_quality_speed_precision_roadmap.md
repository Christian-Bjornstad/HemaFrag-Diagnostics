# Plan 13 - App Quality, Speed, and Precision Roadmap

Date: 2026-07-27
Branch: `codex/plan-13-quality-speed-precision`
Status: active

## Execution Goal

Execute Plan 13 end to end: establish a reproducible real-FSA benchmark and timing baseline; add durable run manifests, versioned manual-adjustment provenance, resumable and idempotent report finalization; evaluate sizing, ladder-confidence, artifact-QC, and baseline alternatives in shadow mode; optimize FSA reuse, concurrency, the Rust/Python bridge, and tracking persistence; improve report/review provenance and assay-specific workflows; and promote changes only when correctness, QC-completeness, precision, performance, and chemist-review gates pass.

Progress:

- [ ] Phase 0 - measurement baseline
- [x] Phase 1 - recovery and provenance
- [ ] Phase 2 - precision experiments
- [ ] Phase 3 - throughput
- [ ] Phase 4 - reporting and workflow
- [ ] Phase 5 - assay-specific validation and promotion

Current execution note:

- Phase 0 benchmark tooling is implemented and tested. The first Rust-enabled, three-repeat real-FSA freeze is stored locally at `validation_outputs/plan13_phase0_repeat3_final/` and is excluded from git.
- All four result fingerprints are deterministic. Measured p50/p95 wall times are LIZ `2.75/3.10 s`, ROX `0.18/0.18 s`, combined patient/QC `43.00/47.49 s`, and 25-file FLT3 `15.08/15.33 s`.
- The combined run preserved `22` DIT entries and `14` QC entries with no failed jobs. FLT3 produced `25/25` PASS results: `24` automatic Rust CLI fits and one valid saved manual adjustment.
- Phase 0 remains open for worker counts `1/2/4/6/8`, general-mode coverage, reviewed failure/artifact classes, finer stage timing, and a larger balanced corpus. The native PyO3 wheel contract and tracking-marker Rust attribution are explicit follow-up items.
- Phase 1 is complete: atomic per-run manifests preserve hashed patient/QC membership and stage state; review bundles link back to an absolute manifest path; restart reruns recover the full original cohort; v2 manual sidecars carry source/ladder/channel/review provenance and reject mismatches; final HTML/workbook publication is atomic, idempotent, and count-gated.
- Real Phase 1 smoke: the manifest recorded `22` input files, `8` patient entries, `14` QC entries, two HTML artifacts, and one workbook with matching `Runs=22`, `Patient_Runs=8`, and `Control_Runs=14` sheet counts.
- Phase 2 sizing shadow has started with deterministic leave-one-ladder-anchor comparisons for linear, global quadratic, monotone PCHIP, and Local Southern. It is hard-coded as `promotion_eligible=false` because ladder-anchor holdout is only an interpolation-stability proxy.
- First real shadow observations: LIZ favored linear in this proxy (`1.03 bp` MAE; PCHIP `1.27`, Local Southern `1.35`, quadratic `1.93`), while ROX narrowly favored Local Southern (`0.15 bp`; linear/PCHIP both about `0.16`, quadratic `0.90`). Runtime sizing is unchanged pending independent reviewed fragment references and assay-window gates.

## Objective

Improve HemaFrag's correctness, precision, throughput, recoverability, and operator workflow without changing validated behavior by accident. Every algorithmic idea starts as an offline comparison against reviewed FSA data and ships only after assay-specific acceptance.

## Current Strengths To Preserve

- Rust-first ladder fitting with a Python fallback for supported clonality/general workflows.
- Explicit FLT3 ROX500/GS500ROX channel and quantitation contracts.
- Separate raw-trace area quantitation from stricter detection preprocessing.
- Manual ladder review gate, editor, saved sidecars, and linked report reruns.
- Patient and QC entries combined in final clonality DIT/tracking output.
- Content-hash and grouped-validation safeguards in clonality ML.

## Priority Opportunities

| Priority | Opportunity | Expected value | Main risk |
|---|---|---|---|
| P0 | Golden real-FSA benchmark corpus and stage timings | Makes every later change measurable | Poor corpus balance can hide regressions |
| P0 | Durable run manifest and resumable finalization | Reliable report/QC rebuild after restart | Must avoid storing raw trace data in manifests |
| P0 | Versioned manual-adjustment provenance | Auditable, reproducible ladder corrections | Migration of legacy sidecars |
| P1 | Assay-specific sizing-model comparison | Better local bp accuracy | A model can improve global residuals but worsen clinically relevant ranges |
| P1 | Confidence-aware monotonic ladder matching | Fewer wrong anchors and clearer review cases | Overconfident auto-acceptance |
| P1 | Artifact QC for pull-up, saturation, dye blobs, and missing tails | Better separation of software failures from data/instrument failures | Thresholds must be instrument/run aware |
| P1 | Baseline/detection preprocessing bakeoff | Better weak-peak detection and stable zoom | Quantitative peak area can be biased |
| P2 | Decode each FSA once and reuse immutable artifacts | Lower batch latency and memory churn | Cache invalidation and schema drift |
| P2 | One concurrency budget across Python and Rust | More predictable throughput | Workload differs by machine and batch |
| P2 | Remove JSON round-trip from the in-process Rust bridge | Lower per-file bridge overhead | Python/Rust ABI and array ownership complexity |
| P2 | Transactional run ledger with Excel as an export | Faster, safer tracking updates | Requires careful compatibility and migration |
| P3 | Review queue and report provenance UX | Faster manual review and easier audits | UI complexity |

## Phase 0 - Measurement Baseline

1. Build a de-identified, immutable benchmark manifest covering:
   - LIZ and ROX clonality assays;
   - FLT3 ITD, D835/TKD, controls, and known ladder edge cases;
   - general-mode examples;
   - clean passes, manual fixes, missing ladder, pull-up, saturation, weak signal, and truncated tails.
2. Store only content hashes, sanitized run keys, assay labels, expected outcomes, and local paths outside git.
3. Add stage timings for ABIF decode, ladder candidates, Rust fit, Python fallback, baseline, peak analysis, plots, HTML, and Excel.
4. Record peak memory and p50/p95 wall time at worker counts 1, 2, 4, 6, and 8.
5. Freeze reviewed outputs before algorithm experiments.

Acceptance:

- Repeated runs give the same results and stable timings.
- Every important assay and failure class has reviewed examples.
- No optimization is accepted without before/after evidence on this corpus.

## Phase 1 - Recovery And Provenance

### 1.1 Durable run manifest

Write an atomic manifest beside each batch output containing:

- app/engine versions and settings hash;
- all original FSA identities and content hashes;
- generated patient and QC job membership;
- per-stage status and output paths;
- review-bundle path and correction sidecar hash;
- expected patient, control, HTML, and workbook row counts.

Use it to resume interrupted work and rebuild final reports after restart without rescanning or losing the original QC cohort.

### 1.2 Versioned manual correction sidecar

Extend the sidecar schema in a backward-compatible version to include:

- source FSA content hash, ladder name, channel, assay, and schema version;
- exact selected peak times and expected bp steps;
- before/after QC metrics;
- operator, timestamp, app version, and optional comment;
- validation state showing that the sidecar was successfully reloaded.

Reject a sidecar when its source hash, ladder, or channel does not match the current input. Keep legacy sidecars readable and visibly marked as legacy.

### 1.3 Transactional finalization

- Write HTML/workbook outputs to temporary paths and atomically replace completed outputs.
- Make finalization idempotent: rerunning the same manifest must not duplicate workbook rows.
- Verify expected patient and QC counts before declaring success.

## Phase 2 - Precision Experiments

### 2.1 Sizing-model bakeoff

Compare the current model against:

- Local Southern sizing around each unknown fragment;
- monotone cubic/PCHIP interpolation;
- constrained spline variants;
- the existing polynomial/linear models.

Evaluate by assay and clinically relevant bp window. Local Southern is especially worth testing because it uses nearby standard fragments rather than one global curve, but an anomalous neighboring standard can distort the result. No model becomes a default based only on global R2.

Research basis:

- Thermo Fisher documents Local Southern as two overlapping three-standard fits around the unknown, averaged together, and warns that anomalous standards can distort the estimate: `https://apps.thermofisher.com/apps/peak-scanner/help/GUID-0FF79E69-77A3-4188-BB04-329664C4CBC3.html`.
- The monotone PCHIP comparison follows the shape-preserving interpolation family described by Fritsch and Butland (1984): `https://doi.org/10.1137/0905021`.

Metrics:

- blinded absolute bp error at reviewed reference peaks;
- within-run and between-run repeatability;
- p95 error in each assay decision window;
- extrapolation count and distance;
- monotonicity failures;
- changed clinical classifications.

### 2.2 Confidence-aware ladder matching

Keep top-K monotonic anchor sequences rather than only the winning mapping. Export:

- score margin between first and second candidate;
- per-anchor peak support, shape, intensity, and local alternatives;
- expected-gap residuals;
- model disagreement and extrapolation warnings.

Auto-pass only when the winning sequence is stable under small threshold/preprocessing perturbations and has a sufficient margin. Route ambiguous cases to the editor with the alternatives already visible.

### 2.3 Artifact classification

Add offline detectors for:

- pull-up/crosstalk aligned across dye channels;
- clipped/saturated peaks;
- dye-blob and broad-shoulder morphology;
- missing high-end ladder tail;
- abnormal peak-height decay;
- neighboring-capillary/run-position patterns when metadata is available.

These should classify likely data/instrument problems separately from ladder-algorithm failures, not rescue them by loosening fit thresholds.

### 2.4 Baseline and peak-detection bakeoff

HemaFrag already uses arPLS-related preprocessing. Compare current settings with bounded alternatives such as airPLS/arPLS variants, rolling quantile, and peak-preserving smoothing on labeled traces.

Guardrails:

- detection preprocessing remains separate from FLT3 quantitative area traces;
- peak apex shift, height bias, and area bias are measured;
- no method ships solely because plots look smoother;
- parameters are fixed per validated assay/profile, not adapted from the expected result.

## Phase 3 - Throughput

### 3.1 Immutable per-FSA artifact

Decode ABIF once into a versioned in-memory artifact containing raw channels, metadata, and content hash. Pass it through ladder, baseline, assay analysis, plots, and tracking instead of reopening the file.

Persist only safe derived cache data. Cache keys must include:

- FSA content hash;
- analysis/assay profile;
- engine and algorithm version;
- relevant settings hash;
- manual-adjustment hash.

### 3.2 Unified concurrency budget

Avoid multiplying Python workers by Rust Rayon threads. Benchmark combinations and set one machine-level CPU budget with explicit inner/outer allocation. Keep a low-memory mode for large runs.

### 3.3 Rust/Python bridge

The current PyO3 extension still converts Rust results through serialized JSON values. Prototype direct typed conversion and NumPy-compatible buffers for large arrays. Keep the CLI as a packaging/recovery path until parity is proven.

### 3.4 Tracking storage

Prototype an append-safe SQLite run ledger as the transactional source for identities, provenance, QC metrics, peaks, and report state. Continue producing the same Excel workbooks as operator-facing exports. Do not replace Excel until row-for-row parity, formulas, styling, and update behavior are verified.

## Phase 4 - Reporting And Workflow

- Show the exact source hash, ladder strategy, manual/automatic status, QC reason codes, and output version in reports.
- Add manifest-based "Rebuild final reports" that works after restart and verifies QC completeness.
- In Ladder Studio, show before/after overlays, sidecar save verification, candidate score margins, and whether the correction has been consumed by a successful rerun.
- Add run-level QC trends for ladder residuals, anchor intensities, pass/review/fail rates, pull-up, and saturation.
- Use Shewhart/EWMA-style monitoring only after a stable historical baseline is selected; alerts should signal investigation, not silently change analysis thresholds.

## Phase 5 - Assay-Specific Improvements

### Clonality

- Validate zoom from reference ranges plus detected evidence, with stable minimum spans.
- Add replicate concordance and same-patient context as review evidence, preserving independent raw-file results.
- Continue grouped and source-run stress validation before any ML promotion.

### FLT3

- Preserve raw/local-sideband area quantitation.
- Validate peak selection and ratio repeatability separately for ITD and D835/TKD.
- Keep missing/weak ladders as data-quality failures and manual corrections as explicit reviewed evidence.

### General

- Move ladder/channel/range definitions into versioned profiles.
- Require every custom profile to declare ladder steps, size-standard channel, report fields, and validation status.

## Release Gates

An experimental change can advance only when:

- zero unexplained regressions on user-approved ladder fits;
- 100% manual-correction save/reload/rerun success;
- final reports contain every expected patient and QC entry exactly once;
- no new FLT3 area bias outside an approved tolerance;
- no changed clinical interpretation without explicit chemist review;
- p95 latency or memory improves for performance work;
- outputs retain source, settings, engine, model, and correction provenance;
- shadow-mode evidence is reviewed before default enablement.

## Suggested Execution Order

1. Phase 0 benchmark and timing.
2. Phase 1 run manifest, correction provenance, and idempotent finalization.
3. Phase 2 sizing and artifact experiments in shadow mode.
4. Phase 3 caching/concurrency/bridge optimization.
5. Phase 4 workflow and trend monitoring.
6. Phase 5 assay-specific promotion after chemist review.

## Research Basis

- Thermo Fisher's fragment-analysis guide says size-standard peaks should be sequential, correctly labeled, sufficiently strong, and relatively even; it also identifies missing peaks, pull-up, saturation, spectral calibration, and run conditions as distinct failure sources: https://documents.thermofisher.com/TFS-Assets/LSG/manuals/4474504.pdf
- Thermo Fisher describes Local Southern sizing as a local calculation using neighboring standard fragments and warns that anomalous standard fragments can reduce accuracy: https://apps.thermofisher.com/apps/peak-scanner/help/GUID-0FF79E69-77A3-4188-BB04-329664C4CBC3.html
- Baek et al. describe arPLS baseline estimation that accounts for noise on both sides of the baseline: https://pubmed.ncbi.nlm.nih.gov/25382860/
- Zhang et al. describe airPLS as an adaptive, peak-detection-independent baseline method: https://pubmed.ncbi.nlm.nih.gov/20419267/
- NIST recommends statistical control of measurement processes to detect changes in bias and long-term variability: https://www.itl.nist.gov/div898/handbook/mpc/section2/mpc2.htm
- CLSI EP05 provides current guidance for evaluating within-site and between-site precision of quantitative measurement procedures: https://clsi.org/shop/standards/ep05-plus/
- ISO 15189:2022 defines quality and competence requirements for medical laboratories: https://www.iso.org/standard/76677.html
