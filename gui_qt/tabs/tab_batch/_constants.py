"""
HemaFrag GUI Qt — small inline constants used by the `tab_batch` package.

Auto-curated from the previously-monolithic `gui_qt/tabs/tab_batch.py`
during the 2026-06-27 `code-cleanup` Phase 5. Re-exported via the
package facade.
"""
ANALYSIS_LABELS = {
    "clonality": "Klonalitet",
    "flt3": "FLT3 Analysis",
    "general": "General",
}

GENERAL_LADDER_OPTIONS = [
    ("LIZ500", "LIZ500_250"),
    ("ROX400HD", "ROX400HD"),
    ("GS500ROX", "GS500ROX"),
]
GENERAL_TRACE_OPTIONS = [
    ("DATA1", "Blue trace"),
    ("DATA2", "Green trace"),
    ("DATA3", "Yellow / Black trace"),
]

__all__ = [
    'ANALYSIS_LABELS',
    'GENERAL_LADDER_OPTIONS',
    'GENERAL_TRACE_OPTIONS',
]
