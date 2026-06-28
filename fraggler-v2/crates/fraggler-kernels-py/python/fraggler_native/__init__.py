"""Public re-export of the compiled `fraggler_native` extension module.

Maturin installs the cdylib produced by `Cargo.toml [lib]` at
`fraggler_native/fraggler_native.<so>` (because the lib's crate name and
the python `module-name` from pyproject.toml agree). This file is the
top-level Python entry point that re-exports the compiled symbols.

We import them lazily so Python-only fallback paths don't crash if the
wheel isn't installed.
"""
from __future__ import annotations

# When maturin builds with module-name = "fraggler_native", the
# compiled library lands at `fraggler_native/fraggler_native.<ext>` —
# Python exposes it as `fraggler_native.fraggler_native` submodule.
try:
    from fraggler_native.fraggler_native import (  # type: ignore
        analyze_fsa,
        fraggler_cli_path,
        is_available,
    )
    try:
        from fraggler_native.fraggler_native import __version__ as version  # type: ignore
    except ImportError:
        version = "0.0.0+local"
except ImportError:  # pragma: no cover - wheel not installed
    def analyze_fsa(*_args, **_kwargs):  # type: ignore
        raise RuntimeError(
            "fraggler-kernels wheel not installed in this Python environment. "
            "Install the wheel produced by `maturin build` to enable the "
            "in-process Rust path."
        )

    def fraggler_cli_path():  # type: ignore
        return None

    def is_available() -> bool:  # type: ignore
        return False

    version = "0.0.0+missing"


__all__ = ["analyze_fsa", "fraggler_cli_path", "is_available", "version"]
