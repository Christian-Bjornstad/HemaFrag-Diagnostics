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

**LANDED (2026-07-08, branch pre-push):**

Phase 12.6 helpers + wiring shipped. Helpers landed in
`gui_qt/tabs/tab_ladder/_summary.py`:
- `RELEVANT_CHIP_STATES = {"needs_review", "file_unreachable"}` —
  the chip states Ctrl+. considers worth visiting. Reviewed and
  untouched are deliberately skipped.
- `next_chip_index(rows, current_index, direction, *,
  only_relevant=False, check_filesystem=False, wrap=True)` —
  walks the chip list one-by-one with the same modulo wrap
  semantics as `_save_review_bundle_annotation`'s row math,
  clamping out-of-range `current_index` with `% n` so that
  stale indices from a bundle reload don't behave erratically.
  Returns -1 for empty input or `wrap=False` + nothing qualifies.

GUI wiring in `gui_qt/tabs/tab_ladder/_legacy.py`:
- `_install_navigation_shortcuts()` — three `QShortcut`s
  bound to the *tab* (WindowShortcut context so they fire
  while focus is in the file-list or line edits). Kept on
  `self._nav_shortcuts` for future introspection / phase-12.5
  dialog mode that might disable them.
- `_nav_move_chip(direction)` — Alt+J / Alt+K; silent if no
  bundle or no current selection, so the user's accidental
  chord doesn't blank the chip strip.
- `_nav_jump_next_relevant()` — Ctrl+.; writes a "No further
  chip needs review." status on full-cycle exhaustion with
  `wrap=True`, leaves file focus put.
- `_current_chip_index()` — scans `self._review_bundle_cases`
  for `Path(row["full_path"]) == self._current_file`. Returns
  -1 if no bundle or current selection isn't in the loaded
  rows (typical after a Drop / Locate File reload).

Tests (13 new):
- `tests/test_tab_ladder_submodules.py::NextChipIndexHelperTests`
  (9 cases — walks, wrap, only_relevant, out-of-range clamp,
  constant lock-in).
- `tests/test_tab_ladder_navigation.py` (4 wiring cases —
  shortcut count, silent-on-empty-bundle, current_index
  resolution against synthetic bundle).

Suite: 219 (Phase 12.4) → 232 (+13), 1 skipped, 0 regressions.


## Phase 12.7 — chip filter

- **T-12.7.a** — `apply_filter_rows(rows, allowed_states)`,
  `count_states(rows)` pure helpers + `CHIP_STATE_LABELS`.
- **T-12.7.b** — Filter toggle in chip frame, dim non-matching chips
  with rgba(R,G,B,0.35).

**LANDED (2026-07-08, branch pre-push):**

Phase 12.7 helpers + GUI wiring shipped. Helpers landed in
`gui_qt/tabs/tab_ladder/_summary.py`:
- `count_states = count_chip_states` — alias so GUI code can
  stay terse without forking the implementation.
- `apply_filter_rows(rows, allowed_states)` — returns shallow
  copies of the rows whose chip state is in the allowed set.
  `allowed_states` accepts set / list / tuple / None. None is
  "no filter" (every row passes). Empty set is "match nothing"
  (returns `[]`). Input `None` is tolerated (returns `[]`).
- `is_chip_state_allowed(state, allowed_states)` — does the
  single-state lookup without rerunning `chip_state(row)`;
  used by the GUI to dim each chip without re-extracting.

GUI wiring (`gui_qt/tabs/tab_ladder/_overview.py` +
`_legacy.py`):
- `ChipFilterBar` widget — a horizontal row of toggleable
  buttons, one per chip-state, color-coded per `CHIP_STATE_COLORS`.
  "All" / "None" buttons on the right + a live counts label
  ("3 / 7" or "visible 1 / 7 (Reviewed: 3, Unreachable: 3)"
  when filtered). Initial state: every chip-state allowed
  (`allowedStates()` returns `None` = no filter).
- `FILTER_BAR_STATE_ORDER` — `(reviewed, needs_review,
  file_unreachable, untouched)` so the left→right walk
  matches the natural color-coded urgency.
- `FILTER_BAR_LABELS` — human-readable maps for the counts
  breakdown.
- Tab wires `ChipFilterBar.filterChanged` → `_on_chip_filter_changed`
  → `ChipStripOverview.set_filter(allowed_states)`. The chip strip
  already exposes `set_filter` from Phase 12.3 (it dims
  non-matching chips to opacity 0.35).
- `_sync_chip_strip()` — single writer that pushes rows to
  both the strip and the filter bar; the bar's filter
  selection persists across bundle reloads (counts re-render
  but no reset).

Tests (18 new):
- `ChipFilterHelperTests` (10): None-is-open, subset, empty-set
  semantics, list/tuple normalize, input-None safety, alias
  pin, is_* helpers covering None / set / empty / garbage.
- `ChipFilterBarWiringTests` (5): bar + strip installed,
  initial state, select-all/none, setRows updates counts,
  empty-input clears label.
- `TabLadderChipFilterForwardingTests` (1): bar toggle
  propagates into the chip strip.

Suite: 232 (Phase 12.6) → 250 (+18), 1 skipped, 0 regressions.


## Phase 12.8 — bulk review

- **T-12.8.a** — `bulk_mark_reviewed_no_change(rows, paths, now_iso=None)`.
- **T-12.8.b** — `bulk_save_review_bundle_annotations(bundle_dir, rows)`.
- **T-12.8.c** — "Mark Visible Reviewed (no change)" button.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.8 helpers + GUI wiring shipped.

Helpers:
- `REVIEWED_NO_CHANGE_LABEL = "reviewed_no_change"` — single
  constant so the string is referenced from one place. The GUI's
  status string and the audit event builder both point here.
- `bulk_mark_reviewed_no_change(rows, paths, *, now_iso=None)`
  — pure helper. Returns one annotation dict per *in-bundle*
  path with `label=reviewed_no_change`, `label_note=""`, the
  injected (or fresh) `reviewed_at_utc` ISO timestamp, and
  `adjustment_path=""`. Paths not in the bundle are silently
  skipped so the button can't phantom-write a row that isn't
  tracked.

IO layer (`gui_qt/tabs/tab_ladder/_io.py`):
- `bulk_save_review_bundle_annotations(bundle_dir, new_rows)`
  — single atomic CSV rewrite applying every annotation, plus
  an `ladder_review_annotations.json` accumulator. **Returns
  the count of rows whose stored label *actually flipped***,
  not the touched count — Plan 12 §12.8 pitfall. Empty new
  label means "chemist cleared the field" — don't inflate the
  count, don't overwrite the existing label. Missing CSV
  raises `FileNotFoundError` so the GUI's worker error signal
  surfaces fail-loud.

GUI (`gui_qt/tabs/tab_ladder/_legacy.py`):
- "Mark Visible Reviewed (no change)" button under the chip
  strip (`btn_bulk_mark_reviewed`).
- Companion status label (`bulk_mark_label`) reading
  `Marked X of Y visible row(s) reviewed`.
- `_on_bulk_mark_visible_reviewed_clicked` slot:
  1. Resolves the visible-row paths via `apply_filter_rows(cases,
     self._chip_filter_bar.allowedStates())` so the sweep
     matches the chemist's filter choice.
  2. Calls the pure helper to shape annotations.
  3. Calls the IO helper for the atomic CSV rewrite.
  4. Updates the label and a `_set_status(...)` line with the
     changed count vs the touched count.
  5. Re-loads the bundle via `_load_review_bundle()` so the
     chip strip + filter bar counts reflect the new state.

Tests (14 new):
- `BulkMarkReviewedNoChangeTests` (4): shape, in-bundle gating,
  empty-input, Path-object inputs, default-now-iso-recentness.
- `BulkSaveReviewBundleAnnotationsTests` (6): atomic CSV
  rewrite, label-change-vs-touch count, empty-label no-op,
  missing-CSV raises, empty input returns 0, unknown path
  silently skipped.
- `TabLadderBulkMarkReviewedWiringTests` (3): button installed,
  no-bundle click is no-op, with-bundle click returns
  "Marked 1 of 2".

Suite: 250 (Phase 12.7) → 264 (+14), 1 skipped, 0 regressions.


## Phase 12.9 — audit JSONL stream

- **T-12.9.a** — `make_audit_event`, `append_audit_event`,
  `read_audit_log`.
- **T-12.9.b** — wire emit into save / drop / bulk-review / locate-file.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.9 helpers + wiring shipped. Helpers in
`gui_qt/tabs/tab_ladder/_io.py`:

- `AUDIT_LOG_FILENAME = "ladder_review_audit.jsonl"` —
  single constant.
- `make_audit_event(stage, *, row, action, comment, extra)`
  — pure event constructor; always returns at least
  `{stage, timestamp_utc, row_path_text, action, comment}`.
- `append_audit_event(bundle_dir, event)` — appends one JSON
  line. Returns True/False; never raises. Cwd-anchored when
  `bundle_dir=None`.
- `read_audit_log(bundle_dir)` — reads all events as a list;
  missing log returns `[]`; bad lines silently skipped.

Wire-in (`gui_qt/tabs/tab_ladder/_legacy.py`):
- Every save slot wrapped in `try/except Exception: pass`
  per Plan 12 §14 — audit failure never blocks the primary
  save path.
- `_save_review_bundle_annotation` emits `stage="review"`
  (with linear_max/r2 means).
- `_on_locate_file` emits `stage="locate_file"` carrying
  the old/new path swap.
- `_on_bulk_mark_visible_reviewed_clicked` emits
  `stage="bulk_review"` carrying touched+changed counts.
- `_append_audit_event` + `_audit_event_stream` capped at
  200 (`AUDIT_STREAM_CAP`).
- `_clear_recent_audit_panel` wired into
  `_on_review_bundle_result` so loading a new bundle resets.

Tests (15 new):
- `MakeAuditEventTests` (6): required fields, row_path_text,
  action/comment, extra merge, garbage extras, no-row.
- `AppendAuditEventTests` (5): round-trip, filename,
  None-bundle, missing-log returns `[]`, JSONL line shape.
- `TabLadderAuditStreamWiringTests` (3): stream init,
  200-cap rolling, clear reset.
- `TabLadderBulkMarkWritesAuditEventTests` (1): bulk-review
  click → JSONL write.

Suite: 264 (Phase 12.8) → 279 (+15), 1 skipped, 0 regressions.


## Phase 12.10 — drop row

- **T-12.10.a** — `drop_review_case(bundle_dir, full_path)` atomic
  rewrite + drops audit log.
- **T-12.10.b** — "Drop row from bundle…" menu + confirm + reload.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.10 core helper + wiring shipped.

Core (`core/analyses/clonality/ladder_review_gate.py`):
- `drop_review_case(bundle_dir, full_path | str)` — atomic
  CSV rewrite, removes matching row, appends to
  `ladder_review_drops.json`. Returns dict with
  `{full_path, previous_label, dropped_at_utc,
  dropped_row_index}`. Raises FileNotFoundError on missing
  CSV or unknown path.
- `read_review_drops(bundle_dir)` — chronological log;
  missing file returns `[]`; corrupt JSON returns `[]`
  with no exception.
- `DROPPED_AT_UTC_FORMAT` constant.

GUI (`gui_qt/tabs/tab_ladder/_overview.py` +
`_legacy.py`):
- `chipDropRequested` `pyqtSignal` on `ChipStripOverview`.
- `_bind_chip_click`: right-click menu now **always**
  offers "Drop row from bundle…" (per the skill). Locate
  File still gates on `state == "file_unreachable"` —
  Locate File only makes sense for unreachable paths.
- `_on_drop_review_case` slot — confirms via
  `QMessageBox.question`, calls the helper, emits Phase 12.9
  `stage="drop"` audit event, then reloads the bundle so
  the chip and file list both refresh.
- Failures (missing CSV / unknown row / IO error) turn the
  status bar red and leave the chip in place — destructive
  ops are gated on a clean CSV before they cascade.

Tests (9 new):
- `DropReviewCaseTests` (7): core helper pins (row removal,
  log accumulation, missing/unknown error paths,
  Path-object passthrough).
- `TabLadderDropReviewCaseWiringTests` (2): the chip strip
  exposes the new signal; the slot emits the right audit
  stage when the confirm dialog is stubbed.

Suite: 279 (Phase 12.9) → 288 (+9), 1 skipped, 0 regressions.


## Phase 12.11 — DIT prefix filter

- **T-12.11.a** — `extract_dit_candidates(rows, prefix)` pure helper.
- **T-12.11.b** — QLineEdit "Filter by DIT" + Clear button.
  Composability: `set_filter(allowed_states)` AND
  `dit_filter_keep(kept_paths)`.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.11 helpers + GUI wiring shipped.

Helpers (`gui_qt/tabs/tab_ladder/_summary.py`):
- `_DIT_REGEX = re.compile(r"(\d{2}OUM\d{5})", re.IGNORECASE)`.
- `_row_dit(row)` — best-effort DIT extraction; reads
  `full_path` first, falls back to `source_run_dir` (T7
  Shield rename fallback). Returns `""` on no match.
- `extract_dit_candidates(rows, prefix) -> (indices, dits)` —
  case-insensitive prefix match, prefix compared uppercase
  to uppercase DIT. Empty prefix → `([], [])`. Rows whose
  DIT can't be extracted never match.
- `dit_filter_keep(indices) -> set[int] | None` —
  converts index list to GUI's allowed-set shape; empty
  input returns `None` ("no filter").

GUI (`gui_qt/tabs/tab_ladder/_overview.py` +
`_legacy.py`):
- `ChipStripOverview.dit_filter_keep(kept_indices)` — *separate*
  setter from `set_filter(allowed_states)`. Internally
  AND-composes the two: a chip is full opacity only when
  both filters allow it. None on either disables that filter
  without resetting the other.
- `QLineEdit` "Filter by DIT" with placeholder
  "e.g. 24OUM203" + Clear button.
- Summary label "N matches: DIT1, DIT2, +X more" so the
  chemist sees what survived the filter.
- `_on_dit_filter_changed(text)` slot: re-extracts from
  `self._review_bundle_cases`, calls `dit_filter_keep`,
  sets the summary label.
- `_on_clear_dit_filter_clicked` slot: clears the
  `QLineEdit` with signal-blocking so we get one
  emission rather than two.

Tests (17 new):
- `ExtractDitCandidatesTests` (11): full_path extraction,
  source_run_dir fallback, case-insensitive matching,
  uppercase output, empty prefix, empty rows, no match,
  no-DIT rows, prefix-only-at-start, dit_filter_keep
  None-for-empty, dit_filter_keep set shape.
- `TabLadderDitFilterWiringTests` (6): input + button +
  label installed, slot updates summary on prefix, slot
  clears on empty, zero-matches summary, Clear button
  pathway, AND-composition shape.

Suite: 288 (Phase 12.10) → 305 (+17), 1 skipped, 0 regressions.

## Phase 12.12 — bundle summary banner

- **T-12.12.a** — `most_recent_save_timestamp(rows)`,
  `format_summary_banner(rows, *, visible_count=None,
  total_count=None)` pure helpers.
- **T-12.12.b** — QLabel banner; refresh embedded in
  `_sync_chip_strip`.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.12 helpers + GUI wiring shipped.

Helpers (`gui_qt/tabs/tab_ladder/_summary.py`):
- `NEVER_SAVED_LABEL = "never"` — single constant.
- `most_recent_save_timestamp(rows)` — lexicographic max
  over `reviewed_at_utc` ISO strings; falls back to
  "never".
- `format_summary_banner(rows, *, visible_count=None,
  total_count=None)` — renders the banner line, empty
  input produces the zero-line fallback.

GUI (`gui_qt/tabs/tab_ladder/_legacy.py`):
- `bundle_summary_label` `QLabel` installed directly
  below the chip strip in `_build_source_card`.
- `_sync_chip_strip` is the single writer; the banner
  refresh piggy-backs on it. Every existing trigger path
  (load, save, drop, locate, bulk review) re-renders the
  banner for free.

Tests (12 new):
- `MostRecentSaveTimestampTests` (4): empty / None,
  no-timestamps, picks lexicographic max, garbage
  timestamps tolerated.
- `FormatSummaryBannerTests` (5): empty input zeroed,
  visible-and-total default, visible_count override,
  total_count override shape, includes most-recent save.
- `TabLadderBundleSummaryBannerTests` (3): banner label
  installed, initial zeroed banner, sync refresh.

Suite: 305 (Phase 12.11) → 317 (+12), 1 skipped, 0 regressions.

## Phase 12.13 — Ctrl+R mark-current-reviewed

- **T-12.13.a** — `_mark_current_file_reviewed_no_change` slot using
  the existing `_save_review_bundle_annotation` helper with
  `action="note_only"`. Capture `target_name` BEFORE the save
  helper so `_rebuild_file_list()`'s `_select_file` doesn't
  transient-None-then-crash the status read.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.13 keyboard-shortcut wiring shipped.

GUI (`gui_qt/tabs/tab_ladder/_legacy.py`):
- `_install_navigation_shortcuts` extended to bind Ctrl+R
  alongside Alt+J/K/Ctrl+. — 4 shortcuts total. Listed in
  `self._nav_shortcuts`.
- `_mark_current_file_reviewed_no_change` slot:
  - Safe no-ops: no bundle loaded, no file selected,
    select file not in loaded bundle (refuse rather than
    phantom-write).
  - **Pitfall guard (Plan 12 §13):** captures
    `target_name = self._current_file.name` BEFORE the
    save helper runs, since the save helper ends with
    `_rebuild_file_list()` → `_select_file(...)` which
    transient-Nones `_current_file`. Status string is
    safe even when the selection does transient-null.
  - Reuses `_save_review_bundle_annotation(action="note_only")`
    so Phase 12.9 audit emission (`stage="review"`),
    in-memory mirror, chip-strip refresh, and Phase 12.12
    banner refresh all fire for free.

Tests (4 new + 1 fixup):
- `test_shortcuts_installed` (renamed from `test_three_…`)
  expects 4 shortcuts.
- `TabLadderCtrlRWiringTests` (4): slot method exists,
  no-bundle safe no-op, no-current-file warns, phantom-
  write refuses when select is not in loaded bundle.

Suite: 317 (Phase 12.12) → 321 (+4), 1 skipped, 0 regressions.

## Phase 12.14 — dialog preview header

- **T-12.14.a** — `compose_dialog_header(file_name, assay, ladder)`
  pure helper + `refresh_dialog_header(dialog, fsa)` side-effect wrapper.
- **T-12.14.b** — wire the dialog `__init__` to call
  `refresh_dialog_header(self, fsa)`.

**LANDED (2026-07-08, branch pre-push):**

Phase 12.14 dialog header shipped. Helpers in
`gui_qt/dialogs/ladder_dialog/_legacy.py`:
- `compose_dialog_header(file_name, assay="", ladder="")` -
  pure function. Joins non-empty parts with middle-dot
  separator. Empty intermediates skipped; all-empty falls
  back to the base title.
- `refresh_dialog_header(dialog, fsa=None)` - side-effect
  wrapper that calls `dialog.setWindowTitle`. None dialog
  / None fsa / exceptions all tolerated.
- `LADDER_DIALOG_BASE_TITLE`, `LADDER_DIALOG_TITLE_SEPARATOR`
  constants.

GUI (`gui_qt/dialogs/ladder_dialog/_legacy.py`):
- `LadderAdjustmentDialog.__init__` swaps
  `self.setWindowTitle(f"Ladder Adjustment - {fsa.file_name}")`
  for `refresh_dialog_header(self, fsa=fsa)`.
- Title format: `"Ladder Adjustment · <file> · <assay> · <ladder>"`.

Tests (7 new, in `tests/test_ladder_dialog_header.py`):
- `ComposeDialogHeaderTests` (4): file_only,
  file+assay+ladder, empty_assay_skipped, all_empty_falls_back.
- `RefreshDialogHeaderTests` (3): sets window title,
  tolerates None dialog / None fsa, handles garbage FSA.

Suite: 321 (Phase 12.13) -> 328 (+7), 1 skipped, 0 regressions.

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
