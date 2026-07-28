"""Freeze reproducible HemaFrag reference outputs and timings.

Scenario outputs belong in ignored ``validation_outputs/`` or ``local_triage/``.
The runner records file hashes and compact result summaries, but never copies raw
FSA files unless an explicit future scenario implementation requests it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np


MANIFEST_VERSION = "hemafrag_plan13_benchmark_v1"
DEFAULT_TIMEOUT_SECONDS = 3600.0


def _ensure_repo_on_path(repo_root: Path) -> None:
    repo_text = str(repo_root.resolve())
    if repo_text not in sys.path:
        sys.path.insert(0, repo_text)


def _expand_text(value: object) -> str:
    return os.path.expandvars(os.path.expanduser(str(value or "")))


def _resolve_path(value: object, *, base_dir: Path) -> Path:
    path = Path(_expand_text(value))
    return path if path.is_absolute() else (base_dir / path).resolve()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_identity(payload: object) -> object:
    if isinstance(payload, dict):
        return {
            key: _result_identity(value)
            for key, value in payload.items()
            if key not in {"stage_timings"}
        }
    if isinstance(payload, list):
        return [_result_identity(value) for value in payload]
    return payload


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _runtime_metadata(repo_root: Path) -> dict[str, object]:
    try:
        from app_meta import APP_VERSION
    except Exception:
        APP_VERSION = "unknown"
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        commit = ""
    try:
        from core.rust_bridge import (
            _in_process_native_wheel_is_available,
            _resolve_cli_bin,
        )

        cli_path = _resolve_cli_bin()
        rust_engine = {
            "native_wheel_available": bool(_in_process_native_wheel_is_available()),
            "cli_available": cli_path is not None,
            "cli_sha256": (
                _sha256_file(cli_path) if cli_path is not None and cli_path.is_file() else None
            ),
        }
    except Exception as exc:
        rust_engine = {
            "native_wheel_available": False,
            "cli_available": False,
            "probe_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "app_version": str(APP_VERSION),
        "git_commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "rust_engine": rust_engine,
    }


def _compact_entry(entry: dict[str, Any] | None) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {"available": False}
    fsa = entry.get("fsa")
    return {
        "available": True,
        "file_name": str(
            entry.get("file_name")
            or getattr(fsa, "file_name", "")
            or Path(str(entry.get("original_file_path") or "")).name
        ),
        "assay": str(entry.get("assay") or entry.get("Assay") or ""),
        "ladder": str(entry.get("ladder") or entry.get("InternalLadder") or ""),
        "ladder_qc_status": str(entry.get("ladder_qc_status") or ""),
        "ladder_fit_strategy": str(entry.get("ladder_fit_strategy") or ""),
        "ladder_review_required": bool(entry.get("ladder_review_required")),
        "ladder_r2": entry.get("ladder_r2"),
        "ladder_linear_r2": entry.get("ladder_linear_r2"),
        "ladder_linear_max_residual_bp": entry.get("ladder_linear_max_residual_bp"),
        "ladder_linear_mean_residual_bp": entry.get("ladder_linear_mean_residual_bp"),
        "peak_qc_status": str(entry.get("peak_qc_status") or ""),
        "interpretation": str(entry.get("ClonalityCall") or entry.get("interpretation") or ""),
    }


class _StageRecorder:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self._active: dict[str, tuple[str, float]] = {}
        self._durations: dict[str, list[float]] = defaultdict(list)

    def __call__(self, event: dict[str, object]) -> None:
        now = time.perf_counter()
        raw_job = str(event.get("job_name") or "")
        job_key = hashlib.sha256(raw_job.encode("utf-8")).hexdigest()[:12]
        phase = str(event.get("phase") or "unknown")
        previous = self._active.get(job_key)
        if previous and previous[0] != phase:
            self._durations[previous[0]].append(max(0.0, now - previous[1]))
        if previous is None or previous[0] != phase:
            self._active[job_key] = (phase, now)
        if phase in {"completed", "failed"}:
            current = self._active.pop(job_key, None)
            if current:
                self._durations[current[0]].append(max(0.0, now - current[1]))

    def finish(self) -> dict[str, object]:
        now = time.perf_counter()
        for phase, started in self._active.values():
            self._durations[phase].append(max(0.0, now - started))
        self._active.clear()
        return {
            phase: {
                "count": len(values),
                "total_seconds": round(sum(values), 6),
                "median_seconds": round(float(statistics.median(values)), 6),
                "p95_seconds": round(float(_percentile(values, 0.95) or 0.0), 6),
            }
            for phase, values in sorted(self._durations.items())
        }


def _run_command_scenario(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    scenario_dir: Path,
    scenario_file_dir: Path,
) -> dict[str, object]:
    del scenario_dir, scenario_file_dir
    argv = [_expand_text(value) for value in scenario.get("argv") or []]
    if not argv:
        raise ValueError("Command scenario requires a non-empty argv list.")
    if Path(argv[0]).name.lower() in {"python", "python3", "python.exe"}:
        argv[0] = sys.executable
    timeout = float(scenario.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    completed = subprocess.run(
        argv,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    result: dict[str, object] = {
        "return_code": int(completed.returncode),
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
    }
    if completed.returncode:
        result["stderr_tail"] = completed.stderr[-2000:]
        raise RuntimeError(f"Command exited {completed.returncode}: {result['stderr_tail']}")
    return result


def _run_clonality_file_scenario(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    scenario_dir: Path,
    scenario_file_dir: Path,
) -> dict[str, object]:
    del repo_root, scenario_dir
    input_file = _resolve_path(scenario.get("input_file"), base_dir=scenario_file_dir)
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    from config import APP_SETTINGS
    from core.analyses.clonality import pipeline

    previous = APP_SETTINGS.get("active_analysis")
    APP_SETTINGS["active_analysis"] = "clonality"
    try:
        entry = pipeline._analyze_single_file(input_file)
    finally:
        APP_SETTINGS["active_analysis"] = previous
    sizing_shadow: dict[str, object] | None = None
    ladder_confidence_shadow: dict[str, object] | None = None
    artifact_shadow: dict[str, object] | None = None
    baseline_detection_shadow: dict[str, object] | None = None
    if isinstance(entry, dict) and entry.get("fsa") is not None:
        fsa = entry["fsa"]
        anchor_times = getattr(fsa, "best_size_standard", None)
        anchor_sizes = getattr(fsa, "expected_ladder_steps", None)
        if anchor_sizes is None or len(anchor_sizes) == 0:
            anchor_sizes = getattr(fsa, "ladder_steps", None)
        if anchor_times is not None and anchor_sizes is not None:
            try:
                from core.precision import evaluate_anchor_leave_one_out

                sizing_shadow = evaluate_anchor_leave_one_out(
                    anchor_times,
                    anchor_sizes,
                )
            except ValueError as exc:
                sizing_shadow = {
                    "evaluation": "ladder_anchor_leave_one_out_proxy",
                    "promotion_eligible": False,
                    "unavailable_reason": str(exc),
                }
        from core.precision import (
            evaluate_artifact_shadow,
            evaluate_baseline_detection_shadow,
            evaluate_ladder_confidence_shadow,
        )

        try:
            ladder_confidence_shadow = evaluate_ladder_confidence_shadow(fsa)
        except ValueError as exc:
            ladder_confidence_shadow = {
                "evaluation": "bounded_local_sequence_and_threshold_perturbation_proxy",
                "promotion_eligible": False,
                "unavailable_reason": str(exc),
            }
        try:
            artifact_shadow = evaluate_artifact_shadow(fsa)
        except ValueError as exc:
            artifact_shadow = {
                "evaluation": "raw_trace_artifact_candidate_screen",
                "promotion_eligible": False,
                "unavailable_reason": str(exc),
            }
        try:
            baseline_detection_shadow = evaluate_baseline_detection_shadow(
                np.asarray(getattr(fsa, "sample_data", []), dtype=float),
                min_height=max(
                    1.0,
                    float(getattr(fsa, "min_sample_peak_height", 50.0) or 50.0),
                ),
                min_distance=max(
                    1,
                    int(getattr(fsa, "min_distance_between_peaks", 5) or 5),
                ),
            )
        except ValueError as exc:
            baseline_detection_shadow = {
                "evaluation": "current_preprocessing_relative_bakeoff",
                "promotion_eligible": False,
                "unavailable_reason": str(exc),
            }
    return {
        "input": {
            "file_name": input_file.name,
            "size_bytes": int(input_file.stat().st_size),
            "sha256": _sha256_file(input_file),
        },
        "entry": _compact_entry(entry),
        "sizing_shadow": sizing_shadow,
        "ladder_confidence_shadow": ladder_confidence_shadow,
        "artifact_shadow": artifact_shadow,
        "baseline_detection_shadow": baseline_detection_shadow,
    }


def _run_combined_qc_dit_scenario(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    scenario_dir: Path,
    scenario_file_dir: Path,
) -> dict[str, object]:
    del repo_root
    source_dir = _resolve_path(scenario.get("source_dir"), base_dir=scenario_file_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)
    patient_prefixes = tuple(str(value) for value in scenario.get("patient_prefixes") or [])
    control_prefixes = tuple(str(value) for value in scenario.get("control_prefixes") or [])
    prefixes = patient_prefixes + control_prefixes
    candidates = sorted(source_dir.rglob("*.fsa"))
    selected = [path for path in candidates if not prefixes or path.name.startswith(prefixes)]
    if not selected:
        raise FileNotFoundError(f"No matching FSA files in {source_dir}")

    from config import APP_SETTINGS
    from core.batch import generate_jobs, run_batch_jobs

    previous = APP_SETTINGS.get("active_analysis")
    APP_SETTINGS["active_analysis"] = "clonality"
    recorder = _StageRecorder()
    output_root = scenario_dir / str(scenario.get("output_folder_name") or "combined_qc_dit")
    try:
        jobs = generate_jobs(
            selected,
            aggregate_patients=True,
            patient_regex=str(scenario.get("patient_regex") or r"\d{2}OUM\d{5}"),
        )
        result = run_batch_jobs(
            jobs=jobs,
            output_base=output_root,
            out_folder_tmpl="ASSAY_REPORTS",
            outfile_html_tmpl="QC_REPORT_{name}.html",
            excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
            pipeline_scope="all",
            assay_filter="",
            aggregate_dit_reports=True,
            continue_on_error=True,
            progress_callback=recorder,
        )
    finally:
        APP_SETTINGS["active_analysis"] = previous

    gate = result.get("ladder_review_gate") or {}
    return {
        "inputs": {
            "count": len(selected),
            "content_set_sha256": _stable_fingerprint(
                [{"name": path.name, "sha256": _sha256_file(path)} for path in selected]
            ),
        },
        "jobs": len(jobs),
        "completed_jobs": len(result.get("completed_jobs") or []),
        "failed_jobs": len(result.get("failed_jobs") or []),
        "dit_entry_count": len(result.get("dit_report_entries") or []),
        "qc_entry_count": len(result.get("qc_report_entries") or []),
        "review_case_count": int(gate.get("review_case_count") or 0),
        "stage_timings": recorder.finish(),
    }


def _run_flt3_rox500_qc_scenario(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    scenario_dir: Path,
    scenario_file_dir: Path,
) -> dict[str, object]:
    del repo_root
    source_dir = _resolve_path(scenario.get("source_dir"), base_dir=scenario_file_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)
    from scripts.run_flt3_rox500_qc_all_injections import run_qc

    result = run_qc(
        source_dir,
        scenario_dir / "flt3_rox500_qc",
        years=[str(value) for value in scenario.get("years") or []] or None,
        require_run_name_contains=str(scenario.get("require_run_name_contains") or ""),
        exclude_run_name_contains=str(scenario.get("exclude_run_name_contains") or ""),
        limit=int(scenario.get("limit") or 0),
        workers=int(scenario.get("workers") or 1),
    )
    summary = dict(result.get("summary") or {})
    return {
        key: summary.get(key)
        for key in (
            "size_standard",
            "internal_ladder",
            "preferred_size_standard_channel",
            "size_standard_channel_counts",
            "raw_fsa_count",
            "analyzed_fsa_count",
            "review_row_count",
            "skipped_count",
            "qc_status_counts",
            "ladder_qc_counts",
            "peak_qc_counts",
            "rust_engine_stats",
        )
    }


SCENARIO_RUNNERS: dict[str, Callable[..., dict[str, object]]] = {
    "command": _run_command_scenario,
    "clonality_file_analysis": _run_clonality_file_scenario,
    "combined_qc_dit": _run_combined_qc_dit_scenario,
    "flt3_rox500_qc": _run_flt3_rox500_qc_scenario,
}


def _run_once(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    scenario_dir: Path,
    scenario_file_dir: Path,
) -> dict[str, object]:
    kind = str(scenario.get("kind") or "")
    runner = SCENARIO_RUNNERS.get(kind)
    if runner is None:
        raise ValueError(f"Unsupported scenario kind: {kind or '<empty>'}")
    rss_before = _rss_bytes()
    started = time.perf_counter()
    result = runner(
        scenario,
        repo_root=repo_root,
        scenario_dir=scenario_dir,
        scenario_file_dir=scenario_file_dir,
    )
    elapsed = time.perf_counter() - started
    rss_after = _rss_bytes()
    return {
        "status": "ok",
        "duration_seconds": round(elapsed, 6),
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_growth_bytes": (
            None if rss_before is None or rss_after is None else int(rss_after - rss_before)
        ),
        "result": result,
        "result_fingerprint": _stable_fingerprint(_result_identity(result)),
    }


def freeze_scenarios(
    scenario_file: Path,
    output_dir: Path,
    *,
    repo_root: Path,
    repeats: int = 1,
    strict_missing: bool = False,
) -> tuple[dict[str, object], int]:
    repo_root = repo_root.resolve()
    _ensure_repo_on_path(repo_root)
    scenario_file = scenario_file.resolve()
    payload = json.loads(scenario_file.read_text(encoding="utf-8"))
    scenarios = list(payload.get("scenarios") or [])
    if not scenarios:
        raise ValueError("Scenario file contains no scenarios.")
    repeats = max(1, int(repeats))
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "schema_version": MANIFEST_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenario_file_sha256": _sha256_file(scenario_file),
        "runtime": _runtime_metadata(repo_root),
        "repeats": repeats,
        "scenarios": [],
    }
    exit_code = 0
    for index, scenario in enumerate(scenarios, start=1):
        name = str(scenario.get("name") or f"scenario_{index}")
        safe_name = "".join(char if char.isalnum() or char in "-_." else "_" for char in name)
        scenario_dir = output_dir / f"{index:03d}_{safe_name}"
        scenario_dir.mkdir(parents=True, exist_ok=True)
        runs: list[dict[str, object]] = []
        for repeat_index in range(1, repeats + 1):
            try:
                run = _run_once(
                    scenario,
                    repo_root=repo_root,
                    scenario_dir=scenario_dir / f"run_{repeat_index:03d}",
                    scenario_file_dir=scenario_file.parent,
                )
            except FileNotFoundError as exc:
                run = {"status": "unavailable", "reason": str(exc)}
                if strict_missing:
                    exit_code = 2
            except Exception as exc:
                run = {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                exit_code = 1
            runs.append(run)
            if run["status"] != "ok":
                break

        durations = [
            float(run["duration_seconds"])
            for run in runs
            if run.get("status") == "ok" and run.get("duration_seconds") is not None
        ]
        fingerprints = [
            str(run["result_fingerprint"])
            for run in runs
            if run.get("status") == "ok" and run.get("result_fingerprint")
        ]
        scenario_summary = {
            "name": name,
            "kind": str(scenario.get("kind") or ""),
            "status": runs[-1]["status"] if runs else "error",
            "runs": runs,
            "timing": {
                "count": len(durations),
                "min_seconds": min(durations) if durations else None,
                "median_seconds": statistics.median(durations) if durations else None,
                "p95_seconds": _percentile(durations, 0.95),
                "max_seconds": max(durations) if durations else None,
            },
            "deterministic": bool(fingerprints) and len(set(fingerprints)) == 1,
        }
        _atomic_write_json(scenario_dir / "scenario_summary.json", scenario_summary)
        manifest["scenarios"].append(scenario_summary)

    _atomic_write_json(output_dir / "baseline_manifest.json", manifest)
    return manifest, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--strict-missing", action="store_true")
    args = parser.parse_args(argv)
    manifest, exit_code = freeze_scenarios(
        args.scenario_file,
        args.output_dir,
        repo_root=args.repo_root.resolve(),
        repeats=args.repeats,
        strict_missing=args.strict_missing,
    )
    statuses = [
        f"{scenario['name']}={scenario['status']}"
        for scenario in manifest.get("scenarios", [])
    ]
    print(f"Wrote {args.output_dir / 'baseline_manifest.json'}")
    print("Scenarios: " + ", ".join(statuses))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
