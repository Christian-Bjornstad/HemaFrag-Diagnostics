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

## Incomplete: research deliverables

- [~] DELIVERABLE 1: pubmed_anchor_survey.md - STUB ONLY (commit 6415817)
      18-line status note + TODO list. The async researcher-agent (deleg_77136ad2)
      returned "time to write" at the end of its 32-minute run but never wrote the
      file. The main-session exhausted tool canvas for 2.5kB markdown.
      URLs to re-anchor tomorrow are:
        - euroclonality.org
        - pubmed.ncbi.nlm.nih.gov/14671650  (van Dongen 2003)
        - pmc.ncbi.nlm.nih.gov/articles/PMC3469789  (Langerak 2012)
        - pmc.ncbi.nlm.nih.gov/articles/PMC6746026  (TRG multiplex)
        - invivoscribe.com/uploads/collateral/D-0329.pdf
        - nature.com/articles/leu2012246

- [ ] DELIVERABLE 2: model_registry_2026-06-28.md - NOT STARTED
      Re-do tomorrow alongside deliverable 1.

## Tomorrow's pickup list (Phase 3+)

1. Re-author the two Obsidian research deliverables (above).
2. Phase 3 / T-3.1 - scripts/train_clonality_interpretation_models.py  (full pipeline):
   - 22k-labelled catalogue from /Volumes/T7 Shield/DATA/clonality.
   - DIT-by-DIT stratified split.
   - RandomForest + QDA per assay with N >= 200.
   - Save per-assay joblib artifacts under ObsidianVault/Clonality_ML_Log/models/<date>/<assay>/.

3. Phase 3 / T-3.2 - core/analyses/clonality/ml_training.py (shared internal).
4. Phase 3 / T-3.3 - tests/test_clonality_interpretation_ml.py (>=6 cases).
5. Phase 4 calibration review with chemist.
6. Trigger criterion for xgboost if rare-class F1 < 0.85 on FR1 OOF.
