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

1. Standardize one labelled table per sample/injection with:
   - `DIT`, `Assay`, `File`, `SourceRunDir`, `RunDate`, `Well`
   - chemist label in `ClonalityChemistLabel`
   - current rule output and review flag
   - raw `.fsa` path or resolvable relative path
2. Export a manifest that records which raw files were included but stores no raw clinical data in Git.
3. Add a validation command that fails fast when labels, assay names, or DITs are missing.

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
2. [Completed 2026-07-26] Generate local review HTML panels for disagreement and low-confidence cases.
3. [Partially completed 2026-07-26] Track performance by run date and sanitized run folder. Instrument-specific drift awaits a reliable instrument field.

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

## Phase 6 - Learning Loop

1. Make labeling ergonomic in the Qt app:
   - filter unlabeled/review-needed
   - keyboard labels
   - quick save back to tracking workbook
2. Export new labelled batches after each chemist session.
3. Re-train, compare against previous model, and only promote if validation improves or review burden drops without harming monoklonal precision.

## Immediate Next Tasks

1. [Completed 2026-07-26] Build a real-data feature audit script that reads a tracking workbook plus raw `.fsa` root and reports:
   - rows with missing raw files
   - assay/label counts
   - DIT grouping quality
   - feature null/zero rates
2. [Completed 2026-07-26] Add richer reference-window trace-shape features to `features_from_entry` and the offline feature builder.
3. Train one first real per-assay model on the best labelled workbook and generate disagreement panels.
4. Decide threshold gates from the first validation report before enabling anything in normal reports.

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
`--max-calibration-error` gates. Exit code `2` means promotion was blocked;
the candidate and validation reports remain available for inspection.

The feature CSV stores numeric summaries, source hashes, chemist labels, and
rule outputs for disagreement analysis. It does not store raw traces or raw
FSA paths. All audit, feature, and model artifacts remain local and ignored by
Git.
