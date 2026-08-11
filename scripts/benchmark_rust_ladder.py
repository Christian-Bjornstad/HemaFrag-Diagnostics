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
    refinement = fit.get("refinement") or {}
    model = fit.get("sizing_model") or {}
    qc = model.get("qc_metrics") or {}
    scans = refinement.get("refined_scan_indices") or fit.get("best_scan_indices") or []
    review = result.get("ladder_review_assessment") or {}
    return {
        "ladder": str(result.get("ladder") or ""),
        "size_standard_channel": str(result.get("size_standard_channel_guess") or ""),
        "search_tier": str(fit.get("search_tier") or ""),
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
        "taxonomy_case_count": sum(row.get("taxonomy_agreement") is not None for row in rows),
        "taxonomy_agreement_count": sum(row.get("taxonomy_agreement") is True for row in rows),
        "taxonomy_model_transition_count": sum(
            status == "model_transition" for status in taxonomy_statuses
        ),
        "taxonomy_inapplicable_count": sum(
            status == "not_applicable_human_label_required"
            for status in taxonomy_statuses
        ),
    }


def _gold_anchor_metrics(
    selected: list[int], expected: list[int] | None
) -> dict[str, object]:
    if expected is None:
        return {
            "gold_exact_match": None,
            "gold_anchors_changed": None,
            "gold_mean_abs_scan_delta": None,
            "gold_max_abs_scan_delta": None,
            "gold_major_wrong_sequence": None,
        }
    exact = selected == expected
    if len(selected) != len(expected):
        return {
            "gold_exact_match": False,
            "gold_anchors_changed": max(len(selected), len(expected)),
            "gold_mean_abs_scan_delta": None,
            "gold_max_abs_scan_delta": None,
            "gold_major_wrong_sequence": True,
        }
    deltas = [abs(left - right) for left, right in zip(selected, expected)]
    changed = sum(delta != 0 for delta in deltas)
    return {
        "gold_exact_match": exact,
        "gold_anchors_changed": changed,
        "gold_mean_abs_scan_delta": statistics.mean(deltas) if deltas else 0.0,
        "gold_max_abs_scan_delta": max(deltas, default=0),
        "gold_major_wrong_sequence": (not exact and changed >= 2),
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
            gold_metrics = _gold_anchor_metrics(selected_scans, expected_scans)
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
        "overall": _summarize(rows),
        "by_ladder": by_ladder,
        "by_failure_family": by_failure_family,
        "by_engine_outcome": by_engine_outcome,
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
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "deterministic": result["deterministic"],
                "by_ladder": result["by_ladder"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
