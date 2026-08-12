#!/usr/bin/env python3
"""Resumable FLT3 archive orchestration for the Qt Archive Runner."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import APP_SETTINGS
from core.analyses.clonality.ladder_review_gate import (
    write_ladder_review_gate,
)
from core.batch import generate_jobs, run_batch_jobs
from scripts.combine_flt3_yearly_overview import combine_run_root
from scripts.run_clonality_yearly import (
    discover_month_folders,
    normalize_month_keys,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return cleaned.strip("._-")


def _emit(callback: Callable | None, payload) -> None:
    if callback is not None:
        callback(payload)


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_review_bundle(result: dict, month_dir: Path) -> dict:
    entries = list(result.get("dit_report_entries") or [])
    gate = write_ladder_review_gate(
        entries,
        month_dir / "reports_archive" / "ladder_review_gate",
        source="flt3_archive",
    )
    manifest_path = result.get("run_manifest_path")
    if manifest_path:
        gate["run_manifest_path"] = str(Path(manifest_path).resolve())
        summary_path = Path(str(gate["summary_path"]))
        summary_path.write_text(
            json.dumps(
                {
                    key: value
                    for key, value in gate.items()
                    if key != "summary_path"
                },
                indent=2,
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
    return gate


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
    del folder_workers, refresh_each_folder, include_sl, cleanup_staging_root
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
        f"flt3_archive_{year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_root = destination / base_name
    if run_root.exists() and not resume_existing:
        run_root = destination / (
            f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / f"full_{year}_run_manifest.json"
    existing: dict = {}
    if resume_existing and manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    manifest = {
        **existing,
        "schema_version": "hemafrag_flt3_archive_v1",
        "created_at_utc": existing.get("created_at_utc") or _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "running",
        "analysis": "flt3",
        "year": year,
        "run_dir": str(run_root.resolve()),
        "input_root": str(source.resolve()),
        "settings": {
            "max_workers": int(max_workers),
            "use_rust": bool(use_rust),
            "skip_html_reports": bool(skip_html_reports),
        },
        "months": dict(existing.get("months") or {}),
    }
    _write_json(manifest_path, manifest)
    _emit(
        progress_callback,
        {"event": "run_started", "run_dir": str(run_root)},
    )

    settings_backup = copy.deepcopy(APP_SETTINGS)
    failures: list[str] = []
    try:
        APP_SETTINGS["active_analysis"] = "flt3"
        APP_SETTINGS.setdefault("engine", {})["use_rust"] = bool(use_rust)
        profile = APP_SETTINGS.setdefault("analyses", {}).setdefault(
            "flt3",
            {},
        )
        batch_settings = profile.setdefault("batch", {})
        pipeline_settings = profile.setdefault("pipeline", {})
        patient_regex = str(
            batch_settings.get("patient_id_regex") or r"\d{2}OUM\d{5}"
        )

        for month_key in month_keys:
            prior = manifest["months"].get(month_key) or {}
            if resume_existing and prior.get("status") == "done":
                _emit(
                    progress_callback,
                    {
                        "event": "month_resumed",
                        "month": month_key,
                        "run_dir": str(
                            run_root / "month_runs" / month_key
                        ),
                    },
                )
                continue
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
            _write_json(manifest_path, manifest)
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

            _emit(status_callback, f"Running FLT3 archive month {month_key}")
            try:
                jobs = generate_jobs(
                    folders,
                    aggregate_patients=bool(
                        batch_settings.get("aggregate_by_patient", True)
                    ),
                    patient_regex=patient_regex,
                )
                if not jobs:
                    month_state["status"] = "skipped_empty"
                    month_state["finished_at_utc"] = _utc_now()
                    continue
                result = run_batch_jobs(
                    jobs=jobs,
                    output_base=month_dir,
                    out_folder_tmpl="ASSAY_REPORTS",
                    outfile_html_tmpl="QC_REPORT_{name}.html",
                    excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
                    pipeline_scope=str(
                        pipeline_settings.get("mode", "all") or "all"
                    ),
                    assay_filter=str(
                        pipeline_settings.get("assay_filter_substring", "")
                        or ""
                    ),
                    aggregate_dit_reports=True,
                    continue_on_error=True,
                    max_workers=max(1, int(max_workers)),
                    tracking_excel_path=month_dir / "FLT3_Tracking.xlsx",
                    aggregate_outdir_name="reports_archive",
                    skip_html_reports=bool(skip_html_reports),
                )
                gate = _write_review_bundle(result, month_dir)
                failed_jobs = list(result.get("failed_jobs") or [])
                month_state.update(
                    {
                        "status": (
                            "completed_with_errors"
                            if failed_jobs
                            else "done"
                        ),
                        "failed_jobs": failed_jobs,
                        "review_case_count": int(
                            gate.get("review_case_count") or 0
                        ),
                        "batch_manifest_path": str(
                            result.get("run_manifest_path") or ""
                        ),
                    }
                )
                failures.extend(
                    f"{month_key}/{name}" for name in failed_jobs
                )
            except Exception as exc:
                month_state["status"] = "failed"
                month_state["error"] = f"{type(exc).__name__}: {exc}"
                failures.append(month_key)
            month_state["finished_at_utc"] = _utc_now()
            manifest["updated_at_utc"] = _utc_now()
            _write_json(manifest_path, manifest)
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
        APP_SETTINGS.clear()
        APP_SETTINGS.update(settings_backup)

    workbook_path: Path | None = None
    try:
        workbook_path = combine_run_root(
            run_root,
            run_root / f"track-flt3-{year}-overview.xlsx",
            year_label=year,
        )
    except FileNotFoundError:
        workbook_path = None
    manifest["status"] = "completed_with_errors" if failures else "completed"
    manifest["failed_items"] = failures
    manifest["combined_workbook_path"] = (
        str(workbook_path.resolve()) if workbook_path else ""
    )
    manifest["review_bundles"] = [
        str(path.parent.resolve())
        for path in sorted(run_root.rglob("ladder_review_cases.csv"))
    ]
    manifest["updated_at_utc"] = _utc_now()
    manifest["completed_at_utc"] = _utc_now()
    _write_json(manifest_path, manifest)
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
    _emit(status_callback, "FLT3 yearly archive run finished")
    return manifest


__all__ = [
    "discover_month_folders",
    "normalize_month_keys",
    "run_yearly_validation",
]
