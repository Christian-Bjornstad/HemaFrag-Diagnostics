from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import benchmark_rust_ladder as benchmark_module
from scripts.benchmark_rust_ladder import (
    BENCHMARK_SCHEMA,
    _load_gold_expectations,
    _load_manifest,
    _load_manifest_metadata,
    _gold_anchor_metrics,
    _percentile,
    _result_identity,
    _run_once,
    _stable_fingerprint,
    _taxonomy_comparison,
    benchmark,
    evaluate_fit_candidate,
)


def test_ladder_benchmark_identity_ignores_non_fit_metadata():
    result = {
        "file_name": "sensitive-name.fsa",
        "ladder": "LIZ500_250",
        "size_standard_channel_guess": "DATA105",
        "ladder_fit_preview": {
            "best_scan_indices": [10, 20, 30],
            "search_diagnostics": {
                "fit_tier": "deep_rescue_10s",
                "elapsed_us": 12345,
            },
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
    assert "elapsed_us" not in identity["search_diagnostics"]


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
    content_hash = hashlib.sha256(input_file.read_bytes()).hexdigest()
    manifest = tmp_path / "gold.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": str(input_file),
                        "content_sha256": content_hash,
                        "expected_scan_indices": [10.0, 20.2, 31],
                        "review_approved": True,
                        "review_label": "manual_adjusted",
                        "reviewed_at_utc": "2026-08-11T08:00:00+00:00",
                        "reviewed_by": "chemist",
                        "analysis_id": "clonality",
                        "identity_key": "patient-001",
                        "sample_kind": "patient",
                        "gold_eligible": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert _load_gold_expectations(manifest) == {
        input_file.resolve(): [10, 20, 31]
    }


def test_ladder_benchmark_does_not_load_unapproved_gold_expectations(tmp_path):
    input_file = tmp_path / "provisional.fsa"
    input_file.write_bytes(b"fixture")
    manifest = tmp_path / "provisional.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": str(input_file),
                        "expected_scan_indices": [10, 20, 31],
                        "review_approved": False,
                        "analysis_id": "clonality",
                        "sample_kind": "patient",
                        "gold_eligible": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _load_gold_expectations(manifest) == {}


@pytest.mark.parametrize(
    ("field", "value"),
    (("identity_key", ""), ("content_sha256", "not-a-sha256")),
)
def test_ladder_benchmark_rejects_gold_without_bound_identity_or_hash(
    tmp_path, field, value
):
    input_file = tmp_path / "manual.fsa"
    input_file.write_bytes(b"fixture")
    entry = {
        "path": str(input_file),
        "content_sha256": hashlib.sha256(input_file.read_bytes()).hexdigest(),
        "expected_scan_indices": [10, 20, 31],
        "review_approved": True,
        "review_label": "manual_adjusted",
        "reviewed_at_utc": "2026-08-11T08:00:00+00:00",
        "reviewed_by": "chemist",
        "analysis_id": "clonality",
        "identity_key": "patient-001",
        "sample_kind": "patient",
        "gold_eligible": True,
    }
    entry[field] = value
    manifest = tmp_path / "invalid-gold.json"
    manifest.write_text(json.dumps({"files": [entry]}), encoding="utf-8")

    assert _load_gold_expectations(manifest) == {}


def test_ladder_benchmark_loads_research_case_metadata(tmp_path):
    input_file = tmp_path / "manual.fsa"
    input_file.write_bytes(b"fixture")
    manifest = tmp_path / "research.json"
    manifest.write_text(
        json.dumps(
            {
                "partition": "locked_validation",
                "files": [
                    {
                        "path": str(input_file),
                        "expected_scan_indices": [10, 20],
                        "failure_family": "fit_rejected_with_usable_signal",
                        "truth_source": "manual_v2",
                        "ladder": "LIZ",
                        "content_sha256": "abc",
                        "physical_run_key": "2026_data/run-a",
                        "review_approved": True,
                        "review_label": "manual_adjusted",
                        "reviewed_at_utc": "2026-08-11T08:00:00+00:00",
                        "reviewed_by": "chemist",
                        "analysis_id": "clonality",
                        "identity_key": "patient-001",
                        "sample_kind": "patient",
                        "gold_eligible": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _load_manifest_metadata(manifest) == {
        input_file.resolve(): {
            "partition": "locked_validation",
            "failure_family": "fit_rejected_with_usable_signal",
            "truth_source": "manual_v2",
            "ladder": "LIZ",
            "content_sha256": "abc",
            "physical_run_key": "2026_data/run-a",
            "review_approved": "True",
            "review_label": "manual_adjusted",
            "reviewed_at_utc": "2026-08-11T08:00:00+00:00",
            "reviewed_by": "chemist",
            "analysis_id": "clonality",
            "identity_key": "patient-001",
            "sample_kind": "patient",
            "gold_eligible": "True",
        }
    }


def test_ladder_benchmark_manifest_rejects_hash_mismatch_before_execution(tmp_path):
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {"path": str(input_file), "content_sha256": "0" * 64}
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        _load_manifest(manifest)


def test_ladder_benchmark_manifest_rejects_duplicate_content(tmp_path):
    first = tmp_path / "first.fsa"
    second = tmp_path / "second.fsa"
    first.write_bytes(b"same fixture")
    second.write_bytes(b"same fixture")
    content_hash = hashlib.sha256(first.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {"path": str(first), "content_sha256": content_hash},
                    {"path": str(second), "content_sha256": content_hash},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate content"):
        _load_manifest(manifest)


def test_ladder_benchmark_runner_is_deterministic_and_bounded(tmp_path):
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli")
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    output_dir = tmp_path / "output"
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        output_dir.mkdir()
        (output_dir / "analyze_summary.json").write_text(
            json.dumps([{"ladder_fit_preview": {}}]), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    _elapsed, result = _run_once(
        cli,
        input_file,
        output_dir,
        timeout_seconds=7,
        run_command=fake_run,
    )

    assert "--deterministic" in observed["command"]
    assert observed["kwargs"]["timeout"] == 7
    assert result == {"ladder_fit_preview": {}}


@pytest.mark.parametrize(
    ("historical", "engine", "agreement", "status"),
    (
        (
            "fit_accepted_but_wrong",
            "unresolved",
            None,
            "not_applicable_human_label_required",
        ),
        (
            "fit_correct_review_only",
            "unresolved",
            None,
            "not_applicable_human_label_required",
        ),
        (
            "missing_ladder_signal",
            "fit_rejected_with_usable_signal",
            False,
            "model_transition",
        ),
        ("unresolved", "unresolved", True, "agreement"),
    ),
)
def test_ladder_benchmark_taxonomy_marks_human_labels_and_model_transitions(
    historical, engine, agreement, status
):
    assert _taxonomy_comparison(historical, engine) == (agreement, status)


def test_ladder_benchmark_reports_all_repeat_tail_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli")
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    content_hash = hashlib.sha256(input_file.read_bytes()).hexdigest()
    durations = iter((1.0, 2.0, 100.0))

    def fake_run_once(
        _cli, _input_file, _output_dir, *, timeout_seconds, run_command=None
    ):
        assert timeout_seconds == 9
        return next(durations), {
            "ladder": "LIZ500_250",
            "ladder_peak_count": 20,
            "ladder_fit_preview": {
                "best_scan_indices": [10, 20],
                "sizing_model": {},
            },
            "ladder_review_assessment": {
                "suggested_review": False,
                "reason_codes": [],
            },
            "timings_us": {"ladder_fit": 1_000_000},
        }

    monkeypatch.setattr(benchmark_module, "_run_once", fake_run_once)

    result = benchmark(
        [input_file],
        cli=cli,
        repeats=3,
        warmups=0,
        timeout_seconds=9,
        case_metadata={
            input_file.resolve(): {
                "content_sha256": content_hash,
                "physical_run_key": "run-a",
                "failure_family": "fit_accepted_but_wrong",
                "ladder": "LIZ",
            }
        },
    )

    row = result["files"][0]
    summary = result["by_ladder"]["LIZ500_250"]
    assert result["configuration"]["timeout_seconds"] == 9
    assert row["p95_seconds"] == pytest.approx(90.2)
    assert result["overall"]["p95_seconds"] == pytest.approx(90.2)
    assert summary["repeat_count"] == 3
    assert summary["p95_seconds"] == pytest.approx(90.2)
    assert row["taxonomy_agreement"] is None
    assert (
        row["taxonomy_comparison_status"]
        == "not_applicable_human_label_required"
    )


def test_ladder_benchmark_reports_exact_anchor_error_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli")
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    content_hash = hashlib.sha256(input_file.read_bytes()).hexdigest()

    monkeypatch.setattr(
        benchmark_module,
        "_run_once",
        lambda *_args, **_kwargs: (
            0.1,
            {
                "ladder": "LIZ500_250",
                "ladder_peak_count": 3,
                "ladder_fit_preview": {
                    "best_scan_indices": [10, 25, 31],
                    "sizing_model": {},
                },
                "ladder_review_assessment": {"reason_codes": []},
            },
        ),
    )
    metadata = {
        "content_sha256": content_hash,
        "physical_run_key": "run-a",
        "review_approved": "True",
        "approved_for_fit_gold": "True",
        "gold_eligible": "True",
        "review_label": "manual_adjusted",
        "reviewed_at_utc": "2026-08-11T12:00:00+00:00",
        "reviewed_by": "chemist",
        "analysis_id": "clonality",
        "identity_key": "patient:run-a",
        "sample_kind": "patient",
    }

    result = benchmark(
        [input_file],
        cli=cli,
        repeats=1,
        warmups=0,
        timeout_seconds=10,
        gold_expectations={input_file.resolve(): [10, 20, 30]},
        case_metadata={input_file.resolve(): metadata},
    )

    row = result["files"][0]
    assert row["gold_exact_match"] is False
    assert row["gold_anchors_changed"] == 2
    assert row["gold_mean_abs_scan_delta"] == pytest.approx(2.0)
    assert row["gold_max_abs_scan_delta"] == 5
    assert row["gold_major_wrong_sequence"] is True
    assert result["gold_core_exact_match_count"] == 0
    assert result["by_ladder"]["LIZ500_250"][
        "gold_core_major_wrong_sequence_count"
    ] == 1


def test_liz_gold_metrics_treat_35_as_outside_the_core():
    metrics = _gold_anchor_metrics(
        [90, 200, 300, 400],
        [100, 200, 300, 400],
        ladder="LIZ500_250",
    )

    assert metrics["gold_exact_match"] is False
    assert metrics["gold_core_exact_match"] is True
    assert metrics["gold_core_anchors_changed"] == 0
    assert metrics["gold_core_major_wrong_sequence"] is False


def test_ladder_benchmark_reports_search_tier_and_watchdog_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli")
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    monkeypatch.setattr(
        benchmark_module,
        "_run_once",
        lambda *_args, **_kwargs: (
            0.1,
            {
                "ladder": "ROX400HD",
                "ladder_fit_preview": {
                    "best_scan_indices": [10, 20, 30],
                    "search_tier": "deep_rescue_10s",
                    "search_diagnostics": {
                        "fit_tier": "deep_rescue_10s",
                        "watchdog_reached": True,
                        "expansions_used": 50,
                        "expansion_limit": 50,
                        "elapsed_us": 10_000_001,
                    },
                    "sizing_model": {},
                },
                "ladder_review_assessment": {"reason_codes": []},
                "timings_us": {"ladder_fit": 100_000},
            },
        ),
    )

    result = benchmark(
        [input_file], cli=cli, repeats=1, warmups=0, timeout_seconds=10
    )

    assert result["by_tier"]["deep_rescue_10s"]["file_count"] == 1
    assert result["overall"]["rescue_invocation_count"] == 1
    assert result["overall"]["watchdog_reached_count"] == 1


def _comparison_fixture(*, candidate_exact=True, candidate_major=False):
    baseline = {
        "deterministic": True,
        "configuration": {"timeout_seconds": 10},
        "files": [
            {
                "content_sha256": "a" * 64,
                "ladder": "ROX400HD",
                "gold_exact_match": True,
                "gold_major_wrong_sequence": False,
                "gold_anchors_changed": 0,
                "gold_max_abs_scan_delta": 0,
                "identity": {"scan_indices": [10, 20], "search_tier": "primary_beam"},
                "runs": [],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["files"][0].update(
        {
            "gold_exact_match": candidate_exact,
            "gold_major_wrong_sequence": candidate_major,
            "gold_anchors_changed": 2 if not candidate_exact else 0,
            "gold_max_abs_scan_delta": 5 if not candidate_exact else 0,
        }
    )
    if not candidate_exact:
        candidate["files"][0]["identity"]["scan_indices"] = [11, 25]
    return baseline, candidate


def test_promotion_gate_requires_exact_controls_and_no_major_regression():
    baseline, candidate = _comparison_fixture()
    gate = evaluate_fit_candidate(baseline, candidate)
    assert gate["existing_exact_preserved"] is True
    assert gate["major_wrong_sequence_regressions"] == 0
    assert gate["promotable"] is True


def test_promotion_gate_rejects_changed_exact_control():
    baseline, candidate = _comparison_fixture(candidate_exact=False)
    gate = evaluate_fit_candidate(baseline, candidate)
    assert gate["existing_exact_preserved"] is False
    assert gate["promotable"] is False


def test_promotion_gate_preserves_liz_core_when_only_35_moves():
    baseline, candidate = _comparison_fixture(candidate_exact=False)
    baseline["files"][0]["ladder"] = "LIZ500_250"
    candidate["files"][0]["ladder"] = "LIZ500_250"
    baseline["files"][0].update(
        {"gold_core_exact_match": True, "gold_core_major_wrong_sequence": False}
    )
    candidate["files"][0].update(
        {"gold_core_exact_match": True, "gold_core_major_wrong_sequence": False}
    )
    candidate["files"][0]["identity"]["scan_indices"] = [11, 20]

    gate = evaluate_fit_candidate(baseline, candidate)

    assert gate["existing_core_exact_preserved"] is True
    assert gate["core_exact_control_regressions"] == 0


def test_promotion_gate_rejects_liz_core_regression():
    baseline, candidate = _comparison_fixture(candidate_exact=False)
    baseline["files"][0]["ladder"] = "LIZ500_250"
    candidate["files"][0]["ladder"] = "LIZ500_250"
    baseline["files"][0].update(
        {"gold_core_exact_match": True, "gold_core_major_wrong_sequence": False}
    )
    candidate["files"][0].update(
        {"gold_core_exact_match": False, "gold_core_major_wrong_sequence": True}
    )

    gate = evaluate_fit_candidate(baseline, candidate)

    assert gate["existing_core_exact_preserved"] is False
    assert gate["core_major_wrong_sequence_regressions"] == 1
    assert gate["promotable"] is False


def test_promotion_gate_rejects_new_major_wrong_sequence():
    baseline, candidate = _comparison_fixture(
        candidate_exact=False, candidate_major=True
    )
    baseline["files"][0]["gold_exact_match"] = False
    baseline["files"][0]["gold_anchors_changed"] = 1
    gate = evaluate_fit_candidate(baseline, candidate)
    assert gate["major_wrong_sequence_regressions"] == 1
    assert gate["promotable"] is False


def test_promotion_gate_rejects_nondeterminism_and_watchdog_overflow():
    baseline, candidate = _comparison_fixture()
    candidate["deterministic"] = False
    candidate["files"][0]["runs"] = [
        {
            "identity": {
                "search_tier": "deep_rescue_10s",
                "search_diagnostics": {
                    "watchdog_reached": True,
                    "elapsed_us": 10_000_001,
                },
            }
        }
    ]
    gate = evaluate_fit_candidate(baseline, candidate)
    assert gate["deterministic"] is False
    assert gate["watchdog_overflow_count"] == 1
    assert gate["promotable"] is False


def test_promotion_gate_rejects_slower_fast_path_p95():
    baseline, candidate = _comparison_fixture()
    baseline["by_tier"] = {
        "primary_beam": {"p95_engine_ladder_seconds": 0.10}
    }
    candidate["by_tier"] = {
        "primary_beam": {"p95_engine_ladder_seconds": 0.20}
    }
    gate = evaluate_fit_candidate(baseline, candidate)
    assert gate["fast_path_p95_regression"] is True
    assert gate["promotable"] is False


def test_ladder_benchmark_rejects_programmatic_hash_mismatch_before_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli")
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    called = False

    def unexpected_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("runner must not execute")

    monkeypatch.setattr(benchmark_module, "_run_once", unexpected_run)

    with pytest.raises(ValueError, match="SHA-256"):
        benchmark(
            [input_file],
            cli=cli,
            repeats=1,
            warmups=0,
            case_metadata={
                input_file.resolve(): {
                    "content_sha256": "0" * 64,
                    "physical_run_key": "run-a",
                }
            },
        )

    assert called is False


def test_ladder_benchmark_rejects_unapproved_programmatic_gold_before_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli")
    input_file = tmp_path / "case.fsa"
    input_file.write_bytes(b"fixture")
    content_hash = hashlib.sha256(input_file.read_bytes()).hexdigest()
    called = False

    def unexpected_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("runner must not execute")

    monkeypatch.setattr(benchmark_module, "_run_once", unexpected_run)

    with pytest.raises(ValueError, match="explicit review approval"):
        benchmark(
            [input_file],
            cli=cli,
            repeats=1,
            warmups=0,
            gold_expectations={input_file.resolve(): [10, 20]},
            case_metadata={
                input_file.resolve(): {
                    "content_sha256": content_hash,
                    "review_approved": "False",
                    "analysis_id": "clonality",
                    "sample_kind": "patient",
                }
            },
        )

    assert called is False
