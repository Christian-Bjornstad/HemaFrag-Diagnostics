"""
Runtime defaults for packaged HemaFrag desktop builds.
"""
from __future__ import annotations

import os
import sys


class _NullTextStream:
    encoding = "utf-8"

    def write(self, _text):
        return 0

    def flush(self):
        return None

    def isatty(self):
        return False

    def reconfigure(self, **_kwargs):
        return None


if sys.stdout is None:
    sys.stdout = _NullTextStream()
if sys.stderr is None:
    sys.stderr = _NullTextStream()

# Packaged desktop builds should not start the legacy embedded Panel server by default.
os.environ.setdefault("HEMAFRAG_ENABLE_LEGACY_PANEL", "0")
os.environ.setdefault("FRAGGLER_ENABLE_LEGACY_PANEL", os.environ["HEMAFRAG_ENABLE_LEGACY_PANEL"])
# Packaged desktop builds should stay single-process to avoid GUI child launches.
os.environ.setdefault("FRAGGLER_DISABLE_MULTIPROCESSING", "1")

# Fedora 35 / offline Linux target: prefer X11/xcb for stable Qt startup.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
