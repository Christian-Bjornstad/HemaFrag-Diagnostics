from pathlib import Path
from types import SimpleNamespace

from core.runner import _stamp_entry_source_provenance


def test_stamp_entry_source_provenance_restores_staged_file(tmp_path):
    run_dir = tmp_path / "2026_01_27_full_instrument_run"
    run_dir.mkdir()
    source = run_dir / "26OUM12345_TCRg_A_A01.fsa"
    source.touch()
    entry = {
        "fsa": SimpleNamespace(
            file_name="00001_01234567_26OUM12345_TCRg_A_A01.fsa"
        ),
        "file_name": "00001_01234567_26OUM12345_TCRg_A_A01.fsa",
        "source_run_dir": "2026-01-27_short_key",
    }

    stamped = _stamp_entry_source_provenance([entry], [source])

    assert stamped[0]["file_name"] == source.name
    assert stamped[0]["source_run_dir"] == run_dir.name
    assert stamped[0]["original_file_path"] == str(source.resolve())


def test_stamp_entry_source_provenance_leaves_unmatched_entry_unchanged(tmp_path):
    entry = {
        "fsa": SimpleNamespace(file_name="unmatched.fsa"),
        "source_run_dir": "existing-run",
    }

    stamped = _stamp_entry_source_provenance(
        [entry],
        [tmp_path / "different.fsa"],
    )

    assert stamped[0]["source_run_dir"] == "existing-run"
    assert "original_file_path" not in stamped[0]
