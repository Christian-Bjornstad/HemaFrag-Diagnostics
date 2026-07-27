"""HemaFrag analysis — split package (code-cleanup Phase 2).

Re-exports the legacy public API of the monolithic `core/analysis.py`
that existed before the 2026-06-27 split. Existing
`from core.analysis import X` statements keep working unchanged while the
implementation now lives in focused submodules.

Submodules:
- `_constants`: tunable thresholds / ladder-family step arrays
- `_legacy`: ladder fitting (LIZ/ROX/GS500), SL peak detection,
  baseline estimation, ladder QC metrics, ladder-adjustment persistence.
  Scheduled for further splitting in subsequent code-cleanup phases.
"""
from core.analysis._constants import *  # noqa: F401,F403
from core.analysis._legacy import *      # noqa: F401,F403


# Explicit re-export of the private helper that
# core.analyses.flt3.pipeline.py already imports via
# `from core.analysis import _select_best_ladder_candidate`.
# Star-import would skip the leading-underscore name.
from core.analysis._legacy import _select_best_ladder_candidate  # noqa: F401
