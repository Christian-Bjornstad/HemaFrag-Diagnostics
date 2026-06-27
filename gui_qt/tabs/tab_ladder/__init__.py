"""HemaFrag GUI Qt — `tab_ladder` split package (code-cleanup Phase 5).

Re-exports the legacy public API of the previously-monolithic
`gui_qt/tabs/tab_ladder.py` module so existing
`from gui_qt.tabs.tab_ladder import X` statements keep working
unchanged.

Submodules:
- `_legacy`:    the imports block plus one tiny helper `_open_path` and
  the giant `TabLadder` `QWidget` class.
from gui_qt.tabs.tab_ladder._legacy import *  # noqa: F401,F403