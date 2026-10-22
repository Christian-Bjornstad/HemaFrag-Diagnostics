"""General sizing must consume the same channel and analysis scope it records."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from config import APP_SETTINGS


@pytest.mark.parametrize("ladder,channel,function", [
    ("LIZ500_250", "DATA5", "analyse_fsa_liz"),
    ("ROX400HD", "DATA105", "analyse_fsa_rox"),
    ("GS500ROX", "DATA5", "analyse_fsa_rox"),
])
def test_general_profile_reaches_sizing_loader(tmp_path, monkeypatch, ladder, channel, function):
    from core.analyses.general import pipeline

    seen = []
    expected = object()

    def load(path, sample_channel, **kwargs):
        seen.append((path, sample_channel, kwargs))
        return expected

    monkeypatch.setattr(pipeline, function, load)
    source = tmp_path / "sample.fsa"
    assert pipeline._load_fsa(source, {
        "ladder": ladder, "sample_channel": "DATA2", "size_standard_channel": channel,
    }) is expected
    assert seen == [(source, "DATA2", {
        "ladder_name": ladder, "size_standard_channel": channel, "analysis_id": "general",
    })]


@pytest.mark.parametrize("function,ladder", [
    ("analyse_fsa_liz", "LIZ500_250"),
    ("analyse_fsa_rox", "ROX400HD"),
    ("analyse_fsa_rox", "GS500ROX"),
])
@pytest.mark.parametrize("use_rust", [False, True])
def test_explicit_channel_and_analysis_survive_native_and_python_paths(
    tmp_path, monkeypatch, function, ladder, use_rust,
):
    from core.analysis import _legacy as analysis
    import core.rust_bridge as bridge

    constructed = []
    native_kinds = []

    def create_fsa(**kwargs):
        fsa = SimpleNamespace(
            **kwargs,
            file_name=Path(kwargs["file"]).name,
            size_standard=np.zeros(16),
            size_standard_raw=np.zeros(16),
            size_standard_peaks=np.array([], dtype=int),
            ladder_steps=np.array([35.0, 50.0, 75.0]),
            expected_ladder_steps=np.array([35.0, 50.0, 75.0]),
        )
        constructed.append(fsa)
        return fsa

    def native_fit(fsa, kind):
        native_kinds.append(kind)
        return fsa

    def unexpected_detection(*_args):
        raise AssertionError("An explicit channel must not be replaced by auto-detection")

    monkeypatch.setitem(APP_SETTINGS["engine"], "use_rust", use_rust)
    monkeypatch.setenv("HEMAFRAG_SKIP_DEEP_SEARCH", "True")
    monkeypatch.setattr(analysis, "FsaFile", create_fsa)
    monkeypatch.setattr(analysis, "_preferred_size_standard_channel_for_file", unexpected_detection)
    monkeypatch.setattr(analysis, "prepare_size_standard_trace", lambda fsa: fsa)
    monkeypatch.setattr(analysis, "find_size_standard_peaks", lambda fsa: fsa)
    monkeypatch.setattr(analysis, "_supplement_rox_preferred_region_peaks", lambda *_a, **_kw: [])
    monkeypatch.setattr(analysis, "_clean_rox_size_standard_peaks", lambda *_a: [])
    monkeypatch.setattr(analysis, "_recover_rox_size_standard_peaks_from_baseline", lambda *_a: False)
    monkeypatch.setattr(analysis, "load_ladder_adjustment", lambda _fsa: None)
    monkeypatch.setattr(analysis, "_try_apply_saved_ladder_adjustment", lambda *_a: None)
    monkeypatch.setattr(analysis, "compute_ladder_qc_metrics", lambda _fsa: {})
    monkeypatch.setattr(analysis, "_finalize_auto_fit_metadata", lambda fsa: fsa)
    monkeypatch.setattr(analysis, "_annotate_fit_qc_review", lambda fsa, _qc: fsa)
    monkeypatch.setattr(bridge, "run_ladder_fit_hybrid", native_fit)

    result = getattr(analysis, function)(
        tmp_path / "sample.fsa", "DATA1", ladder_name=ladder,
        size_standard_channel="DATA5", analysis_id="general",
    )

    assert len(constructed) == (1 if use_rust else 5)
    assert all(fsa.size_standard_channel == "DATA5" for fsa in constructed)
    assert all(fsa.analysis_id == "general" for fsa in constructed)
    assert native_kinds == (["general"] if use_rust else [])
    assert result is (constructed[0] if use_rust else None)
