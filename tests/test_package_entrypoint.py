from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import ModuleType


def test_packaged_entrypoint_delegates_to_existing_qt_main(monkeypatch) -> None:
    called: list[bool] = []
    qt_app = ModuleType("qt_app")
    qt_app.main = lambda: called.append(True)
    monkeypatch.setitem(sys.modules, "qt_app", qt_app)

    from hemafrag_diagnostics.__main__ import main

    main()

    assert called == [True]


def test_package_discovery_excludes_the_nested_rust_workspace() -> None:
    configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "fraggler-v2*" in configuration["tool"]["setuptools"]["packages"][
        "find"
    ]["exclude"]
