"""MlLearning IO helpers.

Phase A (Plan 13).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def list_fsa_files(folder: Path) -> list[Path]:
    """Walk ``folder`` and return all FSA files, sorted.

    Mirrors ``core.batch._scan_folder_fsa_files`` but is fractionally simpler
    so headless tests don't have to spin up the full batch module.
    """
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        return []
    out: list[Path] = []
    for candidate in sorted(folder.rglob("*.fsa")):
        if not candidate.is_file():
            continue
        if candidate.stat().st_size <= 0:
            continue
        # Skip the backfill-known-hang set if it exists - falls back gracefully
        # if the constant is missing.
        try:
            from core.batch import KNOWN_CLONALITY_BACKFILL_SKIP_FILES
        except Exception:
            skip_set: set[str] = set()
        else:
            skip_set = KNOWN_CLONALITY_BACKFILL_SKIP_FILES
        if candidate.name in skip_set:
            continue
        out.append(candidate)
    return out


def write_json(path: Path, payload: Any) -> Path:
    """Atomic-ish JSON write. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path) -> Any:
    """Read a JSON file; returns None if missing."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def append_jsonl(path: Path, record: dict[str, Any]) -> int:
    """Append ONE JSON line; returns the count of records written after append.

    Idempotent: callers can pass a record twice and decide whether to dedup
    at consumption time (matches the Plan 11 trainer convention).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 1 + _count_lines(path)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


__all__ = [
    "append_jsonl",
    "list_fsa_files",
    "read_json",
    "write_json",
]
