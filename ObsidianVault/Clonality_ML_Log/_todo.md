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




## Tomorrow's pickup (Phase 5+ — re-evaluating)

Today's session shipped two important pre-flight pieces:

- [x] Smoke-tested the train CLI end-to-end on synthetic data:
      commands/train_clonality_interpretation_models.py produces
      joblib + metadata + per-assay markdown reports for FR1,
      TCRG-A, DHJH_D. (commit c8c59fb)
- [x] Fixed four pre-existing flaky tests from the
      package-shell refactor: cache pruning monkeypatch targets,
      monkeypatch module path issues, missing import os/sys.
      (commit 2d8182a. 171 tests green.)
- [x] QFileDialog Browse button on the interpretation tab
      so chemists can pick any tracking workbook from the GUI.
      (commit 698ea73.)
- [x] scripts/export_clonality_labels_csv.py -- the missing
      glue that lets us turn a tracking Excel into labels.csv
      without regenerating the Excel via the rule engine.
      (commit 698ea73.)

Tomorrow's pickup (revised):

1. **Real-data first model run.** Use the new exporter:
   ```
   python scripts/export_clonality_labels_csv.py \
       --xls /Volumes/T7 Shield/DATA/clonality/Clonality_Tracking.xlsx \
       --out /tmp/labels.csv
   python scripts/train_clonality_interpretation_models.py \
       --xls /Volumes/T7 Shield/DATA/clonality/Clonality_Tracking.xlsx \
       --labels-csv /tmp/labels.csv \
       --output-dir /Volumes/T7 Shield/DATA/clonality/models/
   ```
   This should now work end-to-end on the 22k labelled catalogue.

2. **Chemist calibration review** — once the first OOF metrics
   are in, review per-assay τ values in `config.py`.

3. **xgboost trigger criterion** — if FR1 rare-class F1 < 0.85,
   per `decisions/xgboost_pending.md`.

4. **Phase 7 feedback loop** — when chemist iterates on disagreement
   rows via the Browse-loaded GUI tab, append JSONL lines under
   `ObsidianVault/Clonality_ML_Log/feedback/<date>.jsonl`.

---

## Plan 12 — Ladder Studio remodel (branch `ml-clonality-interpretation-2026-06-27`)

Started 2026-07-08. Skill file
`~/.hermes/skills/lab-workflow/hemafrag-diagnostics-lab/SKILL.md`
is the consolidated design. Master plan + tasks:
`ObsidianVault/Clonality_ML_Log/ladder_editor/_plan.md`,
`ObsidianVault/Clonality_ML_Log/ladder_editor/_tasks.md`.

Status re-implementation after lost container work:

- [x] Phase 12.0 — fix silent-drop in bundle loader (commit `12d29ad`)
- [x] Phase 12.1 — split `tab_ladder` into package (commit `a75d64a`)
- [x] Phase 12.3 — chip-strip overview widget (commit `14b7bc1`)
- [x] Phase 12.4 — Locate File re-entry (`relocate_review_case` + GUI, commit `43d2bfc`)
- [x] Phase 12.6 — keyboard nav (Alt+J/K/Ctrl+.) — commit `20f8e90`.
        13 new tests (9 helper + 4 wiring integration). Suite: 219 → 232 + 1 skipped.
        Helpers: `next_chip_index(rows, current_index, direction, *, only_relevant, wrap)`.
        Routes: `QShortcut` on the *tab* (not on the strip — strip owns
        mouse semantics; chord keys live on the window context).
- [x] Phase 12.7 — chip filter helpers + GUI filter bar — commit `3e9868c`.
        18 new tests. Suite: 232 → 250 + 1 skipped. Helpers: `apply_filter_rows`,
        `count_states` (alias of `count_chip_states`), `is_chip_state_allowed`.
        GUI: `ChipFilterBar` widget above `ChipStripOverview` with toggleable
        color-coded chips + "All" / "None" + counts label. Toggles propagate
        via `filterChanged → set_filter(allowed_states)`.
- [x] Phase 12.8 — Mark Visible Reviewed bulk button — commit `7f6cff7`.
        14 new tests. Suite: 250 → 264 + 1 skipped. Helpers: `bulk_mark_reviewed_no_change`
        (pure), `bulk_save_review_bundle_annotations` (CSV+JSON atomic), and constant
        `REVIEWED_NO_CHANGE_LABEL`. GUI: button under chip strip; status label
        reports CHANGED-count, not touched-count (Plan 12 §12.8 pitfall). After save,
        reload the bundle so chip strip + counts re-render.
- [x] Phase 12.9 — audit JSONL stream — commit `3620e8b`.
        15 new tests. Suite: 264 → 279 + 1 skipped. Helpers: `make_audit_event`,
        `append_audit_event`, `read_audit_log` + constant `AUDIT_LOG_FILENAME`.
        Wire-in: every save slot wrapped in try/except (Plan 12 §14 — audit never
        blocks the CSV save). Stable `stage` values: `"review"`, `"locate_file"`,
        `"bulk_review"`. In-memory mirror `_audit_event_stream` capped at 200
        (AUDIT_STREAM_CAP) for the Phase 12.17 panel to consume.
- [x] Phase 12.10 — drop-row hook — commit `c2d810b`.
        9 new tests. Suite: 279 → 288 + 1 skipped. Core: `drop_review_case`
        (atomic CSV rewrite + `ladder_review_drops.json` append, returns
        `{full_path, previous_label, dropped_at_utc, dropped_row_index}`)
        + `read_review_drops`. GUI: chip-strip right-click menu now always
        offers "Drop row from bundle…"; QMessageBox confirms; emits Phase 12.9
        `stage="drop"`; reloads bundle so chip and file list refresh.
- [x] Phase 12.11 — DIT prefix filter — commit `00d5859`.
        17 new tests. Suite: 288 → 305 + 1 skipped. Helpers: `extract_dit_candidates(rows, prefix)`
        (case-insensitive, full_path → source_run_dir fallback), `dit_filter_keep(indices)`;
        GUI: `QLineEdit` "Filter by DIT" + Clear button + summary label. ChipStrip
        gains `dit_filter_keep(kept_indices)` setter that AND-composes with
        `set_filter(allowed_states)`; slot reads `self._review_bundle_cases` and
        dispatches both.
- [x] Phase 12.12 — bundle summary banner — commit `4cd6b54`.
        12 new tests. Suite: 305 → 317 + 1 skipped. Helpers: `most_recent_save_timestamp`
        (lexicographic max over ISO strings, "never" fallback), `format_summary_banner`
        (renders `visible N of T | needs_review | unreachable | reviewed | untouched |
        last saved: <ts>`). GUI: `bundle_summary_label` QLabel below chip strip,
        rendered as part of `_sync_chip_strip` (single writer) so every existing
        trigger path (load / save / drop / locate / bulk review) drives the banner
        for free.
- [x] Phase 12.13 — Ctrl+R mark-current-reviewed — commit `eb3e929`.
        4 new tests + 1 fixup. Suite: 317 → 321 + 1 skipped. GUI: extended
        `_install_navigation_shortcuts` to bind Ctrl+R alongside Alt+J/K/Ctrl+.,
        plus the new `_mark_current_file_reviewed_no_change` slot. Reuses
        `_save_review_bundle_annotation(action="note_only")`; captures
        `target_name = self._current_file.name` BEFORE the save call so
        `_rebuild_file_list()`'s `_select_file` transient-null doesn't crash
        the status string (Plan 12 §13 pitfall).
- [ ] Phase 12.14 — ladder editor preview header. `compose_dialog_header(file, assay, ladder)`
        + `refresh_dialog_header(dialog, fsa)`. Dialog `__init__`
        swaps `setWindowTitle(...)` → `refresh_dialog_header(self, fsa)`.
- [ ] Phase 12.15 — rerun-rationale JSONL (`ladder_review_rationale.jsonl`).
        `append_rerun_rationale / read_rerun_rationales / build_rerun_rationale / format_rerun_rationale_line`.
        Wires into `_on_single_rerun_finished` and `_on_review_bundle_rerun_finished`.
- [ ] Phase 12.16 — bundle import/export zip.
        `import_bundle(zip_path, target_dir)` / `export_bundle(bundle_dir, zip_path)`.
        "Import Bundle..." / "Export Bundle..." buttons in the chip frame.
- [ ] Phase 12.17 — audit-trail mini panel.
        `_append_audit_event(event)` + `_audit_event_stream` (capped 200),
        read-only `QPlainTextEdit` rendered via `format_audit_event_line`.
        `_clear_recent_audit_panel()` wired into `_on_review_bundle_result`.

Deferred: Phase 12.2 (dialog package split), Phase 12.5
(J/K next-missing inside the Ladder Adjustment dialog).

Cadence: one atomic commit per phase (helpers + tests + GUI
wiring + status doc, all in one commit). `git push origin
ml-clonality-interpretation-2026-06-27` immediately after each
so a container restart can't lose the work — see Plan 12 §15.

