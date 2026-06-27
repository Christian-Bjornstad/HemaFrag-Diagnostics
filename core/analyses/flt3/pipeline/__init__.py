"""HemaFrag FLT3 pipeline — split package (code-cleanup Phase 3).

Re-exports the legacy public API of the previously-monolithic
`core/analyses/flt3/pipeline.py` module so existing
`from core.analyses.flt3.pipeline import X` statements keep working
unchanged while the implementation now lives in focused submodules.

Submodules:
- `_constants`: tunable FLT3 thresholds, ladder/QC review bands,
  mode-name strings, size-standard token tables.
- `_legacy`:    the ladder fitting, peak detection, manual-ratio
  reporting, run_pipeline orchestration, FLT3 QC tracker work,
  GS500ROX start-family prior pipeline, etc. Scheduled for further
  granulization in subsequent code-cleanup phases.

Migration guidance:
- New code should prefer importing the focused submodules when
  possible (`from core.analyses.flt3.pipeline._legacy import ...`),
  but the facade here is a stable surface.
"""
from core.analyses.flt3.pipeline._constants import *  # noqa: F401,F403
from core.analyses.flt3.pipeline._legacy import *      # noqa: F401,F403
