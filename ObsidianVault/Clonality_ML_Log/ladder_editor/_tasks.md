# Plan 12 — Task list

Numbered `T-12.X.Y`. Each task carries `scope`, `do`, `verify`, `done_when`.

## Phase 12.0 — fix silent-drop in `_load_review_bundle_worker`

- **T-12.0.a** — Replace `if not full_path.exists(): continue` with
  "keep all rows; tag unreachable ones so the editor surfaces them."
- **T-12.0.b** — Add `missing_paths` to the worker result dict.
- **T-12.0.c** — `_on_review_bundle_result`: when missing_paths > 0,
  mark status bar red with `⚠ N case(s) reference a path that is currently
  unreachable`.
- **T-12.0.d** — Tests: `test_keeps_rows_with_unreachable_full_path`,
  `test_keeps_empty_full_path_unchanged_when_present_only_for_real_rows`.

## Phase 12.1 — split `tab_ladder` into a package

- **T-12.1.a** — `_constants.py` (UI strings).
- **T-12.1.b** — `_summary.py` (cache key resolution, entry shims,
  bundle counts, format_file_item).
- **T-12.1.c** — `_io.py` (bundle CSV IO: load + save annotation +
  review_case_paths).
- **T-12.1.d** — `_workers.py` (scan, metadata, find_report_matches).
- **T-12.1.e** — `_legacy.py` slim TabLadder class shell.
- **T-12.1.f** — `__init__.py` star-reexport facade.

## Phase 12.2 — split `dialogs/ladder_dialog`

- **T-12.2.a** — `_style.py` (QSS block).
- **T-12.2.b** — `_matches.py`, `_candidates.py`, `_qc.py` (card
  builders + their slots).
- **T-12.2.c** — slim `_legacy.py`.

## Phase 12.3 — chip-strip overview

- **T-12.3.a** — `_summary.chip_state(row, *, check_filesystem=False)`:
  `reviewed` | `needs_review` | `file_unreachable` | `untouched`.
- **T-12.3.b** — new `_overview.py` widget: horizontal chip strip.
- **T-12.3.c** — wire to top of `_build_overview_card`.

## Phase 12.4 — Locate File re-entry

- **T-12.4.a** — `core/analyses/clonality/ladder_review_gate.py`:
  `relocate_review_case(bundle_dir, old_path, new_path)` atomic rewrite
  + `ladder_review_relocations.json` log.
- **T-12.4.b** — chip context menu: "Locate File…" → QFileDialog →
  helper → reload bundle.

## Phase 12.5 — keyboard loop in dialog (defer until 12.1-12.4 in place)

## Phase 12.6 — chip-strip tab nav

- **T-12.6.a** — `next_relevant_row(rows, current_index, predicate)`
  pure helper.
- **T-12.6.b** — QShortcut bindings: Alt+J, Alt+K, Ctrl+.

## Phase 12.7 — chip filter

- **T-12.7.a** — `apply_filter_rows(rows, allowed_states)`,
  `count_states(rows)` pure helpers + `CHIP_STATE_LABELS`.
- **T-12.7.b** — Filter toggle in chip frame, dim non-matching chips
  with rgba(R,G,B,0.35).

## Phase 12.8 — bulk review

- **T-12.8.a** — `bulk_mark_reviewed_no_change(rows, paths, now_iso=None)`.
- **T-12.8.b** — `bulk_save_review_bundle_annotations(bundle_dir, rows)`.
- **T-12.8.c** — "Mark Visible Reviewed (no change)" button.

## Phase 12.9 — audit JSONL stream

- **T-12.9.a** — `make_audit_event`, `append_audit_event`,
  `read_audit_log`.
- **T-12.9.b** — wire emit into save / drop / bulk-review / locate-file.

## Phase 12.10 — drop row

- **T-12.10.a** — `drop_review_case(bundle_dir, full_path)` atomic
  rewrite + drops audit log.
- **T-12.10.b** — "Drop row from bundle…" menu + confirm + reload.

## Phase 12.11 — DIT prefix filter

- **T-12.11.a** — `extract_dit_candidates(rows, prefix)` pure helper.
- **T-12.11.b** — QLineEdit "Filter by DIT" + Clear button. Composability:
  `set_filter(allowed_states)` AND `dit_filter_keep(kept_paths)`.

## Phase 12.12 — bundle summary banner

- **T-12.12.a** — `most_recent_save_timestamp(rows)`,
  `format_summary_banner(rows, *, visible_count=None, total_count=None)`
  pure helpers.
- **T-12.12.b** — QLabel banner; refresh embedded in
  `_sync_overview_with_bundle`.

## Phase 12.13 — Ctrl+R mark-current-reviewed

- **T-12.13.a** — `_mark_current_file_reviewed_no_change` slot using
  the existing `_save_review_bundle_annotation` helper with
  `action="note_only"`. Capture `target_name` BEFORE the save helper
  so `_rebuild_file_list()`'s `_select_file` re-select doesn't drop the
  `_current_file` attribute.

## Phase 12.14 — dialog preview header

- **T-12.14.a** — `compose_dialog_header(file_name, assay, ladder)`
  pure helper + `refresh_dialog_header(dialog, fsa)` side-effect wrapper.
- **T-12.14.b** — wire the dialog `__init__` to call
  `refresh_dialog_header(self, fsa)`.

## Phase 12.15 — rerun-rationale JSONL

- **T-12.15.a** — `append_rerun_rationale(bundle_dir, event)`,
  `read_rerun_rationales(bundle_dir)`, `build_rerun_rationale(...)`,
  `format_rerun_rationale_line(event)`.
- **T-12.15.b** — wire emit into `_on_single_rerun_finished` and
  `_on_review_bundle_rerun_finished` with mirrors to in-memory audit
  stream.

## Phase 12.16 — bundle import/export zip

- **T-12.16.a** — `import_bundle(zip_path, target_dir)` and
  `export_bundle(bundle_dir, zip_path, *, include_reports=False)` pure
  helpers.
- **T-12.16.b** — Import / Export buttons in chip frame with confirm.

## Phase 12.17 — audit-trail mini panel

- **T-12.17.a** — `_append_audit_event(event)` append + render
  `_audit_event_stream` (capped at 200) into a read-only `QPlainTextEdit`
  under the summary banner.
- **T-12.17.b** — `_clear_recent_audit_panel()` wired into
  `_on_review_bundle_result` (fresh-bundle reset).

---

## Verification gate

Each phase ships only when:
1. `QT_QPA_PLATFORM=offscreen python -m pytest --tb=no -q` is at or
   above the expected test count for this branch.
2. No new file exceeds the per-file line budget.
3. The Obsidian `_todo.md` is updated to reflect what landed.
