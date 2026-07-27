"""HemaFrag GUI Qt — `ladder_dialog` split package (code-cleanup Phase 5).

Re-exports the legacy public API of the previously-monolithic
`gui_qt/dialogs/ladder_dialog.py` module so existing
`from gui_qt.dialogs.ladder_dialog import X` statements keep working
unchanged.

Submodules:
- `_constants`: small inline thresholds (`PASS_R2`, `CHECK_R2`,
  `PASS_MAX_ABS_RESIDUAL`, `CHECK_MAX_ABS_RESIDUAL`) plus a guarded
  optional `pyqtgraph` import (returns module `None` if missing).
- `_legacy`:    the imports block plus the giant
  `LadderAdjustmentDialog` QDialog class.
"""
from gui_qt.dialogs.ladder_dialog._constants import *  # noqa: F401,F403
from gui_qt.dialogs.ladder_dialog._legacy import *      # noqa: F401,F403
