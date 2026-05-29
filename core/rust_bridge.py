"""
HemaFrag Diagnostics — Rust Engine Bridge.

Provides a hybrid mode where the fast Rust engine is used to detect
and fit the size standard peaks, while Python maintains the rest of
the pipeline for full compatibility with existing Plotly HTML reports
and QC log tracking.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.engine_flags import strict_rust_ladder_enabled
from core.log import log
from fraggler.fraggler import FsaFile, baseline_arPLS, fit_size_standard_to_ladder


ROX_PREFERRED_TIME_MIN = 1500.0
ROX_PREFERRED_TIME_MAX = 4000.0
ROX_HARD_TIME_MIN = 1300.0
ROX_HARD_TIME_MAX = 4300.0
ROX_MAX_FIRST_ANCHOR = 1900.0
ROX_MIN_SPAN = 1100.0
ROX_MIN_MEDIAN_GAP = 26.0
ROX_MIN_HARD_WINDOW_FRACTION = 0.75

GS500ROX_PREFERRED_TIME_MIN = 1400.0
GS500ROX_PREFERRED_TIME_MAX = 4200.0
GS500ROX_ABSOLUTE_TIME_MIN = 1300.0
GS500ROX_HARD_TIME_MIN = 1180.0
GS500ROX_HARD_TIME_MAX = 4550.0
GS500ROX_ABSOLUTE_TIME_MAX = 6000.0
GS500ROX_MAX_FIRST_ANCHOR = 1700.0
GS500ROX_MIN_SPAN = 2500.0
GS500ROX_MIN_MEDIAN_GAP = 36.0
GS500ROX_MIN_HARD_WINDOW_FRACTION = 0.60

LIZ_HARD_TIME_MIN = 1150.0
LIZ_HARD_TIME_MAX = 4300.0
LIZ_MAX_FIRST_ANCHOR = 1700.0
LIZ_MIN_SPAN = 900.0
LIZ_MIN_MEDIAN_GAP = 22.0
LIZ_MIN_HARD_WINDOW_FRACTION = 0.80

_CLI_BIN_CACHE: Path | None = None
_RUST_WORKER: "_RustPrimitiveWorker | None" = None
_RUST_WORKER_LOCK = threading.Lock()
_RUST_PREWARM_WORKERS: list["_RustPrimitiveWorker"] = []
_RUST_PREWARM_WORKERS_LOCK = threading.Lock()
_RUST_RESULT_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_RUST_RESULT_CACHE_LOCK = threading.Lock()


def _windows_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}

    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= startf_use_showwindow
        startupinfo.wShowWindow = sw_hide
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _persistent_rust_worker_supported() -> bool:
    if sys.platform == "win32":
        return False
    return True


class _RustSizingModel:
    def __init__(
        self,
        *,
        strategy: str,
        coefficients: list[float],
        scan_indices: np.ndarray,
        ladder_steps: np.ndarray,
    ) -> None:
        self.strategy = str(strategy or "")
        self.coefficients = np.asarray(coefficients, dtype=float)
        self.scan_indices = np.asarray(scan_indices, dtype=float)
        self.ladder_steps = np.asarray(ladder_steps, dtype=float)

    def predict(self, x_values: np.ndarray) -> np.ndarray:
        x_array = np.asarray(x_values, dtype=float).reshape(-1)
        if self.strategy == "willros_monotone_spline":
            return np.asarray(
                [
                    _eval_monotone_cubic_spline(
                        self.scan_indices,
                        self.ladder_steps,
                        self.coefficients,
                        float(xq),
                    )
                    for xq in x_array
                ],
                dtype=float,
            )
        if self.strategy == "polynomial_fallback":
            return np.asarray(
                [_eval_polynomial(self.coefficients, float(xq)) for xq in x_array],
                dtype=float,
            )
        raise ValueError(f"Unsupported Rust sizing strategy: {self.strategy}")


def _eval_polynomial(coefficients: np.ndarray, x_value: float) -> float:
    return float(
        sum(float(coefficient) * (x_value ** power) for power, coefficient in enumerate(coefficients))
    )


def _eval_monotone_cubic_spline(
    x: np.ndarray,
    y: np.ndarray,
    tangents: np.ndarray,
    x_query: float,
) -> float:
    if x.size == 1:
        return float(y[0])
    if x_query <= float(x[0]):
        return float(y[0] + tangents[0] * (x_query - x[0]))
    if x_query >= float(x[-1]):
        return float(y[-1] + tangents[-1] * (x_query - x[-1]))

    upper = int(np.searchsorted(x, x_query, side="right"))
    index = min(max(upper - 1, 0), x.size - 2)
    step = float(x[index + 1] - x[index])
    if step <= 0.0:
        return float(y[index])
    t = (x_query - float(x[index])) / step
    t2 = t * t
    t3 = t2 * t

    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2

    return float(
        h00 * y[index]
        + h10 * step * tangents[index]
        + h01 * y[index + 1]
        + h11 * step * tangents[index + 1]
    )


def _apply_rust_sizing_model_to_fsa(
    fsa: FsaFile,
    scan_indices: list[int],
    expected_bps: list[float],
    model_preview: dict[str, Any],
) -> FsaFile | None:
    strategy = str(model_preview.get("strategy") or "")
    coefficients = model_preview.get("coefficients")
    if strategy not in {"willros_monotone_spline", "polynomial_fallback"} or not isinstance(coefficients, list):
        return None

    scan_array = np.asarray(scan_indices, dtype=float)
    ladder_array = np.asarray(expected_bps, dtype=float)
    model = _RustSizingModel(
        strategy=strategy,
        coefficients=[float(value) for value in coefficients],
        scan_indices=scan_array,
        ladder_steps=ladder_array,
    )

    sample_trace = np.asarray(getattr(fsa, "sample_data", []), dtype=float)
    if sample_trace.size == 0:
        return None

    time_values = np.arange(sample_trace.size, dtype=float)
    basepairs = model.predict(time_values).round(2)
    sample_df = (
        pd.DataFrame({"time": time_values.astype(int), "peaks": sample_trace, "basepairs": basepairs})
        .loc[lambda df: df["basepairs"] >= 0]
        .reset_index(drop=True)
    )
    if sample_df.empty:
        return None

    fsa.ladder_model = model
    fsa.sample_data_with_basepairs = sample_df
    fsa.fitted_to_model = True
    rust_qc = model_preview.get("qc_metrics")
    if isinstance(rust_qc, dict):
        fsa.rust_ladder_qc_metrics = rust_qc
    return fsa


def _is_rox_ladder(fsa: FsaFile, expected_bps: list[float]) -> bool:
    ladder_name = str(
        getattr(fsa, "rust_detected_ladder", None) or getattr(fsa, "ladder", "") or ""
    ).upper()
    if "LIZ" in ladder_name:
        return False
    if "ROX" in ladder_name:
        return True
    return len(expected_bps) >= 20


def _is_gs500rox_ladder(fsa: FsaFile, expected_bps: list[float]) -> bool:
    ladder_name = str(
        getattr(fsa, "rust_detected_ladder", None) or getattr(fsa, "ladder", "") or ""
    ).upper()
    analysis_id = str(getattr(fsa, "analysis_id", "") or "").lower()
    if "LIZ" in ladder_name:
        return False
    if "GS500ROX" in ladder_name:
        return True
    if analysis_id == "flt3":
        return True
    if len(expected_bps) == 16:
        rounded = {int(round(float(value))) for value in expected_bps}
        return 500 in rounded and 490 in rounded and 35 in rounded
    return False


def _flt3_liz_override_enabled() -> bool:
    raw = (
        os.environ.get("HEMAFRAG_FLT3_LADDER")
        or os.environ.get("HEMAFRAG_FLT3_SIZE_STANDARD")
        or ""
    )
    token = raw.strip().upper().replace("-", "_")
    return token in {"LIZ", "LIZ500", "LIZ500_250", "LIZ500250"}


def _resolve_cli_bin() -> Path | None:
    global _CLI_BIN_CACHE
    if _CLI_BIN_CACHE is not None and _CLI_BIN_CACHE.exists():
        return _CLI_BIN_CACHE

    cli_names = ["fraggler-cli.exe", "fraggler-cli"] if sys.platform == "win32" else ["fraggler-cli"]
    root = Path(__file__).resolve().parent.parent
    if getattr(sys, 'frozen', False):
        bundle_dirs = [
            Path(getattr(sys, "_MEIPASS", "")),
            Path(sys.executable).parent,
            Path(sys.executable).parent / "_internal",
        ]
        for base_dir in bundle_dirs:
            if not base_dir:
                continue
            for cli_name in cli_names:
                cli_bin = base_dir / cli_name
                if cli_bin.exists():
                    _CLI_BIN_CACHE = cli_bin
                    return cli_bin
        return None

    preferred_paths = []
    for cli_name in cli_names:
        preferred_paths.extend(
            [
                root / "fraggler-v2" / "target" / "release" / cli_name,
                root / "fraggler-v2" / "target" / "debug" / cli_name,
                root / "bin" / cli_name,
            ]
        )
    cli_bin = next((p for p in preferred_paths if p.exists()), None)
    if cli_bin is not None:
        _CLI_BIN_CACHE = cli_bin
    return cli_bin


class _RustPrimitiveWorker:
    def __init__(self, cli_bin: Path) -> None:
        self.cli_bin = cli_bin
        self._proc = subprocess.Popen(
            [str(cli_bin), "serve-primitives", "--log-filter", "error"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            **_windows_subprocess_kwargs(),
        )
        self._lock = threading.Lock()

    def close(self) -> None:
        proc = self._proc
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def request(
        self,
        fsa_path: Path,
        analysis_kind: str,
        timeout_seconds: int,
    ) -> dict[str, Any] | None:
        if self._proc.poll() is not None:
            return None
        if self._proc.stdin is None or self._proc.stdout is None:
            return None

        payload = {
            "input": str(fsa_path),
            "analysis": str(analysis_kind or "").lower() or None,
        }

        with self._lock:
            if self._proc.poll() is not None:
                return None
            try:
                self._proc.stdin.write(json.dumps(payload) + "\n")
                self._proc.stdin.flush()
            except Exception:
                return None

            fd = self._proc.stdout.fileno()
            ready, _, _ = select.select([fd], [], [], max(timeout_seconds, 1))
            if not ready:
                self.close()
                return {"error": f"worker timeout after {timeout_seconds}s"}

            line = self._proc.stdout.readline()
            if not line:
                stderr = ""
                if self._proc.stderr is not None:
                    try:
                        stderr = self._proc.stderr.read()[-1000:]
                    except Exception:
                        stderr = ""
                return {"error": f"worker closed unexpectedly: {stderr.strip()}"}
            try:
                response = json.loads(line)
            except Exception as exc:
                return {"error": f"invalid worker response: {exc}"}
            return response

    def request_many(
        self,
        fsa_paths: list[Path],
        analysis_kind: str,
        timeout_seconds: int,
    ) -> dict[str, Any] | None:
        if self._proc.poll() is not None:
            return None
        if self._proc.stdin is None or self._proc.stdout is None:
            return None

        payload = {
            "inputs": [str(path) for path in fsa_paths],
            "analysis": str(analysis_kind or "").lower() or None,
        }

        with self._lock:
            if self._proc.poll() is not None:
                return None
            try:
                self._proc.stdin.write(json.dumps(payload) + "\n")
                self._proc.stdin.flush()
            except Exception:
                return None

            fd = self._proc.stdout.fileno()
            ready, _, _ = select.select([fd], [], [], max(timeout_seconds, 1))
            if not ready:
                self.close()
                return {"error": f"worker timeout after {timeout_seconds}s"}

            line = self._proc.stdout.readline()
            if not line:
                stderr = ""
                if self._proc.stderr is not None:
                    try:
                        stderr = self._proc.stderr.read()[-1000:]
                    except Exception:
                        stderr = ""
                return {"error": f"worker closed unexpectedly: {stderr.strip()}"}
            try:
                response = json.loads(line)
            except Exception as exc:
                return {"error": f"invalid worker response: {exc}"}
            return response


def _get_rust_worker() -> _RustPrimitiveWorker | None:
    global _RUST_WORKER
    if not _persistent_rust_worker_supported():
        return None
    with _RUST_WORKER_LOCK:
        if _RUST_WORKER is not None and _RUST_WORKER._proc.poll() is None:
            return _RUST_WORKER
        cli_bin = _resolve_cli_bin()
        if cli_bin is None or not cli_bin.exists():
            return None
        _RUST_WORKER = _RustPrimitiveWorker(cli_bin)
        return _RUST_WORKER


def _invalidate_rust_worker() -> None:
    global _RUST_WORKER
    with _RUST_WORKER_LOCK:
        if _RUST_WORKER is not None:
            _RUST_WORKER.close()
            _RUST_WORKER = None


def _rust_prewarm_worker_count() -> int:
    from config import APP_SETTINGS

    configured = APP_SETTINGS.get("engine", {}).get("rust_worker_pool_size", "auto")
    if isinstance(configured, str) and configured.strip().lower() == "auto":
        physical_cpu, logical_cpu = _cpu_topology()
        if logical_cpu >= physical_cpu * 2 and physical_cpu >= 2:
            return max(1, min(logical_cpu, physical_cpu + 1))
        return max(1, min(logical_cpu, physical_cpu))
    try:
        desired = int(configured)
    except Exception:
        desired = 1
    if desired <= 0:
        physical_cpu, logical_cpu = _cpu_topology()
        if logical_cpu >= physical_cpu * 2 and physical_cpu >= 2:
            return max(1, min(logical_cpu, physical_cpu + 1))
        return max(1, min(logical_cpu, physical_cpu))
    cpu_count = max(int(os.cpu_count() or 1), 1)
    return max(1, min(desired, cpu_count))


@lru_cache(maxsize=1)
def _cpu_topology() -> tuple[int, int]:
    logical_cpu = max(int(os.cpu_count() or 1), 1)
    physical_cpu = logical_cpu

    if sys.platform == "darwin":
        try:
            output = subprocess.check_output(
                ["sysctl", "-n", "hw.physicalcpu", "hw.logicalcpu"],
                text=True,
                timeout=1.0,
            ).strip().splitlines()
            if len(output) >= 2:
                physical_cpu = max(int(output[0]), 1)
                logical_cpu = max(int(output[1]), 1)
                return physical_cpu, logical_cpu
        except Exception:
            return physical_cpu, logical_cpu

    return physical_cpu, logical_cpu


def _invalidate_rust_worker_pool() -> None:
    global _RUST_PREWARM_WORKERS
    with _RUST_PREWARM_WORKERS_LOCK:
        for worker in _RUST_PREWARM_WORKERS:
            try:
                worker.close()
            except Exception:
                pass
        _RUST_PREWARM_WORKERS = []


def _get_rust_worker_pool(worker_count: int) -> list[_RustPrimitiveWorker]:
    global _RUST_PREWARM_WORKERS
    if not _persistent_rust_worker_supported():
        return []
    with _RUST_PREWARM_WORKERS_LOCK:
        alive = [worker for worker in _RUST_PREWARM_WORKERS if worker._proc.poll() is None]
        if len(alive) == worker_count:
            _RUST_PREWARM_WORKERS = alive
            return list(_RUST_PREWARM_WORKERS)

        for worker in _RUST_PREWARM_WORKERS:
            if worker not in alive:
                try:
                    worker.close()
                except Exception:
                    pass

        if alive:
            for worker in alive:
                try:
                    worker.close()
                except Exception:
                    pass
            alive = []

        cli_bin = _resolve_cli_bin()
        if cli_bin is None or not cli_bin.exists():
            return []
        _RUST_PREWARM_WORKERS = [_RustPrimitiveWorker(cli_bin) for _ in range(worker_count)]
        return list(_RUST_PREWARM_WORKERS)


def _cache_key(fsa_path: Path, analysis_kind: str) -> tuple[str, str]:
    return (str(Path(fsa_path).resolve()), str(analysis_kind or "").lower())


def _store_cached_rust_result(fsa_path: Path, analysis_kind: str, result: dict[str, Any]) -> None:
    with _RUST_RESULT_CACHE_LOCK:
        _RUST_RESULT_CACHE[_cache_key(fsa_path, analysis_kind)] = result


def _pop_cached_rust_result(fsa_path: Path, analysis_kind: str) -> dict[str, Any] | None:
    with _RUST_RESULT_CACHE_LOCK:
        return _RUST_RESULT_CACHE.pop(_cache_key(fsa_path, analysis_kind), None)


def prime_rust_worker_results(
    fsa_paths: list[Path],
    analysis_kind: str,
) -> int:
    if not _persistent_rust_worker_supported():
        return 0

    cli_bin = _resolve_cli_bin()
    if not cli_bin or not cli_bin.exists():
        return 0

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in fsa_paths:
        key = str(Path(path).resolve())
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(Path(path))

    if not unique_paths:
        return 0

    timeout_seconds = max(_rust_timeout_seconds(analysis_kind), 1)
    worker_count = min(_rust_prewarm_worker_count(), len(unique_paths))
    if worker_count <= 1:
        worker = _get_rust_worker()
        if worker is None:
            return 0

        cached = 0
        chunk_size = 16 if analysis_kind.lower() == "clonality" else 8
        for offset in range(0, len(unique_paths), chunk_size):
            chunk = unique_paths[offset: offset + chunk_size]
            response = worker.request_many(chunk, analysis_kind, timeout_seconds)
            if not response or not response.get("ok"):
                if response and response.get("error"):
                    log(f"[RUST ERROR] Worker batch prewarm failed: {response['error']}")
                _invalidate_rust_worker()
                return cached

            results = response.get("results")
            if not isinstance(results, list):
                single = response.get("result")
                results = [single] if isinstance(single, dict) else []

            for path, result in zip(chunk, results):
                if not isinstance(result, dict):
                    continue
                _store_cached_rust_result(path, analysis_kind, result)
                cached += 1
        return cached

    workers = _get_rust_worker_pool(worker_count)
    if len(workers) != worker_count:
        return 0

    shards: list[list[Path]] = [[] for _ in range(worker_count)]
    for index, path in enumerate(unique_paths):
        shards[index % worker_count].append(path)

    shard_results: dict[int, tuple[list[Path], list[dict[str, Any]]]] = {}

    def _prime_shard(
        shard_index: int,
        worker: _RustPrimitiveWorker,
        shard_paths: list[Path],
    ) -> tuple[int, list[Path], list[dict[str, Any]]]:
        response = worker.request_many(shard_paths, analysis_kind, timeout_seconds)
        if not response or not response.get("ok"):
            error = response.get("error") if isinstance(response, dict) else "worker batch prewarm failed"
            raise RuntimeError(str(error))
        results = response.get("results")
        if not isinstance(results, list):
            single = response.get("result")
            results = [single] if isinstance(single, dict) else []
        normalized = [result for result in results if isinstance(result, dict)]
        return shard_index, shard_paths, normalized

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_prime_shard, index, workers[index], shards[index])
                for index in range(worker_count)
                if shards[index]
            ]
            for future in as_completed(futures):
                shard_index, shard_paths, results = future.result()
                shard_results[shard_index] = (shard_paths, results)
    except Exception as exc:
        log(f"[RUST ERROR] Worker pool batch prewarm failed: {exc}")
        _invalidate_rust_worker_pool()
        return 0

    cached = 0
    for shard_index in range(worker_count):
        shard_payload = shard_results.get(shard_index)
        if not shard_payload:
            continue
        shard_paths, results = shard_payload
        for path, result in zip(shard_paths, results):
            _store_cached_rust_result(path, analysis_kind, result)
            cached += 1
    return cached


def _rust_timeout_seconds(analysis_kind: str) -> int:
    from config import APP_SETTINGS

    engine_settings = APP_SETTINGS.get("engine", {})
    kind = str(analysis_kind or "").lower()
    if kind == "rox":
        return int(engine_settings.get("rust_timeout_seconds_rox", engine_settings.get("rust_timeout_seconds", 60)))
    if kind == "liz":
        return int(engine_settings.get("rust_timeout_seconds_liz", engine_settings.get("rust_timeout_seconds", 60)))
    return int(engine_settings.get("rust_timeout_seconds", 60))


def _anchor_intensity(trace: np.ndarray, scan_idx: int) -> float:
    if trace.size == 0:
        return float("nan")
    idx = int(np.clip(scan_idx, 0, trace.size - 1))
    return float(trace[idx])


def _baseline_correct_for_validation(trace: np.ndarray) -> np.ndarray:
    if trace.size == 0:
        return trace
    try:
        baseline = np.asarray(baseline_arPLS(trace), dtype=float)
        if baseline.shape != trace.shape:
            return np.maximum(trace, 0.0)
        return np.maximum(trace - baseline, 0.0)
    except Exception:
        return np.maximum(trace, 0.0)


def _validation_trace_for_fsa(fsa: FsaFile) -> np.ndarray:
    channel_name = str(getattr(fsa, "rust_size_standard_channel", "") or "").strip()
    raw_map = getattr(fsa, "fsa", None)
    if channel_name and isinstance(raw_map, dict):
        channel_values = raw_map.get(channel_name)
        if channel_values is not None:
            try:
                return np.asarray(channel_values, dtype=float)
            except Exception:
                pass
    return np.asarray(getattr(fsa, "size_standard", []), dtype=float)


def _normalized_size_standard_trace_for_fsa(fsa: FsaFile) -> np.ndarray:
    raw_trace = _validation_trace_for_fsa(fsa)
    if raw_trace.size == 0:
        return raw_trace

    existing = np.asarray(getattr(fsa, "size_standard", []), dtype=float)
    if existing.size == raw_trace.size and np.all(np.isfinite(existing)) and float(np.min(existing)) >= 0.0:
        return existing

    corrected = _baseline_correct_for_validation(raw_trace)
    if corrected.size == raw_trace.size and np.all(np.isfinite(corrected)):
        return corrected
    return np.maximum(raw_trace, 0.0)


def _validate_rust_anchor_selection(
    fsa: FsaFile,
    scan_indices: list[int],
    expected_bps: list[float],
) -> tuple[bool, str]:
    if not scan_indices or len(scan_indices) != len(expected_bps):
        return False, "scan/step length mismatch"

    scans = np.asarray(scan_indices, dtype=float)
    if scans.size < 3:
        return False, "too few anchor points"
    if np.any(np.diff(scans) <= 0):
        return False, "anchors are not strictly increasing"

    span = float(scans[-1] - scans[0])
    gaps = np.diff(scans)
    median_gap = float(np.median(gaps)) if gaps.size else 0.0

    size_standard = _validation_trace_for_fsa(fsa)
    validation_trace = _baseline_correct_for_validation(size_standard)
    anchor_signal = np.asarray(
        [_anchor_intensity(validation_trace, int(v)) for v in scan_indices],
        dtype=float,
    )
    median_signal = float(np.nanmedian(anchor_signal)) if anchor_signal.size else float("nan")

    is_gs500rox = _is_gs500rox_ladder(fsa, expected_bps)
    is_rox = _is_rox_ladder(fsa, expected_bps)
    if is_gs500rox:
        if scans[0] < GS500ROX_ABSOLUTE_TIME_MIN:
            return False, f"GS500ROX first anchor before absolute scan limit ({scans[0]:.0f})"
        if scans[-1] > GS500ROX_ABSOLUTE_TIME_MAX:
            return False, f"GS500ROX last anchor beyond absolute scan limit ({scans[-1]:.0f})"
        in_hard = np.logical_and(scans >= GS500ROX_HARD_TIME_MIN, scans <= GS500ROX_HARD_TIME_MAX)
        hard_fraction = float(np.mean(in_hard)) if scans.size else 0.0
        if hard_fraction < GS500ROX_MIN_HARD_WINDOW_FRACTION:
            return False, f"GS500ROX anchors mostly outside expected time window ({hard_fraction:.2f})"
        if scans[0] > GS500ROX_MAX_FIRST_ANCHOR:
            return False, f"GS500ROX first anchor too late ({scans[0]:.0f})"
        if not (GS500ROX_PREFERRED_TIME_MIN <= float(np.median(scans)) <= GS500ROX_PREFERRED_TIME_MAX):
            return False, f"GS500ROX median anchor outside preferred window ({np.median(scans):.0f})"
        if span < GS500ROX_MIN_SPAN:
            return False, f"GS500ROX anchor span too small ({span:.0f})"
        if median_gap < GS500ROX_MIN_MEDIAN_GAP:
            return False, f"GS500ROX anchors too tightly clustered (median gap {median_gap:.1f})"
        if np.isfinite(median_signal) and median_signal < 20.0:
            return False, f"GS500ROX anchor signal too weak (median {median_signal:.1f})"
        return True, "GS500ROX anchor checks passed"

    if is_rox:
        in_hard = np.logical_and(scans >= ROX_HARD_TIME_MIN, scans <= ROX_HARD_TIME_MAX)
        hard_fraction = float(np.mean(in_hard)) if scans.size else 0.0
        if hard_fraction < ROX_MIN_HARD_WINDOW_FRACTION:
            return False, f"ROX anchors mostly outside expected time window ({hard_fraction:.2f})"
        if scans[0] > ROX_MAX_FIRST_ANCHOR:
            return False, f"ROX first anchor too late ({scans[0]:.0f})"
        if not (ROX_PREFERRED_TIME_MIN <= float(np.median(scans)) <= ROX_PREFERRED_TIME_MAX):
            return False, f"ROX median anchor outside preferred window ({np.median(scans):.0f})"
        if span < ROX_MIN_SPAN:
            return False, f"ROX anchor span too small ({span:.0f})"
        if median_gap < ROX_MIN_MEDIAN_GAP:
            return False, f"ROX anchors too tightly clustered (median gap {median_gap:.1f})"
        if np.isfinite(median_signal) and median_signal < 45.0:
            return False, f"ROX anchor signal too weak (median {median_signal:.1f})"
        return True, "ROX anchor checks passed"

    in_hard = np.logical_and(scans >= LIZ_HARD_TIME_MIN, scans <= LIZ_HARD_TIME_MAX)
    hard_fraction = float(np.mean(in_hard)) if scans.size else 0.0
    if hard_fraction < LIZ_MIN_HARD_WINDOW_FRACTION:
        return False, f"LIZ anchors mostly outside expected time window ({hard_fraction:.2f})"
    if scans[0] > LIZ_MAX_FIRST_ANCHOR:
        return False, f"LIZ first anchor too late ({scans[0]:.0f})"
    if span < LIZ_MIN_SPAN:
        return False, f"LIZ anchor span too small ({span:.0f})"
    if median_gap < LIZ_MIN_MEDIAN_GAP:
        return False, f"LIZ anchors too tightly clustered (median gap {median_gap:.1f})"
    if np.isfinite(median_signal) and median_signal < 35.0:
        return False, f"LIZ anchor signal too weak (median {median_signal:.1f})"

    # LIZ control failures often start by missing the 35/50 bp anchors and
    # replacing them with low baseline shoulders or dye blobs. Tighten the
    # first-anchor checks so these fits are rejected before hydration.
    first_signals = anchor_signal[: min(3, anchor_signal.size)]
    relaxed_external_liz_first_anchor = False
    if first_signals.size:
        first_signal = float(first_signals[0])
        median_first_signal = float(np.nanmedian(first_signals))
        relaxed_external_liz_first_anchor = (
            _flt3_liz_override_enabled()
            and np.isfinite(first_signal)
            and np.isfinite(median_first_signal)
            and first_signal >= 100.0
        )
        if first_signal < 55.0:
            return False, f"LIZ first anchor too weak ({first_signal:.1f})"
        if (
            np.isfinite(median_first_signal)
            and first_signal < median_first_signal * 0.55
            and not relaxed_external_liz_first_anchor
        ):
            return False, f"LIZ first anchor too weak relative to early ladder ({first_signal:.1f})"

    first_anchor = int(round(float(scans[0])))
    second_anchor = int(round(float(scans[1])))
    if 0 <= first_anchor < validation_trace.size:
        first_height = float(validation_trace[first_anchor])
        local_window = validation_trace[max(0, first_anchor - 20): min(validation_trace.size, second_anchor + 1)]
        if local_window.size:
            local_max = float(np.max(local_window))
            if (
                first_height < max(35.0, local_max * 0.20)
                and not relaxed_external_liz_first_anchor
            ):
                return False, f"LIZ first anchor looks like baseline ({first_height:.1f} vs local max {local_max:.1f})"

    first_gap = float(scans[1] - scans[0]) if scans.size >= 2 else float("inf")
    if first_gap > 95.0 and not (_flt3_liz_override_enabled() and first_gap <= 160.0):
        return False, f"LIZ first gap too large ({first_gap:.1f})"

    return True, "LIZ anchor checks passed"


def _allow_guardrail_review_hydration(
    fsa: FsaFile,
    reason: str,
    review_assessment: dict[str, Any] | None,
    model_preview: dict[str, Any] | None,
    scan_indices: list[int],
    expected_bps: list[float],
) -> bool:
    if not isinstance(review_assessment, dict) or not isinstance(model_preview, dict):
        return False

    qc_metrics = model_preview.get("qc_metrics")
    if not isinstance(qc_metrics, dict):
        return False
    if len(scan_indices) != len(expected_bps):
        return False
    if not bool(qc_metrics.get("monotonic_on_ladder", False)):
        return False

    if _is_gs500rox_ladder(fsa, expected_bps):
        linear_max = float(qc_metrics.get("linear_trend_max_abs_error_bp", float("inf")))
        linear_mean = float(qc_metrics.get("linear_trend_mean_abs_error_bp", float("inf")))
        linear_r2 = float(qc_metrics.get("linear_trend_r2", float("-inf")))
        max_abs_error_bp = float(qc_metrics.get("max_abs_error_bp", float("inf")))

        if not (
            np.isfinite(linear_max)
            and np.isfinite(linear_mean)
            and np.isfinite(linear_r2)
            and np.isfinite(max_abs_error_bp)
        ):
            return False
        if len(scan_indices) != len(expected_bps) or len(scan_indices) < 16:
            return False

        first_anchor = float(scan_indices[0]) if scan_indices else float("inf")
        last_anchor = float(scan_indices[-1]) if scan_indices else float("-inf")
        if last_anchor > GS500ROX_ABSOLUTE_TIME_MAX:
            return False
        span = last_anchor - first_anchor
        lower_reason = reason.lower()
        acceptable_linear = (
            linear_max <= 6.0
            and linear_mean <= 3.0
            and linear_r2 >= 0.9985
            and max_abs_error_bp <= 1.0
        )
        strict_span = span >= GS500ROX_MIN_SPAN and last_anchor >= 4500.0
        compact_3730_span = (
            span >= 2480.0
            and last_anchor >= 3900.0
            and first_anchor <= 1600.0
        )
        acceptable_span = strict_span or compact_3730_span
        acceptable_guardrail_reason = (
            "first anchor too late" in lower_reason
            or "anchor span too small" in lower_reason
            or "blob" in lower_reason
            or "weak_start_region" in lower_reason
        )
        if not (
            acceptable_linear
            and acceptable_span
            and acceptable_guardrail_reason
            and first_anchor <= 2000.0
        ):
            return False

        log(
            f"[RUST REVIEW] Accepting guarded GS500ROX fit for {fsa.file_name} despite anchor warning: {reason}. "
            "The fit remains Rust-owned and avoids Python fallback blob/tail remapping."
        )
        return True

    if _is_rox_ladder(fsa, expected_bps):
        linear_max = float(qc_metrics.get("linear_trend_max_abs_error_bp", float("inf")))
        linear_mean = float(qc_metrics.get("linear_trend_mean_abs_error_bp", float("inf")))
        linear_r2 = float(qc_metrics.get("linear_trend_r2", float("-inf")))
        max_abs_error_bp = float(qc_metrics.get("max_abs_error_bp", float("inf")))

        if not (
            np.isfinite(linear_max)
            and np.isfinite(linear_mean)
            and np.isfinite(linear_r2)
            and np.isfinite(max_abs_error_bp)
        ):
            return False
        if len(scan_indices) < 19:
            return False

        acceptable_linear = (
            linear_max <= 8.0
            and linear_mean <= 3.0
            and linear_r2 >= 0.9985
            and max_abs_error_bp <= 1.5
        )
        if not acceptable_linear:
            return False

        lower_reason = reason.lower()
        if "first anchor too late" not in lower_reason and "anchor signal too weak" not in lower_reason:
            return False

        log(
            f"[RUST REVIEW] Accepting guarded ROX fit for {fsa.file_name} despite anchor warning: {reason}. "
            "The fit remains Rust-owned and may still be marked for review downstream."
        )
        return True

    return False


def run_ladder_fit_hybrid(fsa: FsaFile, analysis_kind: str) -> FsaFile | None:
    """
    Passes the FSA file to the fraggler-cli to perform baseline correction,
    peak detection, and ladder fitting. Retrieves the mapped ladder steps 
    and applies them directly to the Python FsaFile.
    """
    cli_bin = _resolve_cli_bin()
    if not cli_bin or not cli_bin.exists():
        log("[RUST ERROR] Could not find fraggler-cli. Rust runtime analysis cannot continue.")
        return None

    fsa_path = Path(fsa.file)
    timeout_seconds = max(_rust_timeout_seconds(analysis_kind), 1)
    started = time.monotonic()
    cached = _pop_cached_rust_result(fsa_path, analysis_kind)
    if isinstance(cached, dict):
        elapsed = time.monotonic() - started
        log(f"[RUST] Using prewarmed worker result for {fsa.file_name} after {elapsed:.1f}s")
        return _apply_rust_result_to_fsa(fsa, cached)

    worker = _get_rust_worker()
    if worker is not None:
        worker_response = worker.request(fsa_path, analysis_kind, timeout_seconds)
        if worker_response and worker_response.get("ok") and worker_response.get("result"):
            elapsed = time.monotonic() - started
            log(f"[RUST] Worker finished in {elapsed:.1f}s for {fsa.file_name}")
            res = worker_response["result"]
        else:
            if worker_response and worker_response.get("error"):
                elapsed = time.monotonic() - started
                log(f"[RUST ERROR] Worker failed after {elapsed:.1f}s for {fsa.file_name}: {worker_response['error']}")
            _invalidate_rust_worker()
            res = None
    else:
        res = None

    if res is None:
        res = _run_cli_once(cli_bin, fsa_path, analysis_kind, fsa.file_name)
        if res is None:
            return None

    return _apply_rust_result_to_fsa(fsa, res)


def _run_cli_once(cli_bin: Path, fsa_path: Path, analysis_kind: str, file_name: str) -> dict[str, Any] | None:
    with tempfile.TemporaryDirectory(prefix="fraggler_hybrid_") as tdir:
        tdir_path = Path(tdir)
        from config import APP_SETTINGS
        skip_html_reports = APP_SETTINGS.get("engine", {}).get("skip_html_reports", False)

        req = {
            "contract_version": {"major": 1, "minor": 0},
            "run_kind": "analyze",
            "analysis_kind": analysis_kind,
            "correlation_id": "00000000-0000-0000-0000-000000000000",
            "inputs": {
                "paths": [str(fsa_path)],
                "manifest_path": None,
                "report_source_path": None
            },
            "output": {
                "root_dir": str(tdir_path),
                "report_dir": None,
                "artifacts_dir": None
            },
            "options": {
                "max_workers": 1,
                "deterministic": True,
                "emit_compact_json": True,
                "open_reports_in_browser": False,
                "shadow_reference_python": False,
                "skip_html_reports": skip_html_reports,
                "extra": {}
            }
        }
        
        req_path = tdir_path / "req.json"
        with open(req_path, "w") as f:
            json.dump(req, f)

        cmd = [str(cli_bin), "analyze", "--json-request", str(req_path)]
        import time
        start_time = time.monotonic()
        timeout_seconds = max(_rust_timeout_seconds(analysis_kind), 1)
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,
                stdin=subprocess.DEVNULL,
                **_windows_subprocess_kwargs(),
            )
            elapsed = time.monotonic() - start_time
            log(f"[RUST] Engine finished in {elapsed:.1f}s for {file_name}")
        except subprocess.TimeoutExpired as e:
            log(
                f"[RUST ERROR] CLI timed out after {timeout_seconds}s for {file_name}. "
                f"Stderr: {e.stderr}"
            )
            return None
        except subprocess.CalledProcessError as e:
            log(f"[RUST ERROR] CLI failed with code {e.returncode} for {file_name}. Stderr: {e.stderr}")
            return None

        summary_path = tdir_path / "analyze_summary.json"
        if not summary_path.exists():
            log("[RUST ERROR] Missing analyze_summary.json from Rust engine.")
            return None

        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                results = json.load(f)
        except Exception as e:
            log(f"[RUST ERROR] Failed to parse analyze_summary.json: {e}")
            return None
            
        if not results:
            log("[RUST ERROR] results is empty")
            return None
        return results[0]


def _apply_rust_result_to_fsa(fsa: FsaFile, res: dict[str, Any]) -> FsaFile | None:
    review_assessment = res.get("ladder_review_assessment")
    if isinstance(review_assessment, dict):
        fsa.rust_ladder_review_assessment = review_assessment
        fsa.rust_review_reason_codes = list(review_assessment.get("reason_codes") or [])
        fsa.rust_review_primary_reason = review_assessment.get("primary_reason")
        fsa.rust_review_summary = str(review_assessment.get("summary") or "")
    detected_ladder = res.get("ladder")
    if isinstance(detected_ladder, str) and detected_ladder:
        fsa.rust_detected_ladder = detected_ladder
    size_standard_guess = res.get("size_standard_channel_guess")
    if isinstance(size_standard_guess, str) and size_standard_guess:
        fsa.rust_size_standard_channel = size_standard_guess
    flt3_preview = res.get("flt3_preview")
    if isinstance(flt3_preview, dict):
        fsa.rust_flt3_preview = flt3_preview
    ladder_peak_preview = res.get("ladder_peak_preview")
    if isinstance(ladder_peak_preview, list):
        fsa.rust_ladder_peak_preview = ladder_peak_preview
    clonality_preview = res.get("clonality_preview")
    if isinstance(clonality_preview, dict):
        fsa.rust_clonality_preview = clonality_preview

    fit_preview = res.get("ladder_fit_preview")
    if not fit_preview:
        log("[RUST ERROR] ladder_fit_preview missing")
        return None

    refinement = fit_preview.get("refinement")
    if refinement and refinement.get("refined_scan_indices"):
        scan_indices = refinement["refined_scan_indices"]
    else:
        scan_indices = fit_preview.get("best_scan_indices", [])

    if not scan_indices:
        log(f"[RUST ERROR] scan_indices empty for {fsa.file_name}")
        if res and isinstance(res, dict) and res.get("stderr"):
            log(f"[RUST DIAG] Stderr: {res.get('stderr').strip()}")
        return None

    model_preview = fit_preview.get("sizing_model")
    if not model_preview or not model_preview.get("predicted_ladder_basepairs"):
        log("[RUST ERROR] model_preview missing predicted_ladder_basepairs")
        return None

    expected_bps = model_preview["predicted_ladder_basepairs"]
    if len(scan_indices) != len(expected_bps):
        log(
            f"[RUST ERROR] Mismatch between selected scan indices ({len(scan_indices)}) "
            f"and predicted basepairs ({len(expected_bps)})."
        )
        return None

    ok, reason = _validate_rust_anchor_selection(fsa, scan_indices, expected_bps)
    if not ok:
        if not _allow_guardrail_review_hydration(
            fsa,
            reason,
            review_assessment if isinstance(review_assessment, dict) else None,
            model_preview if isinstance(model_preview, dict) else None,
            scan_indices,
            expected_bps,
        ):
            log(
                f"[RUST GUARDRAIL] Rejected anchor set for {fsa.file_name}: {reason}. "
                "Returning control to the runtime without Python rescue."
            )
            return None
        fsa.rust_guardrail_review_required = True
        fsa.ladder_review_required = True
        fsa.rust_review_primary_reason = reason
        reason_codes = list(getattr(fsa, "rust_review_reason_codes", []) or [])
        if "guarded_gs500rox_anchor_family" not in reason_codes:
            reason_codes.append("guarded_gs500rox_anchor_family")
        fsa.rust_review_reason_codes = reason_codes
        existing_summary = str(getattr(fsa, "rust_review_summary", "") or "")
        fsa.rust_review_summary = (
            f"{existing_summary}; Guardrail accepted for manual review: {reason}"
            if existing_summary
            else f"Guardrail accepted for manual review: {reason}"
        )

    fsa.best_size_standard = np.array(scan_indices, dtype=float)
    fsa.ladder_steps = np.array(expected_bps, dtype=float)
    fsa.expected_ladder_steps = np.array(expected_bps, dtype=float)
    normalized_size_standard = _normalized_size_standard_trace_for_fsa(fsa)
    if normalized_size_standard.size:
        fsa.size_standard = normalized_size_standard
        fsa.size_standard_baseline_corrected = True

    hydrated = _apply_rust_sizing_model_to_fsa(fsa, scan_indices, expected_bps, model_preview)
    if hydrated is not None:
        return hydrated

    if strict_rust_ladder_enabled():
        log(
            f"[STRICT RUST] Rust sizing model could not hydrate {fsa.file_name}; "
            "Python ladder fallback is disabled."
        )
        return None

    try:
        fsa = fit_size_standard_to_ladder(fsa)
    except Exception as e:
        log(f"[HYBRID ERROR] fit_size_standard_to_ladder failed: {e}")
        return None

    return fsa
