"""HemaFrag — `plotting_plotly` split package (code-cleanup Phase 6).

Re-exports the legacy public API of the previously-monolithic
`core/plotting_plotly.py` module so existing
`from core.plotting_plotly import X` statements keep working
unchanged. The implementations live in a single `_legacy.py`
submodule today (file was nearly pure-function code), with the
one tunable constant `FLT3_NEGATIVE_CONTROL_YMIN` carried inside
that submodule.

Future sub-splits may extract focused helper submodules per
function family (peak plots, group ymax, batch HTML builders).
"""
from core.plotting_plotly._legacy import *  # noqa: F401,F403
