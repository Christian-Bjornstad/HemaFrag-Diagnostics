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


def test_legacy_ml_settings_are_removed_without_losing_active_profiles_or_files(tmp_path):
    target = tmp_path / "settings.yaml"
    legacy_model = tmp_path / "clonality-model.joblib"
    legacy_model.write_bytes(b"historical model")
    legacy_learning_dir = tmp_path / "learning-annotations"
    legacy_learning_dir.mkdir()
    legacy_annotation = legacy_learning_dir / "annotation.json"
    legacy_annotation.write_text("{}", encoding="utf-8")
    target.write_text(
        f"""
active_analysis: clonality
analyses:
  clonality:
    batch:
      tracking_excel_path: retained-clonality.xlsx
    pipeline:
      file_timeout_seconds: 321
    interpretation:
      enabled: true
      model_path: {legacy_model.as_posix()}
      thresholds:
        FR1: 0.99
    learning:
      enabled: true
      output_dir: {legacy_learning_dir.as_posix()}
  flt3:
    batch:
      tracking_excel_path: retained-flt3.xlsx
  general:
    pipeline:
      profile_id: retained-general-profile
""".lstrip(),
        encoding="utf-8",
    )

    loaded = config.load_settings(target, env={"HEMAFRAG_UNUSED_TEST": "1"})
    clonality = loaded["analyses"]["clonality"]

    assert clonality["interpretation"] == {"enabled": True}
    assert "learning" not in clonality
    assert clonality["batch"]["tracking_excel_path"] == "retained-clonality.xlsx"
    assert clonality["pipeline"]["file_timeout_seconds"] == 321
    assert loaded["analyses"]["flt3"]["batch"]["tracking_excel_path"] == "retained-flt3.xlsx"
    assert loaded["analyses"]["general"]["pipeline"]["profile_id"] == "retained-general-profile"
    assert legacy_model.read_bytes() == b"historical model"
    assert legacy_annotation.read_text(encoding="utf-8") == "{}"

    assert config.save_settings(loaded, target) is True
    persisted = config.yaml.safe_load(target.read_text(encoding="utf-8"))
    persisted_clonality = persisted["analyses"]["clonality"]
    assert persisted_clonality["interpretation"] == {"enabled": True}
    assert "learning" not in persisted_clonality
    assert legacy_model.read_bytes() == b"historical model"
    assert legacy_annotation.read_text(encoding="utf-8") == "{}"
