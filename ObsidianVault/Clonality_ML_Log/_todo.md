# Clonality ML — Active Sprint TODO

> **Goal context:** see plans/11_clonality_interpretation_assist.md
> **Sprint window:** 2026-06-28 (this session).
> **Branch today:** `codex-clonality-interp-v1-2026-06-28`.

## Today's deliverables (status as-of end of session)

- [x] **Branch created** `codex-clonality-interp-v1-2026-06-28` off `code-cleanup@c53b171`.
- [x] **Plan 11 markdown** at `plans/11_clonality_interpretation_assist.md` (pushed to `code-cleanup` as `19c23ea`).
- [x] **T-1.3** `config.py` per-assay thresholds block (push `2426191`).
- [x] **T-1.4 stub** first-run md at `ObsidianVault/Clonality_ML_Log/2026-06-28_first_run.md` (push `2426191`).
- [x] **_CHANGELOG.md** template at `ObsidianVault/Clonality_ML_Log/_CHANGELOG.md` (push `fc9eb07`).
- [x] **open_questions.md** at `ObsidianVault/Clonality_ML_Log/open_questions.md` (push `fc9eb07`).
- [⏳] **T-0.1** asset-map audit under `core/analyses/clonality/audit.md` — being delegated (depth-agent phase 0+2 work).
- [⏳] **T-1.1** `gui_qt/tabs/tab_clonality_interpretation.py` new tab widget — being delegated (depth-agent phase 1 work).
- [⏳] **T-1.2** wire the tab into `gui_qt/main_window.py` — same depth-agent.
- [⏳] **T-2.1 / T-2.2 / T-2.3** feature engineering in `feature_artifacts.py` (+ 8 pytest cases) — same depth-agent Phase 0+2.
- [⏳] **Research output** at `ObsidianVault/Clonality_ML_Log/internet_cite/2026-06-28_pubmed_anchor_survey.md` — separate research-agent in flight.
- [⏳] **Research output** at `ObsidianVault/Clonality_ML_Log/decisions/model_registry_2026-06-28.md` — same research-agent.
- [⏳] **Integration smoke test** `tests/test_clonality_interp_integration.py` — separate depth-agent in flight.

## Tomorrow's pickup list (when you start a new session)

1. **Check what landed on disk from today's delegations.** Run:
   ```bash
   cd C:\Users\molpa\Desktop\Hermes\HemaFrag-Diagnostics-code-cleanup
   git fetch
   git checkout codex-clonality-interp-v1-2026-06-28
   git log --oneline | head
   ls gui_qt/tabs/tab_clonality_interpretation.py core/analyses/clonality/audit.md tests/test_clonality_interpretation_features_v2.py tests/test_clonality_interpretation_tab.py tests/test_clonality_interp_integration.py ObsidianVault/Clonality_ML_Log/internet_cite/2026-06-28_pubmed_anchor_survey.md ObsidianVault/Clonality_ML_Log/decisions/model_registry_2026-06-28.md
   ```
   Missing files → still pending. Existing ones → sanity-check the contents and give yourself a new branch as needed.

2. **Run the test suite** headless under PyQt6 QT_QPA_PLATFORM=offscreen:
   ```powershell
   $env:QT_QPA_PLATFORM='offscreen'
   python -m pytest tests/test_clonality_interp_integration.py -v
   ```
   Expected: all green or one or two with a known-cause note in the file.

3. **Phase 3 (per-assay training)** — bigger lift, takes 4-6 hours of work, scope:
   - `scripts/train_clonality_interpretation_models.py` (full pipeline script)
   - `core/analyses/clonality/ml_training.py` (shared internal module)
   - `tests/test_clonality_interpretation_ml.py` (6+ unit tests)
   - First shipped model per FR1 (≥200 labelled TCRG samples expected to ship after that)
   - Live data feed: `/Volumes/T7 Shield/DATA/clonality`

4. **Calibration review** with chemist: per-assay τ values from T-1.3 are educated guesses; Phase 4 ships Platt-scaled per-assay prob threshold + accept-or-route heuristic. Run after Phase 3 ships a real model.

## What is NOT in scope this sprint (deliberately deferred)

- **Production wire-up** (Phase 6: writing ML columns into tracking exports) — that touches byte-identical output contracts; defer until chemist signs off on Phase 3 model.
- **Feedback loop** (Phase 7: GUI disagreement ledger) — defer because we need real users first.
- **Online retraining** — defer, monthly cron is fine.
- **Any new third-party dependency** — scikit-learn + joblib already in pytest extras. NO xgboost, NO torch, NO transformers — keep foot-print zero.

## Open questions for the chemist (Block until answered)

See `ObsidianVault/Clonality_ML_Log/open_questions.md` — calibration of τ per assay is the chunkiest open question; the rest are operational.

