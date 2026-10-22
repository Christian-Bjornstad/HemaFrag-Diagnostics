"""Verify the shipped Python wheel, including resources outside Python modules."""
from __future__ import annotations

import subprocess
import sys
import zipfile
import os
from pathlib import Path


def test_built_wheel_imports_and_exposes_notices_outside_source_tree(tmp_path):
    project = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel", str(project), "--no-deps",
            "--no-build-isolation", "--wheel-dir", str(tmp_path),
        ],
        check=True, capture_output=True, text=True, timeout=120,
    )
    wheel = next(tmp_path.glob("hemafrag_diagnostics-*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)

    # Exclude the checkout/cwd without hiding dependencies in the user's site.
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import hemafrag_diagnostics
from app_meta import APP_VERSION
from gui_qt.about_content import THIRD_PARTY_NOTICE_PATH, UPSTREAM_LICENSE_PATH
from app_resources import resolve_app_icon_path
import gui_qt.main_window
assert Path(hemafrag_diagnostics.__file__).is_relative_to(Path(sys.argv[1]))
assert hemafrag_diagnostics.__version__ == APP_VERSION
assert THIRD_PARTY_NOTICE_PATH.is_file(), THIRD_PARTY_NOTICE_PATH
assert 'MIT License' in UPSTREAM_LICENSE_PATH.read_text(encoding='utf-8')
assert resolve_app_icon_path().is_file()
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-P", "-c", code, str(installed)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
