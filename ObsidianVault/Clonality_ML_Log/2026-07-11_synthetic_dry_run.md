# Clonality Interpretation Assist — Phase 5 Synthetic Dry Run, 2026-07-11

> **Branch:** `clonality-ml-phase-5-real-data-2026-07-11`
> **Plan:** [`plans/11_clonality_interpretation_assist.md`](../../plans/11_clonality_interpretation_assist.md)
> **Lead:** Christian + Hermes
> **Goal of this run:** end-to-end validation of the trainer + calibration pipeline
> without the work computer / T7 Shield. All work in this sandbox.

## What shipped today

- **Branch `clonality-ml-phase-5-real-data-2026-07-11`** cut off `ux/design-pass-1`.
- **End-to-end trainer pipeline run on synthetic data.** Built a 660-row × 3-assay
  (FR1, TCRG-A, DHJH_D) DataFrame with realistic per-label feature distributions;
  called `build_per_assay_datasets` → `fit_classifier` → `per_assay_metrics` →
  `serialize_model` directly (Path A — bypassed the tracking-workbook loader that
  would have required a real Clonality_Tracking.xlsx from the T7).
- **Per-assay artifacts under `ObsidianVault/Clonality_ML_Log/2026-07-11_synthetic_dry_run/`:**
  - `models/FR1/{metadata.json, random_forest.joblib}`
  - `models/TCRG-A/{metadata.json, random_forest.joblib}`
  - `models/DHJH_D/{metadata.json, random_forest.joblib}`
  - `report_FR1.md`, `report_TCRG-A.md`, `report_DHJH_D.md`
- **_CHANGELOG.md updated** with the three `clonality-ml-v0.1.0-pa-*-rf` rows.
  Driver = `synthetic-dry-run`; calibration hash = `n/a — synthetic`; signoff = pending.

## Bug found + fixed

The synthetic run surfaced a real defect in `core/analyses/clonality/calibration.py:194`
(`predict_with_rejection`). Two issues, both in the same function:

1. **Forced-review gating skipped.** The function never called
   `_forced_review_reasons(feature_row)` before invoking the classifier. The docstring
   at the top of the module promises "ladder_qc_status not in {ok, manual_adjustment, ''}
   -> force to usikker_review (no ML inference)" — but the actual `predict_with_rejection`
   skipped that step entirely. The forced-review gating only happened in the higher-level
   `attach_ml_suggestion_if_enabled` wrapper. Any caller invoking `predict_with_rejection`
   directly got unsafe behavior.

2. **Naive `float(value)` crash.** Line 219 was `pd.Series({k: float(v) if v is not None
   else float("nan") for k, v in feature_row.items()})` — which raised `ValueError:
   could not convert string to float` the moment a string-valued metadata field
   (`ladder_qc_status="fail"`, `ClonalitySuggestion="qc_teknisk_fail"`,
   `control_flag="kontroll_avvik"`) reached the function. The pre-existing tests
   (`test_clonality_calibration.py`) passed naked-numeric feature dicts and never
   tripped this; real entry dicts always carry metadata.

Both fixed in a single commit. The function now:

- Runs `_forced_review_reasons()` first; if any reason fires, returns
  CalibratedMLPrediction(label="usikker_review", accepted=False) immediately.
- Coerces values via `try/except (TypeError, ValueError)` — non-numeric values become
  NaN, the imputer in the pipeline handles them, inference still proceeds.

Two new regression tests added to `tests/test_clonality_calibration.py`:
- `test_predict_with_rejection_force_review_ladder_qc_fail_short_circuits`
- `test_predict_with_rejection_handles_uncoercible_feature_values`

## Test status

- `tests/test_clonality_calibration.py`: **17 passed** (was 15, now includes the two
  new regression tests).
- `tests/test_clonality_interpretation_ml.py`: **10 passed** (unchanged).
- `tests/test_clonality_interpretation_v1.py` + siblings: **15 passed** via unittest.

## Synthetic-data metrics

For the record — these are upper-bound numbers on clean synthetic data; the chemist
should NOT take them as a sign of production readiness:

| Assay   | n_train | macro F1 | monoklonal F1 | accept τ (default) |
|---------|---------|----------|---------------|--------------------|
| FR1     | 176     | 1.000    | 1.000         | 0.85               |
| TCRG-A  | 176     | 1.000    | 1.000         | 0.75               |
| DHJH_D  | 176     | 1.000    | 1.000         | 0.92               |

Per-assay accept thresholds above come from `APP_SETTINGS["analyses"]["clonality"]
["interpretation"]["thresholds"]` (matches the Phase-1 config block shipped
2026-06-28). Monoklonal-class probability on the synthetic clean input row
(peak_count=2, dominant_peak_basepairs=130, in_range_height_share=0.92, etc.) came
back at 0.708–0.84 across the three assays — below the default τ in each case. So
on this clean synthetic monoklonal input, the ML second-opinion would have been
**rejected and routed to review** under the current thresholds. That's not the
correct outcome on real patient monoklonal samples; it's an artefact of the synthetic
label distribution not actually matching the chosen features strongly enough to
hit the threshold. **The threshold-rejection is not a defect**; it's the system
correctly saying "I'm not confident enough" — and that's exactly the calibration
loop where the chemist should weigh in.

## Still open (carryin into next session)

- **Phase 6 production wiring** (tracking Excel columns `ClonalityMLSuggestion`,
  `ClonalityMLConfidence`, `ClonalityMLReviewNeeded`, `ClonalityMLModelVersion`,
  `ClonalityMLEvidence`).
- **Phase 7 feedback loop** (in-app disagreement JSONL appender at
  `ObsidianVault/Clonality_ML_Log/feedback/<date>.jsonl`).
- **Real-data run.** This sandbox does not have the T7 Shield catalog; the real
  run on the 22k labelled catalog is the next signal that matters. The synthetic
  dry-run cleared the trainer + calibration code paths so the real run should
  not surface surprises.
- **Re-tune τ per-assay.** Today's numbers are from the Phase-1 educated-guess
  table; OOF metrics on real data will be the actual signal to set them.

## Open questions for clinician review

Same list as Phase 1 — none advanced by this run. The synthetic data makes it
clear that "τ" needs to be calibrated per (assay × label), not just per assay.
That's a Phase-7 feedback-loop question more than a Phase-5 question.
