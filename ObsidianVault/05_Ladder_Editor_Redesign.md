# Ladder Editor Redesign

## Problem

Current Ladder Editor works technically, but it is hard to use for manual review:
- zoom is reset too often during redraw
- peak-adding is hidden behind a mode that turns off after one click
- operator has to coordinate plot, expected bp table, candidate table, and QC mentally
- possible peaks and selected peaks are visually present, but the fastest action is not obvious
- there is no clear “review queue” workflow from one bad file to the next

## Immediate Fix Already Implemented

First usability patch in `gui_qt/dialogs/ladder_dialog.py`:
- added plot controls:
  - `Full Trace`
  - `Ladder Region`
  - `Zoom Selected`
  - `Y Auto`
  - `Y 300`
  - `Y 1000`
- redraw now preserves current zoom/pan when editing
- renamed `Add Missing From Plot` to `Add Peaks From Trace`
- add-peaks mode now stays active and advances to the next missing bp instead of turning off after one click
- headless dialog smoke test passed on `25OUM12848_tcrgB__260825_F04_H9C0ZJBT.fsa`

Second usability patch:
- model-selected ladder peaks are injected into the candidate table as `model_selected`
- auto-mapping uses time tolerance instead of exact `peak_time in candidates`
- candidate table now shows `Source`
- clicking near a visible candidate assigns it directly to the selected/next missing bp
- `Add Peaks From Trace` first tries nearby existing candidates, then creates a manual apex if needed
- mouse wheel zooms around cursor
- right/middle drag pans the trace
- linear fit panel updates live from current mapping, even before full preview
- manual ladder application can recover when `size_standard_peaks` is missing by seeding from `best_size_standard`, `mapping_times`, and manual candidates

Third usability/crash patch:
- removed nested scroll-area layout and changed the editor into a compact workbench
- header/metachips, side editor, QC panel and actionbar are now tighter and more predictable
- primary action is labelled `Save Adjustment` to make persistence explicit
- removed Matplotlib `tight_layout()` from trace/residual redraw because it can crash with `Singular matrix` during Qt resize/apply
- fixed plotting layout now uses bounded `subplots_adjust()` so redraw cannot block saving

Fourth usability patch:
- pyqtgraph is now the primary trace canvas when installed
- Matplotlib remains a fallback only
- click-to-assign and add-peaks share one trace-click path across both backends
- plot/editor/QC layout has fewer heavy nested boxes and better expanding policies
- keyboard shortcuts are Ctrl-based so they do not interfere with review comment typing

Fifth compact-layout patch:
- top header is reduced to a status strip
- trace toolbar uses small buttons
- right editor rail now uses tabs (`Matches`, `Candidates`) instead of stacking both tables
- match table is reduced to the columns needed during editing: `bp`, `time`, `resid`, `status`
- missing-list hides when empty
- QC/review/residual panel is capped so the trace remains the main work surface

## Proposed Final Interaction Model

### Main Principle

The editor should behave like a ladder-specific annotation tool, not a generic table plus plot. The operator should always know:
- which bp is currently selected
- which peak will be assigned if they click
- whether they are in `Assign`, `Add`, `Pan`, or `Zoom` mode
- whether the final fit is report-safe

### Screen Layout

Top command bar:
- file name, assay, ladder, review reason
- fit status: `OK`, `Needs Review`, `Blocked`, `Manual Saved`
- primary actions: `Save Adjustment`, `Save Note Only`, `Next Review Case`

Left panel:
- expected ladder sequence as large rows
- each row shows bp, assigned scan, height, residual, and status
- missing rows are visually loud
- selecting a row centers the plot around expected/nearby peak region

Center panel:
- large trace canvas
- selected peaks as numbered labels
- possible peaks as smaller markers
- hover/click tooltip with time, height, candidate index, assigned bp
- mode toolbar: `Assign`, `Add Peak`, `Delete`, `Pan`, `Zoom`

Right panel:
- candidate list filtered to current zoom region
- quick buttons:
  - `Assign nearest candidate`
  - `Add apex at cursor`
  - `Clear selected bp`
  - `Recenter selected to local apex`
  - `Fit tail-to-front`
  - `Fit front-to-tail`

Bottom panel:
- residual plot
- linear max / mean / r2
- warning list: baseline-like selected peak, missing bp, non-monotonic order, huge residual, weak peak

## Interaction Rules

- Click candidate in `Assign` mode assigns it to the selected bp and advances to next missing bp.
- Click trace in `Add Peak` mode snaps to local apex, creates a manual candidate, assigns it, and stays in add mode.
- Mouse wheel zooms around cursor.
- Drag pans only in pan mode.
- Double-click candidate zooms to it.
- Press `Space` previews fit.
- Press `A` toggles add mode.
- Press `Delete` clears selected bp.
- Press `N` jumps to next missing bp.
- Press `S` saves when all required bp are assigned and preview is valid.

## Technical Recommendation

### Short Term

Keep Qt/PySide6 and improve the current dialog in layers:
- fast: fix zoom/add-mode and clearer controls
- next: replace Matplotlib toolbar dependency with explicit app-level modes
- then: move from Matplotlib canvas to `QGraphicsView` or pyqtgraph for smoother interaction

This is the lowest-risk route because the app already loads FSA files, applies `.ladder_adj.json`, writes reports, and integrates with the review-gate.

### Medium Term

If the editor remains the bottleneck, build a dedicated ladder-review surface:
- Qt app shell remains
- editor canvas becomes pyqtgraph or QGraphicsView
- backend remains Python + Rust
- review bundle remains `ladder_review_cases.csv`

### Long Term Alternative

Consider a web-based desktop shell only if we want a full product rebuild:
- Tauri: Rust shell + web UI, small app footprint, strong if we want Rust-native packaging
- Electron: fastest for rich Plotly/D3-style editor, but heavier runtime
- Browser/server webapp: easiest to iterate and annotate, but less ideal for offline/local-file clinical workflow unless packaged carefully

Recommendation: do not migrate the whole app now. First make the editor excellent inside Qt, then reassess. A rewrite only makes sense if the final editor needs web-grade interactions that Qt/pyqtgraph cannot deliver cleanly.

## Next Implementation Steps

1. Add explicit mode state banner: `Assign`, `Add Peak`, `Pan`, `Zoom`.
2. Make candidate markers clickable with nearest-marker hit testing instead of relying on local apex lookup only.
3. Add keyboard shortcuts.
4. Add zoom-region candidate filter.
5. Add `Next Review Case` handoff back to Ladder Studio.
6. Add “Save and rebuild reports” once report-rebuild flow exists.

## Acceptance Criteria

- Operator can fix a missing ladder peak without touching the candidate table.
- Zoom does not reset while assigning peaks.
- A sequence of missing peaks can be added in one continuous mode.
- Review bundle case opens, edits, saves `.ladder_adj.json`, and marks the case reviewed.
- No DIT report is built in hard-gate mode until unresolved review cases are resolved.
