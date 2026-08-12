from __future__ import annotations

from core.analyses.general.config import (
    GENERAL_PROFILE_SCHEMA,
    resolve_runtime_config,
)


def _settings(pipeline: dict) -> dict:
    return {"analyses": {"general": {"pipeline": pipeline}}}


def test_general_profile_declares_complete_versioned_contract():
    profile = resolve_runtime_config(
        _settings(
            {
                "profile_id": "custom_rox",
                "profile_version": 3,
                "validation_status": "validated",
                "ladder": "ROX400HD",
                "size_standard_channel": "DATA4",
                "trace_channels": ["DATA1", "DATA2"],
                "primary_peak_channel": "DATA2",
                "bp_min": 80,
                "bp_max": 420,
                "report_fields": ["source_sha256", "ladder_qc"],
            }
        )
    )

    assert profile["schema_version"] == GENERAL_PROFILE_SCHEMA
    assert profile["profile_id"] == "custom_rox"
    assert profile["profile_version"] == 3
    assert profile["validation_status"] == "validated"
    assert profile["ladder_steps"][-1] == 400
    assert profile["size_standard_channel"] == "DATA4"
    assert profile["contract_complete"] is True
    assert len(profile["profile_fingerprint"]) == 64


def test_general_profile_normalizes_invalid_contract_fail_closed():
    profile = resolve_runtime_config(
        _settings(
            {
                "profile_version": "bad",
                "validation_status": "approved-ish",
                "ladder": "unknown",
                "size_standard_channel": "DATA9",
                "trace_channels": ["DATA9"],
                "bp_min": "bad",
                "bp_max": "bad",
            }
        )
    )

    assert profile["profile_version"] == 1
    assert profile["validation_status"] == "unvalidated"
    assert profile["ladder"] == "ROX400HD"
    assert profile["size_standard_channel"] == "DATA4"
    assert profile["trace_channels"] == ["DATA1"]
    assert profile["contract_complete"] is True
