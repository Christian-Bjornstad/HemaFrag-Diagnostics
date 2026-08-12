"""Shared runtime switches for HemaFrag analysis engines."""
from __future__ import annotations

import os


TRUE_TOKENS = {"1", "true", "yes", "on"}


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in TRUE_TOKENS


def strict_rust_ladder_enabled() -> bool:
    """Return whether the operator explicitly requested strict Rust runtime behavior."""
    if env_flag_enabled("HEMAFRAG_STRICT_RUST_LADDER") or env_flag_enabled("HEMAFRAG_RUST_ONLY"):
        return True
    try:
        from config import APP_SETTINGS
    except Exception:
        return False
    return bool(APP_SETTINGS.get("engine", {}).get("strict_rust_ladder", False))


def rust_owned_ladder_enabled() -> bool:
    """Return whether Rust owns ladder selection without Python replacement.

    Rust-owned fitting is the production default.  The old Python ladder
    selector remains available only through the explicit compatibility switch.
    Explicit strict/Rust-only environment switches always win.
    """
    if strict_rust_ladder_enabled():
        return True
    if python_ladder_compatibility_enabled():
        return False
    try:
        from config import APP_SETTINGS
    except Exception:
        return True
    engine = APP_SETTINGS.get("engine", {})
    return bool(engine.get("rust_owned_ladder", True)) or bool(
        engine.get("strict_rust_ladder", False)
    )


def python_ladder_compatibility_enabled() -> bool:
    """Return whether the legacy Python ladder selector may replace Rust."""
    if env_flag_enabled("HEMAFRAG_ENABLE_PYTHON_LADDER_FALLBACK"):
        return True
    try:
        from config import APP_SETTINGS
    except Exception:
        return False
    return bool(APP_SETTINGS.get("engine", {}).get("python_ladder_compatibility_fallback", False))
