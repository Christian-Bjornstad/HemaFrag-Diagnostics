"""Immutable execution context captured when a HemaFrag run is queued."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from config import APP_SETTINGS, DEFAULT_SETTINGS


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_id() -> str:
    return (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )


def _copy_settings_value(value: Any, *, path: str = "settings") -> Any:
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} must contain only string keys")
            copied[key] = _copy_settings_value(nested, path=f"{path}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [
            _copy_settings_value(nested, path=f"{path}[{index}]")
            for index, nested in enumerate(value)
        ]
    if value is None or isinstance(value, (str, bool, int, Path, Enum)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    raise TypeError(
        f"{path} contains unsupported value type {type(value).__name__}"
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(nested) for nested in value)
    return value


def settings_fingerprint(settings: Mapping[str, Any]) -> str:
    """Match the canonical fingerprint used by existing batch manifests."""

    if not isinstance(settings, Mapping):
        raise TypeError("settings must be a mapping")
    canonical_settings = _copy_settings_value(settings)
    encoded = json.dumps(
        canonical_settings,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("created_at_utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("created_at_utc must use UTC")


@dataclass(frozen=True, slots=True)
class RunContext:
    """A validated settings snapshot and stable identity for one execution."""

    run_id: str
    parent_run_id: str | None
    analysis_id: str
    created_at_utc: str
    settings_snapshot: Mapping[str, Any]
    settings_fingerprint: str = field(init=False)

    def settings_copy(self) -> dict[str, Any]:
        """Return a mutable copy for legacy helpers that merge profile defaults."""
        return _copy_settings_value(self.settings_snapshot)

    def __post_init__(self) -> None:
        supported_analyses = DEFAULT_SETTINGS.get("analyses", {})
        if self.analysis_id not in supported_analyses:
            raise ValueError(f"Unsupported analysis_id: {self.analysis_id!r}")
        if not isinstance(self.run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", self.run_id) is None:
            raise ValueError("run_id must be a safe manifest identifier")
        if self.parent_run_id is not None:
            if not isinstance(self.parent_run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", self.parent_run_id) is None:
                raise ValueError("parent_run_id must be a safe manifest identifier or None")
            if self.parent_run_id == self.run_id:
                raise ValueError("parent_run_id cannot equal run_id")
        _validate_timestamp(self.created_at_utc)
        if not isinstance(self.settings_snapshot, Mapping):
            raise TypeError("settings must be a mapping")

        copied = _copy_settings_value(self.settings_snapshot)
        if (
            "active_analysis" in copied
            and copied["active_analysis"] != self.analysis_id
        ):
            raise ValueError(
                "settings active_analysis must match the context analysis_id"
            )
        fingerprint = settings_fingerprint(copied)
        object.__setattr__(self, "settings_snapshot", _freeze(copied))
        object.__setattr__(self, "settings_fingerprint", fingerprint)

    @classmethod
    def create(
        cls,
        *,
        analysis_id: str,
        settings: Mapping[str, Any] | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        created_at_utc: str | None = None,
    ) -> "RunContext":
        """Capture settings now; an explicit empty mapping remains empty."""

        snapshot = APP_SETTINGS if settings is None else settings
        return cls(
            run_id=run_id if run_id is not None else _new_run_id(),
            parent_run_id=parent_run_id,
            analysis_id=analysis_id,
            created_at_utc=(
                created_at_utc if created_at_utc is not None else _utc_now()
            ),
            settings_snapshot=snapshot,
        )


__all__ = ["RunContext", "settings_fingerprint"]
