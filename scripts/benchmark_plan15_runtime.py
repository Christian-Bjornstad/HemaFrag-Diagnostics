"""Repeatable, non-clinical Plan 15 startup and baseline microbenchmarks.

This benchmark uses only a deterministic synthetic trace.  It complements the
ignored real-FSA Plan 13 corpus; it does not replace clinical ladder validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = min(1.0, max(0.0, quantile)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summary(values: list[float]) -> dict:
    return {
        "count": len(values),
        "min_seconds": min(values) if values else 0.0,
        "median_seconds": statistics.median(values) if values else 0.0,
        "p95_seconds": _percentile(values, 0.95),
        "max_seconds": max(values) if values else 0.0,
        "runs_seconds": values,
    }


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def benchmark_startup(repeats: int) -> dict:
    child_code = r"""
import os
import time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
started = time.perf_counter()
import qt_app
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
window = qt_app.MainWindow()
window.resize(1200, 800)
window.show()
app.processEvents()
print(f"{time.perf_counter() - started:.9f}")
window.close()
app.processEvents()
"""
    values: list[float] = []
    for _ in range(max(1, repeats)):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["HEMAFRAG_ENABLE_LEGACY_PANEL"] = "0"
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=90,
        )
        values.append(float(completed.stdout.strip().splitlines()[-1]))
    return _summary(values)


def _synthetic_trace(length: int = 6000) -> np.ndarray:
    rng = np.random.default_rng(1508)
    x = np.arange(length, dtype=float)
    values = -120.0 + 0.012 * x + 5.0 * np.sin(x / 240.0) + rng.normal(0.0, 2.0, length)
    for center, height, width in (
        (500, 500, 5),
        (1100, 900, 7),
        (1800, 650, 6),
        (2700, 1200, 8),
        (3900, 750, 7),
        (5100, 1000, 6),
    ):
        values += height * np.exp(-0.5 * ((x - center) / width) ** 2)
    return values


def benchmark_arpls(repeats: int) -> dict:
    from fraggler.fraggler import _arpls_penalty_matrix, baseline_arPLS

    trace = _synthetic_trace()
    _arpls_penalty_matrix.cache_clear()
    started = time.perf_counter()
    first = np.asarray(baseline_arPLS(trace), dtype=float)
    cold_seconds = time.perf_counter() - started

    values: list[float] = []
    result = first
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        result = np.asarray(baseline_arPLS(trace), dtype=float)
        values.append(time.perf_counter() - started)
    digest = hashlib.sha256(result.astype("<f8", copy=False).tobytes()).hexdigest()
    return {
        "cold_seconds": cold_seconds,
        "warm": _summary(values),
        "output_sha256": digest,
        "finite": bool(np.all(np.isfinite(result))),
    }


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup-repeats", type=int, default=5)
    parser.add_argument("--arpls-repeats", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = {
        "schema_version": "hemafrag_plan15_runtime_benchmark_v1",
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "git_commit": _git_commit(),
        },
        "startup_to_first_event_processing": benchmark_startup(args.startup_repeats),
        "python_arpls_6000": benchmark_arpls(args.arpls_repeats),
        "limitations": [
            "Synthetic arPLS input is not a clinical ladder-validation corpus.",
            "Offscreen startup measures first Qt event processing, not human-perceived taskbar paint time.",
        ],
    }
    if args.output:
        _atomic_write_json(args.output.expanduser().resolve(), payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
