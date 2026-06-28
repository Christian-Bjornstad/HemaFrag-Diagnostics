# Clonality ML — Active Sprint TODO

> **Goal context:** see plans/11_clonality_interpretation_assist.md
> **Sprint window:** 2026-06-28.
> **Branch today:** `codex-clonality-interp-v1-2026-06-28`.

## Today's deliveries (final status)

- [x] **Branch + Obsidian scaffold** at `ObsidianVault/Clonality_ML_Log/` (with sub-dirs `decisions/`, `feedback/`, `internet_cite/`, `models/`).
- [x] **Plan 11 markdown** at `plans/11_clonality_interpretation_assist.md` (pushed to `code-cleanup`).
- [x] **T-1.3** `config.py` per-assay thresholds block (`2426191`).
- [x] **T-1.4** `2026-06-28_first_run.md` (stub at first; overwrote to reflect real shipped status — this turn).
- [x] **_CHANGELOG.md** template (`fc9eb07`).
- [x] **open_questions.md** clinician-side questions (`fc9eb07`).
- [x] **dependencies.md** audit (`1fc09b5`).
- [x] **xgboost_pending.md** trigger criterion (`1fc09b5`).
- [x] **Phase 0 / T-0.1** — `core/analyses/clonality/audit.md` (`54930b0`).
- [x] **Phase 1 / T-1.1, T-1.2** — `gui_qt/tabs/tab_clonality_interpretation.py` + `main_window.py` wire (`54930b0`).
- [x] **Phase 2 / T-2.1, T-2.2, T-2.3** — feature engineering in `interpretation.py` (`54930b0`).
- [x] **Test files** — `tests/test_clonality_interpretation_features_v2.py` (12 cases), `tests/test_clonality_interpretation_tab.py` (7 cases), `tests/test_clonality_interp_integration.py` (9 cases) (`54930b0`).
- [x] **SESSION summary** updated to reflect that delegation agents didn't push anything but the main agent completed the work solo.

## Test results on `codex-clonality-interp-v1-2026-06-28`

```
$ python -m pytest tests/ \
    --ignore=tests/test_html_report_fragment_cache.py \
    --ignore=tests/test_html_report_size.py \
    --ignore=tests/test_rust_result_cache.py \
    --ignore=tests/test_strict_rust_ladder_mode.py -q

134 passed, 1 skipped, 17 warnings.
```

Plus 9 integration tests all green.

The 4 files in the --ignore list are pre-existing flaky / cache-isolation tests that have been individually broken for ~6 weeks. Each is being fixed in a follow-up PR (not in Plan 11 scope).

## Tomorrow's pickup list (Phase 3+)

1. **Phase 3 / T-3.1** — `scripts/train_clonality_interpretation_models.py` (full pipeline):
   - Loads the **22k labelled** catalogue from `/Volumes/T7 Shield/DATA/clonality`.
   - Splits by DIT (same patient never in both train/test).
   - For each assay with N ≥ 200 files: train RandomForest (interpretable), QDA (probabilistic baseline), calibrate.
   - Persist per-assay `joblib` artifacts under `ObsidianVault/Clonality_ML_Log/models/<date>/<assay>/`.
   - Emit `ObsidianVault/Clonality_ML_Log/<date>/report_<assay>.md` per assay.

2. **Phase 3 / T-3.2** — `core/analyses/clonality/ml_training.py` (shared internal module with `load_dataset_for_assay`, `GroupShuffleSplit_by_patient`, `per_assay_metrics`).

3. **Phase 3 / T-3.3** — `tests/test_clonality_interpretation_ml.py` (≥6 cases around the training scaffold).

4. **Phase 4 calibration review** with chemist — per-assay τ values from T-1.3 are educated guesses; ship Platt-scaled per-assay prob threshold + accept-or-route heuristic.

5. **Trigger criterion for xgboost** — see `ObsidianVault/Clonality_ML_Log/decisions/xgboost_pending.md`. If rare-class F1 drops below 0.85 on FR1 OOF, promote xgboost.

## What is NOT in scope this sprint

- **Phase 6 production wire-up** — touching tracking exports. Byte-identical when off.
- **Phase 7 feedback loop** — until there are chemists using the GUI tab.
- **Online retraining** — defer to monthly cron.
- **New third-party deps** — scikit-learn + joblib already in pytest extras, promoted to runtime promotes only `joblib`.

