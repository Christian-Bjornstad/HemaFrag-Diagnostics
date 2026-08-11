# Rust Ladder Staged-Rescue Design

Date: 2026-08-11

## Goal

Improve automatic Rust ladder fitting when a usable ladder signal is present so substantially fewer patient-clonality files require manual correction. Missing-ladder classification is not the optimization target; those files remain explicit exclusions and stay outside fitting metrics.

## Scope and safety boundaries

- Use patient-clonality files only.
- Use raw data only from `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, and `D:\DATA\2026_data`.
- Never enumerate, read, copy, or derive records from `D:\DATA\backup`.
- Keep raw and archive inputs read-only.
- Write generated research artifacts only below `D:\HemaFrag_Research\ladder\current`.
- Preserve deterministic results, existing safety checks, complete monotonic ladders, and current exact fits.
- Do not lower acceptance thresholds merely to reduce manual review.
- A difficult or ambiguous case may remain review-required; a confident wrong sequence is worse than a safe review.
- LIZ requires 16 complete ordered anchors. ROX requires 21 complete ordered anchors.

## Evidence from round two

The finalized blind review contains 18 patient cases:

- 9 explicit no-usable-ladder exclusions, which are outside fitting optimization;
- 2 usable cases whose reviewed anchors match Rust exactly;
- 4 usable LIZ cases dominated by first- or second-anchor errors;
- 3 usable ROX cases with major sequence, offset, or ladder-region errors.

All 12 suspicious cases were unsafe. The six accepted controls contained two exact fits, two incorrect usable fits, and two no-usable-ladder exclusions. Therefore, both rejected and apparently accepted results must be represented in development and validation evidence.

## Chosen architecture

Use a staged deterministic rescue fitter. The current candidate remains a finalist at every stage.

### Tier 0: current fast path

Run the existing bounded candidate generator, repairs, and arbiter unchanged in purpose. If the result is complete, high-confidence, and free of rescue-trigger conditions, return it without invoking a slower search.

Rescue triggers include:

- incomplete sequence;
- review-required result;
- baseline-like or weak selected anchors;
- poor linear or quadratic ladder geometry;
- suspicious ROX compression, offset, or early termination;
- a small score margin between materially different candidate sequences.

### Tier 1: two-second rescue

Use a deterministic operation budget calibrated to complete within two seconds on the supported workstation, with a two-second watchdog ceiling. Search only the regions implicated by the fast-path evidence:

- LIZ prefix alternatives for the first one to three anchors while preserving a stable interior and tail;
- local LIZ substitution windows for weak or baseline-like anchors;
- ROX prefix, insertion/deletion, and one-step sequence-shift hypotheses;
- ROX alternative tail and compressed-family alignments;
- alternative peaks already found by raw, quantile, morphological, and SNIP lanes.

Every candidate is rescored with one shared objective. Specialized repair functions may propose candidates but do not decide the winner independently.

### Tier 2: ten-second deep rescue

Invoke only when Tier 1 remains incomplete, review-required, or ambiguous. Use a deterministic global beam/dynamic-programming search with an operation budget calibrated below ten seconds and a ten-second watchdog ceiling.

The search lattice consists of ordered detected peaks and expected ladder steps. A state records the expected step, selected peak, accumulated score, fitted warp/geometry summary, skipped-peak count, missing-step hypotheses, and deterministic tie-break key. Transitions score:

- monotonicity and expected ladder spacing under the fitted scan-to-basepair curve;
- local and global residuals;
- peak prominence, width, height-family consistency, and baseline separation;
- penalties for baseline feet, blob shoulders, skipped strong peaks, crowded starts, implausible compression, and implausible ladder span;
- explicit insertion/deletion and alternate-start hypotheses for ROX;
- edge-anchor consistency for LIZ.

The deep tier returns only after a complete tier finishes. If its watchdog fires, the engine returns the last completed tier's deterministic result rather than a partially explored candidate.

## Central candidate arbiter

All fast, local-rescue, and deep-rescue candidates enter one arbiter. The arbiter:

1. validates exact expected anchor count and strict scan ordering;
2. applies the same feature and geometry scoring to every candidate;
3. retains the existing fast candidate as a control finalist;
4. compares the best and second-best materially distinct sequences;
5. promotes a rescue only when it improves the shared objective by a configured minimum margin and does not violate any safety guard;
6. retains review-required status when competing sequences remain too close.

This avoids accumulating more independent hand-written rules whose local decisions can conflict.

## Determinism and runtime

Wall-clock time alone must not control which candidate wins. Each tier has a deterministic expansion budget and stable ordering. The two- and ten-second watchdogs are hard safety ceilings. When a watchdog fires, the incomplete tier is discarded and the last completed tier is returned.

Each result records:

- `fit_tier`: `fast`, `rescue_2s`, or `deep_rescue_10s`;
- deterministic expansions used and configured expansion limit;
- elapsed time per tier;
- number of distinct complete candidates considered;
- best shared score, runner-up score, and score margin;
- rescue trigger reasons;
- whether a watchdog ceiling was reached.

The CLI and Python application must retain backward-compatible parsing for existing fields.

## Reviewed-data design

### Existing development evidence

The nine usable round-two ladders become locked regression cases by content SHA-256 and complete reviewed scan sequence. The two exact cases must remain exact. The four LIZ and three ROX errors define the initial rescue behaviors. The nine exclusions remain negative operational evidence but do not participate in fitting-score optimization.

Historical sidecars remain provisional unless explicitly reviewed and approved. They cannot become fitting gold automatically.

### New 100-file review programme

Create two independently randomized, blind, patient-only bundles before tuning begins:

- `development_40`: 40 cases available for the second tuning wave;
- `validation_60`: 60 cases whose identities, allocation, baseline results, and candidate results remain withheld until the Rust candidate is frozen.

Each wave is balanced as closely as feasible across:

- LIZ and ROX;
- currently accepted and currently suspicious/rejected fits;
- 2024, 2025, and 2026;
- assays and physical runs;
- failure signatures and search tiers.

Every selected case requires a unique content hash and normalized physical-run key. Round-one and round-two hashes are excluded. If a stratum cannot meet its requested quota, selection fails with a shortage report instead of silently changing the experiment.

Files without usable ladder signal may be marked with the existing exclusion action. They are counted in operational review totals but excluded from fitting accuracy and tuning.

## Application review workflow

The bundles use Ladder Studio's existing channel-level review behavior and bundle-local adjustment database. The application must:

- open the selected wave directly through `--ladder-review-bundle`;
- force `<bundle>\ladder_adjustments.sqlite3` before constructing the window;
- display wave progress, resolved count, and remaining count without revealing cohort allocation;
- permit complete manual adjustment, reviewed-no-change, or explicit no-usable-ladder exclusion with a required note;
- persist CSV annotations and the annotation JSON transactionally;
- never copy historical sidecars into a blind bundle;
- keep the validation bundle inaccessible to tuning and benchmark commands until an explicit freeze manifest exists.

Development and validation finalizers re-hash copied FSA files, validate bundle containment, require complete 16- or 21-anchor manual mappings, reject adjustment/exclusion contradictions, and publish paired JSON and Markdown results atomically.

## Metrics and promotion gates

The primary metric is the proportion of usable reviewed files requiring no anchor changes. Exact sequence equality is evaluated on scan indices.

Secondary metrics are:

- anchors changed per file;
- mean and maximum absolute scan delta;
- major wrong-sequence rate;
- review-required rate;
- exact-fit rate by LIZ/ROX, year, assay, and baseline cohort;
- median, p90, p95, p99, and maximum runtime;
- Tier 1/Tier 2 invocation rate and watchdog count.

The implementation candidate is promotable only when:

- both existing exact round-two cases remain exact;
- no approved historical regression case becomes worse;
- the four known LIZ edge cases become exact or strictly closer with no new anchor errors;
- the three known ROX sequence cases become exact or materially closer without producing a new confident wrong sequence;
- usable `validation_60` exact-fit rate improves by at least 15 percentage points over the frozen baseline;
- major wrong-sequence rate does not increase in any ladder family;
- deterministic repeat runs produce identical anchors and diagnostics;
- normal fast-path runtime does not materially regress;
- rescue and deep-rescue watchdog ceilings are respected.

An exact-fit rate of at least 90% on usable validation files is the product target, but the minimum evidence gate remains the frozen-baseline improvement and no-regression requirements above.

## Test strategy

Development follows strict red-green-refactor cycles.

1. Convert each of the nine usable reviewed ladders into a content-hash-locked end-to-end regression fixture that runs the real Rust CLI.
2. Add focused synthetic unit tests for LIZ prefix selection, ROX insertion/deletion shifts, alternative regions, arbiter score margins, operation budgets, watchdog fallback, and deterministic tie-breaking.
3. Add the 40-file reviewed development outcomes only after the initial implementation is benchmarked.
4. Freeze the Rust binary hash, configuration fingerprint, source hashes, and baseline outputs before revealing or finalizing the 60-file validation wave.
5. Run repeated deterministic benchmarks and the entire Rust, Python integration, and application test suites before promotion.

No test or benchmark may read from the backup tree. Real-data tests use locked manifests and verify every source hash before starting a subprocess.

## Generated artifacts

All generated artifacts live below:

`D:\HemaFrag_Research\ladder\current\rust_fit_improvement`

The directory contains:

- locked nine-case development manifest;
- frozen baseline benchmark and Rust binary/configuration fingerprints;
- `development_40` blind bundle and withheld allocation;
- `validation_60` blind bundle and withheld allocation;
- bundle-local adjustment databases;
- finalized development and validation outcomes;
- baseline-versus-candidate comparison reports;
- deterministic runtime and tier-usage benchmark reports;
- an explicit freeze manifest required before validation can be finalized or used for promotion.

## Out of scope

- Training the clonality classification ML model.
- Automatically deciding whether an absent ladder was caused by a person or instrument.
- Relaxing complete-ladder or monotonicity requirements.
- Using controls, historical sidecars, or accepted Rust outputs as automatic gold.
- Reading or deriving any artifact from `D:\DATA\backup`.
