"""HemaFrag GUI Qt — bundle/CSV IO helpers for `tab_ladder`.

Phase 12.1 — extracted from the previously-monolithic
`gui_qt/tabs/tab_ladder/_legacy.py` so they can be unit-tested
without spinning up a `QApplication` or constructing a `TabLadder`.

Bundle-level file IO only. The widget-side cache lifecycle methods
(`_set_review_runtime_cache`, etc.) stay on the class because
they hold instance state.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from core.analyses.clonality.ladder_review_labels import (
    is_review_rerunnable,
    is_review_resolved,
)
from gui_qt.tabs.tab_ladder._summary import resolve_cache_key


def _read_bundle_csv(cases_path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Read a ladder-review bundle CSV preserving field order.

    Returns the fieldnames (so the writer can reuse them verbatim)
    and the parsed rows. Errors fall through to the Worker error
    signal in the GUI.
    """
    with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_bundle_csv_atomic(
    cases_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=cases_path.parent,
            prefix=f".{cases_path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            newline="",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, cases_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_review_bundle_worker(bundle_dir: Path) -> dict:
    """Read a ladder-review bundle folder into a tagged case-list.

    Phase 12.0 contract: keep every row whose `full_path` is
    non-empty, even when the FSA is not currently on disk. Unreachable
    rows are tagged `_path_unreachable=true` and collected into
    `missing_paths` so the GUI can surface them.

    Raises FileNotFoundError when `ladder_review_cases.csv` is
    missing — caller surfaces that to the chemist via the red status
    bar.
    """
    cases_path = bundle_dir / "ladder_review_cases.csv"
    if not cases_path.exists():
        raise FileNotFoundError(f"Missing review bundle file: {cases_path.name}")

    rows: list[dict] = []
    missing_paths: list[str] = []
    with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_path = str(row.get("full_path", "") or "").strip()
            if not raw_path:
                continue
            full_path = Path(raw_path).expanduser()
            if not full_path.exists():
                missing_paths.append(raw_path)
                row["_path_unreachable"] = "true"
            else:
                row["_path_unreachable"] = "false"
            row["full_path"] = raw_path
            rows.append(row)

    run_manifest_path: Path | None = None
    summary_path = bundle_dir / "ladder_review_summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            raw_manifest_path = str(summary.get("run_manifest_path") or "").strip()
            if raw_manifest_path:
                candidate = Path(raw_manifest_path).expanduser()
                if candidate.is_file():
                    run_manifest_path = candidate
        except Exception:
            run_manifest_path = None

    return {
        "bundle_dir": bundle_dir,
        "cases_path": cases_path,
        "rows": rows,
        "missing_paths": missing_paths,
        "run_manifest_path": run_manifest_path,
    }


def review_case_paths_from_bundle(bundle_dir: Path) -> set[Path]:
    """Cache-key set of every row's `full_path` in the bundle CSV.

    Used by callers that want to know which file paths a bundle
    references (regardless of whether they currently exist on disk).
    """
    cases_path = bundle_dir / "ladder_review_cases.csv"
    if not cases_path.exists():
        return set()

    paths: set[Path] = set()
    try:
        with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw_path = str(row.get("full_path", "") or "").strip()
                if raw_path:
                    paths.add(resolve_cache_key(Path(raw_path)))
    except Exception:
        return set()
    return paths


def build_review_annotation(
    label: str,
    note: str,
    *,
    reviewed_at_utc: str,
    adjustment_path: str = "",
) -> dict:
    """Build the persisted review fields for one bundle case."""
    return {
        "label": label,
        "label_note": note,
        "reviewed_at_utc": reviewed_at_utc,
        "adjustment_path": adjustment_path,
    }


def save_missing_ladder_exclusion_worker(
    bundle_dir: Path,
    full_path: Path,
    *,
    note: str,
    reviewed_at_utc: str,
) -> dict:
    """Persist a resolved no-ladder exclusion without an adjustment record."""
    label = "excluded_missing_ladder_signal"
    if not is_review_resolved(label) or is_review_rerunnable(label):
        raise RuntimeError("Missing-ladder exclusion label policy is invalid")
    annotation = build_review_annotation(
        label,
        note,
        reviewed_at_utc=reviewed_at_utc,
    )
    return save_review_bundle_annotation_worker(bundle_dir, full_path, annotation)


def save_review_bundle_annotation_worker(
    bundle_dir: Path, full_path: Path, annotation: dict
) -> dict:
    """Update the matching row in ladder_review_cases.csv + append.

    The CSV write is atomic at the row level: read the whole CSV,
    find the row matching full_path (text match or cache-key match),
    rewrite the four review columns in place, then re-emit the CSV
    with the original header order intact. The annotations JSON
    accumulates per-row keyed by FSA path text.

    Raises FileNotFoundError on mis-configured callers (no matching
    row, missing CSV) so the GUI's Worker error signal can surface
    fail-loud to the chemist.
    """
    cases_path = bundle_dir / "ladder_review_cases.csv"
    if not cases_path.exists():
        raise FileNotFoundError(f"Missing review bundle file: {cases_path.name}")

    fieldnames, rows = _read_bundle_csv(cases_path)

    for field in ("label", "label_note", "reviewed_at_utc", "adjustment_path"):
        if field not in fieldnames:
            fieldnames.append(field)

    updated = False
    full_path_text = str(full_path)
    full_path_key = resolve_cache_key(full_path)
    for row in rows:
        row_path_text = str(row.get("full_path", "") or "")
        row_matches = row_path_text == full_path_text
        if not row_matches and row_path_text:
            row_matches = resolve_cache_key(Path(row_path_text)) == full_path_key
        if not row_matches:
            continue
        row["label"] = annotation.get("label", "")
        row["label_note"] = annotation.get("label_note", "")
        row["reviewed_at_utc"] = annotation.get("reviewed_at_utc", "")
        row["adjustment_path"] = annotation.get("adjustment_path", "")
        updated = True
        break

    if not updated:
        raise FileNotFoundError(
            f"Could not find review bundle row for {full_path_text}"
        )

    _write_bundle_csv_atomic(cases_path, fieldnames, rows)

    annotations_path = bundle_dir / "ladder_review_annotations.json"
    existing: dict[str, dict] = {}
    if annotations_path.exists():
        try:
            existing = json.loads(annotations_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing[full_path_text] = annotation
    annotations_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return annotation


def save_review_bundle_rerun_status_worker(
    bundle_dir: Path,
    consumption_by_file: dict[str, dict[str, Any]],
    *,
    run_manifest_path: Path | None,
    rerun_at_utc: str,
) -> int:
    """Persist per-file correction-consumption evidence in a review bundle."""
    cases_path = bundle_dir / "ladder_review_cases.csv"
    if not cases_path.exists():
        raise FileNotFoundError(f"Missing review bundle file: {cases_path.name}")

    fieldnames, rows = _read_bundle_csv(cases_path)
    rerun_fields = (
        "rerun_status",
        "rerun_at_utc",
        "rerun_manifest_path",
        "consumed_adjustment_sha256",
    )
    for field in rerun_fields:
        if field not in fieldnames:
            fieldnames.append(field)

    statuses_by_key = {
        resolve_cache_key(Path(raw_path)): status
        for raw_path, status in consumption_by_file.items()
    }
    updated = 0
    for row in rows:
        raw_path = str(row.get("full_path") or "").strip()
        if not raw_path:
            continue
        status = statuses_by_key.get(resolve_cache_key(Path(raw_path)))
        if status is None:
            continue
        row["rerun_status"] = str(status.get("status") or "not_consumed")
        row["rerun_at_utc"] = rerun_at_utc
        row["rerun_manifest_path"] = (
            str(run_manifest_path.resolve()) if run_manifest_path else ""
        )
        row["consumed_adjustment_sha256"] = str(
            status.get("manual_adjustment_sha256") or ""
        )
        updated += 1

    _write_bundle_csv_atomic(cases_path, fieldnames, rows)
    return updated
