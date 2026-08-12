# Ladder-Fitting Historical Research Design

**Date:** 2026-08-10

**Status:** Approved design; implementation planning pending

**Raw data roots:** `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, `D:\DATA\2026_data`

**Archive root:** `D:\Klonalitet_Archive`
**Explicit exclusion:** `D:\DATA\backup`

## Goal

Use 2.5 years of raw and archived clonality runs to explain Rust ladder-fitting failures, separate human/setup errors from algorithmic failures, and improve automatic ladder fitting without weakening the safety gate or regressing established good fits.

The project concerns ladder fitting only. Patient clonality classification is a separate project with its own design and implementation plan.

## Dataset Baseline

The allowed raw-data roots contain 53,390 FSA files in 555 top-level run folders:

| Year | FSA files | Top-level run folders |
|---|---:|---:|
| 2024 | 21,924 | 229 |
| 2025 | 20,330 | 210 |
| 2026 through August 10 | 11,136 | 116 |

The canonical `reports_backfill` archive summaries cover 552 processed source runs and 32,843 analyzed entries:

| Year | Processed runs | Entries | Review cases | Review rate |
|---|---:|---:|---:|---:|
| 2024 | 226 | 13,805 | 735 | 5.3% |
| 2025 | 210 | 12,603 | 331 | 2.6% |
| 2026 through August 10 | 116 | 6,435 | 89 | 1.4% |

The canonical review files contain 1,155 cases. Of those, 1,089 use LIZ and 66 use ROX. The largest groups are TCRgA, TCRgB, IGK, and KDE. A total of 1,119 review cases have zero fitted steps, while 1,070 expose only the generic reason `rust_ladder_fit_rejected`. Historical output alone is therefore insufficient to diagnose most failures; the raw FSA files must be rerun with richer instrumentation.

The three raw 2024 folders absent from the annual tracking workbook must be reconciled explicitly. Two 2025 logical source runs are nested inside other top-level run folders, so the physical top-level run must be retained as a separate grouping field.

Archived paths still refer to former `F:\DATA` and `F:\Klonalitet_Archive` locations. Research tooling must resolve those paths against the current `D:` roots without rewriting the original archive.

## Data Identification and Provenance

Patient identifiers and file names may be retained because this local dataset is not considered sensitive for this project. Research records will retain the exact local path, file name, run name, and identifiers needed for review.

SHA-256 remains part of the identity contract for technical reasons, not anonymization. It prevents duplicated bytes, renamed files, or repeated processing outputs from being counted as independent evidence. The canonical identity is:

```text
physical top-level run + relative path + file name + FSA SHA-256
```

Archive summaries under `ASSAY_REPORTS` and `REPORTS` are subordinate views. Only the run-level `reports_backfill/ladder_review_gate` bundle is canonical for cohort counts.

## Manual-Correction Evidence

Manual corrections are the strongest available anchor truth and enter the gold corpus before any newly reviewed case.

The allowed raw-data roots currently contain 28 `.ladder_adj.json` sidecars:

| Evidence type | Count | Detail |
|---|---:|---|
| 2025 legacy complete LIZ | 8 | 16 monotonic anchor times |
| 2025 legacy complete ROX | 17 | 21 monotonic anchor times |
| 2025 legacy partial LIZ | 1 | 15 of 16 steps; expected step 14 is omitted |
| 2026 v2 complete LIZ | 1 | Source SHA-256, ladder/channel identity, selected peaks, operator and QC provenance |
| 2026 v2 complete ROX | 1 | Source SHA-256, ladder/channel identity, selected peaks, operator and QC provenance |

All 28 sidecars have a matching local FSA file and strictly increasing stored anchor times.

The 2026 annual workbook records eight rows whose accepted strategy was `manual_adjustment`. These consumed adjustments must be reconciled with the surviving sidecars and run manifests. The archive also contains two 2024 `manual_adjusted` annotations whose sidecars still point to `F:` and are not present under the current `D:` roots. Those are recorded as missing correction artifacts and require either recovery from the old location or fresh review.

Legacy corrections will be imported into a versioned research representation without overwriting their source files. The import will infer LIZ versus ROX only when the ladder identity is supported by expected-step count and the FSA/run configuration. Ambiguous records remain review-required.

## Outcome Taxonomy

Every failed or questioned ladder is assigned exactly one primary outcome:

- `missing_ladder_signal`: no usable size-standard signal; typically preparation, loading, injection, or instrument setup error.
- `wrong_ladder_or_channel`: signal exists, but configured ladder identity or size-standard channel is inconsistent with the file.
- `fit_rejected_with_usable_signal`: the correct ladder signal is present but Rust cannot produce an acceptable fit.
- `fit_accepted_but_wrong`: Rust accepted an incorrect anchor family or mapping; this is the highest-risk failure.
- `fit_correct_review_only`: Rust mapping is correct, but a conservative guardrail routes it to review.
- `unresolved`: available evidence does not support a defensible classification.

Missing-ladder files remain in operational QC and run-level statistics but do not count as algorithm-fitting failures. Controls and patient files are both eligible for ladder research because ladder fitting is independent of patient clonality.

## Components

### Canonical Corpus Inventory

Build a read-only inventory across the three allowed raw-data roots and the archive. It records physical run membership, logical source run, file identity, ladder/channel configuration, archive outcome, tracking-workbook row, review record, manual correction, and source provenance.

The inventory reports unmatched raw files, unmatched archive rows, missing correction sidecars, conflicting identities, and duplicated content. It does not mutate the raw data or archive.

### Diagnostic Rerunner

Rerun the 1,155 canonical review cases and a stratified accepted-fit comparison sample using the current Rust engine in diagnostic mode. Persist:

- raw and corrected ladder-channel signal summaries;
- candidate peak time, height, prominence, width, and local-baseline features;
- expected ladder and size-standard channel;
- selected and alternative anchor families;
- candidate-pool and search-tier counts;
- repair families attempted and accepted;
- best-versus-second-best score margin;
- fitted/missing steps and scan indices;
- linear, quadratic, spline, residual, curvature, and intensity QC;
- precise rejection and review reason codes;
- per-stage timing and deterministic engine/version fingerprint.

A generic `rust_ladder_fit_rejected` result without an underlying diagnostic category fails the research data contract.

### Failure Classifier

The first classifier is deterministic diagnostic logic, not a learned model. It separates absent signal, wrong configuration, low-quality signal, ambiguous candidate family, local missing/weak anchors, baseline/blob selection, late/compressed families, search-budget exhaustion, and correct-but-conservative review.

The categories are validated against manual corrections and fresh operator review. Threshold changes are evidence-driven and never inferred from archive frequencies alone.

### Ladder Review Queue

Create a focused review queue in the existing Ladder Studio workflow. Each case shows the signal, expected ladder, Rust selection, alternatives, diagnostics, current/manual anchors, and linked cases from the same physical run.

The reviewer can record:

- ladder missing or unusable;
- wrong ladder/channel configuration;
- Rust anchors correct with no change;
- corrected full mapping;
- corrected partial mapping;
- unresolved with a note.

New corrections use the v2 provenance contract and are saved atomically. Legacy sidecars remain unchanged.

### Gold Corpus

Gold truth is ranked in this order:

1. Valid v2 manual correction with source hash and ladder/channel identity.
2. Valid imported legacy manual correction confirmed against the matching FSA.
3. Fresh operator-reviewed full or partial anchor annotation.
4. `reviewed_no_change` confirmation of an exact Rust mapping.
5. Stable consensus across independent engine versions, used only for non-difficult comparison cases.

The corpus is split by physical top-level run into:

- a small development set covering every known failure family;
- a locked validation set used for algorithm selection;
- a broader release set spanning year, run, ladder type, assay, controls/patients, and difficulty.

No FSA content hash, patient, or physical run may cross these partitions.

### Rust Improvement Loop

Improve the engine through bounded, failure-directed candidate generation and central candidate arbitration. Likely work includes richer failure provenance, recovery of useful rejected previews, targeted LIZ start/middle/tail repair, wrong-channel safeguards, search-budget reporting, and correct partial-fit representation.

Safety thresholds are not relaxed merely to reduce review counts. Every proposed change is compared against the original candidate and the gold corpus. An uncertain result remains explicit review rather than being forced into an automatic fit.

### Rebuild and Publication

After an engine version passes the ladder release gates, rerun the historical corpus into a new versioned output root. Preserve the original archive and annual workbooks unchanged. Generate replacement annual workbooks transactionally, reconcile every allowed raw run, and publish only after row counts, identities, formulas, and ladder provenance pass validation.

## Data Flow

```text
Allowed raw FSA roots + immutable archive + manual sidecars
    -> canonical inventory and path reconciliation
    -> diagnostic rerun
    -> deterministic failure taxonomy
    -> manual review and gold anchors
    -> development / locked validation / release partitions
    -> bounded Rust changes
    -> regression and safety gates
    -> versioned historical rerun
    -> validated replacement tracking workbooks
```

## Error Handling

- Missing raw FSA: retain the archive record as unresolved and report it.
- Missing manual sidecar: retain annotation/provenance, never fabricate anchors, and queue recovery or fresh review.
- Source hash mismatch: reject the adjustment for automatic use and require review.
- Ambiguous legacy ladder identity: do not infer from step count alone; require run configuration or manual confirmation.
- Missing ladder signal: mark operational/human error and exclude from algorithm success denominators.
- Rust transport failure: distinguish it from an algorithmic low-confidence or no-fit result.
- Diagnostic timeout or candidate cap: preserve the best bounded preview and record the exhausted budget.
- Conflicting reviewed mappings for identical FSA bytes: block gold-corpus publication until resolved.

## Verification and Release Gates

### Inventory gates

- All allowed raw top-level runs are represented or carry an explicit failure record.
- `D:\DATA\backup` never appears in an input, output, manifest, or count.
- The three absent 2024 runs and nested 2025 source runs are explicitly reconciled.
- Canonical counts are not inflated by subordinate report bundles.

### Gold-data gates

- All 28 surviving sidecars are imported or have an explicit rejection reason.
- The eight workbook-recorded 2026 manual consumptions are reconciled.
- The two missing 2024 correction artifacts are recovered or freshly reviewed.
- Every gold record binds to the exact FSA and physical run.

### Algorithm gates

- Zero unexplained regressions against reviewed manual anchors.
- Zero new false automatic acceptances in the locked validation and release sets.
- Good accepted mappings remain deterministic across repeated runs and supported Rust transports.
- Usable-ladder automatic-fit coverage improves by failure family, with confidence intervals reported.
- Missing-ladder and wrong-configuration cases remain explicit QC outcomes.
- Runtime remains bounded; report median, p90, p95, p99, maximum, timeout count, and candidate-cap count.

### Rebuild gates

- New outputs are written to a separate versioned root.
- Workbook identity keys remain unique.
- Raw-run, patient/control, assay, and ladder totals reconcile to the canonical inventory.
- Workbook formula and structural checks pass before publication.
- The original raw data, sidecars, archive, and workbooks remain unchanged.

## Deliverables

- Canonical ladder corpus inventory and reconciliation report.
- Manual-correction import and missing-artifact report.
- Diagnostic rerun artifact with precise failure categories.
- Ladder review queue and versioned gold-anchor corpus.
- Development, locked-validation, and release manifests.
- Before/after Rust benchmark and regression report.
- Versioned historical rerun outputs and validated annual workbooks.
- Operational summary separating human/setup errors from algorithmic fit failures.

## Out of Scope

- Patient clonality model training or promotion.
- Treating absent-ladder files as algorithm-fitting examples.
- Automatically accepting a mapping only because its polynomial residual is low.
- Overwriting the original raw corpus, manual sidecars, archive, or annual workbooks.
- Reading or using any content below `D:\DATA\backup`.
