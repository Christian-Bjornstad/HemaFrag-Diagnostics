from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.benchmark_fsa_artifact_cache import (
    BENCHMARK_SCHEMA,
    _entry_identity,
    _summary,
)


def test_artifact_benchmark_identity_contains_ladder_result_not_raw_trace():
    entry = {
        "assay": "TCRbA",
        "ladder_qc_status": "ok",
        "ladder_fit_strategy": "auto_full",
        "ladder_r2": 1.0,
        "ladder_linear_r2": 0.9999,
        "ladder_linear_max_residual_bp": 2.0,
        "fsa": SimpleNamespace(
            best_size_standard=[100.0, 200.0],
            ladder_steps=[50.0, 60.0],
            fsa={"DATA1": [1, 2, 3]},
        ),
    }

    identity = _entry_identity(entry)

    assert identity["anchor_times"] == [100.0, 200.0]
    assert identity["ladder_steps"] == [50.0, 60.0]
    assert "fsa" not in identity
    assert BENCHMARK_SCHEMA.endswith("_v1")


def test_artifact_benchmark_summary_reports_determinism():
    rows = [
        {
            "duration_seconds": 0.1,
            "result_fingerprint": "same",
            "artifact_stats": {"decode_count": 1},
        },
        {
            "duration_seconds": 0.2,
            "result_fingerprint": "same",
            "artifact_stats": {"decode_count": 1},
        },
    ]

    summary = _summary(rows)

    assert summary["deterministic"] is True
    assert summary["median_seconds"] == pytest.approx(0.15)
    assert summary["decode_counts"] == [1, 1]
