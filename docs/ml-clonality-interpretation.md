# HemaFrag Clonality ML

This is the operator and developer guide for the real-FSA clonality ML
pipeline. ML is a confidence-scored second opinion. The existing rule result
remains the report source of truth.

## Safety Contract

- Raw `.fsa` files and generated clinical artifacts stay local and out of Git.
- Chemist ground truth lives in `ClonalityChemistLabel`.
- `ClonalitySuggestion` is the independent rule output and is never used as
  accidental ground truth.
- Models train and validate per assay.
- Validation groups by `DIT`; the same patient cannot occur in train and test.
- Training produces runtime-ineligible candidates by default.
- Runtime only discovers explicitly promoted `ml_training_pipeline_v2`
  artifacts whose metadata proves complete grouped out-of-fold validation.
- Controls, SL, unavailable traces, failed quality gates, disagreement,
  low confidence, and rare-label predictions are never silently accepted.

## Labels

The canonical classes are:

```text
monoklonal
polyklonal
bi_oligoklonal
irregulaer
pseudoklonal
intet_pcr_produkt_darlig_dna
qc_teknisk_fail
usikker_review
```

Changing this list requires chemist approval, a schema bump, retraining, and
revalidation.

## Pipeline

1. Audit the tracking workbook against the local FSA root.
2. Analyze each resolved FSA and export flat scalar plus per-channel trace
   features.
3. Refresh chemist labels from the current workbook at training time.
4. Build one dataset per assay and validate with `StratifiedGroupKFold`,
   grouping by DIT.
5. Export row-level out-of-fold predictions, disagreements, review cases,
   drift summaries, split provenance, metrics, and a local HTML review panel.
6. Refit the candidate estimator on all labeled rows.
7. Keep the artifact candidate-only unless explicit promotion was requested
   and every configured metric gate passed.
8. At runtime, show eligible ML output as a second-opinion badge without
   replacing the rule interpretation.

## Commands

Audit first:

```powershell
python -m scripts.audit_clonality_ml_data `
  --xls "C:\local\Clonality_Tracking.xlsx" `
  --fsa-root "D:\local\raw-fsa" `
  --output-dir "C:\local\clonality_ml_audit" `
  --strict
```

Build a 25-row smoke artifact:

```powershell
python -m scripts.build_clonality_ml_features `
  --xls "C:\local\Clonality_Tracking.xlsx" `
  --fsa-root "D:\local\raw-fsa" `
  --output-dir "C:\local\clonality_ml_features" `
  --limit 25
```

Resume the full extraction:

```powershell
python -m scripts.build_clonality_ml_features `
  --xls "C:\local\Clonality_Tracking.xlsx" `
  --fsa-root "D:\local\raw-fsa" `
  --output-dir "C:\local\clonality_ml_features" `
  --resume
```

Train candidate models and validation artifacts:

```powershell
python -m scripts.train_clonality_interpretation_models `
  --xls "C:\local\Clonality_Tracking.xlsx" `
  --features-csv "C:\local\clonality_ml_features\clonality_ml_trace_features.csv" `
  --output-dir "C:\local\clonality_ml_models" `
  --min-samples 200 `
  --validation-folds 5 `
  --classifier-kind random_forest
```

After chemist review, request promotion with explicit gates:

```powershell
python -m scripts.train_clonality_interpretation_models `
  --xls "C:\local\Clonality_Tracking.xlsx" `
  --features-csv "C:\local\clonality_ml_features\clonality_ml_trace_features.csv" `
  --output-dir "C:\local\clonality_ml_models_validated" `
  --min-samples 200 `
  --validation-folds 5 `
  --classifier-kind random_forest `
  --promote-if-passes `
  --min-macro-f1 0.70 `
  --min-monoklonal-f1 0.70 `
  --min-monoklonal-precision 0.90 `
  --min-dit-groups 50 `
  --min-accepted-accuracy 0.95 `
  --min-accepted-coverage 0.10 `
  --max-calibration-error 0.10
```

Exit code `2` means explicit promotion was blocked. Candidate models and
reports are still written for inspection.

Each training run requires a fresh output directory. This prevents a failed
or partial retraining run from leaving stale validated assay artifacts mixed
with current candidates.

## Feature Artifact

`clonality_ml_trace_features.csv` contains:

- privacy-preserving identity and FSA content/source hashes;
- assay, DIT, run date, and sanitized source-run key;
- current chemist label;
- independent rule suggestion, confidence, review flag, evidence, and version;
- scalar analysis features;
- deterministic `clonality_trace_features_v1` per-channel trace summaries.

It does not contain raw traces, raw FSA paths, or source-run paths. The local
manifest contains source paths and must not be committed.

Resume requires matching:

- FSA byte content hash;
- trace feature schema;
- assay ranges and nonspecific-peak settings fingerprint.

## Validation Outputs

For each assay, `<output-dir>/reports/<date>/` contains:

```text
report_<assay>.md
metrics_<assay>.json
predictions_<assay>.csv
review_cases_<assay>.csv
review_panel_<assay>.html
drift_<assay>.csv
splits_<assay>.json
```

The predictions file has one out-of-fold row per labeled sample. It includes
chemist, rule, and ML labels; confidence; fold; rule/ML agreement; chemist/ML
agreement; monoklonal false-positive status; review reason; and class
probabilities.

Review reasons include:

```text
monoklonal_false_positive
chemist_ml_disagreement
rule_ml_disagreement
low_confidence
rare_label_prediction
```

Drift summaries report accuracy, confidence, rule disagreement, and
monoklonal false positives by run date and sanitized source-run key.

## Model Metadata

Every candidate stores:

- feature columns and trace schema;
- label order and class counts;
- training row and unique-DIT counts;
- privacy-preserving training-data fingerprint;
- grouped validation strategy, fold count, random state, and metrics;
- promotion thresholds, pass/fail state, and blocking reasons;
- expected calibration error plus high-confidence coverage and accuracy;
- Python, NumPy, pandas, scikit-learn, and joblib versions;
- deployment status and runtime eligibility.

The final estimator is refit on all labeled rows only after out-of-fold
validation is complete. Validation predictions always come from fold models,
never from the refitted candidate.

## Runtime And Reports

ML stays off unless both conditions are true:

1. `analyses.clonality.interpretation.enabled` is true.
2. `model_path` contains at least one eligible validated v2 assay artifact.

The runtime recomputes full raw-trace features when the rule layer only cached
scalar features. It refuses to infer when no trace channel is available.

Tracking/report fields are:

```text
ClonalityMLSuggestion
ClonalityMLConfidence
ClonalityMLThreshold
ClonalityMLReviewNeeded
ClonalityMLEvidence
ClonalityMLModelVersion
```

The HTML badge shows the ML label, confidence, threshold, rule label, and
review state. It does not overwrite `ClonalitySuggestion`.

## Main Modules

```text
core/analyses/clonality/ml_data_audit.py
core/analyses/clonality/trace_features.py
core/analyses/clonality/ml_feature_dataset.py
core/analyses/clonality/ml_training.py
core/analyses/clonality/ml_validation.py
core/analyses/clonality/ml_model.py
core/analyses/clonality/ml_runtime.py
scripts/audit_clonality_ml_data.py
scripts/build_clonality_ml_features.py
scripts/train_clonality_interpretation_models.py
```

## Remaining Real-Data Work

- Run the audit and extraction against the private mounted corpus.
- Inspect per-assay label support, review panels, and run-date drift.
- Decide assay-specific promotion thresholds with the chemist.
- Compare RandomForest with an additional nonlinear baseline where sample
  support allows.
- Add replicate/panel and instrument-context features where provenance is
  reliable.
- Promote no model until real-data evidence supports every configured gate.
