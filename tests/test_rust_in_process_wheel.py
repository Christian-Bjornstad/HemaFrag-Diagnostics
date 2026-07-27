"""Tests that the in-process Rust kernel wheel (fraggler-native) gets
preferred when it is importable, and that the function correctly falls
back to None when the wheel is absent.

These tests intentionally monkeypatch the helpers instead of running
through the full pipeline, so they are fast and not flaky on machines
where the wheel isn't installed.
"""
from __future__ import annotations

import types


def _make_mock_native(monkeypatch, *, available, payload=None):
    fake = types.ModuleType("fraggler_native")

    def _is_available():
        return available

    def _analyze_fsa(path, kind):  # noqa: ANN001
        return payload

    fake.is_available = _is_available
    fake.analyze_fsa = _analyze_fsa

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "fraggler_native", fake)


def test_in_process_native_wheel_is_available_returns_true_when_module_exports(monkeypatch):
    _make_mock_native(monkeypatch, available=True, payload={})
    from core import rust_bridge

    assert rust_bridge._in_process_native_wheel_is_available() is True


def test_in_process_native_wheel_is_available_returns_false_when_module_missing(monkeypatch):
    # Force ImportError by clearing the module from sys.modules.
    import sys as _sys
    monkeypatch.delitem(_sys.modules, "fraggler_native", raising=False)
    # Force the import attempt inside the helper to fail by setting it to None
    _sys.modules["fraggler_native"] = None
    from core import rust_bridge
    assert rust_bridge._in_process_native_wheel_is_available() is False


def test_run_in_process_wheel_once_returns_payload_dict(monkeypatch):
    expected = {
        "file_name": "x.fsa",
        "scan_count": 1234,
        "data_channels": ["DATA1", "DATA2"],
        "ladder": "LIZ500_250",
        "ladder_fit_preview": {"best_scan_indices": [], "sizing_model": {"predicted_ladder_basepairs": []}},
        "ladder_review_assessment": {},
        "ladder_peak_preview": [],
        "sample_channel_guess": "DATA2",
        "size_standard_channel_guess": "DATA1",
        "flt3_preview": {},
        "clonality_preview": {},
    }
    _make_mock_native(monkeypatch, available=True, payload=expected)
    from core import rust_bridge

    from pathlib import Path
    fsa = types.SimpleNamespace(file="/tmp/x.fsa", file_name="x.fsa")
    res = rust_bridge._run_in_process_wheel_once(fsa, "clonality")
    assert res is expected


def test_run_in_process_wheel_once_returns_none_when_module_missing(monkeypatch):
    from core import rust_bridge
    fsa = types.SimpleNamespace(file="/tmp/x.fsa", file_name="x.fsa")
    assert rust_bridge._run_in_process_wheel_once(fsa, "clonality") is None


def test_run_ladder_fit_hybrid_prefers_in_process(monkeypatch):
    """When fraggler_native is available, run_ladder_fit_hybrid should
    call into it BEFORE looking up the CLI binary.

    NB: run_ladder_fit_hybrid lives in core.rust_bridge._legacy, not in
    the facade `core.rust_bridge`. Python resolves bare names inside
    a function body against the function's *defining* module's globals,
    so monkeypatch patches against `rust_bridge.X` alone do NOT take
    effect. We patch against `core.rust_bridge._legacy` to honour the
    real lookup location.
    """
    from core.rust_bridge import _legacy as legacy
    import core.rust_bridge as rust_bridge

    monkeypatch.setattr(
        legacy, "_in_process_native_wheel_is_available", lambda: True
    )

    payload = {
        "file_name": "x.fsa",
        "scan_count": 100,
        "data_channels": ["DATA1"],
        "ladder": "LIZ500_250",
        "ladder_fit_preview": {
            "best_scan_indices": [],
            "sizing_model": {"predicted_ladder_basepairs": []},
        },
        "ladder_review_assessment": {},
        "ladder_peak_preview": [],
        "sample_channel_guess": "DATA2",
        "size_standard_channel_guess": "DATA1",
        "flt3_preview": {},
        "clonality_preview": {},
    }

    tracker = {"in_process": 0, "cli": 0, "apply": 0}

    def _fake_in_process(fsa, kind):
        tracker["in_process"] += 1
        return payload

    def _fake_cli(*a, **k):
        tracker["cli"] += 1
        return None

    def _fake_apply(fsa, res):
        tracker["apply"] += 1
        return fsa

    # Patch against the actual defining module of run_ladder_fit_hybrid.
    monkeypatch.setattr(legacy, "_run_in_process_wheel_once", _fake_in_process)
    monkeypatch.setattr(legacy, "_run_cli_once", _fake_cli)
    monkeypatch.setattr(legacy, "_apply_rust_result_to_fsa", _fake_apply)
    monkeypatch.setattr(legacy, "_get_cached_rust_result", lambda *a, **k: None)
    monkeypatch.setattr(legacy, "_get_rust_worker", lambda: None)
    monkeypatch.setattr(legacy, "_log_rust_cli_missing_once", lambda **k: None)
    monkeypatch.setattr(legacy, "_increment_rust_engine_stat", lambda *a, **k: None)

    # Reset module-level one-shot log state so the test's run doesn't
    # see a stale "[RUST WARNING]" emitted by a previous test invocation.
    legacy._RUST_CLI_MISSING_LOGGED = False
    legacy._RUST_CLI_MISSING_FALLBACK_COUNT = 0

    fsa = types.SimpleNamespace(
        file="/tmp/x.fsa", file_name="x.fsa", analysis_id="clonality"
    )
    out = rust_bridge.run_ladder_fit_hybrid(fsa, "clonality")

    # The in-process path was taken; the CLI subprocess path was NOT.
    # The exact return depends on _apply_rust_result_to_fsa's
    # internal validation (which we patched to return fsa).
    assert tracker["in_process"] == 1, "in-process kernel must be called once"
    assert tracker["cli"] == 0, "CLI subprocess path must NOT fire when wheel succeeds"
    assert tracker["apply"] == 1, "apply_rust_result_to_fsa must be called once"
    assert out is fsa
