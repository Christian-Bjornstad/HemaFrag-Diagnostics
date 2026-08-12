# Plan 14 - Channel-Level Clonality Interpretation and ML

Date: 2026-07-29
Branch: `codex/plan-14-channel-level-clonality`
Status: engineering implementation complete; real-label pilot and model promotion pending

## Execution Summary

Implemented on 2026-07-29:

- Added a versioned semantic interpretation-unit contract for every configured
  clonality assay and trace channel.
- Added independent channel labels to tracking workbooks with safe legacy-label
  migration for single-channel assays only.
- Changed the labeling session and Qt labeling tab to label one selected
  channel at a time, with channel cycling, optional overlay, and explicit
  apply-to-all behavior.
- Changed the feature artifact to long form, with one channel-local row per
  interpretation unit and no morphology features from the other channel.
- Changed training, readiness, auditing, and batch-selection paths to operate
  per interpretation unit while retaining legacy artifact compatibility.
- Added default-off shadow runtime predictions, per-channel tracking fields,
  and report rows without deriving an assay-wide result.
- Added regression coverage for independent mixed labels, workbook round trips,
  long-form features, readiness, batch merge, runtime, reports, and the UI.

No channel model has been promoted. Clinical use remains gated on a real-label
pilot, grouped validation, and chemist sign-off.

## Goal

Make clonality labeling, ML suggestions, tracking, and reports match the
chemist's real interpretation workflow: each relevant trace channel is
interpreted independently. A dual-channel assay may legitimately contain, for
example, a monoclonal green trace and a polyclonal blue trace. HemaFrag must
preserve both technical results instead of forcing one assay-wide label.

The ML remains a review assistant. It must not create an overall molecular
conclusion by collapsing channel results unless a separate, reviewed clinical
rule has been defined and validated.

## Why The Current Contract Is Wrong

- The FSA analysis already retains separate `DATA1`, `DATA2`, and `DATA3`
  traces and per-channel peaks.
- The feature extractor already produces extensive per-channel trace
  measurements.
- The labeling view plots the channels separately but assigns one
  `ClonalityChemistLabel` to the whole FSA injection.
- Training therefore learns one assay-wide answer from combined channel
  features, even when the correct technical descriptions differ by channel.
- Runtime and reports expose one rule suggestion and one ML suggestion per
  assay injection, so a mixed profile cannot be represented faithfully.

Six current clonality assays use two trace channels: `IGK`, `TCRbA`,
`TCRbB`, `TCRbC`, `TCRgA`, and `TCRgB`, with the configured target names
already mapping each dye channel to a biological rearrangement group.

## Recommended Interpretation Unit

Use a stable semantic interpretation unit rather than color alone:

```text
InterpretationUnit = Assay + TargetGroup + Channel
```

Examples:

| Assay | Interpretation unit | Channel |
|---|---|---|
| `FR1` | `FR1_JH` | `DATA1` |
| `IGK` | `IGK_JK5` | `DATA1` |
| `IGK` | `IGK_JK1_4` | `DATA2` |
| `TCRbA` | `TCRBA_JB2` | `DATA1` |
| `TCRbA` | `TCRBA_JB1` | `DATA2` |
| `TCRgA` | `TCRGA_JG11_21` | `DATA1` |
| `TCRgA` | `TCRGA_JG13_23` | `DATA2` |

`DATA1`/blue and `DATA2`/green remain visible to the chemist, but the stable
target ID prevents the model contract from depending only on display color.
Single-channel assays have exactly one interpretation unit.

## Workbook Contract

Keep the existing workbook sheet set. Add channel label columns to `Runs`,
`Patient_Runs`, and `Control_Runs` instead of adding another sheet:

- `ClonalityChemistLabel_DATA1`
- `ClonalityChemistLabel_DATA2`
- `ClonalityChemistLabel_DATA3`

Only channels configured for the assay are editable/populated. The legacy
`ClonalityChemistLabel` remains readable during migration but is no longer
training truth for dual-channel assays.

Migration rules:

1. For a single-channel assay, an existing legacy label can be copied safely to
   that assay's configured channel after an audit preview.
2. For a dual-channel assay, never copy one legacy assay label into both
   channels automatically.
3. Show the old assay label as reference while the chemist assigns the two
   channel labels.
4. Preserve untouched legacy workbooks and write migration changes
   transactionally.
5. Merge labels using the hidden `IdentityKey` plus channel, so repeated file
   names or re-analysis cannot update the wrong row.

## Labeling Experience

Change the existing labeling tab from sample-only focus to
sample-and-channel focus:

- Display channel selectors with the actual blue, green, or orange swatch and
  the configured target name.
- Solo the selected channel while keeping a faint optional overlay of the other
  channel for context.
- Number keys label only the selected channel.
- `Tab` moves to the next channel; the normal next action moves to the next
  injection after all configured channels are labeled.
- Show every channel's current label beside its selector.
- Provide an explicit `Apply to all channels` command for genuinely identical
  profiles; never make this the default.
- Filters count unlabeled interpretation units, not merely unlabeled FSA
  files.
- Save all changed channel labels atomically to the main and split tracking
  sheets.

A mixed result such as `DATA1=polyklonal`, `DATA2=monoklonal` is complete and
valid. It is not automatically a QC failure or review case.

## Feature Dataset

Move the ML training artifact to long form: one row per
`IdentityKey + InterpretationUnit`.

Each row contains:

- source identity, DIT, run, assay, channel, and semantic target ID;
- the chemist label for that channel;
- ladder and injection-level QC context;
- trace/peak features for the selected channel;
- safe patient/run cohort context;
- rule output for that same channel once channel-level rules exist.

For the first candidate, exclude morphology from the other trace channel.
Otherwise a strong blue pattern could incorrectly dominate the prediction for
the green channel. An offline ablation may later test whether bounded
cross-channel context improves held-out performance.

Version the new artifact separately and reject mixed old/new schemas. Existing
raw feature extraction can be reshaped without storing raw traces.

## Model Design

### Recommended First Model

Train one calibrated classifier per interpretation unit, for example:

- `IGK_JK5`
- `IGK_JK1_4`
- `TCRBA_JB2`
- `TCRBA_JB1`

Reuse the existing RandomForest/ExtraTrees comparison, probability
calibration, grouped validation, content deduplication, integrity checks, and
default-off runtime gate.

This is preferable to `MultiOutputClassifier` for the first release:

- it naturally supports missing labels while channel labeling is incomplete;
- each channel can have its own class support and confidence threshold;
- model artifacts stay small and independently promotable;
- one weak channel cannot block a validated model for another channel;
- scikit-learn's `MultiOutputClassifier` also fits one estimator per target,
  so it provides little benefit over the clearer interpretation-unit design.

Shared or multi-task models are a later research option only if individual
units remain data-starved. They must beat the independent baseline on
patient/run-grouped held-out data without reducing monoclonal precision.

## Runtime And Reporting

Runtime should attach independent channel results:

```text
DATA1: polyklonal, confidence 0.91
DATA2: monoklonal, confidence 0.94
```

For every configured channel, retain:

- channel/target suggestion;
- calibrated confidence and acceptance threshold;
- review-needed flag and evidence;
- model version;
- chemist label when available.

Reports should present one technical row per interpretation unit using the
target name and trace color. Do not derive one assay-wide class by majority
vote, maximum severity, or "any monoclonal" logic. An optional summary may say
`mixed channel profile`, but the two actual technical descriptions remain the
result.

Review routing is also channel-specific:

- low confidence on either channel;
- rule/ML disagreement on that channel;
- unavailable or poor-quality trace for that channel;
- unsupported assay/target model.

Different high-confidence labels across two channels are not themselves a
reason for review.

## Validation

Continue grouping all folds by DIT/content component and run folder. Report
metrics for every interpretation unit:

- class support by independent DIT and run;
- macro F1 and balanced accuracy;
- monoclonal precision, recall, and F1;
- accepted coverage and accepted accuracy;
- calibration error and reliability curves;
- false-positive monoclonal cases;
- rule/ML/chemist disagreement;
- performance on same-label versus mixed-channel injections;
- drift by run date and instrument when reliable metadata exists.

Add explicit leakage tests proving that:

- channels from one FSA cannot land in different train/test folds;
- repeated patient samples cannot cross DIT folds;
- duplicate FSA content cannot contribute multiple training votes;
- labels from the other channel are never used as input features.

No channel model becomes runtime-eligible until it independently passes the
existing promotion gates and chemist review.

## Delivery Phases

### Phase 1 - Contract And Migration

1. Add interpretation-unit definitions to clonality configuration.
2. Add channel label columns and a migration preview/audit.
3. Extend labeling-session identity from `IdentityKey` to
   `IdentityKey + InterpretationUnit`.
4. Preserve legacy assay labels as read-only migration context.
5. Add transactional workbook and compatibility tests.

### Phase 2 - Labeling Pilot

1. Add channel selectors, solo mode, target names, and per-channel shortcuts.
2. Build a balanced pilot across all dual-channel assays and mixed-looking
   traces.
3. Have the chemist label both channels without seeing rule or ML answers by
   default.
4. Measure labeling time, skipped units, corrections, and inter-session
   consistency.

### Phase 3 - Dataset And Candidate Models

1. Write the channel-level feature schema and long-form artifact.
2. Reuse existing extracted features where the schema fingerprint matches.
3. Train independent candidate-only models per interpretation unit.
4. Produce grouped out-of-fold review panels and readiness reports.
5. Compare channel-local features against a bounded cross-channel-context
   ablation.

### Phase 4 - Shadow Runtime And Reports

1. Add channel prediction containers without changing clinical output.
2. Render per-channel technical suggestions in a shadow review report.
3. Compare old assay-wide suggestions, new channel suggestions, and chemist
   labels on the same corpus.
4. Confirm that mixed profiles are preserved and do not create false QC
   review flags.

### Phase 5 - Promotion

1. Obtain sufficient independent DIT/run support for each promoted unit.
2. Freeze acceptance, calibration, and monoclonal-precision thresholds.
3. Obtain chemist sign-off on channel terminology and report presentation.
4. Promote units independently; unsupported units remain rule/manual only.
5. Retire the legacy assay-wide label only after all workbook, training, and
   report consumers have migrated.

## Acceptance Criteria

- A chemist can label blue and green traces differently in one FSA and recover
  both labels after closing and reopening the workbook.
- Training truth is channel-specific for every dual-channel assay.
- Single-channel assays remain behaviorally unchanged.
- Reports display every channel result without inventing an overall class.
- Mixed channel profiles do not count as incomplete or failed review.
- ML confidence, calibration, and promotion are evaluated per interpretation
  unit with DIT/content/run grouping.
- Old workbooks remain readable, and dual-channel legacy labels are never
  duplicated silently.
- ML remains default-off until the channel models pass validation and chemist
  sign-off.

## Research Basis

- EuroClonality/BIOMED-2 separates the technical description of individual
  multiplex PCR results from the overall molecular conclusion and notes that a
  clonal conclusion need not require every profile to look clonal:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC3469789/
- scikit-learn documents multi-output classification as one classifier per
  target, which supports using independent interpretation-unit models as the
  clearer first baseline:
  https://scikit-learn.org/stable/modules/generated/sklearn.multioutput.MultiOutputClassifier.html
- Probability calibration must use predictions from data not used to fit the
  underlying classifier; the existing grouped calibration approach should be
  retained for every interpretation unit:
  https://scikit-learn.org/stable/modules/calibration.html
- Patient/run separation remains essential; grouped cross-validation support
  is documented here:
  https://scikit-learn.org/stable/modules/cross_validation.html
