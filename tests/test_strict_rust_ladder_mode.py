from types import SimpleNamespace

import pytest

from core.engine_flags import strict_rust_ladder_enabled


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
    from core import rust_bridge

    monkeypatch.setenv("HEMAFRAG_STRICT_RUST_LADDER", "1")
    monkeypatch.setattr(rust_bridge, "_validate_rust_anchor_selection", lambda *_args: (True, ""))
    monkeypatch.setattr(rust_bridge, "_apply_rust_sizing_model_to_fsa", lambda *_args: None)

    def fail_if_called(_fsa):
        raise AssertionError("Python ladder fallback should not be called in strict Rust mode")

    monkeypatch.setattr(rust_bridge, "fit_size_standard_to_ladder", fail_if_called)
    fsa = SimpleNamespace(file_name="dummy.fsa", ladder="LIZ500", sample_data=[1.0, 2.0, 3.0])
    res = {
        "ladder_fit_preview": {
            "best_scan_indices": [100, 200, 300],
            "sizing_model": {"predicted_ladder_basepairs": [50.0, 100.0, 150.0]},
        }
    }

    assert rust_bridge._apply_rust_result_to_fsa(fsa, res) is None
