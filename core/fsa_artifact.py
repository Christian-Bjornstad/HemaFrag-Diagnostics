"""Versioned per-process ABIF decode artifact."""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class _LazySeqIOModule:
    """Module-like proxy for Bio.SeqIO.

    ``core.fsa_artifact`` sits on the GUI startup path; importing Bio costs
    ~100 ms and drags sqlite3, so it is deferred until the first decode.
    Attribute access (including test monkeypatching of ``SeqIO.read``)
    triggers the one-time import.
    """

    def __getattr__(self, name: str):
        from Bio import SeqIO

        return getattr(SeqIO, name)


SeqIO = _LazySeqIOModule()


FSA_ARTIFACT_SCHEMA = "hemafrag_fsa_artifact_v1"
_DECODE_LOCK = threading.Lock()
_DECODE_COUNT = 0


@dataclass(frozen=True)
class FsaArtifact:
    schema_version: str
    path: Path
    size_bytes: int
    mtime_ns: int
    content_sha256: str
    abif_raw: dict[str, Any]

    @property
    def data_channels(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                str(key)
                for key in self.abif_raw
                if str(key).upper().startswith("DATA")
            )
        )


def _decode_artifact(path_text: str, size_bytes: int, mtime_ns: int) -> FsaArtifact:
    del size_bytes, mtime_ns
    global _DECODE_COUNT
    path = Path(path_text)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    record = SeqIO.read(str(path), "abi")
    raw = record.annotations.get("abif_raw", {})
    if not isinstance(raw, dict):
        raw = dict(raw)
    with _DECODE_LOCK:
        _DECODE_COUNT += 1
    stat = path.stat()
    return FsaArtifact(
        schema_version=FSA_ARTIFACT_SCHEMA,
        path=path,
        size_bytes=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        content_sha256=digest.hexdigest(),
        abif_raw=raw,
    )


@lru_cache(maxsize=16)
def _load_cached(path_text: str, size_bytes: int, mtime_ns: int) -> FsaArtifact:
    return _decode_artifact(path_text, size_bytes, mtime_ns)


def load_fsa_artifact(path: str | Path) -> FsaArtifact:
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    if os.environ.get("HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return _decode_artifact(
            str(resolved),
            int(stat.st_size),
            int(stat.st_mtime_ns),
        )
    return _load_cached(str(resolved), int(stat.st_size), int(stat.st_mtime_ns))


def clear_fsa_artifact_cache() -> None:
    global _DECODE_COUNT
    _load_cached.cache_clear()
    with _DECODE_LOCK:
        _DECODE_COUNT = 0


def get_fsa_artifact_stats() -> dict[str, int | str]:
    info = _load_cached.cache_info()
    with _DECODE_LOCK:
        decode_count = int(_DECODE_COUNT)
    return {
        "schema_version": FSA_ARTIFACT_SCHEMA,
        "decode_count": decode_count,
        "cache_hits": int(info.hits),
        "cache_misses": int(info.misses),
        "cache_entries": int(info.currsize),
        "cache_capacity": int(info.maxsize or 0),
        "cache_disabled": int(
            os.environ.get("HEMAFRAG_DISABLE_FSA_ARTIFACT_CACHE", "").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
    }


__all__ = [
    "FSA_ARTIFACT_SCHEMA",
    "FsaArtifact",
    "clear_fsa_artifact_cache",
    "get_fsa_artifact_stats",
    "load_fsa_artifact",
]
