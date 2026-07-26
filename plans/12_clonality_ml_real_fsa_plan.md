# Clonality ML Real FSA Plan

Date: 2026-07-26
Baseline branch: `clonality-ml-phase-5-real-data-2026-07-11`

## Goal

Build a reliable, chemist-reviewed ML assistant for clonality interpretation from real `.fsa` traces. The first production goal is not autonomous diagnosis; it is a calibrated second opinion that can sort clear cases from review-needed cases while preserving current rule-based reporting.

## Principles

- Raw `.fsa` files stay local and out of Git.
- The rule-based interpreter remains the clinical source of truth until validation proves otherwise.
- Models train and report per assay because FR, IGK/KDE, TCRG, TCRB, DHJH, and SL have different signal shapes and interpretation ranges.
- Evaluation must split by patient/DIT or run folder, never random rows only.
- Rare classes matter. Macro F1, monoklonal F1, and review routing are more important than plain accuracy.

## Phase 1 - Data Contract

1. [Completed 2026-07-26] Standardize one labelled table per sample/injection with:
   - `DIT`, `Assay`, `File`, `SourceRunDir`, `RunDate`, `Well`
   - chemist label in `ClonalityChemistLabel`
   - current rule output and review flag
   - raw `.fsa` path or resolvable relative path
2. [Completed 2026-07-26] Export a manifest that records which raw files were included but stores no raw clinical data in Git.
3. [Completed 2026-07-26] Add a validation command that fails fast when labels, assay names, or DITs are missing.
4. [Completed 2026-07-26] Preserve the original top-level source run through
   Windows staging, including runs that reuse identical filenames.
5. [Completed 2026-07-26] Preserve files without a defensible DIT as
   `unassigned` inventory rows while excluding them from labeling, audit, and
   training by default.

## Phase 2 - FSA Trace Features

1. [Completed 2026-07-26] Keep existing scalar features from `features_from_entry`.
2. [Completed 2026-07-26] Add assay-window trace-shape features per DATA channel:
   - peak count, dominant height/area, height share, area share
   - local noise/MAD, baseline drift, dome/broad-hump indicators
   - reference-window coverage and outside-window signal share
   - peak spacing, symmetry, shoulder count, and multi-peak density
3. [Partially completed 2026-07-26] Add replicate/panel features:
   - [Completed 2026-07-26] same-run patient assay counts and panel completeness
   - [Completed 2026-07-26] duplicate/parallel dominant peak bp distance and
     2 bp concordance
   - control-run context when reliable control provenance is available
4. [Completed 2026-07-26] Store feature artifacts as CSV with a manifest containing code version, settings fingerprint, and source workbook path.

## Phase 3 - Baseline Models

1. Start with interpretable baselines:
   - [Completed 2026-07-26] RandomForest with class balancing
   - [Completed 2026-07-26] ExtraTrees for nonlinear trace patterns
   - [Completed 2026-07-26] calibrated probabilities when class counts allow it
2. [Completed 2026-07-26] Train per assay. Grouped assay families remain research-only comparisons.
3. [Completed 2026-07-26] Save `feature_columns`, `label_order`, thresholds, label counts, data fingerprint, grouped validation metadata, and promotion state with every model.

## Phase 4 - Validation Reports

1. [Completed 2026-07-26] Produce per-assay reports with:
   - confusion matrix
   - macro F1, balanced accuracy, monoklonal F1
   - per-class precision/recall/F1
   - false-positive monoklonal examples
   - rule-vs-ML disagreement table
   - [Completed 2026-07-26] fold-held-out permutation feature importance
2. [Completed 2026-07-26] Generate local review HTML panels for disagreement and low-confidence cases.
3. [Partially completed 2026-07-26] Track performance by run date and sanitized run folder. Instrument-specific drift awaits a reliable instrument field.
4. [Completed 2026-07-26] Require an explicit-classifier stress test that
   holds complete `SourceRunKey` groups out and gates promotion on run support,
   macro F1, and monoklonal precision.

## Phase 5 - Runtime Integration

1. [Completed 2026-07-26] Keep ML default-off.
2. [Completed 2026-07-26] In app reports, show ML as a second-opinion badge only:
   - ML suggestion
   - confidence
   - threshold
   - reason for review
3. [Completed in runtime gate 2026-07-26] Accept an ML second opinion only when:
   - rule and ML agree
   - confidence is above assay threshold
   - ladder/control/DNA quality gates pass
   - assay validation report meets minimum monoklonal and macro-F1 thresholds
4. [Completed 2026-07-26] Always route disagreement, rare-label predictions, low-confidence rows, and unavailable traces to review.
5. [Completed 2026-07-26] Runtime accepts only
   `ml_training_pipeline_v5` artifacts with passing DIT/content-grouped and
   source-run-grouped validation evidence.
6. [Completed 2026-07-26] Coalesce DITs connected by an identical
   `FsaContentHash` before primary OOF splitting, require 100% hash coverage,
   and record duplicate-content provenance in every model.
7. [Completed 2026-07-26] Enforce one physical trace per assay as one training
   vote, apply sample thresholds after deduplication, and reject identical
   bytes with conflicting chemist labels or source-run assignments.

## Phase 6 - Learning Loop

1. [Completed 2026-07-26] Make labeling ergonomic in the Qt app:
   - filter unlabeled/review-needed
   - keyboard labels
   - quick save back to tracking workbook
2. Export new labelled batches after each chemist session.
3. Re-train, compare against previous model, and only promote if validation improves or review burden drops without harming monoklonal precision.

## Immediate Next Tasks

1. Complete and inspect the full local trace-feature extraction. Require zero
   unresolved files, no raw paths in the feature CSV, and a documented error
   review before using the artifact.
2. Run a chemist-labeling pilot from the clean tracking workbook. Sample across
   assays, source runs, rule suggestions, and review-needed cases; do not copy
   the rule suggestion into the chemist label.
3. Re-run the audit after each labeling batch and report class support by
   independent DIT and source run. Do not train an assay with one class or
   inadequate grouped-fold support.
4. Train candidate-only per-assay RandomForest and ExtraTrees models once label
   support passes those gates, then generate grouped out-of-fold disagreement
   panels.
5. Decide assay-specific confidence, precision, coverage, and calibration gates
   with the chemist before promoting any model or enabling it in reports.

## 2026 Real-Data Checkpoint

Completed on 2026-07-26 against the private January-April 2026 corpus:

- 5,280 local `.fsa` files inventoried across 55 source-run folders.
- A clean tracking rebuild completed all 55 folders with zero failed folders.
- The inventory contains 3,103 analyzed rows: 2,402 model-eligible patient
  injections, 700 controls, and one safely unassigned injection.
- Strict audit resolved all 2,402 patient injections uniquely, with zero
  missing FSA files, zero duplicate identities, and all 55 source runs retained.
- No chemist labels were present in the available tracking workbooks. Rule
  suggestions remain comparison data only and must not become training truth.
- Full trace-feature extraction was started from the audited workbook as a
  resumable, local-only artifact.

## Real-Data Audit Command

Chemist labels live in `ClonalityChemistLabel`. The existing
`ClonalitySuggestion` remains the rule-based output so it can be compared with
ML without becoming accidental training ground truth.

```powershell
python -m scripts.audit_clonality_ml_data `
  --xls "C:\path\to\Clonality_Tracking.xlsx" `
  --fsa-root "D:\path\to\raw-fsa" `
  --output-dir "C:\local\clonality-ml-audit" `
  --strict
```

The command understands current `Runs` workbooks, legacy `Run` workbooks, and
split `Patient_Runs`/`Control_Runs` workbooks. It writes a JSON summary plus
local row, missing-file, and feature-quality CSVs. These outputs can contain
clinical identifiers and local paths; keep them outside Git.

`--strict` exits with code 2 for blocking issues such as missing FSA files,
invalid labels, duplicate identities, empty files, or missing DIT values.

## Trace Feature and Training Commands

Run a small smoke extraction first:

```powershell
python -m scripts.build_clonality_ml_features `
  --xls "C:\path\to\Clonality_Tracking.xlsx" `
  --fsa-root "D:\path\to\raw-fsa" `
  --output-dir "C:\local\clonality_ml_features" `
  --limit 25
```

Continue with the full local corpus. Checkpoints are written atomically and
`--resume` skips rows whose file content, trace/cohort feature schemas, and
clonality settings already match:

```powershell
python -m scripts.build_clonality_ml_features `
  --xls "C:\path\to\Clonality_Tracking.xlsx" `
  --fsa-root "D:\path\to\raw-fsa" `
  --output-dir "C:\local\clonality_ml_features" `
  --resume
```

Train per-assay candidate models from the resulting trace artifact:

```powershell
python -m scripts.train_clonality_interpretation_models `
  --xls "C:\path\to\Clonality_Tracking.xlsx" `
  --features-csv "C:\local\clonality_ml_features\clonality_ml_trace_features.csv" `
  --output-dir "C:\local\clonality_ml_models" `
  --min-samples 200 `
  --classifier-kind random_forest
```

Training writes candidate-only models plus grouped out-of-fold predictions,
disagreement/review CSVs, drift summaries, split metadata, and an HTML review
panel. Candidate metadata is rejected by runtime.

Use `--classifier-kind auto` for a candidate-only comparison of RandomForest
and ExtraTrees on identical grouped folds. Inspect the model-comparison output,
then rerun the selected explicit classifier in a fresh directory for promotion;
auto-selected models cannot be promoted directly.

After chemist review, rerun with `--promote-if-passes` and explicit
`--min-macro-f1`, `--min-monoklonal-f1`,
`--min-monoklonal-precision`, `--min-dit-groups`,
`--min-accepted-accuracy`, `--min-accepted-coverage`, and
`--max-calibration-error` gates, plus source-run group, macro-F1, and
monoklonal-precision gates. Exit code `2` means promotion was blocked;
the candidate and validation reports remain available for inspection.

The feature CSV stores numeric summaries, source hashes, chemist labels, and
rule outputs for disagreement analysis. It does not store raw traces or raw
FSA paths. All audit, feature, and model artifacts remain local and ignored by
Git.
