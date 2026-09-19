"""Keep tests and their subprocesses away from operator configuration/data."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_runtime = TemporaryDirectory(prefix="hemafrag-tests-")
_runtime_path = Path(_runtime.name)
_previous_env = {
    name: os.environ.get(name)
    for name in ("HEMAFRAG_SETTINGS_PATH", "HEMAFRAG_LADDER_ADJUSTMENT_DB")
}
os.environ["HEMAFRAG_SETTINGS_PATH"] = str(_runtime_path / "settings.yaml")
os.environ["HEMAFRAG_LADDER_ADJUSTMENT_DB"] = str(_runtime_path / "ladder.sqlite3")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_operator_state(monkeypatch, tmp_path):
    import config

    previous = copy.deepcopy(config.APP_SETTINGS)
    config.APP_SETTINGS.clear()
    config.APP_SETTINGS.update(copy.deepcopy(config.DEFAULT_SETTINGS))
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.yaml")
    monkeypatch.setattr(config, "LEGACY_SETTINGS_PATH", tmp_path / "legacy.yaml")
    monkeypatch.setenv("HEMAFRAG_SETTINGS_PATH", str(tmp_path / "settings.yaml"))
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(tmp_path / "ladder.sqlite3"))
    yield
    config.APP_SETTINGS.clear()
    config.APP_SETTINGS.update(previous)


def pytest_unconfigure(config):
    for name, previous in _previous_env.items():
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
    _runtime.cleanup()
