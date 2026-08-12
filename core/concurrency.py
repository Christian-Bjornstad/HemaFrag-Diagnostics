"""One machine-level concurrency budget for Python and Rust work."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ConcurrencyPlan:
    cpu_budget: int
    outer_workers: int
    rust_threads_per_worker: int
    numeric_threads_per_worker: int
    low_memory: bool

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return max(1, int(default))
    return max(1, parsed)


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_concurrency_plan(
    *,
    requested_outer_workers: int | None,
    task_count: int,
    cpu_budget: int | None = None,
    low_memory: bool | None = None,
) -> ConcurrencyPlan:
    logical_cpus = max(1, int(os.cpu_count() or 1))
    default_budget = max(1, logical_cpus - 1)
    budget = _positive_int(
        cpu_budget if cpu_budget is not None else os.environ.get("HEMAFRAG_CPU_BUDGET"),
        default_budget,
    )
    budget = min(budget, logical_cpus)
    memory_mode = _env_enabled("HEMAFRAG_LOW_MEMORY") if low_memory is None else bool(low_memory)
    requested = _positive_int(requested_outer_workers, min(4, budget))
    outer_limit = min(max(1, int(task_count or 1)), budget)
    if memory_mode:
        outer_limit = min(outer_limit, 2)
    outer = min(requested, outer_limit)
    rust_threads = max(1, budget // outer)
    numeric_threads = 1 if outer > 1 else rust_threads
    return ConcurrencyPlan(
        cpu_budget=budget,
        outer_workers=outer,
        rust_threads_per_worker=rust_threads,
        numeric_threads_per_worker=numeric_threads,
        low_memory=memory_mode,
    )


def initialize_worker_concurrency(
    rust_threads_per_worker: int,
    numeric_threads_per_worker: int,
) -> None:
    rust_threads = _positive_int(rust_threads_per_worker, 1)
    numeric_threads = _positive_int(numeric_threads_per_worker, 1)
    os.environ["RAYON_NUM_THREADS"] = str(rust_threads)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = str(numeric_threads)


@contextmanager
def concurrency_environment(plan: ConcurrencyPlan):
    names = (
        "RAYON_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    previous = {name: os.environ.get(name) for name in names}
    initialize_worker_concurrency(
        plan.rust_threads_per_worker,
        plan.numeric_threads_per_worker,
    )
    try:
        yield plan
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


__all__ = [
    "ConcurrencyPlan",
    "concurrency_environment",
    "initialize_worker_concurrency",
    "resolve_concurrency_plan",
]
