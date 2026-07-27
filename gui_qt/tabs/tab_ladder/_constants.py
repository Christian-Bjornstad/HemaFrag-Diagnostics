"""HemaFrag GUI Qt — small inline constants for `tab_ladder`.

Phase 12.1 — extracted from the previously-monolithic
`gui_qt/tabs/tab_ladder/_legacy.py`.

Display-only strings. Pulling them out keeps the GUI class body
focused on logic and lets tests assert on the placeholder text
without spinning up Qt.
"""

from __future__ import annotations


DEFAULT_TAB_TITLE = "Ladder Studio"
DEFAULT_TAB_SUBTITLE = (
    "Pick one .fsa file, inspect its ladder metadata, and open a focused "
    "ladder-adjustment workflow."
)

SOURCE_CARD_TITLE = "SOURCE FILES"
DETAILS_CARD_TITLE = "SELECTED FILE"
REPORT_CARD_TITLE = "MATCHING REPORTS"

SOURCE_DIR_PLACEHOLDER = "/path/to/folder with .fsa files"
BUNDLE_DIR_PLACEHOLDER = (
    "/optional/path/to/review bundle with ladder_review_cases.csv"
)
REPORT_ROOT_PLACEHOLDER = "/optional/path/to/report root"
FILTER_PLACEHOLDER = "Filter by filename, DIT, assay, plate position..."

FAILED_CLASSIFY_PLACEHOLDER = "Could not classify"
FAILED_LOAD_PLACEHOLDER = "Could not load"

SYNC_HINT_NOTE = (
    "Tip: double-click a file to jump straight into the ladder editor. "
    "Inside the editor you can re-map peaks, preview the fit, and save "
    "the adjustment for re-runs."
)
