"""
HemaFrag — Rust bridge constants.

Auto-curated from the previously-monolithic `core/rust_bridge.py` during
the 2026-06-27 `code-cleanup` Phase 6. Re-exported via the package
facade unchanged.
"""
from collections import OrderedDict
from pathlib import Path
from typing import Any
import sys
import threading






ROX_PREFERRED_TIME_MIN = 1500.0
ROX_PREFERRED_TIME_MAX = 4000.0
ROX_HARD_TIME_MIN = 1300.0
ROX_HARD_TIME_MAX = 4300.0
ROX_MAX_FIRST_ANCHOR = 1900.0
ROX_MIN_SPAN = 1100.0
ROX_MIN_MEDIAN_GAP = 26.0
ROX_MIN_HARD_WINDOW_FRACTION = 0.75

GS500ROX_PREFERRED_TIME_MIN = 1400.0
GS500ROX_PREFERRED_TIME_MAX = 4200.0
GS500ROX_ABSOLUTE_TIME_MIN = 1300.0
GS500ROX_HARD_TIME_MIN = 1180.0
GS500ROX_HARD_TIME_MAX = 4550.0
GS500ROX_ABSOLUTE_TIME_MAX = 6000.0
GS500ROX_MAX_FIRST_ANCHOR = 1700.0
GS500ROX_MIN_SPAN = 2500.0
GS500ROX_MIN_MEDIAN_GAP = 36.0
GS500ROX_MIN_HARD_WINDOW_FRACTION = 0.60

LIZ_HARD_TIME_MIN = 1150.0
LIZ_HARD_TIME_MAX = 4300.0
LIZ_MAX_FIRST_ANCHOR = 1700.0
LIZ_MIN_SPAN = 900.0
LIZ_MIN_MEDIAN_GAP = 22.0
LIZ_MIN_HARD_WINDOW_FRACTION = 0.80

_CLI_BIN_CACHE: Path | None = None
_RUST_WORKER: "_RustPrimitiveWorker | None" = None
_RUST_WORKER_LOCK = threading.Lock()
_RUST_WORKER_OWNER_PID: int | None = None
_RUST_PREWARM_WORKERS: list["_RustPrimitiveWorker"] = []
_RUST_PREWARM_WORKERS_LOCK = threading.Lock()
_RUST_PREWARM_WORKERS_OWNER_PID: int | None = None
_RUST_RESULT_CACHE_MAX = 2048
_RUST_RESULT_CACHE: "OrderedDict[tuple[str, str, int, int], dict[str, Any]]" = OrderedDict()
_RUST_RESULT_CACHE_LOCK = threading.Lock()
_RUST_ENGINE_STATS_LOCK = threading.Lock()
_RUST_ENGINE_STATS: dict[str, int] = {
    "cache_hits": 0,
    "worker_hits": 0,
    "cli_hits": 0,
    "failures": 0,
    "prewarm_cached": 0,
}


def _windows_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}

    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= startf_use_showwindow
        startupinfo.wShowWindow = sw_hide
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _persistent_rust_worker_supported() -> bool:
    disabled = os.environ.get("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return False
    if sys.platform == "win32":
        return False
    return True

