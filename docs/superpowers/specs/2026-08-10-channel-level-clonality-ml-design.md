# Channel-Level Patient Clonality ML Design

**Date:** 2026-08-10

**Status:** Approved design; implementation planning pending

**Raw data roots:** `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, `D:\DATA\2026_data`

**Archive root:** `D:\Klonalitet_Archive`

**Explicit exclusion:** `D:\DATA\backup`

## Goal

Build a manually labeled, leakage-safe machine-learning assistant that classifies patient clonality independently for each configured interpretation channel. The first validated models distinguish `monoklonal` from `polyklonal`. The data contract retains the complete existing label vocabulary so additional classes can be added later without redesigning the labeling or feature pipeline.

The ML remains a channel-level second opinion. It does not replace the rule-based result or create an assay-wide diagnosis. Ladder-fitting research is governed by the separate historical ladder-fitting design.

## Current Dataset Baseline

The allowed raw-data roots contain 53,390 FSA files in 555 top-level run folders. The annual tracking workbooks contain 32,843 unique tracked rows:

| Year | Tracked rows | Patient rows | Control rows | Unassigned rows | Distinct DIT values |
|---|---:|---:|---:|---:|---:|
| 2024 | 13,805 | 11,021 | 2,734 | 50 | 1,020 |
| 2025 | 12,603 | 9,867 | 2,685 | 51 | 898 |
| 2026 through August 10 | 6,435 | 4,823 | 1,611 | 1 | 422 |

All three annual workbooks have unique `IdentityKey` values and the same five-sheet structure: `Dashboard`, `Runs`, `Patient_Runs`, `Control_Runs`, and `PK_Peaks`. None of the 32,843 rows currently has a chemist label in the overall or channel-level label columns.

The corpus contains 7,030 control rows across PK, RK, NK, PK1, and PK2. Controls are valuable for QC, drift, context, and negative testing, but they are not patient clonality ground truth.

Three raw 2024 top-level runs are absent from the annual workbook. Two 2025 logical source runs are nested inside other physical run folders. Archived paths reference the former `F:` roots. These inconsistencies must be resolved before labels or frozen dataset partitions are created.

## Interpretation Unit

The stable prediction and labeling identity is:

```text
InterpretationUnit = Assay + TargetGroup + Channel
```

Examples include:

| Assay | Target group | Channel | Interpretation unit |
|---|---|---|---|
| FR1 | FR1-JH | DATA1 | `FR1_JH` |
| IGK | Jk5 | DATA1 | `IGK_JK5` |
| IGK | Jk1-4 | DATA2 | `IGK_JK1_4` |
| TCRgA | Jg1.1/Jg2.1 | DATA1 | `TCRGA_JG11_21` |
| TCRgA | Jg1.3/Jg2.3 | DATA2 | `TCRGA_JG13_23` |

Each configured channel is labeled and modeled independently. A dual-channel FSA may validly contain different labels for its two interpretation units. The runtime and reports preserve those separate technical results and do not collapse them by majority vote or maximum severity.

## Label Contract

The labeling workflow continues to collect the complete application vocabulary:

- `monoklonal`
- `monoklonal_pa_poly`
- `polyklonal`
- `oligoklonal`
- `irregulaer`
- `lite_pcr_produkt`
- `intet_pcr_produkt`
- `qc_teknisk_fail`
- `usikker_review`

The first model version has this explicit training allowlist:

```text
monoklonal
polyklonal
```

All other valid chemist labels remain stored in the master workbook, audit artifacts, readiness reports, and error galleries. They are excluded from initial binary fitting and routed to manual review at runtime.

The trainable class allowlist is a versioned configuration and is recorded in every dataset and model manifest. Adding a class later requires:

1. Adding it to the allowlist for a new model schema version.
2. Passing that class's independent-patient, content, physical-run, fold-support, calibration, and performance gates.
3. Demonstrating that adding the class does not reduce monoklonal precision or accepted-prediction accuracy for the existing classes.
4. Publishing new candidate artifacts without overwriting the active model.

## Research Workspace

After implementation is approved, create this local working structure:

```text
D:\HemaFrag_Research\
├── ladder\
└── clonality_ml\
    ├── 01_inventory\
    ├── 02_tracking_master\
    ├── 03_labeling_batches\
    ├── 04_feature_datasets\
    ├── 05_frozen_splits\
    ├── 06_candidate_models\
    ├── 07_validation_reports\
    ├── 08_promoted_models\
    └── logs\
```

The original raw FSA files, archive outputs, annual workbooks, and manual ladder corrections remain unchanged. Every generated artifact has a schema version, creation timestamp, code/settings fingerprint, source manifest, and content hash.

## Components

### Canonical Patient and Run Inventory

Build a read-only inventory across the three allowed raw roots and annual workbooks. Preserve exact local identifiers and paths. Record:

- `IdentityKey`, file name, relative path, and FSA SHA-256;
- logical `SourceRunDir` and physical top-level `PhysicalRunKey`;
- DIT, assay, target group, interpretation unit, and channel;
- sample kind and control identity;
- run date, run code, well, and batch;
- ladder identity, ladder QC, fitting strategy, and manual-adjustment provenance;
- raw-file resolution status and dataset eligibility reason.

SHA-256 is used for content identity and leakage prevention, not anonymization.

### Versioned Master Tracking Workbook

Create a new master workbook in `02_tracking_master` from the annual workbooks. Preserve the established sheet set and visual conventions while repairing the data contract.

The master workbook must:

- reconcile all allowed raw runs, including the absent 2024 runs;
- represent nested 2025 logical runs under their physical parent;
- resolve former `F:` paths to current `D:` paths without changing the archive;
- retain unique `IdentityKey` values;
- include `PhysicalRunKey` and FSA SHA-256;
- retain `ClonalityChemistLabel_DATA1`, `DATA2`, and `DATA3`;
- add reviewer, review timestamp, label provenance, and conflict status fields;
- preserve patient, control, and unassigned distinctions;
- keep formulas, tables, filters, dashboards, and split sheets consistent;
- write and publish transactionally so a failed update cannot damage the prior master.

The master workbook is the labeling source of truth. Model-ready datasets are generated from it and never written back into the raw or annual workbooks.

### Manual Labeling Program

Use the existing application labeling page and channel-level interaction:

1. Generate deterministic batches stratified by interpretation unit, year, physical run, rule outcome, review state, and trace-feature diversity.
2. Leave chemist labels blank; never copy rule suggestions into label fields.
3. Hide the rule suggestion during the primary labeling decision when practical, then expose it for disagreement review.
4. Label only the selected configured channel.
5. Save any of the nine valid labels even though the initial model trains on two.
6. Require an explicit reviewer identity and timestamp for every newly assigned label.
7. Double-review at least 10% of labeled interpretation units, oversampling monoclonal, low-quality, ambiguous, and rule-disagreement cases.
8. Adjudicate conflicts before the affected rows become training-eligible.
9. Merge batches by `IdentityKey + InterpretationUnit` with a dry-run conflict report and atomic publication.
10. Recalculate class/readiness support after every merged batch.

Begin with a small workflow pilot. After the pilot passes, select batches adaptively: prioritize interpretation units close to readiness, underrepresented core classes, rare run periods, and the model's held-out disagreements rather than labeling the easiest cases repeatedly.

### Feature Dataset

Export a long-form dataset with one row per:

```text
IdentityKey + InterpretationUnit
```

Each row contains identity and grouping fields, the selected channel's chemist label, ladder/injection QC context, channel-local trace and peak features, bounded run/patient context, feature provenance, and an explicit eligibility reason.

The initial candidate excludes morphology from other biological trace channels. Cross-channel context may be evaluated later as a controlled ablation and is accepted only if grouped held-out performance improves without increasing monoclonal false positives.

Model-eligible rows must have:

- patient sample kind;
- resolvable allowed-root FSA file;
- valid interpretation unit and channel;
- accepted ladder status of `ok` or `manual_adjustment`;
- a non-conflicted chemist label in the two-class training allowlist;
- complete feature and content-hash provenance.

Rows outside those criteria remain visible in audits but are excluded from fitting.

### Controls

Controls never receive patient `monoklonal` or `polyklonal` training truth merely because they are PK, RK, NK, PK1, or PK2.

Controls may contribute:

- run-level assay and signal context;
- expected-peak and reagent-performance checks;
- drift and instrument/run monitoring;
- feature-normalization experiments;
- technical-outlier identification;
- negative tests showing that patient models do not accept control-like patterns.

Any control-derived feature must be available at runtime and computed without seeing future patients or held-out-run outcomes. Controls from a physical run remain in the same partition as that run's patient files. A future auxiliary QC model is a separate artifact and cannot be presented as patient clonality classification.

### Dataset Partitioning and Leakage Control

Deduplicate identical FSA bytes and form connected grouping components from:

- FSA content hash;
- DIT/patient identity;
- physical top-level run;
- repeated injections or linked logical runs.

No identical content, DIT, or physical run may cross training and evaluation partitions.

Use three evaluation views:

1. Grouped out-of-fold validation by DIT/content component for model comparison and threshold tuning.
2. A whole-physical-run held-out stress test.
3. A locked recent-2026 temporal test where each interpretation unit has sufficient class support.

The locked temporal test is not used for feature selection, hyperparameter selection, probability calibration, or threshold tuning.

### Model Training

Train one classifier per interpretation unit. Compare:

- class-balanced RandomForest;
- class-balanced ExtraTrees.

Use grouped probability calibration when fold support permits it. `auto` comparison mode selects a candidate for review, but final promotion requires rerunning the chosen classifier explicitly into a fresh output directory.

Each candidate artifact records:

- interpretation unit, assay, target group, and channel;
- training class allowlist and complete observed-label counts;
- feature columns and dataset fingerprint;
- FSA content, DIT, and physical-run grouping provenance;
- classifier kind, random seed, and runtime versions;
- calibration strategy and evidence;
- decision threshold and promotion gates;
- content-addressed model file, SHA-256, and byte size;
- candidate or promoted status.

### Manual Training and Testing Workflow

The application ML Training page provides the operator workflow:

1. Select the versioned master workbook and feature dataset.
2. Run data audit and label-readiness checks.
3. Show eligible interpretation units and the exact blockers for unsupported units.
4. Train candidate models only for ready units.
5. Open grouped validation, temporal-test, calibration, disagreement, and error-gallery reports.
6. Compare the new candidate with the currently promoted model.
7. Require explicit operator promotion after every configured gate passes.

The same operations have reproducible command-line equivalents. GUI and CLI runs consume the same manifests and produce equivalent model metadata.

## Readiness and Promotion Gates

The existing thresholds remain the initial minimum floor for every interpretation unit:

### Data support

- At least 200 labeled, deduplicated training rows.
- At least 50 distinct DIT groups.
- At least 20 DIT groups for `monoklonal`.
- At least 20 DIT groups for `polyklonal`.
- At least three physical source runs represented in each core class.
- Each core class appears in at least two grouped evaluation folds.
- Every training fold contains at least six rows from each core class.
- No one DIT contributes more than 10% of a class.

### Performance

- Grouped out-of-fold macro F1 at least 0.70.
- Grouped out-of-fold monoklonal F1 at least 0.70.
- Grouped out-of-fold monoklonal precision at least 0.90.
- Accuracy among predictions accepted at the confidence threshold at least 0.95.
- Accepted-prediction coverage at least 0.10.
- Expected calibration error at most 0.10.
- Whole-run-held-out macro F1 at least 0.65.
- Whole-run-held-out monoklonal precision at least 0.85.

These are minimum technical gates, not evidence of clinical validation by themselves. Promotion remains explicit and interpretation-unit-specific.

## Runtime Policy

The initial model is a second opinion and remains default-off until promoted.

For each interpretation unit:

- high-confidence rule/ML agreement may be displayed;
- disagreement, low confidence, unsupported class, or unavailable features routes to review;
- poor ladder, control, DNA, or trace QC disables patient ML inference;
- non-core chemist labels remain manual-review outcomes;
- different valid labels across channels are preserved and are not automatically a QC failure;
- the rule-based result remains authoritative until a separate controlled validation authorizes a broader role.

## Validation Reports

Produce per-interpretation-unit reports containing:

- class support by row, DIT, content component, physical run, and year;
- confusion matrices and per-class precision, recall, and F1;
- macro F1, balanced accuracy, and monoklonal F1;
- monoklonal false-positive gallery;
- rule-versus-ML disagreement gallery;
- low-confidence and rejected-prediction gallery;
- calibration curve, expected calibration error, threshold coverage, and accepted accuracy;
- performance by year and physical run;
- grouped-fold and temporal-test membership;
- feature importance computed only from held-out folds;
- comparison against the prior candidate or promoted model.

## Error Handling

- Missing raw FSA: retain the row with an explicit resolution failure; exclude it from labeling/training until resolved.
- Missing or rejected ladder: exclude patient ML inference and route the ladder through the separate ladder workflow.
- Conflicting labels for the same content and interpretation unit: block training until adjudicated.
- Duplicate bytes assigned to different physical runs or DITs: form one connected grouping component and report the conflict.
- Invalid or unsupported label: reject the batch merge without partially updating the master workbook.
- Missing configured channel: retain an audit row and mark it ineligible.
- Insufficient grouped calibration support: keep the model candidate-only and report the exact support failure.
- Failed model integrity check: reject before deserialization and retain the last valid promoted model.
- Workbook write or formula validation failure: do not publish the staged workbook.

## Verification Gates

### Workbook and data gates

- `D:\DATA\backup` never appears in an input, output, manifest, or count.
- Every allowed raw run is represented or has an explicit failure record.
- Tracking identities are unique and paths resolve through the current `D:` roots.
- Channel labels round-trip through master, batch, merge, feature, readiness, and training workflows.
- Workbook formulas, tables, filters, dashboards, and representative rendered sheets pass verification.

### Leakage gates

- Identical FSA content never crosses a partition.
- A DIT never crosses a partition.
- A physical top-level run never crosses a partition.
- Temporal-test rows are absent from feature and threshold selection.
- Controls cannot leak held-out-run outcome information into training features.

### Model gates

- Training consumes only `monoklonal` and `polyklonal` for the first schema.
- Other valid labels remain visible and route to review.
- Every promoted interpretation unit passes all data, grouped, run-held-out, calibration, and artifact-integrity gates.
- Promotion is explicit and does not silently replace an active model.
- Repeated training with the same inputs and random seed reproduces partitions and model metadata.

## Deliverables

- Canonical patient/run/FSA inventory and reconciliation report.
- Validated versioned master tracking workbook.
- Deterministic channel-level labeling batches and conflict-safe merge reports.
- Long-form channel-local feature datasets and manifests.
- Frozen grouped, whole-run, and temporal-test split manifests.
- Candidate RandomForest and ExtraTrees models per ready interpretation unit.
- Calibration, disagreement, error-gallery, and promotion reports.
- Explicitly promoted content-addressed model artifacts where every gate passes.
- Readiness tables showing when additional classes can safely enter a future multiclass model.

## Out of Scope

- Training patient clonality labels from control identities.
- Training from rule suggestions as if they were chemist truth.
- An assay-wide label derived automatically from multiple channel predictions.
- Automatic training on non-core labels in the first model schema.
- Using rows with missing/rejected ladders as patient model examples.
- Reading or using any content below `D:\DATA\backup`.
- Overwriting the original raw data, archive, annual workbooks, or active model artifacts.
