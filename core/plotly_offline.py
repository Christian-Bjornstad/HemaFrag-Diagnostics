"""
Offline Plotly script tag provider.

Reads plotly-3.1.0.min.js from the bundled assets/ directory. By default,
reports reference one copied local asset per output folder so large batches do
not inline the same multi-MB Plotly runtime into every HTML file.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_PLOTLY_JS = _ASSETS_DIR / "plotly-3.1.0.min.js"
_REPORT_ASSET_DIR = "assets"
_REPORT_PLOTLY_NAME = "plotly-3.1.0.min.js"

# Cache the JS content so we only read it once per process
_PLOTLY_INLINE_CACHE: str | None = None


def plotly_inline_script_tag() -> str:
    """
    Returns a ``<script>…</script>`` tag with the full plotly.js inlined.

    The JS is read from ``assets/plotly-3.1.0.min.js`` on first call and
    cached for subsequent calls.
    """
    global _PLOTLY_INLINE_CACHE
    if _PLOTLY_INLINE_CACHE is None:
        if not _PLOTLY_JS.exists():
            raise FileNotFoundError(
                f"Bundled plotly JS not found at {_PLOTLY_JS}.  "
                f"Please ensure assets/plotly-3.1.0.min.js exists."
            )
        # Use errors="replace" to avoid crashing on unexpected characters in minified JS
        _PLOTLY_INLINE_CACHE = _PLOTLY_JS.read_text(encoding="utf-8", errors="replace")
    return f"<script>{_PLOTLY_INLINE_CACHE}</script>"


def _inline_plotly_reports_enabled() -> bool:
    raw = os.environ.get("HEMAFRAG_INLINE_PLOTLY_REPORTS")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from config import APP_SETTINGS
    except Exception:
        return False
    return bool(APP_SETTINGS.get("engine", {}).get("inline_plotly_reports", False))


def _copy_plotly_asset(out_dir: Path) -> Path:
    if not _PLOTLY_JS.exists():
        raise FileNotFoundError(
            f"Bundled plotly JS not found at {_PLOTLY_JS}. "
            f"Please ensure assets/plotly-3.1.0.min.js exists."
        )
    asset_dir = out_dir / _REPORT_ASSET_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / _REPORT_PLOTLY_NAME
    try:
        if target.exists() and target.stat().st_size == _PLOTLY_JS.stat().st_size:
            return target
    except OSError:
        pass
    shutil.copy2(_PLOTLY_JS, target)
    return target


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------
def local_plotly_tag(out_dir: "Path | None" = None, version: str = "3.1.0") -> str:
    """Drop-in replacement for the old ``plotly_local.local_plotly_tag``."""
    del version
    if out_dir is None or _inline_plotly_reports_enabled():
        return plotly_inline_script_tag()
    try:
        target = _copy_plotly_asset(Path(out_dir))
    except Exception:
        return plotly_inline_script_tag()
    rel = target.relative_to(Path(out_dir)).as_posix()
    return f'<script src="{rel}"></script>'
