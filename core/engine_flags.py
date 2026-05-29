"""Shared runtime switches for HemaFrag analysis engines."""
from __future__ import annotations

import os


TRUE_TOKENS = {"1", "true", "yes", "on"}


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in TRUE_TOKENS


def strict_rust_ladder_enabled() -> bool:
    """Return whether ladder fitting must stop instead of using Python fallback."""
    if env_flag_enabled("HEMAFRAG_STRICT_RUST_LADDER") or env_flag_enabled("HEMAFRAG_RUST_ONLY"):
        return True
    try:
        from config import APP_SETTINGS
    except Exception:
        return False
    return bool(APP_SETTINGS.get("engine", {}).get("strict_rust_ladder", False))
