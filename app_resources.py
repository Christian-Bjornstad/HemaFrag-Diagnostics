"""Portable application resource and desktop-identity helpers.

This module deliberately stays independent of Qt at import time.  Source
launches, Python/wheel deployments, and frozen bundles all use the same
resource lookup and Windows application identity.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Iterable

from app_meta import APP_BUNDLE_ID


_LOGGER = logging.getLogger(__name__)
_ICON_NAMES = {
    "win32": ("app_icon.ico", "app_icon.png"),
    "darwin": ("app_icon.icns", "app_icon.png"),
    "linux": ("app_icon.png", "app_icon.ico"),
}


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            normalized = path.expanduser().resolve(strict=False)
        except OSError:
            normalized = path.expanduser().absolute()
        key = os.path.normcase(str(normalized))
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def application_resource_roots(
    *,
    bundle_dir: str | os.PathLike[str] | None = None,
) -> tuple[Path, ...]:
    """Return portable roots that may contain the bundled ``assets`` folder."""
    module_root = Path(__file__).resolve().parent
    frozen_root = getattr(sys, "_MEIPASS", None)
    executable_root = Path(sys.executable).resolve().parent
    configured_bundle = Path(bundle_dir) if bundle_dir is not None else None

    candidates = [
        configured_bundle,
        Path(frozen_root) if frozen_root else None,
        executable_root / "_internal",
        executable_root,
        module_root,
        Path(sys.prefix) / "share" / "hemafrag",
    ]
    return _unique_paths(path for path in candidates if path is not None)


def resolve_app_icon_path(
    *,
    platform_name: str | None = None,
    bundle_dir: str | os.PathLike[str] | None = None,
    search_roots: Iterable[str | os.PathLike[str]] | None = None,
) -> Path | None:
    """Resolve the best icon for the current platform without importing Qt."""
    platform_key = platform_name or sys.platform
    names = _ICON_NAMES.get(platform_key, _ICON_NAMES["linux"])
    roots = (
        _unique_paths(Path(root) for root in search_roots)
        if search_roots is not None
        else application_resource_roots(bundle_dir=bundle_dir)
    )
    for root in roots:
        for name in names:
            candidate = root / "assets" / name
            if candidate.is_file():
                return candidate
    return None


def load_application_icon(
    *,
    platform_name: str | None = None,
    bundle_dir: str | os.PathLike[str] | None = None,
    search_roots: Iterable[str | os.PathLike[str]] | None = None,
    icon_factory=None,
    log_message: Callable[[str], None] | None = None,
):
    """Load and validate the Qt application icon, returning ``None`` on error."""
    path = resolve_app_icon_path(
        platform_name=platform_name,
        bundle_dir=bundle_dir,
        search_roots=search_roots,
    )
    emit = log_message or _LOGGER.warning
    if path is None:
        roots = search_roots or application_resource_roots(bundle_dir=bundle_dir)
        emit(f"[WARN] HemaFrag app icon was not found in resource roots: {list(map(str, roots))}")
        return None

    if icon_factory is None:
        from PyQt6.QtGui import QIcon

        icon_factory = QIcon
    try:
        icon = icon_factory(str(path))
    except Exception as exc:
        emit(f"[WARN] HemaFrag app icon could not be loaded from {path}: {exc}")
        return None
    if bool(getattr(icon, "isNull", lambda: True)()):
        emit(f"[WARN] HemaFrag app icon is invalid or unsupported: {path}")
        return None
    return icon


def set_windows_app_user_model_id(
    *,
    platform_name: str | None = None,
    app_id: str = APP_BUNDLE_ID,
    setter: Callable[[str], object] | None = None,
    log_message: Callable[[str], None] | None = None,
) -> bool:
    """Give source-launched HemaFrag windows a stable Windows taskbar identity.

    This must run before ``QApplication`` is constructed.  It is a no-op on
    non-Windows platforms and never prevents application startup.
    """
    if (platform_name or sys.platform) != "win32":
        return False
    emit = log_message or _LOGGER.warning
    try:
        if setter is None:
            setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        result = setter(app_id)
        if result not in (None, 0):
            emit(f"[WARN] Windows rejected HemaFrag AppUserModelID {app_id!r}: code {result}")
            return False
        return True
    except Exception as exc:
        emit(f"[WARN] Could not set the HemaFrag Windows AppUserModelID: {exc}")
        return False
