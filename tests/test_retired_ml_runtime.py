from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from config import APP_SETTINGS


RETIRED_ML_COLUMNS = (
    "ClonalityMLSuggestion",
    "ClonalityMLConfidence",
    "ClonalityMLThreshold",
    "ClonalityMLReviewNeeded",
    "ClonalityMLEvidence",
    "ClonalityMLModelVersion",
    "ClonalityMLChannelResults",
)


def test_app_settings_normalizes_retired_ml_keys_from_legacy_yaml(tmp_path):
    settings_path = tmp_path / "legacy-settings.yaml"
    legacy_model = tmp_path / "legacy-model.joblib"
    legacy_model.write_bytes(b"historical model")
    legacy_learning_dir = tmp_path / "legacy-learning"
    legacy_learning_dir.mkdir()
    settings_path.write_text(
        f"""
analyses:
  clonality:
    interpretation:
      enabled: true
      model_path: {legacy_model.as_posix()}
      thresholds:
        FR1: 0.99
    learning:
      enabled: true
      output_dir: {legacy_learning_dir.as_posix()}
""".lstrip(),
        encoding="utf-8",
    )
    script = """
import config

profile = config.APP_SETTINGS["analyses"]["clonality"]
assert profile["interpretation"] == {"enabled": True}
assert "learning" not in profile
"""
    env = os.environ.copy()
    env["HEMAFRAG_SETTINGS_PATH"] = str(settings_path)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert legacy_model.read_bytes() == b"historical model"
    assert legacy_learning_dir.is_dir()


@pytest.mark.parametrize(
    ("settings_yaml", "expected_enabled"),
    (
        (
            """
analyses:
  clonality:
    interpretation:
      enabled: true
      model_path: C:/retired/models
      thresholds:
        FR1: 0.99
    learning:
      enabled: true
      output_dir: C:/retired/learning
""".lstrip(),
            True,
        ),
        (
            """
analyses:
  clonality:
    interpretation:
      enabled: false
""".lstrip(),
            False,
        ),
    ),
    ids=("legacy-yaml", "current-yaml"),
)
def test_app_startup_imports_without_retired_ml_or_labeling_modules(
    tmp_path,
    settings_yaml,
    expected_enabled,
):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(settings_yaml, encoding="utf-8")
    script = f"""
import importlib.abc
import sys

class RejectRetiredImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if (
            fullname.startswith("core.analyses.clonality.ml_")
            or fullname == "core.labeling"
            or fullname.startswith("core.labeling.")
        ):
            raise AssertionError(fullname)
        return None

sys.meta_path.insert(0, RejectRetiredImports())
import config
import core.analyses.clonality
import core.analyses.clonality.pipeline
import core.batch
import gui_qt.main_window
import qt_app

profile = config.APP_SETTINGS["analyses"]["clonality"]
assert profile["interpretation"] == {{"enabled": {expected_enabled!r}}}
assert "learning" not in profile

assert not any(
    name.startswith("core.analyses.clonality.ml_")
    or name == "core.labeling"
    or name.startswith("core.labeling.")
    for name in sys.modules
)
"""
    env = os.environ.copy()
    env["HEMAFRAG_SETTINGS_PATH"] = str(settings_path)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_pipeline_keeps_rule_result_without_cohort_or_ml_attachment(
    tmp_path,
    monkeypatch,
):
    import core.analyses.clonality.pipeline as pipeline

    original_settings = copy.deepcopy(APP_SETTINGS)
    profile = APP_SETTINGS.setdefault("analyses", {}).setdefault("clonality", {})
    profile["interpretation"] = {
        "enabled": True,
        "model_path": str(tmp_path / "missing-models"),
    }
    profile["learning"] = {
        "enabled": True,
        "output_dir": str(tmp_path / "legacy-learning"),
    }
    APP_SETTINGS.setdefault("engine", {})["use_rust"] = False
    rule_result = {
        "ClonalityInterpretationEnabled": True,
        "ClonalitySuggestion": "polyklonal",
        "ClonalityConfidence": 0.66,
        "ClonalityReviewNeeded": True,
        "ClonalityEvidence": "distributed_peak_profile",
        "ClonalityModelVersion": "clonality_rules_v1",
        "features": {"peak_count": 5},
    }
    entry = {
        "file_name": "26OUM00001_FR1__220526_A01_TEST.fsa",
        "dit": "26OUM00001",
        "assay": "FR1",
        "sample_kind": "patient",
        "source_run_dir": str(tmp_path / "run"),
        "clonality_interpretation": copy.deepcopy(rule_result),
        "ClonalitySuggestion": "polyklonal",
        "ClonalityConfidence": 0.66,
        "features": {"peak_count": 5},
    }
    monkeypatch.setattr(
        pipeline,
        "_analyze_single_file_with_timeout",
        lambda _path, _timeout: (entry, ""),
    )

    try:
        entries, skipped = pipeline._analyze_files(
            [tmp_path / "sample.fsa"],
            progress_callback=lambda _event: None,
        )
    finally:
        APP_SETTINGS.clear()
        APP_SETTINGS.update(original_settings)

    assert skipped == 0
    assert entries[0]["ClonalitySuggestion"] == "polyklonal"
    assert entries[0]["clonality_interpretation"] == rule_result
    assert not any(key.startswith("cohort_") for key in entries[0]["features"])
    assert not any(column in entries[0] for column in RETIRED_ML_COLUMNS)


def test_batch_ignores_legacy_learning_export_settings(tmp_path):
    import core.batch as batch

    original_settings = copy.deepcopy(APP_SETTINGS)
    learning_dir = tmp_path / "clonality_learning_annotations"
    profile = APP_SETTINGS.setdefault("analyses", {}).setdefault("clonality", {})
    APP_SETTINGS["active_analysis"] = "clonality"
    profile["interpretation"] = {
        "enabled": True,
        "model_path": str(tmp_path / "missing-models"),
    }
    profile["learning"] = {
        "enabled": True,
        "output_dir": str(learning_dir),
    }
    profile.setdefault("batch", {})["ladder_review_gate"] = {"enabled": False}
    rule_entry = {
        "file_name": "26OUM00001_FR1__220526_A01_TEST.fsa",
        "dit": "26OUM00001",
        "assay": "FR1",
        "ClonalitySuggestion": "polyklonal",
        "ClonalityConfidence": 0.66,
        "ClonalityReviewNeeded": True,
    }
    jobs = [
        {
            "name": "26OUM00001",
            "type": "pipeline",
            "path": tmp_path,
            "files": [tmp_path / "sample.fsa"],
        }
    ]

    try:
        with patch.object(
            batch,
            "run_pipeline_job_collect",
            return_value=[rule_entry],
        ):
            result = batch.run_batch_jobs(
                jobs=jobs,
                output_base=tmp_path / "output",
                out_folder_tmpl="ASSAY_REPORTS",
                outfile_html_tmpl="QC_REPORT_{name}.html",
                excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
                pipeline_scope="all",
                assay_filter="",
                aggregate_dit_reports=True,
                continue_on_error=False,
                aggregate_outdir_name="reports",
                max_workers=1,
                defer_tracking_workbook_refresh=True,
                defer_dit_html_reports=True,
                preserve_deferred_entries=True,
            )
    finally:
        APP_SETTINGS.clear()
        APP_SETTINGS.update(original_settings)

    assert result["completed_jobs"] == ["26OUM00001"]
    assert result["dit_report_entries"][0]["ClonalitySuggestion"] == "polyklonal"
    assert "learning_annotation_seed" not in result
    assert not learning_dir.exists()
    assert not any(
        column in result["dit_report_entries"][0]
        for column in RETIRED_ML_COLUMNS
    )
