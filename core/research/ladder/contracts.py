"""Stable contracts and path policy for historical ladder research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


INVENTORY_SCHEMA_VERSION = "1.0"
MANUAL_CORRECTION_SCHEMA_VERSION = "1.0"
DIAGNOSTIC_SCHEMA_VERSION = "1.0"
PARTITION_SCHEMA_VERSION = "1.0"


class LadderOutcome(str, Enum):
    """Mutually exclusive top-level historical ladder outcomes."""

    MISSING_LADDER_SIGNAL = "missing_ladder_signal"
    WRONG_LADDER_OR_CHANNEL = "wrong_ladder_or_channel"
    FIT_REJECTED_WITH_USABLE_SIGNAL = "fit_rejected_with_usable_signal"
    FIT_ACCEPTED_BUT_WRONG = "fit_accepted_but_wrong"
    FIT_CORRECT_REVIEW_ONLY = "fit_correct_review_only"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ResearchRoots:
    """Explicit input and output boundaries for one research execution."""

    raw_roots: tuple[Path, ...]
    archive_root: Path
    output_root: Path
    excluded_backup_root: Path

    @classmethod
    def default(cls) -> "ResearchRoots":
        return cls(
            raw_roots=(
                Path(r"D:\DATA\2024_DATA"),
                Path(r"D:\DATA\2025_data"),
                Path(r"D:\DATA\2026_data"),
            ),
            archive_root=Path(r"D:\Klonalitet_Archive"),
            output_root=Path(r"D:\HemaFrag_Research\ladder"),
            excluded_backup_root=Path(r"D:\DATA\backup"),
        )


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def assert_allowed_raw_path(path: Path, roots: ResearchRoots) -> Path:
    """Resolve and return a raw path only when it is inside an allowed year root."""

    candidate = Path(path).resolve()
    excluded = roots.excluded_backup_root.resolve()
    if _is_within(candidate, excluded):
        raise ValueError(f"Path is inside the excluded backup root: {candidate}")

    allowed = tuple(root.resolve() for root in roots.raw_roots)
    if not any(_is_within(candidate, root) for root in allowed):
        raise ValueError(f"Path is outside the allowed raw roots: {candidate}")
    return candidate


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Value is not JSON serializable: {type(value).__name__}")


def stable_json_fingerprint(value: Any) -> str:
    """Return a SHA-256 fingerprint of a canonical JSON representation."""

    canonical = json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
