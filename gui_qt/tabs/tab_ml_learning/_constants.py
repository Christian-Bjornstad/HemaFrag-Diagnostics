"""MlLearning constants - shared by tab_ml_learning sub-package.

Phase A (Plan 13).
"""
from __future__ import annotations


# JSONL event schema version - increment when shape changes.
LEARNING_SCHEMA_VERSION = 1

# Output layout (relative to project root or APP_SETTINGS output)
DEFAULT_LEARNING_OUTPUT_DIR = "ML_Learning"

# Sub-folder names rendered inside DEFAULT_LEARNING_OUTPUT_DIR
SUBDIR_ENTRIES = "entries"
SUBDIR_PANEL = "annotation"
SUBDIR_JSONL = "annotations"

# Per-run subdir pattern: "<assay-id>__<YYYYMMDD>_<HHMMSS>"
# e.g. "FR1__2026-07-12_203145"
RUN_DIR_FORMAT = "{assay}__{stamp}"

# Bail-out for the Annotations panel popup if the rendered file is missing
PANEL_HTML_FILENAME = "review_panel.html"
PANEL_ENTRIES_JSON_FILENAME = "entries.json"

# Key codes mirrors the existing label_tool shortcuts:
#   M monoklonal, P polyklonal, B bi_oligoklonal, I irregulaer,
#   Q pseudoklonal, N intet_pcr_produkt_darlig_dna,
#   T qc_teknisk_fail, U usikker_review, Z skip
KEYBOARD_SHORTCUTS = {
    "m": "monoklonal",
    "p": "polyklonal",
    "b": "bi_oligoklonal",
    "i": "irregulaer",
    "q": "pseudoklonal",
    "n": "intet_pcr_produkt_darlig_dna",
    "t": "qc_teknisk_fail",
    "u": "usikker_review",
    "z": "",
}


__all__ = [
    "DEFAULT_LEARNING_OUTPUT_DIR",
    "KEYBOARD_SHORTCUTS",
    "LEARNING_SCHEMA_VERSION",
    "PANEL_ENTRIES_JSON_FILENAME",
    "PANEL_HTML_FILENAME",
    "RUN_DIR_FORMAT",
    "SUBDIR_ENTRIES",
    "SUBDIR_JSONL",
    "SUBDIR_PANEL",
]
