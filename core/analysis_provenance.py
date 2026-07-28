"""Consistent per-file provenance for reports and tracking exports."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app_meta import APP_VERSION


ANALYSIS_PROVENANCE_SCHEMA = "hemafrag_analysis_provenance_v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_path(entry: dict[str, Any], fsa: Any) -> Path | None:
    value = (
        entry.get("original_file_path")
        or getattr(fsa, "file", None)
        or ""
    )
    if not value:
        return None
    return Path(str(value)).expanduser()


def build_analysis_provenance(entry: dict[str, Any]) -> dict[str, object]:
    fsa = entry.get("fsa")
    strategy = str(entry.get("ladder_fit_strategy") or "")
    source = _source_path(entry, fsa)
    artifact = getattr(fsa, "fsa_artifact", None)
    source_hash = str(getattr(artifact, "content_sha256", "") or "")
    if not source_hash and source is not None and source.is_file():
        source_hash = _sha256_file(source)

    adjustment_path = source.with_suffix(".ladder_adj.json") if source is not None else None
    adjustment_hash = ""
    adjustment_schema = ""
    if adjustment_path is not None and adjustment_path.is_file():
        adjustment_hash = _sha256_file(adjustment_path)
        try:
            payload = json.loads(adjustment_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                adjustment_schema = str(payload.get("schema_version") or "legacy")
        except (OSError, ValueError):
            adjustment_schema = "unreadable"

    if strategy == "manual_adjustment":
        engine = "manual"
    elif getattr(fsa, "rust_detected_ladder", None):
        engine = "rust"
    else:
        engine = "python"
    reason_codes = entry.get("ladder_review_reason_codes") or []
    if not isinstance(reason_codes, (list, tuple)):
        reason_codes = [reason_codes]
    return {
        "schema_version": ANALYSIS_PROVENANCE_SCHEMA,
        "app_version": str(APP_VERSION),
        "source_file": source.name if source is not None else str(entry.get("file_name") or ""),
        "source_sha256": source_hash,
        "ladder": str(entry.get("internal_ladder") or entry.get("ladder") or ""),
        "size_standard_channel": str(
            entry.get("size_standard_channel")
            or getattr(fsa, "size_standard_channel", "")
            or ""
        ),
        "ladder_engine": engine,
        "ladder_fit_strategy": strategy,
        "ladder_qc_status": str(entry.get("ladder_qc_status") or ""),
        "ladder_reason_codes": [
            str(value) for value in reason_codes if str(value)
        ],
        "manual_adjustment_consumed": strategy == "manual_adjustment",
        "manual_adjustment_schema": adjustment_schema,
        "manual_adjustment_sha256": adjustment_hash,
    }


def attach_analysis_provenance(entry: dict[str, Any]) -> dict[str, Any]:
    entry["analysis_provenance"] = build_analysis_provenance(entry)
    return entry


__all__ = [
    "ANALYSIS_PROVENANCE_SCHEMA",
    "attach_analysis_provenance",
    "build_analysis_provenance",
]
