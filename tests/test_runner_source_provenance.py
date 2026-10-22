from pathlib import Path
from types import SimpleNamespace

from core.runner import _safe_link_name, _stamp_entry_source_provenance


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


def test_stamp_entry_source_provenance_restores_rejected_alternate(tmp_path):
    run_dir = tmp_path / "instrument_run"
    run_dir.mkdir()
    selected = run_dir / "26OUM00000_ITD_B05.fsa"
    rejected = run_dir / "26OUM00000_ITD_A05.fsa"
    selected.touch()
    rejected.touch()
    entry = {
        "file_name": "00002_01234567_26OUM00000_ITD_B05.fsa",
        "_alternate_ladder_review_entries": [
            {
                "file_name": "00001_01234567_26OUM00000_ITD_A05.fsa",
                "original_file_path": str(tmp_path / "fraggler_stage_deleted" / "00001_01234567_26OUM00000_ITD_A05.fsa"),
                "ladder_review_required": True,
            }
        ],
    }

    _stamp_entry_source_provenance([entry], [selected, rejected])

    alternate = entry["_alternate_ladder_review_entries"][0]
    assert entry["original_file_path"] == str(selected.resolve())
    assert alternate["original_file_path"] == str(rejected.resolve())
    assert alternate["file_name"] == rejected.name
    assert alternate["source_run_dir"] == run_dir.name


def test_same_named_staged_inputs_keep_their_original_run_identity(tmp_path):
    sources = [tmp_path / run / "sample_FR1.fsa" for run in ("run_one", "run_two")]
    entries = [
        {"file_name": _safe_link_name(source, index)}
        for index, source in enumerate(sources, start=1)
    ]

    _stamp_entry_source_provenance(entries, sources)

    assert [entry["original_file_path"] for entry in entries] == [
        str(source.resolve()) for source in sources
    ]
    assert [entry["source_run_dir"] for entry in entries] == ["run_one", "run_two"]


def test_same_named_inputs_use_exact_source_path_when_names_are_unstaged(tmp_path):
    sources = [tmp_path / run / "sample_FR1.fsa" for run in ("run_one", "run_two")]
    entries = [
        {"file_name": source.name, "original_file_path": str(source)}
        for source in sources
    ]

    _stamp_entry_source_provenance(entries, sources)

    assert [entry["original_file_path"] for entry in entries] == [
        str(source.resolve()) for source in sources
    ]


def test_ambiguous_source_basename_is_not_guessed(tmp_path):
    sources = [tmp_path / run / "sample_FR1.fsa" for run in ("run_one", "run_two")]
    entry = {"file_name": "sample_FR1.fsa"}

    _stamp_entry_source_provenance([entry], sources)

    assert "original_file_path" not in entry
