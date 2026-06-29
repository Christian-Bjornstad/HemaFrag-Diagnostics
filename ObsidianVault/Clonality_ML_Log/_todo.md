# Clonality ML — Active Sprint TODO

> Goal context: see plans/11_clonality_interpretation_assist.md
> Sprint window: 2026-06-28.
> Branch today: `codex-clonality-interp-v1-2026-06-28`.

## Today's deliveries (final status, end of session)

- [x] Branch + Obsidian scaffold at ObsidianVault/Clonality_ML_Log/
- [x] Plan 11 markdown at plans/11_clonality_interpretation_assist.md (pushed to code-cleanup)
- [x] T-1.3 config.py thresholds block (2426191)
- [x] T-1.4 first-run md stub + overwrites
- [x] _CHANGELOG.md template (fc9eb07)
- [x] open_questions.md clinician questions (fc9eb07)
- [x] dependencies.md audit (1fc09b5)
- [x] xgboost_pending.md trigger criterion (1fc09b5)
- [x] Phase 0 / T-0.1 - core/analyses/clonality/audit.md (54930b0)
- [x] Phase 1 / T-1.1, T-1.2 - tab_clonality_interpretation.py + main_window wire (54930b0)
- [x] Phase 2 / T-2.1, T-2.2, T-2.3 - feature engineering in interpretation.py (54930b0)
- [x] Test files (28 cases) - test_clonality_interpretation_features_v2.py +
      test_clonality_interpretation_tab.py + test_clonality_interp_

## Test results

```
134 passed, 1 skipped, 0 regressions on the cloned branch.
```

Plus 28 new tests across the three Plan-11 test files. The 4 pre-existing flaky tests
(test_rust_result_cache, test_strict_rust_ladder_mode, test_html_report_fragment_cache,
test_html_report_size) are excluded because they were broken before this sprint.

## Research deliverables shipped

- [x] DELIVERABLE 1 (06deb2c): `internet_cite/2026-06-28_pubmed_anchor_survey.md` (164 lines).
      BIOMED-2 / EuroClonality primary citations + 16-row per-assay bp-window table
      + WHO-HAEM5 informational anchor notes.
- [x] DELIVERABLE 2 (06deb2c): `decisions/model_registry_2026-06-28.md` (143 lines).
      RandomForest + Platt scaling = primary Phase-3 model; Calibrated QDA = head-to-head;
      xgboost deferred per trigger criterion; TabPFN/TabNet surveyed NOT adopted;
      ImmuneML/NetTCR-2.0/TITAN listed out of scope.

## Phases shipped (2026-06-29)

- [x] Phase 1 (54930b0): tab widget, main_window wire, audit.md
- [x] Phase 2 (54930b0): per-channel + reference-window + patient panel features
- [x] Phase 3 (85a9d22): ml_training.py + scripts/train_clonality_interpretation_models.py + 12 tests
- [x] Phase 4 (5c7d1db): calibration.py + predict_with_rejection + 15 tests +
      attach_ml_suggestion_if_enabled orchestrator bridge
- [x] Python 3.12 wheel rebuild (c56c723): cp312-abi3
- [x] Research markdowns (06deb2c): pubmed_anchor_survey.md + model_registry_2026-06-28.md

Current pytest (sans 4 pre-existing flaky): 161 passed, 1 skipped, 22 warnings.


## Tomorrow's pickup (Phase 5+)

1. **Chemist calibration review** — per-assay τ values from T-1.3 are educated-guess. Now that Phase 4 calibration.py ships, run the per-assay OOF pass and let chemist sign off on adjusted τ values.
2. **xgboost trigger criterion** — if FR1 rare-class F1 < 0.85 on OOF, promote xgboost per `decisions/xgboost_pending.md`.
3. **Phase 7 feedback loop** — when GUI disagreement ledger is enabled, append JSONL lines under `ObsidianVault/Clonality_ML_Log/feedback/<date>.jsonl`.
4. **Real-data first model run** — re-run today's CLI on `/Volumes/T7 Shield/DATA/clonality/Clonality_Tracking.xlsx` (22k labelled catalogue) to ship the FIRST per-assay model in production. Required: chemist-approved labels-csv from a recent batch run.
