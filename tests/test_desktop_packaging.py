from __future__ import annotations

from pathlib import Path

import build_qt
import pytest


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


def test_desktop_bundle_includes_the_repository_and_upstream_notices():
    args = build_qt._build_pyinstaller_args(include_rust_engine=False)
    for relative in ("THIRD_PARTY_NOTICES.md", "LICENSES"):
        assert any(
            arg.startswith(f"--add-data={PROJECT_ROOT / relative}")
            for arg in args
        )


def test_python_shortcut_uses_the_application_assets():
    shortcut = (PROJECT_ROOT / "packaging" / "create_windows_shortcut.ps1").read_text(encoding="utf-8")
    assert "app_icon.ico" in shortcut
    assert "qt_app.py" in shortcut
    assert ".exe" not in shortcut.lower()


def test_build_rejects_unsupported_platforms_before_running_tools(monkeypatch):
    monkeypatch.setattr(build_qt.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="requires Windows"):
        build_qt.build_app()


def test_build_does_not_continue_when_rust_artifact_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(build_qt, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build_qt.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(FileNotFoundError, match="Rust build did not produce"):
        build_qt._build_pyinstaller_args()
