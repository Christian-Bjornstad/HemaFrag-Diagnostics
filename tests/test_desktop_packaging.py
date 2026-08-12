from __future__ import annotations

from pathlib import Path

import build_qt


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generated_pyinstaller_spec_lives_under_ignored_build_directory():
    args = build_qt._build_pyinstaller_args(include_rust_engine=False)
    assert f"--specpath={build_qt.SPEC_DIR}" in args
    assert build_qt.PROJECT_ROOT in build_qt.SPEC_DIR.parents
    assert "build" in build_qt.SPEC_DIR.parts
    assert not (PROJECT_ROOT / "HemaFrag.spec").exists()


def test_windows_build_uses_checked_in_multiresolution_ico():
    args = build_qt._build_pyinstaller_args(include_rust_engine=False)
    if build_qt.sys.platform == "win32":
        assert f"--icon={PROJECT_ROOT / 'assets' / 'app_icon.ico'}" in args
        assert not any(".icns" in arg for arg in args)


def test_data_sources_remain_rooted_when_specs_are_generated_under_build():
    args = build_qt._build_pyinstaller_args(include_rust_engine=False)
    assert any(str(PROJECT_ROOT / "assets") in arg and arg.startswith("--add-data=") for arg in args)
    assert any(str(PROJECT_ROOT / "app.py") in arg and arg.startswith("--add-data=") for arg in args)


def test_linux_desktop_entry_and_python_shortcut_assets_are_portable():
    desktop = (PROJECT_ROOT / "packaging" / "linux" / "hemafrag.desktop").read_text(encoding="utf-8")
    assert "Name=HemaFrag Diagnostics" in desktop
    assert "Exec=HemaFrag" in desktop
    assert "Icon=hemafrag" in desktop
    assert "Terminal=false" in desktop

    shortcut = (PROJECT_ROOT / "packaging" / "create_windows_shortcut.ps1").read_text(encoding="utf-8")
    assert "app_icon.ico" in shortcut
    assert "qt_app.py" in shortcut
    assert ".exe" not in shortcut.lower()
