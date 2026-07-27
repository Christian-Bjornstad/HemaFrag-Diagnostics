"""HemaFrag — `html_reports` split package (code-cleanup Phase 6).

Re-exports the legacy public API of the previously-monolithic
`core/html_reports.py` module so existing
`from core.html_reports import X` statements keep working unchanged.

Submodules:
- `_constants`: small lookup tables (`DIT_PATTERN`, `DIT_QC_CONTROL_IDS`)
  plus the multi-line inline `REPORT_STYLE` template and the
  `D835_DIGEST_HEIGHT_MIN` / `D835_DIGEST_AREA_MIN` thresholds.
- `_legacy`:    the imports block plus the 52 module-level helper
  functions that build HTML/DIT reports and shared QC markers.

Future sub-splits may extract focused helpers (e.g. separate
report-template builders and D835 digestion logic) into their own
submodules; for now the package is intentionally lean.
"""
from core.html_reports._constants import *  # noqa: F401,F403
from core.html_reports._legacy import *      # noqa: F401,F003
