"""HemaFrag GUI Qt — `tab_batch` split package (code-cleanup Phase 5).

Re-exports the legacy public API of the previously-monolithic
`gui_qt/tabs/tab_batch.py` module so existing
`from gui_qt.tabs.tab_batch import X` statements keep working
unchanged.

Submodules:
- `_constants`: small inline lookup tables `ANALYSIS_LABELS`,
  `GENERAL_LADDER_OPTIONS`, `GENERAL_TRACE_OPTIONS`.
- `_legacy`:    the imports block plus all four Qt classes
  (FlowLayout, GeneralTraceCard, JobsTableWidget, TabBatch) unchanged.

Migration guidance:
- Keep imports targeting `gui_qt.tabs.tab_batch` to preserve any
  external call sites; new code may prefer the focused submodules.
"""
from gui_qt.tabs.tab_batch._constants import *  # noqa: F401,F403
from gui_qt.tabs.tab_batch._legacy import *      # noqa: F401,F403
