from __future__ import annotations

import copy
from unittest.mock import patch

import config


def test_save_load_round_trip(tmp_path):
    target = tmp_path / "settings.yaml"
    settings = copy.deepcopy(config.DEFAULT_SETTINGS)
    settings["general"]["author"] = "Test author"
    assert config.save_settings(settings, target) is True
    assert config.LAST_SETTINGS_SAVE_ERROR is None
    assert config.load_settings(target, env={"HEMAFRAG_UNUSED_TEST": "1"})["general"]["author"] == "Test author"
    assert list(tmp_path.iterdir()) == [target]


def test_replace_failure_preserves_old_yaml_and_removes_temp(tmp_path):
    target = tmp_path / "settings.yaml"
    target.write_text("general:\n  author: Previous\n", encoding="utf-8")
    settings = copy.deepcopy(config.DEFAULT_SETTINGS)
    settings["general"]["author"] = "New"
    with patch.object(config.os, "replace", side_effect=PermissionError("denied")):
        assert config.save_settings(settings, target) is False
    assert "Previous" in target.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [target]
    assert "denied" in config.LAST_SETTINGS_SAVE_ERROR


def test_write_failure_preserves_old_yaml_and_removes_temp(tmp_path):
    target = tmp_path / "settings.yaml"
    target.write_text("general:\n  author: Previous\n", encoding="utf-8")
    with patch.object(config.yaml, "safe_dump", side_effect=OSError("write failed")):
        assert config.save_settings(copy.deepcopy(config.DEFAULT_SETTINGS), target) is False
    assert "Previous" in target.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [target]
