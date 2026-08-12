from __future__ import annotations

import os

from core.concurrency import (
    concurrency_environment,
    initialize_worker_concurrency,
    resolve_concurrency_plan,
)


def test_concurrency_plan_never_multiplies_past_machine_budget(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 16)

    plan = resolve_concurrency_plan(
        requested_outer_workers=8,
        task_count=25,
        cpu_budget=12,
    )

    assert plan.cpu_budget == 12
    assert plan.outer_workers == 8
    assert plan.rust_threads_per_worker == 1
    assert plan.outer_workers * plan.rust_threads_per_worker <= plan.cpu_budget
    assert plan.numeric_threads_per_worker == 1


def test_concurrency_plan_gives_inner_threads_to_small_outer_pool(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 16)

    plan = resolve_concurrency_plan(
        requested_outer_workers=2,
        task_count=25,
        cpu_budget=12,
    )

    assert plan.outer_workers == 2
    assert plan.rust_threads_per_worker == 6
    assert plan.numeric_threads_per_worker == 1


def test_low_memory_mode_caps_outer_workers(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 16)

    plan = resolve_concurrency_plan(
        requested_outer_workers=8,
        task_count=25,
        cpu_budget=12,
        low_memory=True,
    )

    assert plan.outer_workers == 2
    assert plan.low_memory is True


def test_worker_initializer_sets_rust_and_numeric_thread_limits(monkeypatch):
    for name in (
        "RAYON_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)

    initialize_worker_concurrency(3, 1)

    assert os.environ["RAYON_NUM_THREADS"] == "3"
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert os.environ["OPENBLAS_NUM_THREADS"] == "1"


def test_concurrency_environment_restores_existing_values(monkeypatch):
    monkeypatch.setenv("RAYON_NUM_THREADS", "99")
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    plan = resolve_concurrency_plan(
        requested_outer_workers=4,
        task_count=8,
        cpu_budget=8,
    )

    with concurrency_environment(plan):
        assert os.environ["RAYON_NUM_THREADS"] == "2"
        assert os.environ["OMP_NUM_THREADS"] == "1"

    assert os.environ["RAYON_NUM_THREADS"] == "99"
    assert "OMP_NUM_THREADS" not in os.environ
