"""
Offline Plotly script tag provider.

Reads plotly-3.1.0-basic.min.js from the bundled assets/ directory and
returns a <script> tag with the slim JS inlined. No internet required. No
external file needs to be shipped alongside the HTML — the JS is
embedded inside each per-patient Resultater.html directly.

The slim "basic" partial build is ~1.1 MB instead of the full plotly.js
bundle (~4.6 MB). It supports the trace types and APIs the HemaFrag
HTML reports actually use (Scatter; newPlot; relayout; click handlers).
The full bundle is preserved in assets/ for the rare cases that need
3D/mapbox/finance/etc, but those callers use `full_inline_script_tag`.

Code-cleanup Plan 07 - PR A.
"""
from __future__ import annotations

from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_BASIC_JS_PATH = _ASSETS_DIR / "plotly-3.1.0-basic.min.js"
_FULL_JS_PATH = _ASSETS_DIR / "plotly-3.1.0.min.js"

# Cache the JS content so we read each file at most once per process.
_BASIC_INLINE_CACHE: str | None = None
_FULL_INLINE_CACHE: str | None = None


def _read_once(path: Path) -> str:
    """Read a JS file with `errors="replace"` to survive unexpected chars."""
    return path.read_text(encoding="utf-8", errors="replace")


def plotly_inline_script_tag() -> str:
    """
    Returns a ``<script>...</script>`` tag with the slim plotly-basic
    JS inlined.

    The JS is read from ``assets/plotly-3.1.0-basic.min.js`` on first
    call and cached for subsequent calls.

    This is the default for self-contained per-patient Resultater.html
    files. To embed the full bundle (e.g. for diagnostics that need
    3D/scene traces), use `full_inline_script_tag` instead.
    """
    global _BASIC_INLINE_CACHE
    if _BASIC_INLINE_CACHE is None:
        if not _BASIC_JS_PATH.exists():
            raise FileNotFoundError(
                f"Bundled plotly slim JS not found at {_BASIC_JS_PATH}.  "
                f"Please run scripts/refresh_slim_plotly.py or fetch the "
                f"plotly.js-basic-dist-min bundle from unpkg.com."
            )
        _BASIC_INLINE_CACHE = _read_once(_BASIC_JS_PATH)
    return f"<script>{_BASIC_INLINE_CACHE}</script>"


def full_inline_script_tag() -> str:
    """Returns a <script> tag with the full plotly.js inline (~4.6 MB).

    Reserved for HTMLs that genuinely need features the slim basic
    bundle does not expose (3D scenes, mapbox, finance, gl2d, mesh).
    Most HemaFrag result-HTL paths should stick with
    `plotly_inline_script_tag` (the slim build)."""
    global _FULL_INLINE_CACHE
    if _FULL_INLINE_CACHE is None:
        if not _FULL_JS_PATH.exists():
            raise FileNotFoundError(
                f"Bundled plotly full JS not found at {_FULL_JS_PATH}.  "
                f"Either download it (CARTO_FETCH.md) or call "
                f"plotly_inline_script_tag() for the slim build."
            )
        _FULL_INLINE_CACHE = _read_once(_FULL_JS_PATH)
    return f"<script>{_FULL_INLINE_CACHE}</script>"


# ------------------------------------------------------------------
# Backward-compatible alias (keeps the existing signature for callers
# that pass out_dir / version, neither of which is used).
# ------------------------------------------------------------------
def local_plotly_tag(out_dir: "Path | None" = None, version: str = "3.1.0") -> str:
    """Drop-in replacement for the old ``plotly_local.local_plotly_tag``.

    Returns a slim inline plotly-basic script. Pass `version` for
    informational purposes; it is not embedded into the output tag."""
    return plotly_inline_script_tag()
