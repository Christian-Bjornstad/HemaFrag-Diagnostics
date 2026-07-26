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
- Primary validation groups by connected DIT/FSA-content components; the same
  patient or byte-identical trace cannot occur in train and test. Explicit
  classifier runs also hold out complete source runs.
- Within each assay, one FSA content hash contributes one training vote.
  Conflicting chemist labels or source-run assignments for identical bytes
  stop training.
- Every modeled label must have configurable independent DIT and source-run
  support. `monoklonal` and `polyklonal` are required classes.
- Every label must occur in enough held-out folds, remain present in every
  training fold, and have at least six training rows per fold so tree-model
  confidence is calibrated consistently.
- Replicate and panel context is limited to the same DIT and sanitized source
  run, and controls/SL are excluded from patient context.
- Training produces runtime-ineligible candidates by default.
- Runtime only discovers explicitly promoted `ml_training_pipeline_v6`
  artifacts whose metadata proves complete DIT/content- and source-run-grouped
  out-of-fold validation plus per-class support and fold coverage.
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
4. Build one dataset per assay, require complete `FsaContentHash` coverage,
   reject conflicting duplicate provenance, remove agreeing byte-identical
   copies, then measure row, independent-DIT, and source-run support per class.
5. Validate with `StratifiedGroupKFold`. DITs connected by byte-identical FSA
   content are coalesced into one validation group as defense in depth.
6. In auto mode, compare calibrated RandomForest and ExtraTrees candidates
   on identical grouped folds and select one using the recorded safety-first
   ranking.
7. Rerun the selected explicit classifier with complete source runs held out.
   Require each class to remain trainable and evaluable across both validation
   strategies, including the six-row calibration minimum in every train fold.
8. Export row-level out-of-fold predictions, disagreements, review cases,
   drift summaries, held-out feature importance, split provenance, metrics,
   and a local HTML review panel.
9. Refit the selected candidate estimator on all unique labeled traces.
10. Keep the artifact candidate-only unless explicit promotion was requested
   and every configured metric gate passed.
11. At runtime, show eligible ML output as a second-opinion badge without
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
  --classifier-kind auto
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
  --min-class-dit-groups 10 `
  --min-core-class-dit-groups 20 `
  --min-class-source-run-groups 3 `
  --min-class-evaluation-folds 2 `
  --min-class-training-rows-per-fold 6 `
  --min-accepted-accuracy 0.95 `
  --min-accepted-coverage 0.10 `
  --max-calibration-error 0.10 `
  --source-run-validation-folds 3 `
  --min-source-run-groups 3 `
  --min-source-run-macro-f1 0.65 `
  --min-source-run-monoklonal-precision 0.85
```

Exit code `2` means explicit promotion was blocked. Candidate models and
reports are still written for inspection.

Each training run requires a fresh output directory. This prevents a failed
or partial retraining run from leaving stale validated assay artifacts mixed
with current candidates.

`--classifier-kind auto` is comparison-only and cannot be promoted directly.
Review `model_comparison_<assay>.json`, then rerun the selected explicit
classifier in a fresh directory with the promotion gates.
Auto comparison defers the source-run stress test; an explicit classifier run
must complete it before promotion can succeed.

## Feature Artifact

`clonality_ml_trace_features.csv` contains:

- privacy-preserving identity and FSA content/source hashes;
- assay, DIT, run date, and sanitized source-run key;
- current chemist label;
- independent rule suggestion, confidence, review flag, evidence, and version;
- scalar analysis features;
- deterministic `clonality_trace_features_v1` per-channel trace summaries;
- deterministic `clonality_cohort_features_v1` same-run panel and replicate
  summaries, including duplicate peak-bp concordance.

It does not contain raw traces, raw FSA paths, or source-run paths. The local
manifest contains source paths and must not be committed.

Resume requires matching:

- FSA byte content hash;
- trace feature schema;
- cohort feature schema;
- assay ranges and nonspecific-peak settings fingerprint.

The current artifact version is `clonality_ml_feature_dataset_v2`. A v1
checkpoint cannot be resumed; rebuild it so cohort context is computed over
the complete local artifact.

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
model_comparison_<assay>.json
model_comparison_<assay>.csv
feature_importance_<assay>.csv
source_run_predictions_<assay>.csv
source_run_metrics_<assay>.json
source_run_splits_<assay>.json
```

The three `source_run_*` files are written for explicit classifier runs. They
prove that all rows from each sanitized source run stayed in one fold.

The predictions file has one out-of-fold row per labeled sample. It includes
chemist, rule, and ML labels; confidence; fold; rule/ML agreement; chemist/ML
agreement; monoklonal false-positive status; review reason; and class
probabilities.

The primary split manifest records original DIT count, independent
DIT/content-component count, duplicate content-hash count, cross-DIT duplicate
hash count, and the number of DIT groups coalesced to prevent leakage. Both
primary and source-run split manifests also record, for every label, train/test
fold coverage and minimum rows in any train or test fold.

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

Feature importance is not taken from the final refitted model. In each grouped
fold, the fold model shortlists at most 25 features using native importance,
or label-free fold variance when the estimator has no native importance. Each
shortlisted feature is then permuted on untouched DIT groups. The CSV reports
balanced-accuracy impact, variability, fold coverage, and the fraction of
evaluated folds with positive impact. Use `--importance-max-features` and
`--importance-repeats` to bound or disable this work. Auto comparison skips
permutation work; rerunning its selected explicit classifier produces the
importance report before promotion.

## Model Metadata

Every candidate stores:

- feature columns plus trace and cohort schemas;
- label order, class counts, and per-class DIT/source-run support;
- training row, unique-DIT, and independent DIT/content-group counts;
- raw labeled rows, unique physical traces, removed duplicate copies, content
  hash coverage, and duplicate label/run conflict counts;
- privacy-preserving training-data fingerprint;
- grouped validation strategy, fold count, random state, per-class fold
  coverage, and metrics;
- source-run stress metrics, split provenance, thresholds, and pass/fail state;
- held-out feature-importance method and the top 20 aggregated features;
- requested and selected classifier plus every comparison candidate's metrics;
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
2. `model_path` contains at least one eligible validated v6 assay artifact.

Runtime rejects v1-v5 artifacts and v6 artifacts lacking complete content-hash
deduplication/grouping, per-class independent support and fold coverage, or a
complete passing `SourceRunKey` stress test. This deliberately requires
retraining before an older model can be enabled.

The batch pipeline attaches rule results first, computes same-run patient
context across the completed batch, and only then invokes ML. The runtime
recomputes full raw-trace features when the rule layer only cached scalar
features. It refuses to infer when no trace channel is available, or when a
model requires cohort fields but batch context is unavailable.

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
core/analyses/clonality/cohort_features.py
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
- Confirm every modeled label meets independent-patient, source-run, fold
  coverage, and calibration-row gates; merge or review-route unsupported labels.
- Decide assay-specific promotion thresholds with the chemist.
- Review whether the automatic RandomForest/ExtraTrees ranking is stable
  across run-date cohorts and an external holdout.
- Add control-run and instrument-context features where provenance is reliable.
- Promote no model until real-data evidence supports every configured gate.
