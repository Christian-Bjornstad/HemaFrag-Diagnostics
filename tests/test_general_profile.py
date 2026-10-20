from __future__ import annotations

from core.analyses.general.config import (
    GENERAL_PROFILE_SCHEMA,
    resolve_runtime_config,
)
from config import APP_SETTINGS
from core.run_context import RunContext


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


def test_explicit_empty_settings_use_general_defaults(monkeypatch):
    monkeypatch.setitem(
        APP_SETTINGS["analyses"]["general"],
        "pipeline",
        {"trace_channels": ["DATA3"], "ladder": "LIZ500_250"},
    )

    profile = resolve_runtime_config({})

    assert profile["trace_channels"] == ["DATA1"]
    assert profile["ladder"] == "ROX400HD"


def test_general_pipeline_uses_queued_channels_after_globals_change(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import core.analyses.general.pipeline as general_pipeline
    import core.analysis_provenance as provenance

    trace = tmp_path / "alias.fsa"
    trace.write_bytes(b"synthetic")
    context = RunContext.create(
        analysis_id="general",
        settings=_settings(
            {
                "trace_channels": ["DATA2", "DATA3"],
                "primary_peak_channel": "DATA3",
                "ladder": "LIZ500_250",
            }
        ),
    )
    monkeypatch.setitem(
        APP_SETTINGS["analyses"]["general"],
        "pipeline",
        {"trace_channels": ["DATA1"], "ladder": "ROX400HD"},
    )
    monkeypatch.setattr(general_pipeline, "_scan_files", lambda *_args: [trace])
    monkeypatch.setattr(
        general_pipeline,
        "_load_fsa",
        lambda _path, meta: SimpleNamespace(
            file_name=trace.name,
            ladder_fit_strategy="auto_full",
            ladder_qc_status="ok",
        ),
    )
    monkeypatch.setattr(
        general_pipeline,
        "compute_ladder_qc_metrics",
        lambda _fsa: {"r2": 0.999},
    )
    monkeypatch.setattr(provenance, "attach_analysis_provenance", lambda entry: entry)
    monkeypatch.setattr(
        general_pipeline,
        "finalize_pipeline_run",
        lambda entries, *_args, **_kwargs: entries,
    )

    entries = general_pipeline.run_pipeline(
        tmp_path,
        return_entries=True,
        make_dit_reports=False,
        run_context=context,
    )

    assert entries[0]["trace_channels"] == ["DATA2", "DATA3"]
    assert entries[0]["primary_peak_channel"] == "DATA3"
    assert entries[0]["ladder"] == "LIZ500_250"
