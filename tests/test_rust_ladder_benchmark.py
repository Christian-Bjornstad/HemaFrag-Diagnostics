from __future__ import annotations

import json

import pytest

from scripts.benchmark_rust_ladder import (
    BENCHMARK_SCHEMA,
    _load_gold_expectations,
    _load_manifest,
    _percentile,
    _result_identity,
    _stable_fingerprint,
)


def test_ladder_benchmark_identity_ignores_non_fit_metadata():
    result = {
        "file_name": "sensitive-name.fsa",
        "ladder": "LIZ500_250",
        "size_standard_channel_guess": "DATA105",
        "ladder_fit_preview": {
            "best_scan_indices": [10, 20, 30],
            "sizing_model": {
                "predicted_ladder_basepairs": [35.0, 50.0, 75.0],
                "qc_metrics": {
                    "r2": 0.999,
                    "mean_abs_error_bp": 0.1,
                    "max_abs_error_bp": 0.2,
                    "linear_trend_mean_abs_error_bp": 1.0,
                    "linear_trend_max_abs_error_bp": 2.0,
                    "linear_trend_r2": 0.9991,
                    "monotonic_on_ladder": True,
                },
            },
        },
        "ladder_review_assessment": {
            "suggested_review": False,
            "reason_codes": [],
            "selected_baseline_like_anchor_count": 2,
            "selected_cleaner_neighbor_count": 1,
            "selected_strong_baseline_anchor_count": 1,
        },
        "timings_us": {"total": 123},
    }
    identity = _result_identity(result)
    assert "file_name" not in identity
    assert "timings_us" not in identity
    assert identity["scan_indices"] == [10, 20, 30]
    assert identity["expected_basepairs"] == [35.0, 50.0, 75.0]
    assert identity["selected_baseline_like_anchor_count"] == 2
    assert identity["selected_cleaner_neighbor_count"] == 1
    assert identity["selected_strong_baseline_anchor_count"] == 1


def test_ladder_benchmark_identity_prefers_refined_scans():
    result = {
        "ladder_fit_preview": {
            "best_scan_indices": [10, 20],
            "refinement": {"refined_scan_indices": [11, 21]},
            "sizing_model": {},
        }
    }
    assert _result_identity(result)["scan_indices"] == [11, 21]


def test_ladder_benchmark_fingerprint_is_stable():
    left = {"b": [2, 3], "a": 1}
    right = {"a": 1, "b": [2, 3]}
    assert _stable_fingerprint(left) == _stable_fingerprint(right)


def test_ladder_benchmark_percentile_interpolates():
    assert _percentile([1.0, 2.0, 3.0], 0.5) == pytest.approx(2.0)
    assert _percentile([1.0, 3.0], 0.95) == pytest.approx(2.9)


def test_ladder_benchmark_manifest_supports_list_and_object(tmp_path):
    first = tmp_path / "first.fsa"
    second = tmp_path / "second.fsa"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    list_manifest = tmp_path / "list.json"
    list_manifest.write_text(json.dumps([str(first), str(second)]), encoding="utf-8")
    assert _load_manifest(list_manifest) == [first.resolve(), second.resolve()]

    object_manifest = tmp_path / "object.json"
    object_manifest.write_text(
        json.dumps({"schema": BENCHMARK_SCHEMA, "files": [{"path": str(first)}]}),
        encoding="utf-8",
    )
    assert _load_manifest(object_manifest) == [first.resolve()]
    assert _load_gold_expectations(object_manifest) == {}


def test_ladder_benchmark_loads_optional_manual_gold(tmp_path):
    input_file = tmp_path / "manual.fsa"
    input_file.write_bytes(b"fixture")
    manifest = tmp_path / "gold.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": str(input_file),
                        "expected_scan_indices": [10.0, 20.2, 31],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert _load_gold_expectations(manifest) == {
        input_file.resolve(): [10, 20, 31]
    }
