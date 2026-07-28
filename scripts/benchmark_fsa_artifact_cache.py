#!/usr/bin/env python3
"""Alternating A/B benchmark for the per-process FSA decode artifact."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.freeze_v2_baseline import (
    _atomic_write_json,
    _percentile,
    _runtime_metadata,
    _stable_fingerprint,
)


BENCHMARK_SCHEMA = "hemafrag_fsa_artifact_ab_v1"


def _entry_identity(entry: dict[str, Any] | None) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {"available": False}
    fsa = entry.get("fsa")
    anchor_times = getattr(fsa, "best_size_standard", None)
    ladder_steps = getattr(fsa, "ladder_steps", None)
    return {
        "available": True,
        "assay": str(entry.get("assay") or ""),
        "ladder_qc_status": str(entry.get("ladder_qc_status") or ""),
        "ladder_fit_strategy": str(entry.get("ladder_fit_strategy") or ""),
        "ladder_r2": entry.get("ladder_r2"),
        "ladder_linear_r2": entry.get("ladder_linear_r2"),
        "ladder_linear_max_residual_bp": entry.get("ladder_linear_max_residual_bp"),
        "anchor_times": [float(value) for value in anchor_times]
        if anchor_times is not None
        else [],
        "ladder_steps": [float(value) for value in ladder_steps]
        if ladder_steps is not None
        else [],
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    durations = [float(row["duration_seconds"]) for row in rows]
    fingerprints = sorted({str(row["result_fingerprint"]) for row in rows})
    return {
        "repeat_count": len(rows),
        "median_seconds": float(statistics.median(durations)),
        "p95_seconds": float(_percentile(durations, 0.95) or 0.0),
        "min_seconds": float(min(durations)),
        "max_seconds": float(max(durations)),
        "deterministic": len(fingerprints) == 1,
        "result_fingerprints": fingerprints,
        "decode_counts": [int(row["artifact_stats"]["decode_count"]) for row in rows],
        "runs": rows,
    }


def benchmark_artifact_cache(
    input_file: Path,
    *,
    repo_root: Path,
    repeats: int = 12,
    warmups: int = 1,
    verbose: bool = False,
) -> dict[str, object]:
    from config import APP_SETTINGS
    from core.analyses.clonality.pipeline import _analyze_single_file
    from core.fsa_artifact import clear_fsa_artifact_cache, get_fsa_artifact_stats

    input_file = input_file.expanduser().resolve()
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    repeats = max(2, int(repeats))
    warmups = max(0, int(warmups))
    engine = APP_SETTINGS.setdefault("engine", {})
    previous_rust = engine.get("use_rust")
    previous_bypass = os.environ.get("HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE")
    rows: dict[str, list[dict[str, object]]] = {
        "cache_disabled": [],
        "cache_enabled": [],
    }

    def run_once(disabled: bool, *, record: bool) -> None:
        if disabled:
            os.environ["HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE"] = "1"
        else:
            os.environ.pop("HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE", None)
        clear_fsa_artifact_cache()
        started = time.perf_counter()
        stream = contextlib.nullcontext() if verbose else contextlib.redirect_stdout(io.StringIO())
        with stream:
            entry = _analyze_single_file(input_file)
        duration = time.perf_counter() - started
        if not record:
            return
        identity = _entry_identity(entry)
        rows["cache_disabled" if disabled else "cache_enabled"].append(
            {
                "duration_seconds": duration,
                "result_fingerprint": _stable_fingerprint(identity),
                "artifact_stats": get_fsa_artifact_stats(),
            }
        )

    engine["use_rust"] = False
    try:
        for _ in range(warmups):
            run_once(True, record=False)
            run_once(False, record=False)
        for repeat_index in range(repeats):
            order = (True, False) if repeat_index % 2 == 0 else (False, True)
            for disabled in order:
                run_once(disabled, record=True)
    finally:
        if previous_rust is None:
            engine.pop("use_rust", None)
        else:
            engine["use_rust"] = previous_rust
        if previous_bypass is None:
            os.environ.pop("HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE", None)
        else:
            os.environ["HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE"] = previous_bypass
        clear_fsa_artifact_cache()

    disabled_summary = _summary(rows["cache_disabled"])
    enabled_summary = _summary(rows["cache_enabled"])
    p50_gain = 1.0 - (
        float(enabled_summary["median_seconds"])
        / max(float(disabled_summary["median_seconds"]), 1e-9)
    )
    p95_gain = 1.0 - (
        float(enabled_summary["p95_seconds"])
        / max(float(disabled_summary["p95_seconds"]), 1e-9)
    )
    return {
        "schema_version": BENCHMARK_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "file_name": input_file.name,
            "size_bytes": int(input_file.stat().st_size),
        },
        "runtime": _runtime_metadata(repo_root),
        "configuration": {
            "repeats": repeats,
            "warmups": warmups,
            "rust_enabled": False,
            "alternating_order": True,
        },
        "cache_disabled": disabled_summary,
        "cache_enabled": enabled_summary,
        "output_parity": (
            disabled_summary["result_fingerprints"]
            == enabled_summary["result_fingerprints"]
        ),
        "median_improvement_fraction": p50_gain,
        "p95_improvement_fraction": p95_gain,
        "promotion_gate_passed": bool(
            disabled_summary["deterministic"]
            and enabled_summary["deterministic"]
            and disabled_summary["result_fingerprints"]
            == enabled_summary["result_fingerprints"]
            and p95_gain > 0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    result = benchmark_artifact_cache(
        args.input_file,
        repo_root=REPO_ROOT,
        repeats=args.repeats,
        warmups=args.warmups,
        verbose=args.verbose,
    )
    _atomic_write_json(args.output.expanduser(), result)
    print(json.dumps({
        "output": str(args.output),
        "promotion_gate_passed": result["promotion_gate_passed"],
        "median_improvement_fraction": result["median_improvement_fraction"],
        "p95_improvement_fraction": result["p95_improvement_fraction"],
    }, indent=2))


if __name__ == "__main__":
    main()
