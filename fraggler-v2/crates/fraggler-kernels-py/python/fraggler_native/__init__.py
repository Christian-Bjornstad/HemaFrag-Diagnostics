"""Public re-export of the compiled `_fraggler_native` extension module.

maturin compiles the cdylib as a top-level extension named `fraggler_native`
because of `pyproject.toml [tool.maturin] module-name = "fraggler_native"`.
This package is just the wheel-side Python entry point.

We import the compiled symbols lazily so Python-only fallback paths don't
crash if the wheel isn't installed.
"""
from __future__ import annotations

try:
    from fraggler_native import (  # type: ignore
        analyze_fsa,
        fraggler_cli_path,
        is_available,
    )
    try:
        from fraggler_native import __version__ as version  # type: ignore
    except ImportError:
        version = "0.0.0+local"
except ImportError:  # pragma: no cover - wheel not installed
    def analyze_fsa(*_args, **_kwargs):  # type: ignore
        raise RuntimeError(
            "fraggler-kernels wheel not installed in this Python environment. "
            "Run `pip install -e fraggler-v2/crates/fraggler-kernels-py` "
            "(or build the maturin wheel) to enable the in-process Rust path."
        )

    def fraggler_cli_path():  # type: ignore
        return None

    def is_available() -> bool:  # type: ignore
        return False

    version = "0.0.0+missing"


__all__ = ["analyze_fsa", "fraggler_cli_path", "is_available", "version"]
