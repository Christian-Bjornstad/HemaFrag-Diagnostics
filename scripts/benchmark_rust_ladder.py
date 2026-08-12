#!/usr/bin/env python3
"""Benchmark deterministic Rust ladder fitting from an explicit FSA manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.research.ladder.contracts import LadderOutcome
from core.research.ladder.diagnostics import classify_ladder_outcome


DEFAULT_CLI = REPO_ROOT / "fraggler-v2" / "target" / "release" / "fraggler-cli.exe"
BENCHMARK_SCHEMA = "hemafrag_rust_ladder_benchmark_v1"
HUMAN_DEPENDENT_OUTCOMES = {
    LadderOutcome.FIT_ACCEPTED_BUT_WRONG.value,
    LadderOutcome.FIT_CORRECT_REVIEW_ONLY.value,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _valid_sha256(value: Any) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in text
    )


def _gold_approval_valid(entry: dict[str, Any]) -> bool:
    return bool(
        _valid_sha256(entry.get("content_sha256"))
        and (
            "approved_for_fit_gold" not in entry
            or _truthy(entry.get("approved_for_fit_gold"))
        )
        and _truthy(entry.get("gold_eligible"))
        and _truthy(entry.get("review_approved"))
        and str(entry.get("review_label") or "").strip().casefold()
        in {"manual_adjusted", "reviewed_no_change"}
        and str(entry.get("reviewed_at_utc") or "").strip()
        and str(entry.get("reviewed_by") or "").strip()
        and str(entry.get("analysis_id") or "").strip().casefold() == "clonality"
        and str(entry.get("identity_key") or "").strip()
        and str(entry.get("sample_kind") or "").strip().casefold() == "patient"
    )


def _manifest_records(manifest: object) -> object:
    if not isinstance(manifest, dict):
        return manifest
    return manifest.get("files") if "files" in manifest else manifest.get("records")


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * min(max(fraction, 0.0), 1.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _load_manifest(path: Path) -> list[Path]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    raw_files = _manifest_records(manifest)
    if not isinstance(raw_files, list):
        raise ValueError("Manifest must be a JSON list or an object containing records.")
    files: list[Path] = []
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()
    for entry in raw_files:
        raw_path = entry.get("path") if isinstance(entry, dict) else entry
        candidate = Path(str(raw_path or "")).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        path_key = str(candidate).casefold()
        if path_key in seen_paths:
            raise ValueError(f"Manifest contains a duplicate input path: {candidate}")
        seen_paths.add(path_key)
        actual_hash = _sha256(candidate)
        declared_hash = (
            str(entry.get("content_sha256") or "").strip().lower()
            if isinstance(entry, dict)
            else ""
        )
        if declared_hash and declared_hash != actual_hash:
            raise ValueError(
                f"Manifest SHA-256 does not match input bytes: {candidate}"
            )
        if actual_hash in seen_hashes:
            raise ValueError(
                f"Manifest contains duplicate content SHA-256: {actual_hash}"
            )
        seen_hashes.add(actual_hash)
        files.append(candidate)
    if not files:
        raise ValueError("Manifest contains no input files.")
    return files


def _load_gold_expectations(path: Path) -> dict[Path, list[int]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    raw_files = _manifest_records(manifest)
    if not isinstance(raw_files, list):
        return {}
    expectations: dict[Path, list[int]] = {}
    for entry in raw_files:
        if not isinstance(entry, dict) or not isinstance(
            entry.get("expected_scan_indices"), list
        ):
            continue
        if not _gold_approval_valid(entry):
            continue
        candidate = Path(str(entry.get("path") or "")).expanduser().resolve()
        expectations[candidate] = [
            int(round(float(value))) for value in entry["expected_scan_indices"]
        ]
    return expectations


def _load_manifest_metadata(path: Path) -> dict[Path, dict[str, str]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    raw_files = _manifest_records(manifest)
    if not isinstance(raw_files, list):
        return {}
    partition = str(manifest.get("partition") or "") if isinstance(manifest, dict) else ""
    metadata: dict[Path, dict[str, str]] = {}
    for entry in raw_files:
        if not isinstance(entry, dict):
            continue
        candidate = Path(str(entry.get("path") or "")).expanduser().resolve()
        metadata[candidate] = {
            "partition": str(entry.get("partition") or partition),
            "failure_family": str(entry.get("failure_family") or ""),
            "truth_source": str(entry.get("truth_source") or ""),
            "ladder": str(entry.get("ladder") or ""),
            "content_sha256": str(entry.get("content_sha256") or ""),
            "physical_run_key": str(entry.get("physical_run_key") or ""),
            "review_approved": str(entry.get("review_approved") or ""),
            "review_label": str(entry.get("review_label") or ""),
            "reviewed_at_utc": str(entry.get("reviewed_at_utc") or ""),
            "reviewed_by": str(entry.get("reviewed_by") or ""),
            "analysis_id": str(entry.get("analysis_id") or ""),
            "identity_key": str(entry.get("identity_key") or ""),
            "sample_kind": str(entry.get("sample_kind") or ""),
            "gold_eligible": str(entry.get("gold_eligible") or ""),
        }
    return metadata


def _result_identity(result: dict[str, Any]) -> dict[str, object]:
    fit = result.get("ladder_fit_preview") or {}
    diagnostics = fit.get("search_diagnostics") or {}
    refinement = fit.get("refinement") or {}
    model = fit.get("sizing_model") or {}
    qc = model.get("qc_metrics") or {}
    scans = refinement.get("refined_scan_indices") or fit.get("best_scan_indices") or []
    review = result.get("ladder_review_assessment") or {}
    return {
        "ladder": str(result.get("ladder") or ""),
        "size_standard_channel": str(result.get("size_standard_channel_guess") or ""),
        "search_tier": str(fit.get("search_tier") or ""),
        "search_diagnostics": {
            key: diagnostics.get(key)
            for key in (
                "fit_tier",
                "watchdog_reached",
                "expansions_used",
                "expansion_limit",
                "complete_candidate_count",
                "rescue_triggers",
            )
            if key in diagnostics
        },
        "scan_indices": [int(value) for value in scans],
        "expected_basepairs": [
            float(value) for value in model.get("predicted_ladder_basepairs") or []
        ],
        "qc": {
            key: qc.get(key)
            for key in (
                "r2",
                "mean_abs_error_bp",
                "max_abs_error_bp",
                "linear_trend_mean_abs_error_bp",
                "linear_trend_max_abs_error_bp",
                "linear_trend_r2",
                "monotonic_on_ladder",
            )
        },
        "review_required": bool(review.get("suggested_review")),
        "review_reason_codes": sorted(str(value) for value in review.get("reason_codes") or []),
        "selected_baseline_like_anchor_count": int(
            review.get("selected_baseline_like_anchor_count") or 0
        ),
        "selected_cleaner_neighbor_count": int(
            review.get("selected_cleaner_neighbor_count") or 0
        ),
        "selected_strong_baseline_anchor_count": int(
            review.get("selected_strong_baseline_anchor_count") or 0
        ),
    }


def _run_once(
    cli: Path,
    input_file: Path,
    output_dir: Path,
    *,
    timeout_seconds: int,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter()
    completed = run_command(
        [
            str(cli),
            "analyze",
            "--analysis",
            "clonality",
            "--input",
            str(input_file),
            "--output-dir",
            str(output_dir),
            "--deterministic",
            "--compact-json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    elapsed_seconds = time.perf_counter() - started
    summary_path = output_dir / "analyze_summary.json"
    if not summary_path.is_file():
        raise RuntimeError(
            f"Rust CLI did not create {summary_path}. stderr={completed.stderr.strip()!r}"
        )
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError(f"Unexpected Rust summary shape in {summary_path}")
    return elapsed_seconds, payload[0]


def _taxonomy_comparison(
    historical_family: str, engine_outcome: str
) -> tuple[bool | None, str]:
    historical = str(historical_family or "").strip().casefold()
    engine = str(engine_outcome or "").strip().casefold()
    if not historical:
        return None, "not_available"
    if historical in HUMAN_DEPENDENT_OUTCOMES:
        return None, "not_applicable_human_label_required"
    known_outcomes = {outcome.value for outcome in LadderOutcome}
    if historical not in known_outcomes:
        return None, "not_comparable_unknown_historical_family"
    if historical == engine:
        return True, "agreement"
    return False, "model_transition"


def _validate_benchmark_inputs(
    files: list[Path],
    case_metadata: dict[Path, dict[str, str]],
) -> tuple[list[Path], dict[Path, str]]:
    resolved_files: list[Path] = []
    verified_hashes: dict[Path, str] = {}
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()
    for raw_path in files:
        input_file = Path(raw_path).expanduser().resolve()
        if not input_file.is_file():
            raise FileNotFoundError(input_file)
        path_key = str(input_file).casefold()
        if path_key in seen_paths:
            raise ValueError(f"Benchmark contains a duplicate input path: {input_file}")
        seen_paths.add(path_key)
        actual_hash = _sha256(input_file)
        if actual_hash in seen_hashes:
            raise ValueError(
                f"Benchmark contains duplicate content SHA-256: {actual_hash}"
            )
        seen_hashes.add(actual_hash)
        declared_hash = str(
            (case_metadata.get(input_file) or {}).get("content_sha256") or ""
        ).strip().lower()
        if declared_hash and declared_hash != actual_hash:
            raise ValueError(
                f"Benchmark SHA-256 does not match input bytes: {input_file}"
            )
        resolved_files.append(input_file)
        verified_hashes[input_file] = actual_hash
    if not resolved_files:
        raise ValueError("Benchmark contains no input files")
    return resolved_files, verified_hashes


def _summarize(rows: list[dict[str, Any]]) -> dict[str, object]:
    durations = [
        float(run["elapsed_seconds"])
        for row in rows
        for run in row.get("runs") or []
    ]
    engine_times = [
        float(run["engine_ladder_seconds"])
        for row in rows
        for run in row.get("runs") or []
        if run.get("engine_ladder_seconds") is not None
    ]
    taxonomy_statuses = [
        str(row.get("taxonomy_comparison_status") or "") for row in rows
    ]
    diagnostics = [
        (row.get("identity") or {}).get("search_diagnostics") or {}
        for row in rows
    ]
    return {
        "file_count": len(rows),
        "repeat_count": len(durations),
        "latency_distribution": "all_measured_repeats",
        "median_seconds": statistics.median(durations) if durations else 0.0,
        "p95_seconds": _percentile(durations, 0.95),
        "max_seconds": max(durations, default=0.0),
        "median_engine_ladder_seconds": (
            statistics.median(engine_times) if engine_times else None
        ),
        "p95_engine_ladder_seconds": (
            _percentile(engine_times, 0.95) if engine_times else None
        ),
        "review_count": sum(bool(row["identity"]["review_required"]) for row in rows),
        "gold_case_count": sum(row.get("gold_exact_match") is not None for row in rows),
        "gold_exact_match_count": sum(row.get("gold_exact_match") is True for row in rows),
        "gold_major_wrong_sequence_count": sum(
            row.get("gold_major_wrong_sequence") is True for row in rows
        ),
        "gold_core_exact_match_count": sum(
            row.get("gold_core_exact_match") is True for row in rows
        ),
        "gold_core_major_wrong_sequence_count": sum(
            row.get("gold_core_major_wrong_sequence") is True for row in rows
        ),
        "taxonomy_case_count": sum(row.get("taxonomy_agreement") is not None for row in rows),
        "taxonomy_agreement_count": sum(row.get("taxonomy_agreement") is True for row in rows),
        "taxonomy_model_transition_count": sum(
            status == "model_transition" for status in taxonomy_statuses
        ),
        "taxonomy_inapplicable_count": sum(
            status == "not_applicable_human_label_required"
            for status in taxonomy_statuses
        ),
        "rescue_invocation_count": sum(
            str(value.get("fit_tier") or "")
            in {"rescue_2s", "deep_rescue_10s"}
            for value in diagnostics
        ),
        "watchdog_reached_count": sum(
            bool(value.get("watchdog_reached")) for value in diagnostics
        ),
    }


def _benchmark_rows_by_hash(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = value.get("files") or []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("content_sha256") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("content_sha256") or "")
    }


def _watchdog_overflow_count(value: dict[str, Any]) -> int:
    count = 0
    for row in value.get("files") or []:
        for run in row.get("runs") or []:
            identity = run.get("identity") or {}
            diagnostics = (
                run.get("search_diagnostics")
                or identity.get("search_diagnostics")
                or {}
            )
            tier = str(
                diagnostics.get("fit_tier") or identity.get("search_tier") or ""
            )
            elapsed_us = int(diagnostics.get("elapsed_us") or 0)
            ceiling_us = {
                "rescue_2s": 2_000_000,
                "deep_rescue_10s": 10_000_000,
            }.get(tier)
            if bool(diagnostics.get("watchdog_reached")) or (
                ceiling_us is not None and elapsed_us > ceiling_us
            ):
                count += 1
    return count


def _strictly_closer_to_gold(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    if candidate.get("gold_exact_match") is True:
        return True
    before_changed = baseline.get("gold_anchors_changed")
    after_changed = candidate.get("gold_anchors_changed")
    before_delta = baseline.get("gold_max_abs_scan_delta")
    after_delta = candidate.get("gold_max_abs_scan_delta")
    if before_changed is None or after_changed is None:
        return False
    return bool(
        after_changed < before_changed
        or (
            after_changed == before_changed
            and before_delta is not None
            and after_delta is not None
            and after_delta < before_delta
        )
    )


def _fast_path_p95(value: dict[str, Any]) -> float | None:
    by_tier = value.get("by_tier") or {}
    for tier in ("primary_beam", "fast"):
        summary = by_tier.get(tier) or {}
        measured = summary.get("p95_engine_ladder_seconds")
        if measured is not None:
            return float(measured)
    return None


def evaluate_fit_candidate(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, object]:
    """Evaluate a candidate without allowing aggregate gains to hide regressions."""

    baseline_rows = _benchmark_rows_by_hash(baseline)
    candidate_rows = _benchmark_rows_by_hash(candidate)
    same_cases = set(baseline_rows) == set(candidate_rows) and bool(baseline_rows)
    exact_regressions = 0
    major_regressions = 0
    core_exact_regressions = 0
    core_major_regressions = 0
    farther_changed_cases = 0
    ladder_major_deltas: dict[str, int] = {}
    ladder_core_major_deltas: dict[str, int] = {}
    if same_cases:
        ladders = sorted(
            {str(row.get("ladder") or "") for row in baseline_rows.values()}
        )
        for ladder in ladders:
            before = sum(
                row.get("gold_major_wrong_sequence") is True
                for row in baseline_rows.values()
                if str(row.get("ladder") or "") == ladder
            )
            after = sum(
                row.get("gold_major_wrong_sequence") is True
                for row in candidate_rows.values()
                if str(row.get("ladder") or "") == ladder
            )
            ladder_major_deltas[ladder] = after - before
            core_before = sum(
                row.get(
                    "gold_core_major_wrong_sequence",
                    row.get("gold_major_wrong_sequence"),
                )
                is True
                for row in baseline_rows.values()
                if str(row.get("ladder") or "") == ladder
            )
            core_after = sum(
                row.get(
                    "gold_core_major_wrong_sequence",
                    row.get("gold_major_wrong_sequence"),
                )
                is True
                for row in candidate_rows.values()
                if str(row.get("ladder") or "") == ladder
            )
            ladder_core_major_deltas[ladder] = core_after - core_before
        for content_hash, before in baseline_rows.items():
            after = candidate_rows[content_hash]
            if before.get("gold_exact_match") is True and after.get(
                "gold_exact_match"
            ) is not True:
                exact_regressions += 1
            if before.get("gold_major_wrong_sequence") is not True and after.get(
                "gold_major_wrong_sequence"
            ) is True:
                major_regressions += 1
            before_core_exact = before.get(
                "gold_core_exact_match", before.get("gold_exact_match")
            )
            after_core_exact = after.get(
                "gold_core_exact_match", after.get("gold_exact_match")
            )
            if before_core_exact is True and after_core_exact is not True:
                core_exact_regressions += 1
            before_core_major = before.get(
                "gold_core_major_wrong_sequence",
                before.get("gold_major_wrong_sequence"),
            )
            after_core_major = after.get(
                "gold_core_major_wrong_sequence",
                after.get("gold_major_wrong_sequence"),
            )
            if before_core_major is not True and after_core_major is True:
                core_major_regressions += 1
            before_scans = (before.get("identity") or {}).get("scan_indices") or []
            after_scans = (after.get("identity") or {}).get("scan_indices") or []
            if (
                before_scans != after_scans
                and before.get("gold_exact_match") is not True
                and not _strictly_closer_to_gold(before, after)
            ):
                farther_changed_cases += 1
    watchdog_overflow_count = _watchdog_overflow_count(candidate)
    deterministic = bool(candidate.get("deterministic"))
    family_major_regressions = sum(delta > 0 for delta in ladder_major_deltas.values())
    family_core_major_regressions = sum(
        delta > 0 for delta in ladder_core_major_deltas.values()
    )
    baseline_fast_p95 = _fast_path_p95(baseline)
    candidate_fast_p95 = _fast_path_p95(candidate)
    fast_path_p95_regression = bool(
        baseline_fast_p95 is not None
        and candidate_fast_p95 is not None
        and candidate_fast_p95 > baseline_fast_p95 * 1.25 + 0.01
    )
    promotable = bool(
        same_cases
        and deterministic
        and core_exact_regressions == 0
        and core_major_regressions == 0
        and family_core_major_regressions == 0
        and watchdog_overflow_count == 0
        and not fast_path_p95_regression
    )
    return {
        "same_case_set": same_cases,
        "deterministic": deterministic,
        "existing_exact_preserved": exact_regressions == 0,
        "exact_control_regressions": exact_regressions,
        "existing_core_exact_preserved": core_exact_regressions == 0,
        "core_exact_control_regressions": core_exact_regressions,
        "major_wrong_sequence_regressions": major_regressions,
        "core_major_wrong_sequence_regressions": core_major_regressions,
        "major_wrong_sequence_delta_by_ladder": ladder_major_deltas,
        "core_major_wrong_sequence_delta_by_ladder": ladder_core_major_deltas,
        "ladder_families_with_major_regression": family_major_regressions,
        "ladder_families_with_core_major_regression": family_core_major_regressions,
        "changed_cases_not_strictly_closer": farther_changed_cases,
        "watchdog_overflow_count": watchdog_overflow_count,
        "baseline_fast_path_p95_seconds": baseline_fast_p95,
        "candidate_fast_path_p95_seconds": candidate_fast_p95,
        "fast_path_p95_regression": fast_path_p95_regression,
        "promotable": promotable,
    }


def _sequence_metrics(selected: list[int], expected: list[int]) -> dict[str, object]:
    exact = selected == expected
    if len(selected) != len(expected):
        return {
            "exact_match": False,
            "anchors_changed": max(len(selected), len(expected)),
            "mean_abs_scan_delta": None,
            "max_abs_scan_delta": None,
            "major_wrong_sequence": True,
        }
    deltas = [abs(left - right) for left, right in zip(selected, expected)]
    changed = sum(delta != 0 for delta in deltas)
    return {
        "exact_match": exact,
        "anchors_changed": changed,
        "mean_abs_scan_delta": statistics.mean(deltas) if deltas else 0.0,
        "max_abs_scan_delta": max(deltas, default=0),
        "major_wrong_sequence": (not exact and changed >= 2),
    }


def _gold_anchor_metrics(
    selected: list[int], expected: list[int] | None, *, ladder: str = ""
) -> dict[str, object]:
    if expected is None:
        return {
            "gold_exact_match": None,
            "gold_anchors_changed": None,
            "gold_mean_abs_scan_delta": None,
            "gold_max_abs_scan_delta": None,
            "gold_major_wrong_sequence": None,
            "gold_core_exact_match": None,
            "gold_core_anchors_changed": None,
            "gold_core_mean_abs_scan_delta": None,
            "gold_core_max_abs_scan_delta": None,
            "gold_core_major_wrong_sequence": None,
        }
    strict = _sequence_metrics(selected, expected)
    core_selected = selected[1:] if ladder == "LIZ500_250" else selected
    core_expected = expected[1:] if ladder == "LIZ500_250" else expected
    core = _sequence_metrics(core_selected, core_expected)
    return {
        **{f"gold_{key}": value for key, value in strict.items()},
        **{f"gold_core_{key}": value for key, value in core.items()},
    }


def benchmark(
    files: list[Path],
    *,
    cli: Path,
    repeats: int,
    warmups: int,
    timeout_seconds: int = 60,
    gold_expectations: dict[Path, list[int]] | None = None,
    case_metadata: dict[Path, dict[str, str]] | None = None,
) -> dict[str, object]:
    cli = cli.expanduser().resolve()
    if not cli.is_file():
        raise FileNotFoundError(cli)
    repeats = max(1, int(repeats))
    warmups = max(0, int(warmups))
    timeout_seconds = max(1, int(timeout_seconds))
    gold_expectations = gold_expectations or {}
    case_metadata = {
        Path(path).expanduser().resolve(): dict(metadata)
        for path, metadata in (case_metadata or {}).items()
    }
    gold_expectations = {
        Path(path).expanduser().resolve(): list(scans)
        for path, scans in gold_expectations.items()
    }
    files, verified_hashes = _validate_benchmark_inputs(files, case_metadata)
    for gold_path in gold_expectations:
        if gold_path not in verified_hashes:
            raise ValueError(
                f"Gold expectation does not match a benchmark input: {gold_path}"
            )
        if not _gold_approval_valid(case_metadata.get(gold_path) or {}):
            raise ValueError(
                f"Gold benchmarking requires explicit review approval: {gold_path}"
            )
    rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="hemafrag_ladder_benchmark_") as temp_root:
        temp_root_path = Path(temp_root)
        for file_index, input_file in enumerate(files):
            run_rows: list[dict[str, Any]] = []
            for iteration in range(warmups + repeats):
                output_dir = temp_root_path / f"{file_index:05d}_{iteration:03d}"
                elapsed_seconds, result = _run_once(
                    cli,
                    input_file,
                    output_dir,
                    timeout_seconds=timeout_seconds,
                )
                if iteration < warmups:
                    continue
                identity = _result_identity(result)
                timings_us = result.get("timings_us") or {}
                run_rows.append(
                    {
                        "elapsed_seconds": elapsed_seconds,
                        "engine_total_seconds": (
                            float(timings_us["total"]) / 1_000_000.0
                            if "total" in timings_us
                            else None
                        ),
                        "engine_ladder_seconds": (
                            float(timings_us["ladder_fit"]) / 1_000_000.0
                            if "ladder_fit" in timings_us
                            else None
                        ),
                        "timings_us": timings_us,
                        "identity": identity,
                        "search_diagnostics": (
                            (result.get("ladder_fit_preview") or {}).get(
                                "search_diagnostics"
                            )
                            or {}
                        ),
                        "identity_fingerprint": _stable_fingerprint(identity),
                        "candidate_peak_count": int(result.get("ladder_peak_count") or 0),
                        "estimated_combinations": int(
                            (result.get("ladder_fit_preview") or {}).get(
                                "estimated_combination_count"
                            )
                            or 0
                        ),
                        "evaluated_combinations": int(
                            (result.get("ladder_fit_preview") or {}).get(
                                "evaluated_combination_count"
                            )
                            or 0
                        ),
                    }
                )
            fingerprints = sorted({row["identity_fingerprint"] for row in run_rows})
            identities = {json.dumps(row["identity"], sort_keys=True) for row in run_rows}
            engine_ladder_times = [
                float(row["engine_ladder_seconds"])
                for row in run_rows
                if row["engine_ladder_seconds"] is not None
            ]
            first = run_rows[0]
            expected_scans = gold_expectations.get(input_file)
            metadata = case_metadata.get(input_file, {})
            selected_scans = [int(value) for value in first["identity"]["scan_indices"]]
            gold_metrics = _gold_anchor_metrics(
                selected_scans,
                expected_scans,
                ladder=str(first["identity"]["ladder"]),
            )
            engine_outcome = classify_ladder_outcome(
                {
                    "configured_ladder": metadata.get("ladder", ""),
                    "detected_ladder": first["identity"]["ladder"],
                    "ladder_peak_count": first["candidate_peak_count"],
                    "candidate_peak_count": first["candidate_peak_count"],
                    "fitted_count": len(selected_scans),
                    "review_required": first["identity"]["review_required"],
                    "accepted": bool(selected_scans)
                    and not first["identity"]["review_required"],
                    "reason_codes": first["identity"]["review_reason_codes"],
                }
            ).value
            historical_family = str(metadata.get("failure_family") or "")
            taxonomy_agreement, taxonomy_comparison_status = _taxonomy_comparison(
                historical_family,
                engine_outcome,
            )
            elapsed_times = [float(row["elapsed_seconds"]) for row in run_rows]
            rows.append(
                {
                    "fixture_id": f"sha256:{verified_hashes[input_file]}",
                    "content_sha256": verified_hashes[input_file],
                    "size_bytes": input_file.stat().st_size,
                    "ladder": first["identity"]["ladder"],
                    "repeat_count": len(run_rows),
                    "median_seconds": statistics.median(elapsed_times),
                    "p95_seconds": _percentile(elapsed_times, 0.95),
                    "max_seconds": max(elapsed_times),
                    "median_engine_ladder_seconds": (
                        statistics.median(engine_ladder_times)
                        if engine_ladder_times
                        else None
                    ),
                    "p95_engine_ladder_seconds": (
                        _percentile(engine_ladder_times, 0.95)
                        if engine_ladder_times
                        else None
                    ),
                    "deterministic": len(fingerprints) == 1 and len(identities) == 1,
                    "identity_fingerprints": fingerprints,
                    "identity": first["identity"],
                    **gold_metrics,
                    "gold_max_scan_delta": gold_metrics["gold_max_abs_scan_delta"],
                    "candidate_peak_count": first["candidate_peak_count"],
                    "estimated_combinations": first["estimated_combinations"],
                    "evaluated_combinations": first["evaluated_combinations"],
                    "partition": str(metadata.get("partition") or ""),
                    "historical_failure_family": historical_family,
                    "truth_source": str(metadata.get("truth_source") or ""),
                    "physical_run_key": str(metadata.get("physical_run_key") or ""),
                    "engine_outcome": engine_outcome,
                    "taxonomy_agreement": taxonomy_agreement,
                    "taxonomy_comparison_status": taxonomy_comparison_status,
                    "runs": run_rows,
                }
            )

    by_ladder = {
        ladder: _summarize([row for row in rows if row["ladder"] == ladder])
        for ladder in sorted({str(row["ladder"]) for row in rows})
    }
    by_failure_family = {
        family: _summarize(
            [row for row in rows if row["historical_failure_family"] == family]
        )
        for family in sorted(
            {str(row["historical_failure_family"]) for row in rows if row["historical_failure_family"]}
        )
    }
    by_engine_outcome = {
        outcome: _summarize([row for row in rows if row["engine_outcome"] == outcome])
        for outcome in sorted({str(row["engine_outcome"]) for row in rows})
    }
    by_tier = {
        tier: _summarize(
            [row for row in rows if row["identity"]["search_tier"] == tier]
        )
        for tier in sorted({str(row["identity"]["search_tier"]) for row in rows})
    }
    return {
        "schema_version": BENCHMARK_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cli": {
            "path": str(cli),
            "size_bytes": cli.stat().st_size,
            "modified_at_utc": datetime.fromtimestamp(
                cli.stat().st_mtime, timezone.utc
            ).isoformat(),
            "sha256": _sha256(cli),
        },
        "configuration": {
            "repeats": repeats,
            "warmups": warmups,
            "timeout_seconds": timeout_seconds,
            "analysis": "clonality",
            "deterministic": True,
        },
        "deterministic": all(bool(row["deterministic"]) for row in rows),
        "gold_case_count": sum(row.get("gold_exact_match") is not None for row in rows),
        "gold_exact_match_count": sum(row.get("gold_exact_match") is True for row in rows),
        "gold_major_wrong_sequence_count": sum(
            row.get("gold_major_wrong_sequence") is True for row in rows
        ),
        "gold_core_exact_match_count": sum(
            row.get("gold_core_exact_match") is True for row in rows
        ),
        "gold_core_major_wrong_sequence_count": sum(
            row.get("gold_core_major_wrong_sequence") is True for row in rows
        ),
        "overall": _summarize(rows),
        "by_ladder": by_ladder,
        "by_failure_family": by_failure_family,
        "by_engine_outcome": by_engine_outcome,
        "by_tier": by_tier,
        "files": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Optional prior benchmark used to add a promotion_gate comparison.",
    )
    args = parser.parse_args()

    result = benchmark(
        _load_manifest(args.manifest.expanduser().resolve()),
        cli=args.cli,
        repeats=args.repeats,
        warmups=args.warmups,
        timeout_seconds=args.timeout_seconds,
        gold_expectations=_load_gold_expectations(args.manifest.expanduser().resolve()),
        case_metadata=_load_manifest_metadata(args.manifest.expanduser().resolve()),
    )
    if args.baseline is not None:
        baseline = json.loads(
            args.baseline.expanduser().resolve().read_text(encoding="utf-8")
        )
        if not isinstance(baseline, dict):
            raise ValueError("Baseline benchmark must be a JSON object")
        result["promotion_gate"] = evaluate_fit_candidate(baseline, result)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "deterministic": result["deterministic"],
                "by_ladder": result["by_ladder"],
                "promotion_gate": result.get("promotion_gate"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
