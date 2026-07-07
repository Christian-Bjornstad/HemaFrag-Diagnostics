# HemaFrag ML — Clonality Interpretation

> Branch: `ml-clonality-interpretation-2026-06-27`
> Context: extracted from session `20260627_180325_8ee258` (June 27, 2026).
> Purpose: single entry point for anyone taking up the ML pipeline.

---

## What the ML does

Given a labelled tracking workbook (`Clonality_Tracking.xlsx`), the pipeline
trains **per-assay** clonality classifiers that predict one of 8 annotation
classes from electrophenogram features.  The goal is a **second opinion** —
after the rule-based interpreter (`interpretation.py`) produces a suggestion,
the ML model produces an independent probability estimate.  When the two agree
and the ML probability exceeds the per-assay threshold, the suggestion is
**auto-accepted**; otherwise it is flagged for chemist review.

---

## Annotation classes (canonical order)

```python
# core/analyses/clonality/interpretation.py  ANNOTATION_CLASSES
# core/analyses/clonality/ml_training.py     ANNOTATION_CLASSES_ORDER
ANNOTATION_CLASSES_ORDER = (
    "monoklonal",
    "polyklonal",
    "bi_oligoklonal",
    "irregulaer",
    "pseudoklonal",
    "intet_pcr_produkt_darlig_dna",
    "qc_teknisk_fail",
    "usikker_review",
)
```

The order matters: the confusion matrix printer, the metric reporter, and the
Phase-4 calibration layer all iterate in this order.

---

## Feature set

Features are extracted by `core/analyses/clonality/feature_artifacts.py` and
`core/analyses/clonality/tracking_excel.py` into three CSV artefacts:

| Artefact | Contents |
|---|---|
| `clonality_feature_artifacts.csv` (combined) | Patient + control rows, all scalar features |
| `clonality_ladder_features.csv` | Ladder-only rows |
| `clonality_pk_features.csv` | Peak-control rows |

Feature columns used for training (`train_clonality_interpretation_quick_model.py`
`NUMERIC_FEATURES`, `NON_NUMERIC_PREFIX_FEATURES`, `CATEGORICAL_FEATURES`):

**Numeric (65 features):**
- Ladder quality: `ladder_r2`, `ladder_linear_r2`, `ladder_linear_mean_residual_bp`,
  `ladder_linear_max_residual_bp`
- Peak counts: `raw_peak_count`, `peak_count`, `peak_count_in_interpretation_range`,
  `peak_count_outside_interpretation_range`
- Dominant peak: `dominant_peak_basepairs`, `dominant_peak_height`, `dominant_peak_area`,
  `dominant_height_share`, `dominant_area_share`, `dominant_to_second_ratio`,
  `second_peak_height`, `total_peak_height`, `total_peak_area`
- Range: `interpretation_range_min_bp`, `interpretation_range_max_bp`,
  `outside_interpretation_height_share`
- Rust preview (from `fraggler-cli`): `rust_preview_top_score`,
  `rust_preview_top_clonal_groups`, `rust_preview_top_dominant_ratio`
- QC tracking: `tracking_marker_count`, `tracking_marker_hits`, `tracking_marker_misses`
- Size ladder (SL): `sl_total_area`, `sl_100_percent`, `sl_200_percent`,
  `sl_300_percent`, `sl_400_percent`, `sl_600_percent`, `sl_fragmented_percent`

**Trace-prefixed features** (`trace_*`, `replicate_*`): extracted per-channel from
raw FSA trace data, prefixed by channel name.

**Non-numeric prefix features** (one-hot encoded separately):
- `trace_primary_channel`, `trace_channels_evaluated`, `trace_reference_ranges_bp`,
  `replicate_peak_basepairs`

**Categorical features** (OneHotEncoder):
- `assay`, `ladder`, `primary_peak_channel`, `sample_kind`, `control`

> Note: `_ensure_numeric_X()` in `ml_training.py` factorises any remaining
> non-numeric column to float, so stray string columns do not crash training.

---

## Module map

```
core/analyses/clonality/
├── ml_training.py          # Pure training logic (0 side effects)
│   ├── ANNOTATION_CLASSES_ORDER        # canonical label tuple
│   ├── PerAssayDataset                 # dataclass: X / y / dit / assay / counts
│   ├── PerAssayMetrics                 # dataclass: holdout metrics
│   ├── build_per_assay_datasets()      # filter + split by assay, enforce min N
│   ├── group_shuffle_split_by_dit()    # GroupShuffleSplit (patient never in train+test)
│   ├── fit_classifier()                 # RandomForest or QDA+imputer
│   ├── per_assay_metrics()              # accuracy / F1 / confusion matrix
│   ├── serialize_model()               # joblib + metadata.json per assay
│   └── deserialize_model()             # inverse of serialize
│
├── calibration.py          # Phase 4 — inference with rejection
│   ├── CalibratedMLPrediction           # dataclass: label / confidence / accepted / reason
│   ├── load_calibrated_pipeline()      # load estimator + metadata from path
│   ├── predict_with_rejection()        # apply rules + threshold, return CalibratedMLPrediction
│   └── attach_ml_suggestion_if_enabled() # entry-level wrapper (APP_SETTINGS driven)
│
├── interpretation.py       # Rule-based first-pass interpreter
│   ├── ANNOTATION_CLASSES, ANNOTATION_SCHEMA_VERSION, MODEL_VERSION
│   ├── CONTROL_FLAGS, TRACKING_COLUMNS
│   ├── interpret_entry()                # main rule interpreter
│   ├── features_from_entry()            # extract scalar features per entry
│   └── assay_interpretation_ranges()    # per-assay bp ranges
│
├── feature_artifacts.py    # Export features to CSV
│   ├── build_clonality_feature_tables()  # reads XLSX → combined/ladder/pk DataFrames
│   └── write_clonality_feature_artifacts() # persists to CSV + manifest
│
├── pipeline.py            # Batch analysis loop (_analyze_single_file)
├── tracking_excel.py      # XLSX read helpers (Patient_Runs, Control_Runs, PK_Peaks)

scripts/
├── train_clonality_interpretation_models.py   # Plan 11 Phase 3 CLI driver
│   ├── _assemble_labelled_df()                # direct from XLSX (needs ClonalitySuggestion col)
│   ├── _assemble_labelled_df_with_labels_csv() # merge labels from separate CSV
│   ├── _train_one_assay()                     # DIT holdout + fit + metrics
│   ├── _render_per_assay_markdown()           # markdown report per assay
│   └── main()                                 # orchestrates everything
│
└── train_clonality_interpretation_quick_model.py  # Ad-hoc single-script trainer
    ├── NUMERIC_FEATURES, CATEGORICAL_FEATURES, NON_NUMERIC_PREFIX_FEATURES
    ├── build_features_frame()           # assemble feature matrix from XLSX
    ├── train_and_evaluate()             # single assay, single classifier
    └── quick_model()                    # CLI entry point

scripts/
└── render_clonality_interpretation_annotation_html.py  # Annotation panel renderer
    ├── collect_candidate_files()        # gather FSA files for annotation
    ├── render_annotation_panel()        # draw electropherogram + ML suggestion panel
    └── render_annotation_set()          # batch export to HTML
```

---

## Classifier options

| `classifier-kind` | What is fitted | When to use |
|---|---|---|
| `random_forest` (default) | `RandomForestClassifier(n_estimators=400, class_weight="balanced")` wrapped in `CalibratedClassifierCV(cv=3)` (Platt scaling) | Primary workhorse.  Skips Platt if any class has < 6 samples in training fold. |
| `qda_calibrated` | `Pipeline(SimpleImputer(median) → QuadraticDiscriminantAnalysis())` | Fallback when RF overfits rare classes or data is very small. |

Auto-selection logic (inside `fit_classifier()`):
```
min_class_count = y_train.value_counts().min()
if min_class_count >= 6:
    CalibratedClassifierCV(base, method="sigmoid", cv=3)  # Platt scaling
else:
    raw RandomForestClassifier  (no calibration)
```

---

## Group split strategy

`group_shuffle_split_by_dit()` uses `sklearn.model_selection.GroupShuffleSplit`
with `groups = DIT` (patient ID).  A patient's samples are **never split across
train and test** — prevents leakage from the same patient appearing in both folds.

Default split: 80 % train / 20 % test, `random_state=12345`.

---

## Training CLI

```bash
# Direct XLSX (needs ClonalitySuggestion column already in the workbook)
python -m scripts.train_clonality_interpretation_models \
    --xls "D:/HemaFrag/NightRuns/overnight_all_2026-05-28_214248/clonality/Clonality_Tracking_All_T7.xlsx" \
    --output-dir "D:/HemaFrag/ML_Models" \
    --min-samples 200 \
    --classifier-kind random_forest \
    --assays FR1,TCRG-A

# Via external labels CSV (when XLSX lacks ClonalitySuggestion)
python -m scripts.train_clonality_interpretation_models \
    --xls "D:/HemaFrag/NightRuns/.../Clonality_Tracking_All_T7.xlsx" \
    --labels-csv "D:/HemaFrag/external_labels.csv" \
    --output-dir "D:/HemaFrag/ML_Models" \
    --min-samples 200
```

**CSV column requirements for `--labels-csv`:**
- Canonical: `DIT`, `Assay`, `ClonalitySuggestion`
- Accepted aliases: `identity_key` → `DIT`, `assay` → `Assay`

**Output per assay** (`<output-dir>/<assay>/`):
```
random_forest.joblib    # fitted estimator (joblib)
metadata.json           # schema_version, assay, label_order, accept_threshold_tau,
                         # classifier_kind, rare_class_counts, trained_at_utc
```

**Report** (`<output-dir>/reports/<date>/`):
```
<assay>.md  # confusion matrix + per-class precision/recall/F1 + macro-F1 + notes
```

---

## Phase 4 — Inference / Calibration

`calibration.py` wraps the trained models for use during batch runs.

**Trigger conditions** (any of these forces `usikker_review`, no ML inference):

1. `ladder_qc_status` not in `{"", "ok", "manual_adjustment"}`
2. `control_flag` in `{"kontroll_avvik", "kontaminasjon_mistenkt"}`
3. Rule-derived label in `{"qc_teknisk_fail", "intet_pcr_produkt_darlig_dna"}`

**Acceptance condition** (if none of the above apply):
```
ML argmax ∈ {"monoklonal", "polyklonal", "bi_oligoklonal"}
AND
ML probability >= per_assay_accept_threshold[assay]
```
→ `accepted = True`, write `ClonalityMLSuggestion` / `ClonalityMLConfidence`

Otherwise → `accepted = False`, route to `usikker_review`.

**Threshold**: `accept_threshold_tau` is persisted in `metadata.json` and
defaults to `0.85` (from `APP_SETTINGS["analyses"]["clonality"]["interpretation"]["thresholds"]`).
Chemist calibrates per assay from the markdown reports.

**ML auto-apply guard** (from markdown report notes):
```
if monoklonal-class F1 < 0.70: do not auto-apply → route to usikker_review
```

---

## Quick model (ad-hoc trainer)

`scripts/train_clonality_interpretation_quick_model.py` is a self-contained
training script for single-assay experimentation without the full XLSX
pipeline.  It reads the feature table CSV directly and produces a `quick_model.joblib`
plus a JSON summary.  Useful for rapid feature engineering iteration.

---

## Column aliasing (last fixed in session 20260627)

Two layers of aliasing exist to bridge the tracking export names with the
canonical names the ML layer uses:

```
# feature_artifacts.py emits        → ml_training.py expects
  identity_key                         DIT
  assay                                Assay
  y                                    ClonalitySuggestion
```

Both `build_per_assay_datasets()` (ml_training.py) and
`_assemble_labelled_df_with_labels_csv()` (train script) handle renames
automatically.  The labels CSV itself may use either canonical or aliased
names — both are accepted.

If you see `KeyError: 'DIT'` or `KeyError: 'ClonalitySuggestion'` from the
training CLI, the input data used the alias form and the rename logic either
wasn't triggered or the column is genuinely missing.  Run with `--verbose` or
check the merged DataFrame before `build_per_assay_datasets()`.

---

## Known issues / session findings

1. **`from_X_inherit` `__all__` is required in split packages.**
   Every `_constants.py` inside a split package **must** declare `__all__`
   enumerating every underscore-prefixed name (`_CACHE`, `_LOCK`, `_STATS`).
   Without it, `from ._constants import *` silently drops private state,
   causing `NameError: name '_X' is not defined` at runtime.
   Run `scripts/audit_split_package_reexports.py .` after any package split.

2. **abi3 wheel is Python-version-agnostic but scripts must match.**
   `fraggler_kernels-0.1.0-cp311-abi3-win_amd64.whl` works on Python 3.12
   because abi3-py311 means "stable ABI from Python 3.11 upward".  However,
   `install.bat` must be verified to target the correct Python 3.12 venv.
   Cross-compilation prep (`python-3.11.9-embed-amd64.zip`) is still needed
   for PyO3 linking — host Python 3.12 does not change the link target.

3. **Platt scaling requires ≥ 6 samples per class.**
   `fit_classifier()` checks `min_class_count >= 6` before attempting
   `CalibratedClassifierCV(cv=3)`.  Assays below this threshold get a raw
   RF (uncalibrated probabilities — confidence values are unreliable).

---

## Taking up this pipeline

**Prerequisites on thechemist's machine:**
```powershell
# Python 3.12 at the standard location
C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe --version

# Dependencies
pip install numpy pandas scikit-learn joblib matplotlib openpyxl
```

**Minimal retraining workflow:**
```bash
# 1. Produce the feature table (if not already done)
python -m core.analyses.clonality.feature_artifacts \
    --xlsx "D:/HemaFrag/.../Clonality_Tracking_All_T7.xlsx" \
    --output-dir "D:/HemaFrag/features"

# 2. Train
python -m scripts.train_clonality_interpretation_models \
    --xls "D:/HemaFrag/.../Clonality_Tracking_All_T7.xlsx" \
    --output-dir "D:/HemaFrag/ML_Models" \
    --min-samples 200

# 3. Read reports under D:/HemaFrag/ML_Models/reports/<date>/
#    Calibrate per-assay tau from monoklonal F1 + macro F1
#    Edit APP_SETTINGS["analyses"]["clonality"]["interpretation"]["thresholds"]

# 4. Enable Phase 4 calibration in APP_SETTINGS
#    analyses.clonality.interpretation.enabled = true
#    analyses.clonality.learning.enabled = true
#    analyses.clonality.learning.output_dir = "D:/HemaFrag/ML_Learning"
```

**Key files to modify for new features:**
1. Add feature to `NUMERIC_FEATURES` / `NON_NUMERIC_PREFIX_FEATURES` in
   `train_clonality_interpretation_quick_model.py` and `ml_training.py`
2. Re-run `train_clonality_interpretation_models.py`
3. Compare reports: macro F1, balanced accuracy, monoklonal F1

**Adding a new annotation class:**
1. Append to `ANNOTATION_CLASSES_ORDER` in `ml_training.py`
2. Append to `ANNOTATION_CLASSES` in `interpretation.py`
3. Update `_FORCE_REVIEW_LABELS` / `_ACCEPTED_LABELS` in `calibration.py`
   if the new class should be handled specially
4. Re-train and re-calibrate thresholds