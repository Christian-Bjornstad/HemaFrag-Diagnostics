# Clonality Interpretation Asset Map (Phase 0 / T-0.1)

> Reads top-down so a clinical chemist unfamiliar with the codebase can answer
> "what function computes what feature and what rule path decides which
> annotation class?" in one sitting.

## Pipeline direction (one-paragraph)

1. Pipeline orchestrator (`pipeline.py::run_pipeline`) reads `.fsa` files, classifies each by
   filename assay, runs a classifier chain (`_analyze_single_file`), returns a list of entry dicts.
2. Per-entry features are computed in-place by `interpretation.py::features_from_entry(...)`.
3. The rule engine (`interpretation.py::interpret_entry(...)`) consumes the entry dict,
   walks the rule path for the entry's assay, and returns one of ANNOTATION_CLASSES values
   plus evidence strings.
4. Optional ML second-opinion: when interpretation is enabled,
   `ml_runtime.attach_ml_prediction_if_enabled(...)` loads only an explicitly
   promoted, dual-group-validated v3 per-assay artifact. It recomputes raw trace
   features when needed and leaves the rule output unchanged.
5. Tracking Excel writer (`tracking_excel.py::update_clonality_tracking_workbook`) writes
   the rule columns by default, plus ML columns when enabled.

## Public functions in `core/analyses/clonality/interpretation.py`

| Symbol | Lines (start) | Purpose | Inputs | Outputs | Downstream consumer | ML/Phase-3 hook |
|--------|---------------|---------|--------|---------|---------------------|-----------|
| `interpretation_enabled` | 67 | gate (off by default) | settings dict | bool | entry-runner functions | — |
| `learning_mode_enabled` | ~95 | gate for offline training export | settings dict | bool | training scripts | optional |
| `learning_output_dir` | ~110 | resolves output dir for training | settings dict | Path | training scripts | optional |
| `sample_kind_for_file` | — | derives patient/pk/nk/rk from filename | fsa Path | str | `sample_annotation_files`, `peak_context_for_assay` | — |
| `sample_annotation_files` | — | yields (path, sample_kind) tuples | fsa dir | generator | training export | — |
| `features_from_entry` | — | **PRIMARY** feature builder, called per-entry | entry dict | entry dict w/ all features | `interpret_entry` | **extends** with new per-channel / reference-window / patient-panel (T-2.1/2.2/2.3) |
| `interpret_entry` | — | **PRIMARY** rule decision; returns ANNOTATION_CLASSES label + evidence | entry dict | dict w/ ClonalitySuggestion, ClonalityConfidence, ClonalityEvidence, ClonalityReviewNeeded | tracking_excel; GUI review widget | independent of ML |
| `attach_interpretation_if_enabled` | — | writes rule columns to entry dict | entry dict | entry dict (mutated) | called from pipeline | — |
| `annotation_export_rows_to_frame` | — | shapes json training rows | json + entry dict | pd.DataFrame | training scripts | consumed in Phase 3 |
| `write_annotation_csv_from_json` | — | writes training CSV | json dir | Path | training scripts | consumed in Phase 3 |
| `write_learning_annotation_seed` | — | dumps app-run entries under learning.output_dir | entry dict, settings | Path | operator review | — |
| `write_rows_csv` | — | generic CSV writer | rows | Path | training scripts | — |
| `utc_now_iso` | — | timestamp helper | — | ISO str | tracking, drift report | — |
| `sl_quality_from_metrics` | — | SL-specific quality classifier (DNA-quality, not clonality) | sl metrics dict | dict w/ p100/p200/percent | tracking_excel; entry Sl-writing | none |
| `assay_interpretation_ranges` | — | returns ASSAY_REFERENCE_RANGES for an assay | assay name | dict (bp_min/bp_max) | features_from_entry, interpret_entry | bounds for T-2.2 window features |
| `assay_interpretation_range` | — | per-assay helper | assay name | (bp_min, bp_max) | features_from_entry | — |
| `peak_context_for_assay` | — | extracts dominant-peak / in-window peak series | entry dict, assay | DataFrame | interpret_entry + ML | — |

## Real-FSA feature and validation modules

| Module | Purpose |
|--------|---------|
| `trace_features.py` | deterministic scalar and per-channel raw FSA trace geometry |
| `ml_feature_dataset.py` | resumable, content-hashed local feature artifact |
| `ml_training.py` | per-assay RandomForest/ExtraTrees/QDA datasets, estimators, metrics, serialization |
| `ml_validation.py` | DIT/source-run-grouped OOF predictions, promotion gates, review/drift outputs |
| `ml_model.py` | validated-v2 artifact discovery and inference contract |
| `ml_runtime.py` | default-off second-opinion attachment and quality/review routing |

## Public functions in `core/analyses/clonality/candidate_artifacts.py`

| Symbol | Purpose |
|--------|---------|
| `extract_candidate_artifacts` | yields candidate peak rows for downstream review |
| `summarize_candidate_artifacts` | prints / logs aggregate candidate stats |
| ... (any others listed in __all__) | see source |

## Public functions in `core/analyses/clonality/ladder_review_gate.py`

| Symbol | Purpose |
|--------|---------|
| `ladder_qc_gate` | returns True when ladder fit is shape-acceptable |

## Numeric features currently in the rule model

(see `train_clonality_interpretation_quick_model.py:NUMERIC_FEATURES`)

1. `ladder_r2`, `ladder_linear_r2`, `ladder_linear_mean_residual_bp`, `ladder_linear_max_residual_bp` — ladder fit quality
2. `raw_peak_count`, `peak_count`, `peak_count_in_interpretation_range`, `peak_count_outside_interpretation_range` — call density
3. `dominant_peak_basepairs`, `outside_interpretation_height_share` — position relative to assay window
4. `interpretation_range_min_bp`, `interpretation_range_max_bp` — assay-specific window bounds
5. `dominant_peak_height`, `second_peak_height`, `dominant_to_second_ratio`, `dominant_height_share`, `total_peak_height` — height stack
6. `dominant_peak_area`, `total_peak_area` — area stack

## Rule-path mapping (rule → annotation class)

Walked from `interpret_entry()` and `_interpret_<assay>()` functions. Each row below is one **final** annotation decision (after per-assay rules, ladder-qc gate, control-flag override, FK-routing, etc.):

| Final class | Rule summary | Notes |
|--------------|-------------|-------|
| `polyklonal` | zero peaks in window OR many small close-in-BP peaks | broad reference range, low signal-to-noise |
| `monoklonal` | one dominant peak at expected bp height ≥ 2× second-tallest | FR1/FR2/FR3, TCRG/TCRB, IGK |
| `bi_oligoklonal` | 2-3 dominant peaks in window, all near expected bp, height comparable | rare |
| `irregulaer` | peaks in window but no clean dominant pattern | noisy but not failing |
| `pseudoklonal` | single dominant at bp just outside expected window | suspected pipetting artifact |
| `intet_pcr_produkt_darlig_dna` | zero total peaks across all channels | sample-quality failure |
| `qc_teknisk_fail` | input-DNA control failed | OR carry-over from `_interpret_*` |
| `usikker_review` | forced rule fallback for ladder/QC/control uncertainty | always terminal in rule tracking; ML disagreement is stored separately as review evidence |

Per-assay detail:
- `FR1/FR2/FR3`: dominant_peak + Biglari variant. FR1 zero-peak → polyklonal.
- `TCRG-A/B`: germline pattern detection vs MRD-style mono detection.
- `DHJH_D/E`: zero-peak → polyklonal.
- `Ktr-albumin`: input-DNA control; routed through control-flag path.
- `IKZF1`: monitoring primer set; interpretation is monitoring (presence / size-of-band over time), not per-sample clonality. Pass-through.
- `IGK/KDE`: dual-tube dominance test.
- `SL`: only SL-specific helper, never enters above branches.

## Control flags

`CONTROL_FLAGS = ["kontroll_ok", "kontroll_avvik", "kontaminasjon_mistenkt", "svakt_signal"]`

Triggered by `control_id_from_filename()` (in `core/qc/qc_markers.py`) and propagated
through `entry["control_flag"]`. Any `kontroll_avvik` or `kontaminasjon_mistenkt` **MUST**
override the label to `usikker_review` regardless of model output.

## Tracking columns written by `tracking_excel.py`

`ClonalityInterpretationEnabled`, `ClonalitySuggestion`, `ClonalityConfidence`, `ClonalityReviewNeeded`,
`ClonalityEvidence`, `ClonalitySLQualityClass`, `ClonalitySLFragmentedPercent`,
`ClonalitySLQualityPhrase`, `ClonalityModelVersion`.

Validated ML adds `ClonalityMLSuggestion`, `ClonalityMLConfidence`,
`ClonalityMLThreshold`, `ClonalityMLReviewNeeded`, `ClonalityMLEvidence`, and
`ClonalityMLModelVersion` without replacing rule fields.

## Existing schema versions

- `ANNOTATION_SCHEMA_VERSION = "clonality_interpretation_v1"`
- `INTERPRETATION_RULE_VERSION = "clonality_interpretation_rules_v1"`
- `MODEL_VERSION = "clonality_interpretation_quick_model_v1"`
- `TRACE_FEATURE_SCHEMA_VERSION = "clonality_trace_features_v1"`
- validated runtime model schema: `ml_training_pipeline_v3`

Keep all three under versioned definitions; bumping either triggers:
- Tracking-column metadata update
- Obsidian changelog entry
- DoC re-validation

## ML integration hotspots

| File | Function | Why here | Phase |
|------|----------|----------|-------|
| `core/analyses/clonality/interpretation.py` | `features_from_entry` | shared scalar plus optional raw-trace feature contract | 2 |
| `core/analyses/clonality/ml_validation.py` | `grouped_oof_validate`, `source_run_grouped_validate` | patient/run-safe validation and disagreement evidence | 6 |
| `core/analyses/clonality/ml_model.py` | `_runtime_eligible_metadata` | candidate/validated deployment boundary | 5 |
| `core/analyses/clonality/ml_runtime.py` | `attach_ml_prediction_if_enabled` | second-opinion and review routing | 5 |
| `core/analyses/clonality/tracking_excel.py` | `update_clonality_tracking_workbook` | rule and ML tracking columns | 5 |

## Canonical ANNOTATION_CLASSES values

`["polyklonal", "monoklonal", "bi_oligoklonal", "irregulaer", "pseudoklonal",
  "intet_pcr_produkt_darlig_dna", "qc_teknisk_fail", "usikker_review"]`

Eight classes total. Define new annotation classes ONLY after chemist sign-off,
and bump `ANNOTATION_SCHEMA_VERSION`.

## OPEN: what this map does NOT (yet) cover

- `tracking_excel.py::aggregate_clonality_tracking_*` functions emitted when multiple batches merged — call-graph to be added in Phase 6.
- The TITAN/ImmuneML research-only candidate would not plug into `interpret_entry`; it remains deferred until real-data baselines justify the added complexity.
- Per-sample feature shared by multiple files (patient panel view) is `T-2.3` material — see `ObsidianVault/Clonality_ML_Log/decisions/dependencies.md` for Phase 2 wiring.
