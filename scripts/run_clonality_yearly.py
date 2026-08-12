#!/usr/bin/env python3
"""Resumable yearly clonality archive orchestration for the Qt runner."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import APP_SETTINGS
from core.clonality_backfill import run_clonality_backfill
from scripts.combine_clonality_yearly_overview import combine_run_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return cleaned.strip("._-")


def normalize_month_keys(year_label: str, months: list[str]) -> list[str]:
    year = str(year_label).strip()
    normalized: list[str] = []
    for raw in months:
        value = str(raw).strip().replace("-", "_")
        if value.isdigit() and len(value) <= 2:
            value = f"{year}_{int(value):02d}"
        elif re.fullmatch(r"\d{4}_\d{1,2}", value):
            prefix, month = value.split("_", 1)
            value = f"{prefix}_{int(month):02d}"
        if not re.fullmatch(rf"{re.escape(year)}_(0[1-9]|1[0-2])", value):
            continue
        if value not in normalized:
            normalized.append(value)
    return sorted(normalized)


def discover_month_folders(input_root: Path, year_label: str) -> dict[str, list[Path]]:
    root = Path(input_root).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"Input root not found: {root}")
    months = {f"{year_label}_{month:02d}": [] for month in range(1, 13)}
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        key = folder.name[:7].replace("-", "_")
        if key in months:
            months[key].append(folder)
    return months


def _emit(callback: Callable | None, payload) -> None:
    if callback is not None:
        callback(payload)


def _write_manifest(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _review_bundles(run_root: Path) -> list[str]:
    return [
        str(path.parent.resolve())
        for path in sorted(run_root.rglob("ladder_review_cases.csv"))
    ]


def run_yearly_validation(
    *,
    year_label: str,
    input_root: Path,
    output_root: Path,
    run_name: str | None = None,
    months: list[str] | None = None,
    max_workers: int = 1,
    folder_workers: int = 1,
    refresh_each_folder: bool = False,
    include_sl: bool = False,
    cleanup_staging_root: bool = False,
    resume_existing: bool = False,
    use_rust: bool = True,
    skip_html_reports: bool = True,
    progress_callback: Callable | None = None,
    status_callback: Callable | None = None,
) -> dict:
    year = str(year_label).strip()
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError("Year must contain four digits.")
    source = Path(input_root).expanduser()
    destination = Path(output_root).expanduser()
    month_keys = normalize_month_keys(
        year,
        months or [f"{year}_{month:02d}" for month in range(1, 13)],
    )
    if not month_keys:
        raise ValueError("No valid months were selected.")
    month_map = discover_month_folders(source, year)

    base_name = _safe_name(run_name or "") or (
        f"clonality_archive_{year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_root = destination / base_name
    if run_root.exists() and not resume_existing:
        run_root = destination / (
            f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / f"full_{year}_run_manifest.json"
    manifest: dict = {
        "schema_version": "hemafrag_clonality_archive_v1",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "running",
        "year": year,
        "run_dir": str(run_root.resolve()),
        "input_root": str(source.resolve()),
        "settings": {
            "max_workers": int(max_workers),
            "folder_workers": int(folder_workers),
            "refresh_each_folder": bool(refresh_each_folder),
            "include_sl": bool(include_sl),
            "cleanup_staging_root": bool(cleanup_staging_root),
            "use_rust": bool(use_rust),
            "skip_html_reports": bool(skip_html_reports),
        },
        "months": {},
    }
    _write_manifest(manifest_path, manifest)
    _emit(
        progress_callback,
        {"event": "run_started", "run_dir": str(run_root)},
    )

    previous_rust = APP_SETTINGS.setdefault("engine", {}).get("use_rust", True)
    APP_SETTINGS["engine"]["use_rust"] = bool(use_rust)
    failures: list[str] = []
    try:
        for month_key in month_keys:
            folders = month_map.get(month_key, [])
            month_dir = run_root / "month_runs" / month_key
            month_dir.mkdir(parents=True, exist_ok=True)
            month_state = {
                "status": "running",
                "folder_count": len(folders),
                "run_dir": str(month_dir.resolve()),
                "started_at_utc": _utc_now(),
            }
            manifest["months"][month_key] = month_state
            manifest["updated_at_utc"] = _utc_now()
            _write_manifest(manifest_path, manifest)
            _emit(
                progress_callback,
                {
                    "event": "month_started",
                    "month": month_key,
                    "folder_count": len(folders),
                    "run_dir": str(month_dir),
                },
            )
            if not folders:
                month_state["status"] = "skipped_empty"
                month_state["finished_at_utc"] = _utc_now()
                _emit(
                    progress_callback,
                    {
                        "event": "month_skipped_empty",
                        "month": month_key,
                        "folder_count": 0,
                        "run_dir": str(month_dir),
                    },
                )
                continue

            _emit(status_callback, f"Running archive month {month_key}")
            try:
                state = run_clonality_backfill(
                    input_root=source,
                    month=month_key,
                    output_base=month_dir,
                    tracking_excel_path=month_dir / "track-clonality.xlsx",
                    state_file=month_dir / "backfill_state.json",
                    max_workers=max(1, int(max_workers)),
                    folder_workers=max(1, int(folder_workers)),
                    retry_failed=bool(resume_existing),
                    defer_tracking_refresh=not bool(refresh_each_folder),
                    skip_html_reports=bool(skip_html_reports),
                )
                failed = [
                    name
                    for name, item in (state.get("folders") or {}).items()
                    if str(item.get("status") or "") == "failed"
                    and str(item.get("month") or "") == month_key
                ]
                month_state["status"] = "completed_with_errors" if failed else "done"
                month_state["failed_folders"] = failed
                if failed:
                    failures.extend(f"{month_key}/{name}" for name in failed)
            except Exception as exc:
                month_state["status"] = "failed"
                month_state["error"] = f"{type(exc).__name__}: {exc}"
                failures.append(month_key)
            month_state["finished_at_utc"] = _utc_now()
            manifest["updated_at_utc"] = _utc_now()
            _write_manifest(manifest_path, manifest)
            _emit(
                progress_callback,
                {
                    "event": "month_finished",
                    "month": month_key,
                    "run_dir": str(month_dir),
                    "status": month_state["status"],
                },
            )
    finally:
        APP_SETTINGS["engine"]["use_rust"] = previous_rust

    workbook_path: Path | None = None
    try:
        workbook_path = combine_run_root(
            run_root,
            run_root / f"track-clonality-{year}-overview.xlsx",
            year_label=year,
            include_sl=include_sl,
        )
    except FileNotFoundError:
        workbook_path = None

    manifest["status"] = "completed_with_errors" if failures else "completed"
    manifest["failed_items"] = failures
    manifest["combined_workbook_path"] = (
        str(workbook_path.resolve()) if workbook_path else ""
    )
    manifest["review_bundles"] = _review_bundles(run_root)
    manifest["updated_at_utc"] = _utc_now()
    manifest["completed_at_utc"] = _utc_now()
    _write_manifest(manifest_path, manifest)
    _emit(
        progress_callback,
        {
            "event": "manifest_written",
            "manifest_path": str(manifest_path),
            "run_dir": str(run_root),
        },
    )
    _emit(
        progress_callback,
        {
            "event": "run_finished",
            "manifest_path": str(manifest_path),
            "run_dir": str(run_root),
        },
    )
    _emit(status_callback, "Yearly archive run finished")
    return manifest


__all__ = [
    "discover_month_folders",
    "normalize_month_keys",
    "run_yearly_validation",
]
