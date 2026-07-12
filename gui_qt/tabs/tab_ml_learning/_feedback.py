"""MlLearning JSONL feedback loop.

Phase C (Plan 13). The chemist exports annotations from the browser-hosted
Plotly panel (which downloads a JSON file via a blob anchor). The tab
watches ML_Learning/imports/*.json on disk and folds them into a JSONL
file that the Plan 11 trainer reads.

Idempotency:
  - We deduplicate by (raw_path, annotated_at_utc) - repeat imports of the
    same export file do NOT duplicate rows.
  - Imports track a sidecar ``imports/_imported.jsonl`` manifest so we
    can skip files we've already processed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from gui_qt.tabs.tab_ml_learning._constants import (
    LEARNING_SCHEMA_VERSION,
    SUBDIR_JSONL,
)


# File paths ---------------------------------------------------------------

def feedback_paths(root: Path) -> dict[str, Path]:
    """Return the canonical file paths for the feedback loop under ``root``."""
    return {
        "imports_dir": root / "imports",
        "imports_manifest": root / "imports" / "_imported.jsonl",
        "annotations_jsonl": root / SUBDIR_JSONL / "learning.jsonl",
    }


def ensure_dirs(paths: dict[str, Path]) -> None:
    for p in paths.values():
        Path(p).parent.mkdir(parents=True, exist_ok=True)


# Harvest ------------------------------------------------------------------

def harvest_to_records(
    annotations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pick only the fields the trainer needs and stamp them."""
    rows: list[dict[str, Any]] = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        cls = str(ann.get("annotation_class") or "").strip()
        if not cls:
            continue  # skip rows the chemist left blank
        rows.append({
            "raw_path": str(ann.get("raw_path") or ""),
            "file": str(ann.get("file") or ""),
            "assay": str(ann.get("assay") or ""),
            "dit": str(ann.get("dit") or ""),
            "annotation_class": cls,
            "control_flag": str(ann.get("control_flag") or ""),
            "note": str(ann.get("note") or ""),
            "annotated_at_utc": str(
                ann.get("annotated_at_utc")
                or datetime.now(timezone.utc).isoformat()
            ),
            "schema_version": LEARNING_SCHEMA_VERSION,
        })
    return rows


def record_dedupe_key(record: dict[str, Any]) -> str:
    """Stable hash for dedupe - same file + same ``annotated_at_utc`` ⇒ dup."""
    raw = json.dumps(
        {
            "raw_path": record["raw_path"],
            "annotated_at_utc": record["annotated_at_utc"],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# Append + manifest --------------------------------------------------------


def load_manifest(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    seen: set[str] = set()
    with manifest_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("kind") == "import":
                seen.add(obj.get("import_id") or "")
    return seen


def import_id_for(source_path: Path, payload: Any) -> str:
    """Stable hash for a source-export file + payload fingerprint."""
    raw = json.dumps(
        {"file": source_path.name, "n": len(payload) if isinstance(payload, list) else -1},
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def import_one(
    *,
    source_path: Path,
    payload: Any,
    paths: dict[str, Path],
) -> dict[str, int]:
    """Fold ONE export file into the JSONL + manifest.

    Returns counts: {imported: int, skipped: int, total: int}.
    """
    if not isinstance(payload, list):
        return {"imported": 0, "skipped": 0, "total": 0}
    ensure_dirs(paths)

    manifest = load_manifest(paths["imports_manifest"])
    source_id = import_id_for(source_path, payload)

    if source_id in manifest:
        return {"imported": 0, "skipped": len(payload), "total": len(payload)}

    records = harvest_to_records(payload)
    seen_keys = _existing_keys(paths["annotations_jsonl"])
    written = 0
    with paths["annotations_jsonl"].open("a", encoding="utf-8") as fh:
        for rec in records:
            key = record_dedupe_key(rec)
            if key in seen_keys:
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            seen_keys.add(key)
            written += 1

    # Mark this import done in the manifest
    with paths["imports_manifest"].open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(
            {
                "kind": "import",
                "import_id": source_id,
                "source_file": source_path.name,
                "imported_at_utc": datetime.now(timezone.utc).isoformat(),
                "records_written": written,
            },
            ensure_ascii=False,
        ) + "\n")

    return {"imported": written, "skipped": len(payload) - written, "total": len(payload)}


def _existing_keys(jsonl_path: Path) -> set[str]:
    if not jsonl_path.exists():
        return set()
    keys: set[str] = set()
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            try:
                keys.add(record_dedupe_key(obj))
            except Exception:
                continue
    return keys


# Trainer integration helper ---------------------------------------------

def load_jsonl_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Read all valid JSONL rows from disk. Skips malformed lines."""
    if not jsonl_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def annotations_summary(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Tiny summary useful for the GUI status bar."""
    by_assay: dict[str, int] = {}
    by_class: dict[str, int] = {}
    n = 0
    for rec in records:
        n += 1
        by_assay[rec.get("assay", "?")] = by_assay.get(rec.get("assay", "?"), 0) + 1
        by_class[rec.get("annotation_class", "?")] = by_class.get(rec.get("annotation_class", "?"), 0) + 1
    return {
        "total": n,
        "by_assay": by_assay,
        "by_class": by_class,
    }


__all__ = [
    "annotations_summary",
    "feedback_paths",
    "harvest_to_records",
    "import_one",
    "load_jsonl_records",
    "record_dedupe_key",
]
