# In-App Labeling Tab — Plan 2026-07-14

## Goal
Replace the Excel + HTML report context-switching workflow with a single
in-app tab where the chemist views the FSA electropherogram plot for each
sample and assigns a clonality label using keyboard shortcuts. Labels are
written back to the tracking Excel automatically.

## Workflow (chemist's perspective)
1. Sidebar → **Labeling** tab (new clonality sub-button, replaces nothing)
2. Browse → tracking Excel (`Clonality_Tracking_All_T7.xlsx`)
3. Browse → FSA root (`D:/DATA/2025_data`)
4. Tab populates with all unlabeled (or all) samples from the Excel
5. For each sample:
   - Left panel: sample metadata (DIT, assay, well, file name, current label)
   - Right panel: FSA electropherogram plot (Plotly in QWebEngineView)
   - Combo plots below when relevant (TCRb A+B+C, TCRg A+B)
6. Keyboard:
   - `1` = monoclonal, `2` = polyclonal, `3` = biclonal, `4` = oligoclonal
   - `5` = negative, `6` = irregular clonal, `7` = not enough PCR product
   - `↑/↓` = navigate samples
   - `Enter` = save current label + advance
   - `Ctrl+S` = save all to Excel
   - `Backspace` = clear label
7. Progress bar: "X / N labeled"
8. "Save labels to Excel" button (also auto-saves on close)

## Architecture

### New files
- `gui_qt/tabs/tab_labeling.py` — the tab widget (~300-400 lines)
- `core/labeling/labeling_session.py` — session model: load Excel, iterate
  samples, write labels back (~150-200 lines)
- `tests/test_labeling_session.py` — unit tests for the session model

### Existing files to modify
- `gui_qt/main_window.py` — add "Labeling" sub-button to clonality group,
  add tab to stack, update `_sub_button_map`
- `gui_qt/tabs/tab_settings.py` — add FSA root path setting for clonality

### Plot rendering
Reuse the existing Plotly trace extraction from `core/html_reports/_legacy.py`.
For each sample, generate a small HTML snippet with the electropherogram
trace(s) and load it into a `QWebEngineView`. This avoids re-implementing
trace rendering and gives the same visual quality as the HTML reports.

### Label set
```
ANNOTATION_LABELS = {
    "1": "monoclonal",
    "2": "polyclonal",
    "3": "biclonal",
    "4": "oligoclonal",
    "5": "negative",
    "6": "irregular clonal",
    "7": "not enough PCR product",
}
```
Mirrors the existing `ANNOTATION_CLASSES_ORDER` used by the ML model.

### Keyboard-first design
- Focus on the sample list (QListWidget or custom)
- Number keys intercepted via QShortcut
- No mouse needed for the full label → advance → save cycle
- Tab title shows progress: "Labeling — 142/750"

## Task breakdown

### Task 1: labeling_session.py — Excel read/iterate/write
- Load tracking Excel Run sheet
- Build list of samples: {dit, assay, well, file, source_run_dir, current_label}
- `label_sample(index, label)` — set label in memory
- `save_to_excel()` — write labels back to the Excel
- `unsampled_count()` / `labeled_count()` — progress
- Tests: load mock Excel, label samples, save, reload, verify

### Task 2: tab_labeling.py — UI skeleton
- Tab widget with Browse-xlsx, Browse-fsa-root, sample list, plot area
- QWebEngineView for plot rendering
- Keyboard shortcuts for labeling
- Progress indicator
- Connect to labeling_session

### Task 3: Wire into main_window
- Add "Labeling" sub-button to clonality
- Add to stack + _sub_button_map
- Update keyboard shortcut letters (R/L/A/M/G/S → add "B" for labeling?)

### Task 4: Plot rendering
- For each sample, extract the FSA trace using existing fraggler/pipeline code
- Generate a minimal HTML with Plotly trace
- Load into QWebEngineView
- Handle missing FSA files gracefully (show placeholder)

### Task 5: Excel writeback + auto-save
- Write labels back to the correct column in the tracking Excel
- Auto-save on tab switch / app close
- Verify round-trip: label in tab → Excel → reload

### Task 6: Tests + edge cases
- Empty Excel / no samples
- Missing FSA files
- FSA root not set
- Duplicate entries
- Labeled samples skipped by default (filter: "show unlabeled only")

## Scope note
This is a multi-session feature. Ship incrementally:
- **This session**: Tasks 1-3 (session model + UI skeleton + wiring)
- **Next session**: Tasks 4-5 (plot rendering + Excel writeback)
- **Final**: Task 6 (tests + edge cases + polish)

## What I will NOT do in this plan
- ML prediction during labeling (the ML tab already handles that)
- Undo/history (overkill for v1)
- Multi-user editing (single user, single Excel)
- Export to other formats (Excel IS the format)
