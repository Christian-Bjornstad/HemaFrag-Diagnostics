from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.research.ladder.contracts import LadderOutcome
from core.research.ladder.diagnostics import (
    classify_ladder_outcome,
    normalize_rust_result,
    run_rust_diagnostic,
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"ladder_peak_count": 0, "reason_codes": ["no_ladder_signal"]},
            LadderOutcome.MISSING_LADDER_SIGNAL,
        ),
        (
            {"configured_ladder": "LIZ", "detected_ladder": "ROX400HD"},
            LadderOutcome.WRONG_LADDER_OR_CHANNEL,
        ),
        (
            {
                "ladder_peak_count": 22,
                "fitted_count": 0,
                "reason_codes": ["candidate_space_capped"],
            },
            LadderOutcome.FIT_REJECTED_WITH_USABLE_SIGNAL,
        ),
        (
            {"reviewed_label": "reviewed_no_change", "review_required": True},
            LadderOutcome.FIT_CORRECT_REVIEW_ONLY,
        ),
        (
            {"reviewed_label": "manual_adjusted", "accepted": True},
            LadderOutcome.FIT_ACCEPTED_BUT_WRONG,
        ),
    ],
)
def test_outcome_taxonomy(payload, expected):
    assert classify_ladder_outcome(payload) is expected


def test_normalization_preserves_rejected_preview_candidate_qc_and_timing():
    payload = {
        "ladder": "LIZ500_250",
        "size_standard_channel_guess": "DATA4",
        "ladder_peak_count": 19,
        "ladder_fit_preview": {
            "best_scan_indices": [100, 200, 300],
            "estimated_combination_count": 2000,
            "evaluated_combination_count": 250,
            "search_tier": "bounded_repair",
            "sizing_model": {
                "qc_metrics": {"r2": 0.999, "max_abs_error_bp": 4.2}
            },
        },
        "ladder_review_assessment": {
            "suggested_review": True,
            "reason_codes": ["candidate_space_capped"],
        },
        "timings_us": {"total": 12345, "ladder_fit": 4567},
    }

    normalized = normalize_rust_result(
        payload,
        source_path=Path("sample.fsa"),
        configured_ladder="LIZ",
        reviewed_label="",
    )

    assert normalized.preview_scan_indices == (100, 200, 300)
    assert normalized.candidate_peak_count == 19
    assert normalized.estimated_combinations == 2000
    assert normalized.evaluated_combinations == 250
    assert normalized.qc_metrics["max_abs_error_bp"] == 4.2
    assert normalized.timings_us["ladder_fit"] == 4567
    assert normalized.outcome is LadderOutcome.FIT_REJECTED_WITH_USABLE_SIGNAL


def test_generic_rejection_is_flagged_as_missing_underlying_reason():
    normalized = normalize_rust_result(
        {
            "ladder": "LIZ500_250",
            "ladder_peak_count": 18,
            "ladder_fit_preview": {},
            "ladder_review_assessment": {
                "suggested_review": True,
                "reason_codes": ["rust_ladder_fit_rejected"],
            },
        },
        source_path=Path("sample.fsa"),
        configured_ladder="LIZ",
        reviewed_label="",
    )

    assert "underlying_reason_missing" in normalized.issue_codes


def test_runner_uses_bounded_deterministic_cli_and_validates_summary(tmp_path):
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"fsa")
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"binary")
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "analyze_summary.json").write_text(
            json.dumps(
                [
                    {
                        "ladder": "LIZ500_250",
                        "ladder_peak_count": 0,
                        "ladder_review_assessment": {
                            "suggested_review": True,
                            "reason_codes": ["no_ladder_signal"],
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="warning")

    record = run_rust_diagnostic(
        cli,
        source,
        configured_ladder="LIZ",
        timeout_seconds=7,
        run_command=fake_run,
    )

    command = observed["command"]
    assert "--deterministic" in command
    assert "--compact-json" in command
    assert observed["kwargs"]["timeout"] == 7
    assert record.transport_status == "ok"
    assert record.stderr == "warning"
    assert record.outcome is LadderOutcome.MISSING_LADDER_SIGNAL


def test_runner_returns_transport_timeout_separately(tmp_path):
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"fsa")
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"binary")

    def timeout_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="too slow")

    record = run_rust_diagnostic(
        cli,
        source,
        configured_ladder="LIZ",
        timeout_seconds=3,
        run_command=timeout_run,
    )

    assert record.transport_status == "timeout"
    assert record.outcome is LadderOutcome.UNRESOLVED
    assert "transport_timeout" in record.issue_codes
