# Plan 03 — Plotting + GUI review

> Branch: `code-cleanup` (off `codex-clonality-ladder-finalize-2026-05-14`).
> Test baseline: `Ran 33 tests, OK` via
> `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests`.
> Reviewer responsibility: **real findings only**.

This plan covers the Plotly + Matplotlib HTML/MPL helpers and the
PyQt6 GUI tabs/dialogs.

---

## 1. Architecture summary

- **Report builders**:
  - `core/plotting_plotly/_legacy.py` (2039 lines) builds
    Interactive Plotly HTML — peak plots, group y-max helpers,
    assay-batch plots.
  - `core/html_reports/_legacy.py` (1597 lines) builds
    Final Q / DIT HTML reports (per-run + aggregated).
  - `core/html_reports/_constants.py` carries the 277-line
    multi-line `REPORT_STYLE` string plus the small lookup tables
    `DIT_PATTERN` (regex), `DIT_QC_CONTROL_IDS` (set), and the
    D835-DIGEST thresholds.
  - `core/plotting_mpl.py` (305 lines, single module) provides
    matplotlib zoom helpers — `compute_zoom_ymax`.
- **GUI dispatcher**:
  - `gui_qt/main_window.py` (301 lines) wires tabs and serves the
    `MainWindow`. Loads styles from `gui_qt/styles.py` (539 lines).
  - Five live tabs: `TabAnalysisSettings` (settings tab),
    `TabBatch`, `TabLadder`, `TabFlt3Validation`,
    `TabArchiveRunner`, `TabLog`, `TabAbout`.
- **Ladder dialog**: `gui_qt/dialogs/ladder_dialog/_legacy.py`
  (2023 lines) — `LadderAdjustmentDialog` QDialog with 72 methods,
  plus a shared `pyqtgraph` optional import.
- **Big QWidget classes** (each their own package since Phase 5):
  - `FlowLayout(QLayout)` (`gui_qt/tabs/tab_batch/_legacy.py:26`) —
    12 methods.
  - `GeneralTraceCard(QFrame)` (`:101`) — 3 methods.
  - `JobsTableWidget(QTableWidget)` (`:139`) — 3 methods.
  - `TabBatch(QWidget)` (`:171`) — 56 methods, 1665 lines total.
  - `TabLadder(QWidget)` (`gui_qt/tabs/tab_ladder/_legacy.py:46`) —
    70 methods, 1741 lines total.
  - `LadderAdjustmentDialog(QDialog)`
    (`gui_qt/dialogs/ladder_dialog/_legacy.py:37`) — 72 methods,
    2033 lines total.
- **Worker abstraction**: `gui_qt/worker.py` (66 lines) — Qt
  `QThreadPool` adapter to drive blocking calls off the UI thread.
- **Style**: `gui_qt/styles.py` (539 lines) defines `VIBRANT_PRO_QSS`
  stylesheet.

## 2. File inventory (verbatim `wc -l`)

```
plotting_plotly tree:
   14  core/plotting_plotly/__init__.py
 2039  core/plotting_plotly/_legacy.py
 2053  total

html_reports tree:
   19  core/html_reports/__init__.py
  299  core/html_reports/_constants.py
 1597  core/html_reports/_legacy.py
 1915  total

gui_qt tree:
   52  gui_qt/about_content.py
   21  gui_qt/dialogs/ladder_dialog/_constants.py
 2023  gui_qt/dialogs/ladder_dialog/_legacy.py
   16  gui_qt/dialogs/ladder_dialog/__init__.py
  283  gui_qt/ladder_utils.py
   23  gui_qt/log_handler.py
  301  gui_qt/main_window.py
  539  gui_qt/styles.py
  140  gui_qt/tabs/tab_about.py
  716  gui_qt/tabs/tab_archive_runner.py
   23  gui_qt/tabs/tab_batch/_constants.py
 1646  gui_qt/tabs/tab_batch/_legacy.py
   19  gui_qt/tabs/tab_batch/__init__.py
  540  gui_qt/tabs/tab_flt3_validation.py
 1742  gui_qt/tabs/tab_ladder/_legacy.py
   12  gui_qt/tabs/tab_ladder/__init__.py
   56  gui_qt/tabs/tab_log.py
  328  gui_qt/tabs/tab_settings.py
   66  gui_qt/worker.py
 8546  total

standalone:
  305  core/plotting_mpl.py
```

## 3. Cross-reference map (selected)

- `core/plotting_plotly/_legacy.py` is consumed by:
  - `core/analyses/clonality/pipeline.py` imports
    `compute_group_ymax_for_entries`, `build_interactive_assay_batch_plot_html`.
  - `core/analyses/general/reporting.py` imports
    `build_interactive_peak_plot_for_entry`.
  - `core/html_reports/_legacy.py` imports both of the above.
- `core/html_reports/_legacy.py` is consumed by:
  - `core/analyses/clonality/pipeline.py` imports
    `extract_dit_from_name`.
  - `scripts/render_clonality_interpretation_annotation_html.py`.
  - `core/batch.py`.
  - `core/clonality_backfill.py`.
  - `gui_qt/tabs/tab_batch/_legacy.py` (CLONALITY button flow).
- PyQt6 + Plotly integration: `core/plotly_offline.py`
  (not under review here — small) provides `local_plotly_tag`
  and `plotly_inline_script_tag`; both `core/__init__.py` and the
  plotting modules reach for these.

## 4. Intentional tech debt (do not churn)

- **Silent ImportError swallows**:
  - `gui_qt/tabs/tab_archive_runner.py` (lines ~30-40) wraps
    `scripts.run_clonality_yearly` +
    `scripts.combine_clonality_yearly_overview` in
    `try`/`except`, sets `_ARCHIVE_SUPPORT_AVAILABLE = False`
    silently.
  - `gui_qt/tabs/tab_flt3_validation.py` (lines ~30-50) wraps
    `scripts.run_flt3_backfill_validation` similarly. Plan 01
    Task 6 also cites this for cross-tracking.

  The user agreed during Phase 1 that falling silently is the
  current policy (we deleted the missing scripts). **Add a
  notice**: per Plan 01 Task 6 + Plan 03 Task 2 below.

- **277-line `REPORT_STYLE` multi-line triple-quoted string** in
  `core/html_reports/_constants.py:150-426`. Kept inline to keep
  the report writer and style co-located; extracting to a
  separate file would lose the line-length suppression on review.

- **`plotly_offline.py`** is the bundled-Plotly loader; if upstream
  fails to load, the system degrades gracefully. Don't swap to a
  CDN-based load script that requires network during package time.

- **Big QWidget classes** (`TabBatch`, `TabLadder`, `LadderAdjustmentDialog`)
  — single-class files are intentional at this stage; the Phase 5
  package conversion made them safely isolatable but the sub-class
  splits are explicitly out of scope unless requested.

## 5. Actionable task list

### Task 1 — Sub-split: extract `_batch_table.py` from `TabBatch`
- **Scope**: take the `JobsTableWidget` (L139-167) class and
  surrounding row-build helpers (`_rebuild_table`,
  `_selected_row_count`) out of
  `gui_qt/tabs/tab_batch/_legacy.py` into a new
  `gui_qt/tabs/tab_batch/_table_widget.py`.
- **Why**: `JobsTableWidget` is one of four classes in the file;
  isolating it lets the table logic iterate independently.
- **Acceptance**: facade re-export; tests still pass (GUI tests
  exercised via `ladder_review_gate`).
- **Commit**: `refactor(tab_batch): extract JobsTableWidget to _table_widget.py`
- **Risk**: low.  **Effort**: S.

### Task 2 — Hygiene: surface silent ImportError in `tab_archive_runner.py`
- **Scope**: replace the bare `except Exception as exc:`porch
  in `gui_qt/tabs/tab_archive_runner.py:32` to add a single-line
  `print_warning` (or a `Qt` warning banner set on the tab when
  shown) calling out the parked helper scripts.
- **Why**: cross-references Plan 01 Task 6.
- **Acceptance**: when the tab is constructed, the parked state
  is visible.
- **Commit**: `fix(gui): surface silent ImportError fallback in tab_archive_runner.py`
- **Risk**: low.  **Effort**: S.

### Task 3 — Sub-split: extract Plotly peak plot family
- **Scope**: from `core/plotting_plotly/_legacy.py`'s 2039 lines,
  pull the `_flt3_peak_id`, `build_*_peak_plot*` family into a
  new submodule `core/plotting_plotly/_peak_plots.py`.
- **Why**: peak plots are the dominant caller pattern; isolating
  them shrinks `_legacy.py` meaningfully.
- **Acceptance**: facade re-export; tests still 33/33.
- **Commit**: `refactor(plotting): split peak-plot builders to _peak_plots.py`
- **Risk**: medium.  **Effort**: M.

### Task 4 — Sub-split: extract DIT HTML reporter sub-module
- **Scope**: pull the `generate_flt3_peak_report`,
  `generate_flt3_bp_validation_report`, `aggregate_dit_*` family
  out of `core/html_reports/_legacy.py` into
  `core/html_reports/_dit_reports.py`. Complements Plan 01 Task 3.
- **Why**: DIT report logic is the dominant consumer of
  `REPORT_STYLE`.
- **Acceptance**: facade re-export; tests still 33/33.
- **Commit**: `refactor(html-reports): split DIT report writers to _dit_reports.py`
- **Risk**: medium.  **Effort**: M.

### Task 5 — Styles: split `gui_qt/styles.py`
- **Scope**: `gui_qt/styles.py` is 539 lines. Split into
  `gui_qt/styles/_palette.py` (CSS color tokens, ~100 lines),
  `gui_qt/styles/_qss.py` (`VIBRANT_PRO_QSS`, ~380 lines),
  facade `__init__.py`.
- **Why**: 539 lines is large for a styles-only module.
- **Acceptance**: facade re-exports `VIBRANT_PRO_QSS` import;
  tests still pass.
- **Commit**: `refactor(styles): split gui_qt/styles.py into styles package`
- **Risk**: low.  **Effort**: S.

### Task 6 — Test gap: add `test_html_report_fragment_cache.py` extensions
- **Scope**: existing `tests/test_html_report_fragment_cache.py`
  is only 42 lines. Add cases for:
  - empty `entries` argument (e.g., empty list, empty DataFrame).
  - `entries` with stale `dit_pattern` text.
  - `entries` referring to reads whose run metadata is missing.
- **Why**: defensive regression coverage before the html_reports
  refactor (Task 4) lands.
- **Acceptance**: tests still pass.
- **Commit**: `test(html-reports): extend fragment-cache tests for empty/stale/missing entries`
- **Risk**: low.  **Effort**: M.

### Task 7 — Type hint sweep: `gui_qt/main_window.py`
- **Scope**: add `from __future__ import annotations` if missing,
  add `# type: ignore[arg-type]` only where genuine, tighten
  signal-slot signatures.
- **Why**: many `pyqtSignal` factories today don't carry
  payload types.
- **Acceptance**: file compiles under `mypy --ignore-missing-imports`.
- **Commit**: `chore(gui): add type hints to MainWindow signals/slots`
- **Risk**: low.  **Effort**: M.

## 6. Verification

```
$ wc -l /workspace/hemafrag/core/plotting_plotly/*.py \
        /workspace/hemafrag/core/html_reports/*.py \
        /workspace/hemafrag/gui_qt
[as in section 2 above]

$ grep -n '^class \|^def ' /workspace/hemafrag/gui_qt/tabs/tab_batch/_legacy.py | head
26:class FlowLayout(QLayout):
101:class GeneralTraceCard(QFrame):
139:class JobsTableWidget(QTableWidget):
171:class TabBatch(QWidget):

$ grep -l 'from core.plotting_plotly\|from core.html_reports' \
       /workspace/hemafrag --include='*.py' -r
/workspace/hemafrag/core/analyses/clonality/pipeline.py
/workspace/hemafrag/core/analyses/general/reporting.py
/workspace/hemafrag/core/html_reports.py
[routes via package too]

$ QT_QPA_PLATFORM=offscreen python3 -c "import qt_app, gui_qt.main_window, gui_qt.tabs.tab_batch, gui_qt.tabs.tab_ladder, gui_qt.dialogs.ladder_dialog"
[imports succeed — Phase 7 fix commit ensures __init__.py docstrings are valid]

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
