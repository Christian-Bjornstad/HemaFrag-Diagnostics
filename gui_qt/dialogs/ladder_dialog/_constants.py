"""
HemaFrag GUI Qt — small inline constants used by the `ladder_dialog` package.

Auto-curated from the previously-monolithic `gui_qt/dialogs/ladder_dialog.py`
during the 2026-06-27 `code-cleanup` Phase 5.

Also houses the guarded optional `pyqtgraph` import (returns module `None`
if missing) so `_legacy.py` and downstream importers can rely on the
symbol.
"""
try:
    import pyqtgraph as pg
except Exception:
    pg = None



PASS_R2 = 0.9995
CHECK_R2 = 0.9990
PASS_MAX_ABS_RESIDUAL = 0.5
CHECK_MAX_ABS_RESIDUAL = 1.5
