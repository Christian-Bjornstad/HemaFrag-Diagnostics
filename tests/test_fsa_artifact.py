from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from core.analysis._constants import _preferred_size_standard_channel_for_file
from core.fsa_artifact import (
    FSA_ARTIFACT_SCHEMA,
    clear_fsa_artifact_cache,
    get_fsa_artifact_stats,
    load_fsa_artifact,
)
from fraggler.fraggler import FsaFile


def _record() -> SimpleNamespace:
    trace = np.arange(200, dtype=float)
    return SimpleNamespace(
        annotations={
            "abif_raw": {
                "DATA1": trace,
                "DATA4": trace + 1,
                "DATA105": trace + 2,
                "TUBE1": b"A01",
            }
        }
    )


def test_fsa_artifact_cache_invalidates_on_file_stat_change(tmp_path, monkeypatch):
    path = tmp_path / "sample.fsa"
    path.write_bytes(b"first")
    calls: list[str] = []

    def fake_read(file_name, _format):
        calls.append(str(file_name))
        return _record()

    monkeypatch.setattr("core.fsa_artifact.SeqIO.read", fake_read)
    clear_fsa_artifact_cache()

    first = load_fsa_artifact(path)
    second = load_fsa_artifact(path)
    path.write_bytes(b"second-version")
    third = load_fsa_artifact(path)

    assert first is second
    assert third is not first
    assert len(calls) == 2
    assert first.schema_version == FSA_ARTIFACT_SCHEMA
    assert first.content_sha256 != third.content_sha256
    stats = get_fsa_artifact_stats()
    assert stats["decode_count"] == 2
    assert stats["cache_hits"] == 1


def test_channel_probe_and_fsa_file_share_one_decode(tmp_path, monkeypatch):
    path = tmp_path / "sample.fsa"
    path.write_bytes(b"fake-abif")
    calls: list[str] = []

    def fake_read(file_name, _format):
        calls.append(str(file_name))
        return _record()

    monkeypatch.setattr("core.fsa_artifact.SeqIO.read", fake_read)
    clear_fsa_artifact_cache()

    channel = _preferred_size_standard_channel_for_file(path, "LIZ500_250")
    fsa = FsaFile(
        file=str(path),
        ladder="LIZ500_250",
        sample_channel="DATA1",
        min_distance_between_peaks=5,
        min_size_standard_height=50,
        size_standard_channel=channel,
    )

    assert channel == "DATA105"
    assert fsa.fsa_artifact is load_fsa_artifact(path)
    assert len(calls) == 1
    assert get_fsa_artifact_stats()["cache_hits"] == 2


def test_fsa_artifact_cache_has_explicit_benchmark_bypass(tmp_path, monkeypatch):
    path = tmp_path / "sample.fsa"
    path.write_bytes(b"fake-abif")
    calls: list[str] = []

    def fake_read(file_name, _format):
        calls.append(str(file_name))
        return _record()

    monkeypatch.setattr("core.fsa_artifact.SeqIO.read", fake_read)
    monkeypatch.setenv("HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE", "1")
    clear_fsa_artifact_cache()

    first = load_fsa_artifact(path)
    second = load_fsa_artifact(path)

    assert first is not second
    assert len(calls) == 2
    assert get_fsa_artifact_stats()["cache_disabled"] == 1
