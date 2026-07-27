# Clonality ML — In-App Training, Prediction, and HTML Integration

> **For Hermes:** Implement task-by-task with TDD. Plan lives at `.hermes/plans/2026-07-13_clonality-ml-app-integration.md`.

**Goal:** Make the clonality ML a first-class citizen of the app. (1) Train it on real labeled data from the in-app workflow. (2) Load it via Settings → use it during batch + DIT runs to write per-row predictions into the tracking workbook and the HTML report. (3) Add per-sample dismissal in the HTML so the pathologist only sees calls the chemist trusts.

**Architecture:** A new `core/analyses/clonality/ml_model.py` wraps `ml_training.py` (already battle-tested on synthetic data) behind a `ClonalityModelStore` that loads a directory of `<assay>/<classifier>.joblib + metadata.json` files. The pipeline runtime calls `store.predict(assay, features)` after rule interpretation, attaching `ClonalityMLSuggestion`, `ClonalityMLConfidence`, `ClonalityMLReviewNeeded` to each entry. The rendering layer (`build_dit_html_reports`) injects a dismissible badge under each sample header; the "Save Peaks" download already serializes the DOM via `PeakManager.downloadUpdatedHtml`, so we extend its replacement pass to also capture `clonality-decisions` state. A new `TabMlTraining` (a sibling of `TabClonalityInterpretation`) launches training jobs from inside the app — point it at the tracking xlsx, pick assays, press Train, save the model folder back to Settings.

**Tech Stack:** Python 3.11+, PyQt6, scikit-learn (`RandomForestClassifier` + `CalibratedClassifierCV` already proven in Phase 5), joblib, html/css/js inside the existing Plotly bundle — no new deps.

---

## Current context (confirmed by reading the branch)

- Branch `clonality-ml-phase-5-real-data-2026-07-11` is checked out and clean. Phase 5 dry-run is merged. 406 tests pass + 1 skipped per memory.
- `core/analyses/clonality/ml_training.py` already exposes `fit_classifier`, `serialize_model`, `deserialize_model`, `PerAssayDataset`, `build_per_assay_datasets`, plus `ANNOTATION_CLASSES_ORDER`. **Reuse, don't rewrite.**
- `core/analyses/clonality/interpretation.py` exports `attach_interpretation_if_enabled(entry)` and `features_from_entry(entry)`. The runtime already computes `features` and `ClonalitySuggestion` for every entry.
- `core/analyses/clonality/tracking_excel.py` writes the tracking workbook (already emits `ClonalitySuggestion`, just not `MLSuggestion`).
- `core/html_reports/_legacy.py::build_dit_html_reports` is the single HTML assembly point. `_render_assay_block` is where per-sample rendering happens; `_render_file_summary_table` is the file-level summary. Both are the right surgical spots for the ML badge.
- `gui_qt/tabs/tab_settings.py` already has `chk_clonality_interpretation`, `clonality_model_path` (Browse → joblib). Currently it points to *_a single joblib_* but Phase 3 ships a _folder_ per assay — we extend the setting to accept a directory and migrate gracefully.
- `gui_qt/main_window.py` registers tabs; `tab_clonality_interpretation.py` already has the rule-vs-ML comparison tab — we add a sibling `tab_ml_training.py`.

---

## Plan — bite-sized tasks

### Task 1: `ClonalityModelStore` — load + predict + cache

**Files:**
- Create: `core/analyses/clonality/ml_model.py`
- Test: `tests/test_clonality_ml_model.py`

Write failing tests:
- `test_store_returns_empty_when_dir_missing`
- `test_store_loads_joblib_for_known_assay`
- `test_store_caches_after_first_load`
- `test_predict_handles_missing_assay_gracefully`
- `test_predict_returns_label_confidence_after_threshold`

Implement `ClonalityModelStore`:
- `__init__(*, model_dir: Path|None)` — directory of `<assay>/<classifier>.joblib + metadata.json`. Lazy per-assay load. Accept `None` for "off".
- `predict(assay, features: dict) -> dict | None` — None if assay has no model; else `{"label": str, "confidence": float, "review_needed": bool, "model_version": str}`. Threshold `metadata["accept_threshold_tau"]` governs `review_needed`.
- `is_enabled(assay) -> bool` — cheap path for HTML rendering decisions.

Reuses `ml_training.deserialize_model`. No sklearn import here unless needed.

Run: `pytest tests/test_clonality_ml_model.py -v` — expect green.

Commit: `feat(ml): ClonalityModelStore wraps per-assay joblib + predict API`.

### Task 2: Feature vector adapter for the store

**Files:**
- Modify: `core/analyses/clonality/ml_model.py`
- Test: `tests/test_clonality_ml_model.py` — extend

The features dict produced by `features_from_entry` is wide and partly nested (`peak_count_per_channel` is `{DATA1: 5, DATA2: 7}`). The Phase 3 trainer feed (`scripts/train_clonality_interpretation_models.py`) uses a known column contract.

- `_flatten_for_inference(features: dict) -> pd.DataFrame` — flatten the nested per-channel dicts to columns named `trace_count_DATA1`, etc., preserving the exact column order expected by the loaded estimator when it provides a `feature_columns` field (extend `serialize_model` metadata to also persist `feature_columns: list[str]`). Falls back gracefully if a column is missing (impute 0).
- Mirror the existing `_ensure_numeric_X` semantics (NaN/inf → 0).

Test:
- `test_flatten_matches_trainer_columns` — derive a features dict, compare the resulting DataFrame's columns/order to the saved metadata.

Commit: `feat(ml): persisted feature_columns + flatten adapter for inference`.

### Task 3: Extend `serialize_model`/`deserialize_model` to record feature columns

**Files:**
- Modify: `core/analyses/clonality/ml_training.py:316-376` (region around `serialize_model`)
- Modify: `core/analyses/clonality/ml_training.py:370-432` (region around `deserialize_model`)
- Test: `tests/test_clonality_interpretation_ml.py` — extend

Add `feature_columns: list[str]` to metadata round-trip. Re-train on synthetic fixture, assert metadata contains the columns, assert the columns match the X columns used at fit time.

Commit: `feat(ml): serialize feature_columns alongside joblib metadata`.

### Task 4: `attach_ml_prediction_if_enabled(entry)` runtime hook

**Files:**
- Create: `core/analyses/clonality/ml_runtime.py`
- Test: `tests/test_clonality_ml_runtime.py`

Following the rule-pattern of `attach_interpretation_if_enabled`:
- Singleton `model_store` lazy-built off `APP_SETTINGS` once.
- `attach_ml_prediction_if_enabled(entry) -> entry` runs `features_from_entry`, calls `model_store.predict`, attaches:
  - `ClonalityMLSuggestion`
  - `ClonalityMLConfidence`
  - `ClonalityMLReviewNeeded` (true if either side low-conf or disagree)
  - `ClonalityMLModelVersion` (= `metadata["schema_version"]`)
- On any exception → log + leave entry untouched (defensive; Pathologist-facing output must never crash because of ML).
- `MLCOLUMNS = [...]` exported for the tracking Excel.

Tests:
- `test_runtime_is_noop_when_settings_off`
- `test_runtime_attaches_ml_columns_when_on`
- `test_runtime_does_not_crash_on_bad_features`

Commit: `feat(ml): runtime attach_ml_prediction_if_enabled + ML tracking columns`.

### Task 5: Extend `TRACKING_COLUMNS` and write ML columns to the workbook

**Files:**
- Modify: `core/analyses/clonality/tracking_excel.py`

After the workbook update completes a run, the columns `ClonalityMLSuggestion / Confidence / ReviewNeeded / ModelVersion` are written for every patient row. (The ML hook attaches these to entries before they're handed to the writer.) Add the four columns to the schema and emit empty string when the ML hook was disabled.

Test:
- `tests/test_clonality_tracking_output.py::test_tracking_includes_ml_columns_filled` — entry with ML fields → assertion; entry without ML fields → empty-string cells.

Commit: `feat(tracking): emit Clonality ML columns in workbook`.

### Task 6: HTML report renders per-sample ML badge with dismiss action

**Files:**
- Modify: `core/html_reports/_legacy.py::_render_assay_block`
- Modify: `core/html_reports/_legacy.py::_render_file_summary_table`
- Add inline CSS block to `REPORT_STYLE` (in `core/html_reports/_constants.py`) — `.clonality-ml-badge`, `.clonality-ml-badge.dismissed`, `.medisinsk-grunnlag`.

Inside `_render_assay_block`, after `_build_report_plot_fragment` for each `e`, if `e.get("ClonalityMLSuggestion")` is present:
```
<div class="clonality-ml-badge" id="clonality-{hash(e['fsa'].file_name + e['assay'])}" data-state="active" data-dit="<dit>" data-assay="<assay>" data-file="<file>" data-ml-label="<label>">
    <span class="ml-badge-label">ML: <strong>polyklonal</strong> (0.82)</span>
    <button class="ml-dismiss" onclick="dismissClonalityBadge(this)">Skjul for patolog</button>
    <button class="ml-restore" onclick="restoreClonalityBadge(this)" hidden>Gjenopprett</button>
</div>
```
Insert a `<script id="clonality-decisions" type="application/json">{}</script>` in `_create_html_header` next to `peak-data` and `plot-state`.

Extend `_render_file_summary_table` to add a column `ML-forslag` (only when any entry has a ML suggestion); empty string otherwise.

Tests in `tests/test_html_report_fragment_cache.py`:
- `test_render_includes_ml_badge_when_present`
- `test_render_omits_ml_block_when_disabled`
- `test_render_does_not_break_when_ml_fields_missing`

Commit: `feat(html): per-sample ML badge block + summary column + dismissable JS hooks`.

### Task 7: JS dismiss/restore + serialisation through PeakManager

**Files:**
- Modify: inline `<script>` block inside `_create_html_header` in `core/html_reports/_legacy.py` (the `PeakManager` block continues from line 580)

Inside the same `<script>`:
```js
window.ClonalityDecisionLog = {
    dismissClonalityBadge: function(btn) { ... },
    restoreClonalityBadge: function(btn) { ... },
    serializeDecisions: function() {
        var decisions = {};
        document.querySelectorAll('.clonality-ml-badge').forEach(function(el) {
            decisions[el.id] = {
                dit: el.dataset.dit, assay: el.dataset.assay,
                file: el.dataset.file, ml_label: el.dataset.mlLabel,
                dismissed: el.dataset.state === 'dismissed'
            };
        });
        return decisions;
    }
};
```
(Use the exact `window.X = { ... }` style already in the file.)

Extend `downloadUpdatedHtml` so it also captures `clonality-decisions`:
```js
var decisionsStr = JSON.stringify((window.ClonalityDecisionLog && window.ClonalityDecisionLog.serializeDecisions) ? window.ClonalityDecisionLog.serializeDecisions() : {});
var decisionsPattern = /<script id="clonality-decisions" type="application\/json">[\s\S]*?<\/script>/;
var newDecisionsTag = '<script id="clonality-decisions" type="application\/json">\n' + decisionsStr + '\n<\/script>';
```
Attach to the existing `blob` download.

Plus: a `restoreClonalityBadgeFromState(id, state)` call on document load that re-applies dismissed state.

Tests: `tests/test_pass3_edge_cases.py` or new `tests/test_html_report_clonality_badge.py` — render fixtures with `ClonalityMLSuggestion` set, assert the script tag is rewritten on download. Use a minimal monkeypatched serialiser unit test (don't try to spin up a real browser).

Commit: `feat(html): ClonalityDecisionLog — dismiss/restore/persist through Save Peaks`.

### Task 8: Settings page — point at the model directory

**Files:**
- Modify: `gui_qt/tabs/tab_settings.py`

Change semantics: `clonality_model_path` becomes the path to the *root directory* of `<assay>/<*.joblib>` artifacts. Placeholder text updates. Label: "ML Model Directory (off → leave blank)". Add a small status pill next to the field that calls a helper `enumerate_model_dir(path)` → shows `FR1: ok · TCRG-A: not loaded · ...`. Persistence path is already `interpretation.interpretation.model_path` — keep it the same key for backward compatibility; document the semantic change in CHANGELOG.

Test: `tests/test_tab_settings_save.py` *(new)* — set the path, call `save`, assert `interpretation_settings["model_path"]` round-trips.

Commit: `feat(settings): ML model directory + per-assay status pill`.

### Task 9: `TabMlTraining` — GUI for training from inside the app

**Files:**
- Create: `gui_qt/tabs/tab_ml_training.py`
- Modify: `gui_qt/main_window.py` — register the tab
- Reuse: `scripts/train_clonality_interpretation_models.py` as the engine

UI:
- Source: Browse → `Clonality_Tracking_*.xlsx`. Default = the same path Settings has.
- Per-assay checkboxes (multi-select): FR1, FR2, FR3, IGK, KDE, TCRbA/B/C, TCRgA/B, DHJH_D/E. Defaults: all.
- Classifier kind: combo (Random Forest | QDA calibrated). Default RF.
- Min samples per assay: spin box (default 30, since not all our assays will hit 200).
- Accept threshold `τ`: spin box (default 0.80).
- Output dir: Browse → defaults to `<default_output>/ml_models/<YYYY-MM-DD_HHMMSS>`.
- **Train** button → runs `train_clonality_interpretation_models` synchronously inside a `QThread` worker (matches the existing pattern in `gui_qt/worker.py`).
- On finish: status pill says "Wrote 4 assay models to <dir>". Status pill clicks link `Open Folder` (uses `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`).
- **Open Interpretation tab** link button.

Tests:
- `tests/test_tab_ml_training.py` — load via `load_from_settings`, prep an in-memory workbook fixture, trigger `_train_clicked`, assert `model_dir/<assay>/random_forest.joblib` exists.

Commit: `feat(gui): TabMlTraining — train per-assay models from tracking workbook`.

### Task 10: Wire `attach_ml_prediction` into the runtime pipeline

**Files:**
- Modify: `core/analyses/clonality/pipeline.py` — calls `attach_interpretation_if_enabled` — add a sibling call `attach_ml_prediction_if_enabled` right after, in the same loop.
- Test: `tests/test_push_through_clonality_pipeline.py` *(new — modelled after existing `test_clonality_file_timeout.py`)* — feed a fixture with a model dir configured, assert ML fields appear.

Defensive: this is wrapped in try/except in the runtime hook (Task 4), so we don't need extra guardrails here.

Commit: `feat(pipeline): attach_ml_prediction_if_enabled during DIT/batch runs`.

### Task 11: End-to-end smoke test — full batch → HTML → dismiss → Save Peaks round-trip

**Files:**
- Test: `tests/test_clonality_ml_e2e_app.py` *(new)*

Synthesize a tiny tracking xlsx + a synthetic model directory (1 model per assay, accuracy ~1.0 on a 1-row fixture). Run the full pipeline. Open the produced HTML with `html.parser`, assert `.clonality-ml-badge` is present + has correct `data-ml-label`. Then simulate the dismiss flow by setting `data-state="dismissed"` on the badge, run the `serializeDecisions` JS via a tiny `py_mini_racer` if available, **else** skip and replace with a pure-Python replay of the dict-update logic that's equivalent. (If `py_mini_racer` is dirty on Windows, the JS logic should also be mirrored as a Python function `serialize_clonality_decisions(html_text) -> dict` so the test is robust. The Python helper lives in `core/html_reports/_legacy.py` and is used by tests; the JS calls the Python helper through `py_mini_racer` only when needed.) Update memory when we settle on one.

Run: `pytest tests/ -q` — expect green.

Commit: `test(ml): e2e batch → HTML badge → dismiss → Save Peaks round-trip`.

### Task 12: CHANGELOG + plan + memory

**Files:**
- Modify: `CHANGELOG.md` (or the per-release file used currently — check `ls -la *.md`)
- Modify: `ObsidianVault/Clonality_ML_Log/Lab_Log.md` *(append a row)*
- Modify memory: replace the line about Phase 6 "ready" with "SHIPPED 2026-07-13".

Commit: `docs(ml): App integration shipped — train/predict/dismiss round-trip`.

---

## Files likely to change (summary)

| File | Tasks |
|---|---|
| `core/analyses/clonality/ml_model.py` | 1, 2 (new) |
| `core/analyses/clonality/ml_runtime.py` | 4 (new) |
| `core/analyses/clonality/ml_training.py` | 3 |
| `core/analyses/clonality/pipeline.py` | 10 |
| `core/analyses/clonality/tracking_excel.py` | 5 |
| `core/html_reports/_legacy.py` | 6, 7 |
| `core/html_reports/_constants.py` | 6 (CSS) |
| `gui_qt/tabs/tab_settings.py` | 8 |
| `gui_qt/tabs/tab_ml_training.py` | 9 (new) |
| `gui_qt/main_window.py` | 9 (tab register) |
| `tests/test_clonality_ml_model.py` | 1, 2 |
| `tests/test_clonality_ml_runtime.py` | 4 |
| `tests/test_clonality_tracking_output.py` | 5 |
| `tests/test_html_report_fragment_cache.py` | 6 |
| `tests/test_html_report_clonality_badge.py` | 7 (new) |
| `tests/test_tab_settings_save.py` | 8 (new) |
| `tests/test_tab_ml_training.py` | 9 (new) |
| `tests/test_clonality_ml_e2e_app.py` | 11 (new) |

## Verification (post-implementation)

```bash
# 1. Unit
pytest tests/test_clonality_ml_model.py tests/test_clonality_ml_runtime.py tests/test_clonality_tracking_output.py tests/test_html_report_fragment_cache.py tests/test_html_report_clonality_badge.py tests/test_tab_settings_save.py tests/test_tab_ml_training.py -v

# 2. Full suite — must end at 406+ pass (Phase 5 baseline). New tests additively extend.
pytest tests/ -q

# 3. Real-data smoke — drive the actual flow on NightRuns data
python -m scripts.run_real_data_diagnostic --clonality --batch-style
```

## Risks & open questions

- **`fsa` object is a dataclass, not a dict** — `attach_ml_prediction_if_enabled(entry)` operates on the dict that's already plumbed in. Verified by reading `interpretation.py:438` — `interpret_entry(entry)` accepts the dict form. No issue.
- **Qt worker + sklearn import in the same process:** `tab_ml_training.py` will trigger the cold-import of sklearn via `ml_training.py`. Cold start ≈ 4s. Acceptable for a Train action. Pre-loading in `qt_app.py` startup would shave 4s but risks loading sklearn when the user never trains — YAGNI.
- **`py_mini_racer` availability on Windows:** if missing, the e2e dismiss test in Task 11 will replay the logic in pure Python via the helper. This is a defensive choice; see the note in Task 11.
- **What "rule + ML disagree → review-needed" looks like** — the chemist always wins; **dismiss** is just "I want the pathologist to only see my call, not the ML one." Decision outcome: ML column in summary table still shows the value (audit trail) but a dismissed badge disappears from the printed page.
- **Migration of existing `model_path` setting from a single .joblib to a directory** — silent behavior change. CHANGELOG note required; document a one-line error path "this looks like a .joblib file — set the parent dir instead."

## Execution handoff

Plan saved at `.hermes/plans/2026-07-13_clonality-ml-app-integration.md`. Ready to execute task-by-task with `subagent-driven-development`. Confirm and I dispatch.
