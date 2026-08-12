from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.freeze_v2_baseline import (
    MANIFEST_VERSION,
    _percentile,
    _result_identity,
    freeze_scenarios,
)


def _write_scenarios(path: Path, scenarios: list[dict]) -> Path:
    path.write_text(json.dumps({"scenarios": scenarios}), encoding="utf-8")
    return path


def test_percentile_interpolates_small_samples():
    assert _percentile([], 0.95) is None
    assert _percentile([2.0], 0.95) == 2.0
    assert _percentile([1.0, 3.0], 0.5) == 2.0


def test_result_identity_excludes_performance_telemetry():
    first = {"count": 3, "stage_timings": {"analyze": {"total_seconds": 1.2}}}
    second = {"count": 3, "stage_timings": {"analyze": {"total_seconds": 8.4}}}

    assert _result_identity(first) == _result_identity(second) == {"count": 3}


def test_command_scenario_freezes_repeatable_results(tmp_path):
    scenario_file = _write_scenarios(
        tmp_path / "scenarios.json",
        [
            {
                "name": "portable-command",
                "kind": "command",
                "argv": [sys.executable, "-c", "print('stable')"],
            }
        ],
    )
    output_dir = tmp_path / "output"

    manifest, exit_code = freeze_scenarios(
        scenario_file,
        output_dir,
        repo_root=Path(__file__).resolve().parents[1],
        repeats=2,
    )

    assert exit_code == 0
    assert manifest["schema_version"] == MANIFEST_VERSION
    assert "rust_engine" in manifest["runtime"]
    assert manifest["scenarios"][0]["status"] == "ok"
    assert manifest["scenarios"][0]["deterministic"] is True
    assert manifest["scenarios"][0]["timing"]["count"] == 2
    written = json.loads((output_dir / "baseline_manifest.json").read_text(encoding="utf-8"))
    assert written["scenario_file_sha256"] == manifest["scenario_file_sha256"]


def test_missing_real_data_is_inspectable_without_failing_by_default(tmp_path):
    scenario_file = _write_scenarios(
        tmp_path / "scenarios.json",
        [
            {
                "name": "missing-fsa",
                "kind": "clonality_file_analysis",
                "input_file": str(tmp_path / "missing.fsa"),
            }
        ],
    )

    manifest, exit_code = freeze_scenarios(
        scenario_file,
        tmp_path / "output",
        repo_root=Path(__file__).resolve().parents[1],
    )

    assert exit_code == 0
    assert manifest["scenarios"][0]["status"] == "unavailable"
    assert "missing.fsa" in manifest["scenarios"][0]["runs"][0]["reason"]


def test_strict_missing_returns_nonzero(tmp_path):
    scenario_file = _write_scenarios(
        tmp_path / "scenarios.json",
        [
            {
                "name": "missing-fsa",
                "kind": "clonality_file_analysis",
                "input_file": str(tmp_path / "missing.fsa"),
            }
        ],
    )

    _, exit_code = freeze_scenarios(
        scenario_file,
        tmp_path / "output",
        repo_root=Path(__file__).resolve().parents[1],
        strict_missing=True,
    )

    assert exit_code == 2


def test_missing_flt3_root_is_reported_as_unavailable(tmp_path):
    scenario_file = _write_scenarios(
        tmp_path / "scenarios.json",
        [
            {
                "name": "missing-flt3",
                "kind": "flt3_rox500_qc",
                "source_dir": str(tmp_path / "missing"),
            }
        ],
    )

    manifest, exit_code = freeze_scenarios(
        scenario_file,
        tmp_path / "output",
        repo_root=Path(__file__).resolve().parents[1],
    )

    assert exit_code == 0
    assert manifest["scenarios"][0]["status"] == "unavailable"


def test_cli_file_invocation_can_import_application_modules(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    scenario_file = _write_scenarios(
        tmp_path / "scenarios.json",
        [
            {
                "name": "portable-command",
                "kind": "command",
                "argv": [sys.executable, "-c", "print('stable')"],
            }
        ],
    )
    output_dir = tmp_path / "output"

    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "freeze_v2_baseline.py"),
            "--scenario-file",
            str(scenario_file),
            "--output-dir",
            str(output_dir),
            "--repo-root",
            str(repo_root),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(
        (output_dir / "baseline_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["runtime"]["app_version"] != "unknown"
    assert manifest["scenarios"][0]["status"] == "ok"
