from types import SimpleNamespace

import pytest

from core.engine_flags import (
    python_ladder_compatibility_enabled,
    rust_owned_ladder_enabled,
    strict_rust_ladder_enabled,
)


def test_rust_owned_ladder_is_the_default(monkeypatch):
    monkeypatch.delenv("HEMAFRAG_ENABLE_PYTHON_LADDER_FALLBACK", raising=False)

    assert rust_owned_ladder_enabled()
    assert not python_ladder_compatibility_enabled()


def test_emergency_python_compatibility_switch(monkeypatch):
    monkeypatch.delenv("HEMAFRAG_STRICT_RUST_LADDER", raising=False)
    monkeypatch.delenv("HEMAFRAG_RUST_ONLY", raising=False)
    monkeypatch.setenv("HEMAFRAG_ENABLE_PYTHON_LADDER_FALLBACK", "1")

    assert python_ladder_compatibility_enabled()
    assert not rust_owned_ladder_enabled()


def test_strict_rust_ladder_env_switch(monkeypatch):
    monkeypatch.delenv("HEMAFRAG_RUST_ONLY", raising=False)
    monkeypatch.setenv("HEMAFRAG_STRICT_RUST_LADDER", "1")

    assert strict_rust_ladder_enabled()


def test_strict_rust_ladder_disables_clonality_multiprocessing(monkeypatch):
    from core.analyses.clonality import pipeline

    monkeypatch.setenv("HEMAFRAG_STRICT_RUST_LADDER", "1")

    assert not pipeline._should_use_multiprocessing()


def test_strict_rust_ladder_disables_flt3_template_rescue(monkeypatch):
    from core.analyses.flt3 import pipeline

    monkeypatch.setenv("HEMAFRAG_STRICT_RUST_LADDER", "1")
    fsa = SimpleNamespace(ladder_review_required=True)

    assert not pipeline._should_attempt_flt3_template_rescue(fsa, "FLT3-D835", None)


def test_strict_rust_ladder_skips_python_fit_in_rust_bridge(monkeypatch):
    """Under HEMAFRAG_STRICT_RUST_LADDER=1, _apply_rust_result_to_fsa
    must NOT fall back to fit_size_standard_to_ladder, even if the Rust
    preview returns 0 valid scan_indices.

    Note: fit_size_standard_to_ladder lives in fraggler.fraggler, not
    in core.rust_bridge. The previous version of this test patched the
    wrong name; that was the failing root cause.
    """
    import fraggler.fraggler
    from core.rust_bridge import _legacy as legacy

    monkeypatch.setenv("HEMAFRAG_STRICT_RUST_LADDER", "1")
    monkeypatch.setattr(legacy, "_validate_rust_anchor_selection", lambda *_args: (True, ""))
    monkeypatch.setattr(
        legacy, "_apply_rust_sizing_model_to_fsa", lambda *_args: None
    )

    def fail_if_called(_fsa):
        raise AssertionError(
            "Python ladder fallback should not be called in strict Rust mode"
        )

    monkeypatch.setattr(fraggler.fraggler, "fit_size_standard_to_ladder", fail_if_called)
    fsa = SimpleNamespace(
        file_name="dummy.fsa", ladder="LIZ500",
        sample_data=[1.0, 2.0, 3.0],
    )
    res = {
        "ladder_fit_preview": {
            "best_scan_indices": [100, 200, 300],
            "sizing_model": {"predicted_ladder_basepairs": [50.0, 100.0, 150.0]},
        }
    }

    assert legacy._apply_rust_result_to_fsa(fsa, res) is None


def test_rust_bridge_rejects_multiple_strong_baseline_anchors():
    from core.rust_bridge import _legacy as legacy

    fsa = SimpleNamespace(file_name="baseline-noise.fsa")
    res = {
        "ladder_review_assessment": {
            "suggested_review": True,
            "reason_codes": ["selected_baseline_like_ladder_peaks"],
            "selected_baseline_like_anchor_count": 2,
            "selected_cleaner_neighbor_count": 1,
            "selected_strong_baseline_anchor_count": 2,
        },
        "ladder_fit_preview": {
            "search_tier": "reduced_pool_fallback",
            "best_scan_indices": [100, 200, 300],
            "sizing_model": {"predicted_ladder_basepairs": [50.0, 100.0, 150.0]},
        },
    }

    assert legacy._apply_rust_result_to_fsa(fsa, res) is None
    assert fsa.rust_guardrail_review_required is True
    assert fsa.ladder_review_required is True
