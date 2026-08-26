"""
HemaFrag Diagnostics — Shared Utilities.
"""
from __future__ import annotations
import re

# Centralized Regex for Control identification
# "Positiv_kontroll"/"Negativ_kontroll" (norsk) mappes videre til PK/NK
# i control_id_from_filename() — her godtar vi dem som kontroller.
CONTROL_PREFIX_RE = re.compile(
    r"^(PK1|PK2|PK|NK|RK|DIT|KTR|NTC|IVS[-_]?0000|IVS[-_]?P001"
    r"|Positiv[\s_-]*kontroll|Negativ[\s_-]*kontroll)"
    r"([_\-\s]|(?=\.fsa)|$)",
    re.IGNORECASE,
)
# Norske kontrollnavn -> intern kortform (PK/NK); nøkler sammenlignes
# uten skilletegn ("positiv-kontroll"/"Positiv Kontroll" == POSITIVKONTROLL)
NORWEGIAN_CONTROL_ALIASES = {
    "POSITIVKONTROLL": "PK",
    "NEGATIVKONTROLL": "NK",
}
WATER_RE = re.compile(
    r"^(v(?:ann)?|water|h2o|mq|milliq|milli[-_ ]?q)(?:[_\-\s.]|(?=\d)|(?=\.fsa)|$)",
    re.IGNORECASE,
)

def strip_stage_prefix(name: str) -> str:
    """Removes the 5-digit prefix and 8-character hash from filenames."""
    clean_name = re.sub(r"^\d{5}_[a-f0-9]{8}_", "", name, flags=re.IGNORECASE)
    return re.sub(r"^\d+__", "", clean_name)

def is_water_file(filename: str) -> bool:
    """Returns True if the filename looks like a water/negative control."""
    clean_name = strip_stage_prefix(filename)
    return bool(WATER_RE.match(clean_name))

def is_control_file(filename: str) -> bool:
    """Returns True if the filename starts with a known control prefix (after stripping stage)."""
    clean_name = strip_stage_prefix(filename)
    return bool(CONTROL_PREFIX_RE.match(clean_name))

# Shared Color configuration (can be moved here if it helps centralize)
CHANNEL_COLORS = {
    "DATA1": "#3b82f6",     # Vibrant Blue
    "DATA2": "#10b981",     # Vibrant Emerald Green
    "DATA3": "#334155",     # Slate/Black
    "DATA4": "#ef4444",     # Vibrant Red/Rose
    "DATA105": "#f97316",   # Vibrant Orange
}
DEFAULT_TRACE_COLOR = "#3b82f6"
