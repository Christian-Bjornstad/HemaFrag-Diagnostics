"""Transactional SQLite snapshots for future tracking-workbook storage."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


RUN_LEDGER_SCHEMA = "hemafrag_run_ledger_v1"


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT PRIMARY KEY,
            created_at_utc TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sheets (
            snapshot_id TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            PRIMARY KEY (snapshot_id, sheet_name),
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
                ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sheet_rows (
            snapshot_id TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (snapshot_id, sheet_name, row_index),
            FOREIGN KEY (snapshot_id, sheet_name)
                REFERENCES sheets(snapshot_id, sheet_name) ON DELETE CASCADE
        );
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)",
        ("schema_version", RUN_LEDGER_SCHEMA),
    )
    connection.commit()
    return connection


def replace_snapshot(
    ledger_path: str | Path,
    *,
    snapshot_id: str,
    frames: Mapping[str, pd.DataFrame],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Atomically replace one run snapshot while retaining other runs."""
    identifier = str(snapshot_id).strip()
    if not identifier:
        raise ValueError("snapshot_id is required.")
    normalized_frames = {
        str(name): frame.copy()
        for name, frame in frames.items()
        if str(name).strip()
    }
    path = Path(ledger_path).expanduser()
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO snapshots(snapshot_id, created_at_utc, metadata_json)
            VALUES (?, ?, ?)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                created_at_utc=excluded.created_at_utc,
                metadata_json=excluded.metadata_json
            """,
            (
                identifier,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(
                    {str(key): _json_value(value) for key, value in (metadata or {}).items()},
                    sort_keys=True,
                    ensure_ascii=True,
                ),
            ),
        )
        connection.execute(
            "DELETE FROM sheet_rows WHERE snapshot_id = ?",
            (identifier,),
        )
        connection.execute(
            "DELETE FROM sheets WHERE snapshot_id = ?",
            (identifier,),
        )
        for sheet_name, frame in sorted(normalized_frames.items()):
            columns = [str(column) for column in frame.columns]
            connection.execute(
                """
                INSERT INTO sheets(snapshot_id, sheet_name, columns_json, row_count)
                VALUES (?, ?, ?, ?)
                """,
                (
                    identifier,
                    sheet_name,
                    json.dumps(columns, ensure_ascii=True),
                    int(len(frame)),
                ),
            )
            payloads = []
            for row_index, row in enumerate(frame.itertuples(index=False, name=None)):
                payload = {
                    column: _json_value(value)
                    for column, value in zip(columns, row)
                }
                payloads.append(
                    (
                        identifier,
                        sheet_name,
                        int(row_index),
                        json.dumps(payload, sort_keys=True, ensure_ascii=True),
                    )
                )
            connection.executemany(
                """
                INSERT INTO sheet_rows(
                    snapshot_id, sheet_name, row_index, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                payloads,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "schema_version": RUN_LEDGER_SCHEMA,
        "path": str(path.resolve()),
        "snapshot_id": identifier,
        "sheet_rows": {
            name: int(len(frame)) for name, frame in sorted(normalized_frames.items())
        },
    }


def read_snapshot(
    ledger_path: str | Path,
    snapshot_id: str,
) -> dict[str, pd.DataFrame]:
    path = Path(ledger_path).expanduser()
    connection = _connect(path)
    try:
        sheets = connection.execute(
            """
            SELECT sheet_name, columns_json
            FROM sheets
            WHERE snapshot_id = ?
            ORDER BY sheet_name
            """,
            (str(snapshot_id),),
        ).fetchall()
        output: dict[str, pd.DataFrame] = {}
        for sheet_name, columns_json in sheets:
            columns = json.loads(columns_json)
            rows = connection.execute(
                """
                SELECT payload_json
                FROM sheet_rows
                WHERE snapshot_id = ? AND sheet_name = ?
                ORDER BY row_index
                """,
                (str(snapshot_id), str(sheet_name)),
            ).fetchall()
            records = [json.loads(payload_json) for (payload_json,) in rows]
            output[str(sheet_name)] = pd.DataFrame(records, columns=columns)
        return output
    finally:
        connection.close()


def snapshot_workbook(
    ledger_path: str | Path,
    *,
    snapshot_id: str,
    workbook_path: str | Path,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    workbook = Path(workbook_path).expanduser()
    frames = pd.read_excel(workbook, sheet_name=None)
    result = replace_snapshot(
        ledger_path,
        snapshot_id=snapshot_id,
        frames=frames,
        metadata={
            **dict(metadata or {}),
            "source_workbook": str(workbook.resolve()),
        },
    )
    result["source_workbook"] = str(workbook.resolve())
    return result


def export_snapshot_workbook(
    ledger_path: str | Path,
    *,
    snapshot_id: str,
    output_path: str | Path,
) -> Path:
    frames = read_snapshot(ledger_path, snapshot_id)
    if not frames:
        raise KeyError(f"Snapshot not found or empty: {snapshot_id}")
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}.",
            suffix=".xlsx",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            for sheet_name, frame in frames.items():
                frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


__all__ = [
    "RUN_LEDGER_SCHEMA",
    "export_snapshot_workbook",
    "read_snapshot",
    "replace_snapshot",
    "snapshot_workbook",
]
