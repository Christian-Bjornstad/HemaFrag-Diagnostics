from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

from app_meta import APP_BUNDLE_ID
from app_resources import (
    load_application_icon,
    resolve_app_icon_path,
    set_windows_app_user_model_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_platform_icon_resolution_prefers_native_formats(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("app_icon.png", "app_icon.ico", "app_icon.icns"):
        (assets / name).write_bytes(b"placeholder")

    assert resolve_app_icon_path(platform_name="win32", search_roots=[tmp_path]).name == "app_icon.ico"
    assert resolve_app_icon_path(platform_name="darwin", search_roots=[tmp_path]).name == "app_icon.icns"
    assert resolve_app_icon_path(platform_name="linux", search_roots=[tmp_path]).name == "app_icon.png"


def test_checked_in_icon_assets_are_valid_and_windows_icon_is_multiresolution():
    expected = {
        "app_icon.png": "PNG",
        "app_icon_transparent.png": "PNG",
        "app_icon.ico": "ICO",
        "app_icon.icns": "ICNS",
    }
    for name, image_format in expected.items():
        with Image.open(PROJECT_ROOT / "assets" / name) as image:
            assert image.format == image_format
            assert image.width >= 256
            assert image.height >= 256

    with Image.open(PROJECT_ROOT / "assets" / "app_icon.ico") as image:
        assert {16, 32, 48, 256}.issubset({width for width, _height in image.ico.sizes()})


def test_application_icon_loader_rejects_a_null_icon(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app_icon.png").write_bytes(b"not-an-image")
    messages: list[str] = []

    class NullIcon:
        def __init__(self, _path):
            pass

        def isNull(self):
            return True

    assert load_application_icon(
        platform_name="linux",
        search_roots=[tmp_path],
        icon_factory=NullIcon,
        log_message=messages.append,
    ) is None
    assert any("invalid or unsupported" in message for message in messages)


def test_checked_in_qt_icon_loads_successfully():
    code = (
        "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; "
        "from PyQt6.QtWidgets import QApplication; app=QApplication([]); "
        "from app_resources import load_application_icon; "
        "icon=load_application_icon(platform_name='win32', search_roots=['.']); "
        "print(icon is not None and not icon.isNull())"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert completed.stdout.strip().splitlines()[-1] == "True"


def test_windows_app_id_is_set_before_qt_through_injectable_setter():
    calls: list[str] = []
    assert set_windows_app_user_model_id(
        platform_name="win32",
        setter=lambda value: calls.append(value) or 0,
    )
    assert calls == [APP_BUNDLE_ID]
    assert not set_windows_app_user_model_id(
        platform_name="linux",
        setter=lambda _value: (_ for _ in ()).throw(AssertionError("must not run")),
    )


def test_main_window_import_does_not_eagerly_load_unrouted_flt3_validation_tab():
    code = (
        "import os,sys; "
        "os.environ['QT_QPA_PLATFORM']='offscreen'; "
        "import gui_qt.main_window; "
        "print('gui_qt.tabs.tab_flt3_validation' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert completed.stdout.strip().splitlines()[-1] == "False"
