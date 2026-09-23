"""Clonality worker decisions use the queued settings snapshot."""

from pathlib import Path

from config import APP_SETTINGS
from core.run_context import RunContext
from core.analyses.clonality import interpretation, pipeline, tracking_excel


def _context(*, rust=False, timeout=0, interpret=False, qc_window=3.0,
             master_path=""):
    return RunContext.create(
        analysis_id="clonality",
        settings={
            "active_analysis": "clonality",
            "engine": {"use_rust": rust},
            "qc": {"sample_peak_window_bp": qc_window},
            "analyses": {"clonality": {
                "pipeline": {"file_timeout_seconds": timeout},
                "interpretation": {"enabled": interpret},
                "batch": {"global_tracking_excel_path": master_path},
            }},
        },
    )


def test_timeout_and_interpretation_ignore_later_global_changes(monkeypatch):
    context = _context(timeout=17, interpret=True)
    monkeypatch.setitem(APP_SETTINGS, "analyses", {"clonality": {
        "pipeline": {"file_timeout_seconds": 3},
        "interpretation": {"enabled": False},
    }})

    assert pipeline._clonality_file_timeout_seconds(context.settings_snapshot) == 17
    assert interpretation.interpretation_enabled(context.settings_snapshot) is True
    assert interpretation.interpretation_enabled({}) is False


def test_analysis_rust_prewarm_uses_snapshot(monkeypatch, tmp_path):
    context = _context(rust=False)
    monkeypatch.setitem(APP_SETTINGS, "engine", {"use_rust": True})
    primed = []
    monkeypatch.setattr(pipeline, "_should_use_multiprocessing", lambda **kwargs: False)
    monkeypatch.setattr(pipeline, "_analyze_single_file_with_timeout", lambda *_args, **_kwargs: ({"file_name": "x.fsa"}, ""))
    monkeypatch.setattr(pipeline, "_clonality_file_timeout_seconds", lambda settings=None: 0)
    from core import rust_bridge
    monkeypatch.setattr(rust_bridge, "prime_rust_worker_results", lambda *_: primed.append(True))

    entries, _ = pipeline._analyze_files([tmp_path / "x.fsa"], settings=context.settings_snapshot)

    assert entries == [{"file_name": "x.fsa"}]
    assert primed == []


def test_tracking_rules_and_master_path_use_snapshot(monkeypatch, tmp_path):
    target = tmp_path / "captured.xlsx"
    context = _context(qc_window=9.0, master_path=str(target))
    monkeypatch.setitem(APP_SETTINGS, "qc", {"sample_peak_window_bp": 1.0})
    monkeypatch.setitem(APP_SETTINGS, "analyses", {"clonality": {
        "batch": {"global_tracking_excel_path": str(tmp_path / "changed.xlsx")}
    }})

    rules = tracking_excel.build_clonality_qc_rules(context.settings_snapshot)
    assert rules.sample_peak_window_bp == 9.0
    assert tracking_excel.resolve_global_clonality_tracking_path(context.settings_snapshot) == target


def test_clonality_pipeline_passes_snapshot_to_analysis_and_tracking(monkeypatch, tmp_path):
    context = _context(timeout=17)
    source = tmp_path / "x.fsa"
    source.write_bytes(b"synthetic")
    seen = {}
    monkeypatch.setattr(pipeline, "_scan_files", lambda *_: [source])
    monkeypatch.setattr(
        pipeline, "_analyze_files",
        lambda files, *, progress_callback=None, settings=None: (
            seen.update(analysis_settings=settings) or [{"file_name": "x.fsa"}], 0
        ),
    )
    monkeypatch.setattr(
        pipeline, "update_clonality_tracking_workbook",
        lambda path, entries, **kwargs: seen.update(tracking_settings=kwargs.get("settings")),
    )
    monkeypatch.setattr(pipeline, "finalize_pipeline_run", lambda *_args, **_kwargs: [])

    pipeline.run_pipeline(
        tmp_path, tmp_path, "out", run_context=context,
    )

    assert seen["analysis_settings"] is context.settings_snapshot
    assert seen["tracking_settings"] is context.settings_snapshot
