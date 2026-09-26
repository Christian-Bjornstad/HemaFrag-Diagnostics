"""Persistent storage for manually corrected ladder fits."""
from __future__ import annotations

import hashlib
import json
import logging
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
_LOGGER = logging.getLogger(__name__)


class InvalidLadderAdjustmentRecord(ValueError):
    """An existing record failed integrity checks and must not be replaced implicitly."""


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


def _payload_digest(payload: dict[str, Any], *, sort_keys: bool = True) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=sort_keys,
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
    connection.execute(
        """CREATE TABLE IF NOT EXISTS ladder_adjustment_deactivations (
            source_key TEXT NOT NULL,
            ladder TEXT NOT NULL,
            size_standard_channel TEXT NOT NULL,
            PRIMARY KEY (source_key, ladder, size_standard_channel)
        )"""
    )
    return connection


def deactivate_ladder_adjustment_record(
    source_path: Path, *, ladder: str = "", size_standard_channel: str = ""
) -> None:
    """Deactivate one exact identity, including any legacy sidecar for that identity.

    Byte-identical source copies share a hash identity and are deactivated together.
    A later explicit save reactivates the identity.
    """
    source_key, _ = _source_key(source_path)
    identity = (source_key, _normalize_identity(ladder), _normalize_identity(size_standard_channel))
    with _STORE_LOCK:
        with closing(_connect(resolve_ladder_adjustment_db_path())) as connection:
            with connection:
                connection.execute(
                    "DELETE FROM ladder_adjustments WHERE source_key = ? AND ladder = ? AND size_standard_channel = ?",
                    identity,
                )
                connection.execute(
                    "INSERT OR IGNORE INTO ladder_adjustment_deactivations VALUES (?, ?, ?)",
                    identity,
                )


def is_ladder_adjustment_deactivated(
    source_path: Path, *, ladder: str = "", size_standard_channel: str = ""
) -> bool:
    database_path = resolve_ladder_adjustment_db_path()
    if not database_path.is_file():
        return False
    source_key, _ = _source_key(source_path)
    with _STORE_LOCK:
        with closing(_connect(database_path)) as connection:
            return connection.execute(
                """SELECT 1 FROM ladder_adjustment_deactivations
                   WHERE source_key = ? AND (? = '' OR ladder = ?)
                     AND (? = '' OR size_standard_channel = ?)""",
                (source_key, _normalize_identity(ladder), _normalize_identity(ladder),
                 _normalize_identity(size_standard_channel), _normalize_identity(size_standard_channel)),
            ).fetchone() is not None


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
            connection.execute(
                "DELETE FROM ladder_adjustment_deactivations WHERE source_key = ? AND ladder = ? AND size_standard_channel = ?",
                (source_key, ladder_key, channel_key),
            )
            connection.commit()
    return database_path


def load_ladder_adjustment_record(
    source_path: Path,
    *,
    ladder: str = "",
    size_standard_channel: str = "",
    database_path: Path | None = None,
    allow_unscoped_ladder: bool = True,
    raise_on_invalid: bool = False,
) -> dict[str, Any] | None:
    """Read a verified record, optionally distinguishing invalid from absent data.

    Migration callers must opt into ``raise_on_invalid`` so an invalid existing
    record cannot be mistaken for permission to import an older correction.
    """
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
            if connection.execute(
                "SELECT 1 FROM ladder_adjustment_deactivations WHERE source_key = ? AND ladder = ? AND size_standard_channel = ?",
                (source_key, ladder_key, channel_key),
            ).fetchone():
                return None
            row = connection.execute(
                """
                SELECT payload_json, payload_sha256, saved_at_utc
                FROM ladder_adjustments
                WHERE source_key = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM ladder_adjustment_deactivations AS d
                      WHERE d.source_key = ladder_adjustments.source_key
                        AND d.ladder = ladder_adjustments.ladder
                        AND d.size_standard_channel = ladder_adjustments.size_standard_channel
                  )
                  AND (
                      ? = ''
                      OR ladder = ?
                      OR (? = 1 AND ladder = '')
                  )
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
                    int(bool(allow_unscoped_ladder)),
                    channel_key,
                    channel_key,
                    ladder_key,
                    channel_key,
                ),
            ).fetchone()
    if row is None:
        return None
    try:
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError) as error:
            raise InvalidLadderAdjustmentRecord("Stored adjustment is not valid JSON.") from error
        if not isinstance(payload, dict):
            raise InvalidLadderAdjustmentRecord("Stored adjustment must be a JSON object.")
        # Preserve serialized key order: existing records may have sorted
        # integer mapping keys, which become strings after the JSON round trip.
        if _payload_digest(payload, sort_keys=False) != str(row[1] or ""):
            raise InvalidLadderAdjustmentRecord("Stored adjustment checksum does not match.")
    except InvalidLadderAdjustmentRecord as error:
        if raise_on_invalid:
            raise
        _LOGGER.warning("Ignoring invalid stored ladder adjustment for %s: %s", source_path.name, error)
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
    "InvalidLadderAdjustmentRecord",
    "deactivate_ladder_adjustment_record",
    "is_ladder_adjustment_deactivated",
    "load_ladder_adjustment_record",
    "resolve_ladder_adjustment_db_path",
    "save_ladder_adjustment_record",
]
