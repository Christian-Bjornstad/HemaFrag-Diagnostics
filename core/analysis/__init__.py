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

Startup note (2026-08): this package's heavy scientific dependencies
(scipy / sklearn / Bio / pandas) are now loaded LAZILY via module-level
``__getattr__`` so that merely importing ``core.analysis._constants`` —
or any light GUI module importing it — no longer drags the whole stack
in (~1.5 s of application startup). Any attribute access on the package
(e.g. the first ``from core.analysis import analyse_fsa_liz``) triggers
the one-time load of ``_legacy``.
"""
from typing import Any

_LEGACY_ATTRS: dict[str, Any] | None = None


def _load_legacy_attrs() -> dict[str, Any]:
    global _LEGACY_ATTRS
    if _LEGACY_ATTRS is None:
        import core.analysis._legacy as _legacy

        _LEGACY_ATTRS = {
            name: getattr(_legacy, name)
            for name in dir(_legacy)
            if not name.startswith("__")
        }
    return _LEGACY_ATTRS


def __getattr__(name: str) -> Any:
    """PEP 562 lazy re-export of `_legacy` (and fallback `_constants`)."""
    attrs = _load_legacy_attrs()
    if name in attrs:
        return attrs[name]
    try:
        from core.analysis import _constants as _constants_mod

        return getattr(_constants_mod, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None


def __dir__() -> list[str]:
    attrs = set(_load_legacy_attrs().keys())
    try:
        from core.analysis import _constants as _constants_mod

        attrs.update(name for name in dir(_constants_mod) if not name.startswith("__"))
    except Exception:
        pass
    return sorted(attrs)
