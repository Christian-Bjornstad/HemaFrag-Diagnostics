"""Persistent storage for manually corrected ladder fits."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any
from contextlib import closing


LADDER_ADJUSTMENT_DB_ENV = "HEMAFRAG_LADDER_ADJUSTMENT_DB"
DEFAULT_LADDER_ADJUSTMENT_DB = (
    Path.home() / ".config" / "fraggler" / "ladder_adjustments.sqlite3"
)
_STORE_LOCK = threading.Lock()


def resolve_ladder_adjustment_db_path() -> Path:
    configured = str(os.environ.get(LADDER_ADJUSTMENT_DB_ENV) or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_LADDER_ADJUSTMENT_DB


def _source_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_key(path: Path) -> tuple[str, str]:
    resolved = path.expanduser().resolve()
    digest = _source_hash(resolved)
    return (f"sha256:{digest}" if digest else f"path:{resolved}", digest)


def _normalize_identity(value: str | None) -> str:
    return str(value or "").strip().upper()


def _payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ladder_adjustments (
            source_key TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_path TEXT NOT NULL,
            ladder TEXT NOT NULL,
            size_standard_channel TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            saved_at_utc TEXT NOT NULL,
            PRIMARY KEY (source_key, ladder, size_standard_channel)
        )
        """
    )
    return connection


def save_ladder_adjustment_record(
    source_path: Path,
    payload: dict[str, Any],
    *,
    ladder: str = "",
    size_standard_channel: str = "",
) -> Path:
    database_path = resolve_ladder_adjustment_db_path()
    source_path = source_path.expanduser().resolve()
    source_key, source_sha256 = _source_key(source_path)
    ladder_key = _normalize_identity(ladder)
    channel_key = _normalize_identity(size_standard_channel)
    payload_text = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    payload_sha256 = _payload_digest(payload)
    saved_at = str(
        (payload.get("review") or {}).get("saved_at_utc")
        if isinstance(payload.get("review"), dict)
        else ""
    )

    with _STORE_LOCK:
        with closing(_connect(database_path)) as connection:
            connection.execute(
                """
                INSERT INTO ladder_adjustments (
                    source_key,
                    source_sha256,
                    source_path,
                    ladder,
                    size_standard_channel,
                    payload_json,
                    payload_sha256,
                    saved_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key, ladder, size_standard_channel) DO UPDATE SET
                    source_sha256 = excluded.source_sha256,
                    source_path = excluded.source_path,
                    payload_json = excluded.payload_json,
                    payload_sha256 = excluded.payload_sha256,
                    saved_at_utc = excluded.saved_at_utc
                """,
                (
                    source_key,
                    source_sha256,
                    str(source_path),
                    ladder_key,
                    channel_key,
                    payload_text,
                    payload_sha256,
                    saved_at,
                ),
            )
            connection.commit()
    return database_path


def load_ladder_adjustment_record(
    source_path: Path,
    *,
    ladder: str = "",
    size_standard_channel: str = "",
    database_path: Path | None = None,
) -> dict[str, Any] | None:
    database_path = (
        Path(database_path).expanduser()
        if database_path is not None
        else resolve_ladder_adjustment_db_path()
    )
    if not database_path.is_file():
        return None

    source_key, _source_sha256 = _source_key(source_path)
    ladder_key = _normalize_identity(ladder)
    channel_key = _normalize_identity(size_standard_channel)
    with _STORE_LOCK:
        with closing(_connect(database_path)) as connection:
            row = connection.execute(
                """
                SELECT payload_json, payload_sha256, saved_at_utc
                FROM ladder_adjustments
                WHERE source_key = ?
                  AND (? = '' OR ladder IN (?, ''))
                  AND (? = '' OR size_standard_channel IN (?, ''))
                ORDER BY
                    CASE WHEN ladder = ? THEN 0 ELSE 1 END,
                    CASE WHEN size_standard_channel = ? THEN 0 ELSE 1 END,
                    saved_at_utc DESC
                LIMIT 1
                """,
                (
                    source_key,
                    ladder_key,
                    ladder_key,
                    channel_key,
                    channel_key,
                    ladder_key,
                    channel_key,
                ),
            ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "payload": payload,
        "payload_sha256": str(row[1] or ""),
        "saved_at_utc": str(row[2] or ""),
        "database_path": database_path,
    }


__all__ = [
    "DEFAULT_LADDER_ADJUSTMENT_DB",
    "LADDER_ADJUSTMENT_DB_ENV",
    "load_ladder_adjustment_record",
    "resolve_ladder_adjustment_db_path",
    "save_ladder_adjustment_record",
]
