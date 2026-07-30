#!/usr/bin/env python3
"""Benchmark deterministic Rust ladder fitting from an explicit FSA manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLI = REPO_ROOT / "fraggler-v2" / "target" / "release" / "fraggler-cli.exe"
BENCHMARK_SCHEMA = "hemafrag_rust_ladder_benchmark_v1"


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
    raw_files = manifest.get("files") if isinstance(manifest, dict) else manifest
    if not isinstance(raw_files, list):
        raise ValueError("Manifest must be a JSON list or an object containing a 'files' list.")
    files: list[Path] = []
    for entry in raw_files:
        raw_path = entry.get("path") if isinstance(entry, dict) else entry
        candidate = Path(str(raw_path or "")).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        files.append(candidate)
    if not files:
        raise ValueError("Manifest contains no input files.")
    return files


def _load_gold_expectations(path: Path) -> dict[Path, list[int]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    raw_files = manifest.get("files") if isinstance(manifest, dict) else manifest
    if not isinstance(raw_files, list):
        return {}
    expectations: dict[Path, list[int]] = {}
    for entry in raw_files:
        if not isinstance(entry, dict) or not isinstance(
            entry.get("expected_scan_indices"), list
        ):
            continue
        candidate = Path(str(entry.get("path") or "")).expanduser().resolve()
        expectations[candidate] = [
            int(round(float(value))) for value in entry["expected_scan_indices"]
        ]
    return expectations


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


def _run_once(cli: Path, input_file: Path, output_dir: Path) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter()
    completed = subprocess.run(
        [
            str(cli),
            "analyze",
            "--analysis",
            "clonality",
            "--input",
            str(input_file),
            "--output-dir",
            str(output_dir),
            "--compact-json",
        ],
        check=True,
        capture_output=True,
        text=True,
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


def _summarize(rows: list[dict[str, Any]]) -> dict[str, object]:
    durations = [float(row["median_seconds"]) for row in rows]
    engine_times = [
        float(row["median_engine_ladder_seconds"])
        for row in rows
        if row.get("median_engine_ladder_seconds") is not None
    ]
    return {
        "file_count": len(rows),
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
    }


def benchmark(
    files: list[Path],
    *,
    cli: Path,
    repeats: int,
    warmups: int,
    gold_expectations: dict[Path, list[int]] | None = None,
) -> dict[str, object]:
    cli = cli.expanduser().resolve()
    if not cli.is_file():
        raise FileNotFoundError(cli)
    repeats = max(1, int(repeats))
    warmups = max(0, int(warmups))
    gold_expectations = gold_expectations or {}
    rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="hemafrag_ladder_benchmark_") as temp_root:
        temp_root_path = Path(temp_root)
        for file_index, input_file in enumerate(files):
            run_rows: list[dict[str, Any]] = []
            for iteration in range(warmups + repeats):
                output_dir = temp_root_path / f"{file_index:05d}_{iteration:03d}"
                elapsed_seconds, result = _run_once(cli, input_file, output_dir)
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
            selected_scans = [int(value) for value in first["identity"]["scan_indices"]]
            gold_exact_match = (
                selected_scans == expected_scans if expected_scans is not None else None
            )
            gold_max_scan_delta = (
                max(
                    (
                        abs(selected - expected)
                        for selected, expected in zip(selected_scans, expected_scans)
                    ),
                    default=0,
                )
                if expected_scans is not None and len(selected_scans) == len(expected_scans)
                else None
            )
            rows.append(
                {
                    "fixture_id": f"sha256:{_sha256(input_file)}",
                    "size_bytes": input_file.stat().st_size,
                    "ladder": first["identity"]["ladder"],
                    "median_seconds": statistics.median(
                        float(row["elapsed_seconds"]) for row in run_rows
                    ),
                    "median_engine_ladder_seconds": (
                        statistics.median(engine_ladder_times)
                        if engine_ladder_times
                        else None
                    ),
                    "deterministic": len(fingerprints) == 1 and len(identities) == 1,
                    "identity_fingerprints": fingerprints,
                    "identity": first["identity"],
                    "gold_exact_match": gold_exact_match,
                    "gold_max_scan_delta": gold_max_scan_delta,
                    "candidate_peak_count": first["candidate_peak_count"],
                    "estimated_combinations": first["estimated_combinations"],
                    "evaluated_combinations": first["evaluated_combinations"],
                    "runs": run_rows,
                }
            )

    by_ladder = {
        ladder: _summarize([row for row in rows if row["ladder"] == ladder])
        for ladder in sorted({str(row["ladder"]) for row in rows})
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
        },
        "configuration": {
            "repeats": repeats,
            "warmups": warmups,
            "analysis": "clonality",
        },
        "deterministic": all(bool(row["deterministic"]) for row in rows),
        "gold_case_count": sum(row.get("gold_exact_match") is not None for row in rows),
        "gold_exact_match_count": sum(row.get("gold_exact_match") is True for row in rows),
        "by_ladder": by_ladder,
        "files": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    args = parser.parse_args()

    result = benchmark(
        _load_manifest(args.manifest.expanduser().resolve()),
        cli=args.cli,
        repeats=args.repeats,
        warmups=args.warmups,
        gold_expectations=_load_gold_expectations(args.manifest.expanduser().resolve()),
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
