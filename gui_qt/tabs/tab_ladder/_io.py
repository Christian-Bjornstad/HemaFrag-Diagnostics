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
import threading
from typing import Any

from core.ladder_adjustment_store import load_ladder_adjustment_record
from core.analyses.clonality.ladder_review_labels import (
    is_review_rerunnable,
    is_review_resolved,
)
from gui_qt.tabs.tab_ladder._summary import resolve_cache_key


_BUNDLE_WRITE_LOCK = threading.RLock()


def assert_review_bundle_open_allowed(bundle_dir: Path) -> None:
    """Keep a validation wave locked until its Rust candidate is frozen."""

    bundle = Path(bundle_dir).expanduser().resolve()
    summary_path = bundle / "ladder_review_summary.json"
    if not summary_path.is_file():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("Review bundle summary must be a JSON object")
    if str(summary.get("experiment_wave") or "").strip().casefold() != "validation":
        return

    experiment_raw = str(summary.get("experiment_root") or "").strip()
    if not experiment_raw:
        raise ValueError("Validation bundle is missing its experiment root")
    experiment = Path(experiment_raw).expanduser().resolve()
    if bundle.parent != experiment or experiment.name != "rust_fit_improvement":
        raise ValueError("Validation bundle does not match its experiment root")

    from core.research.ladder.fit_improvement import assert_validation_unlocked

    assert_validation_unlocked(experiment.parent)


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


def _write_bundle_csv_temporary(
    cases_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> Path:
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
        result = temporary_path
        temporary_path = None
        return result
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_bundle_csv_atomic(
    cases_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    temporary_path = _write_bundle_csv_temporary(cases_path, fieldnames, rows)
    try:
        os.replace(temporary_path, cases_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_json_temporary(path: Path, value: Any) -> Path:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=True)
        result = temporary_path
        temporary_path = None
        return result
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _publish_bundle_files_atomically(
    replacements: list[tuple[Path, Path]],
) -> None:
    backups: dict[Path, Path | None] = {}
    backed_up: set[Path] = set()
    published: list[Path] = []
    try:
        for _temporary, target in replacements:
            backup: Path | None = None
            if target.exists():
                with tempfile.NamedTemporaryFile(
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".backup",
                    delete=False,
                ) as handle:
                    backup = Path(handle.name)
                backups[target] = backup
                os.replace(target, backup)
                backed_up.add(target)
            else:
                backups[target] = None

        for temporary, target in replacements:
            os.replace(temporary, target)
            published.append(target)
    except Exception:
        for target in published:
            target.unlink(missing_ok=True)
        try:
            for _temporary, target in reversed(replacements):
                backup = backups.get(target)
                if (
                    target in backed_up
                    and backup is not None
                    and backup.exists()
                ):
                    os.replace(backup, target)
        except Exception as rollback_error:
            raise RuntimeError(
                "Review annotation publication and rollback both failed"
            ) from rollback_error
        raise
    else:
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)
    finally:
        for temporary, _target in replacements:
            temporary.unlink(missing_ok=True)
        for target, backup in backups.items():
            if target not in backed_up and backup is not None:
                backup.unlink(missing_ok=True)


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
    assert_review_bundle_open_allowed(bundle_dir)
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
    if not str(note or "").strip() or not str(reviewed_at_utc or "").strip():
        raise ValueError("Missing-ladder exclusion requires a note and review timestamp")
    annotation = build_review_annotation(
        label,
        note,
        reviewed_at_utc=reviewed_at_utc,
    )
    return save_review_bundle_annotation_worker(
        bundle_dir,
        full_path,
        annotation,
        _require_unresolved_without_adjustment=True,
    )


def save_review_bundle_annotation_worker(
    bundle_dir: Path,
    full_path: Path,
    annotation: dict,
    *,
    _require_unresolved_without_adjustment: bool = False,
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

    with _BUNDLE_WRITE_LOCK:
        fieldnames, rows = _read_bundle_csv(cases_path)

        for field in ("label", "label_note", "reviewed_at_utc", "adjustment_path"):
            if field not in fieldnames:
                fieldnames.append(field)

        updated = False
        matched_path_text = ""
        full_path_text = str(full_path)
        full_path_key = resolve_cache_key(full_path)
        for row in rows:
            row_path_text = str(row.get("full_path", "") or "")
            row_matches = row_path_text == full_path_text
            if not row_matches and row_path_text:
                row_matches = resolve_cache_key(Path(row_path_text)) == full_path_key
            if not row_matches:
                continue
            if _require_unresolved_without_adjustment:
                if str(row.get("label") or "").strip() or str(
                    row.get("adjustment_path") or ""
                ).strip():
                    raise ValueError(
                        "Missing-ladder exclusion requires an unresolved row "
                        "without an adjustment"
                    )
                source_path = Path(row_path_text).expanduser()
                if source_path.with_suffix(".ladder_adj.json").exists() or (
                    load_ladder_adjustment_record(
                        source_path,
                        database_path=bundle_dir / "ladder_adjustments.sqlite3",
                    )
                    is not None
                ):
                    raise ValueError(
                        "Missing-ladder exclusion cannot replace an existing adjustment"
                    )
            row["label"] = annotation.get("label", "")
            row["label_note"] = annotation.get("label_note", "")
            row["reviewed_at_utc"] = annotation.get("reviewed_at_utc", "")
            row["adjustment_path"] = annotation.get("adjustment_path", "")
            matched_path_text = row_path_text
            updated = True
            break

        if not updated:
            raise FileNotFoundError(
                f"Could not find review bundle row for {full_path_text}"
            )

        annotations_path = bundle_dir / "ladder_review_annotations.json"
        existing: dict[str, dict] = {}
        if annotations_path.exists():
            loaded = json.loads(annotations_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Review annotations must contain a JSON object")
            existing = loaded
        existing[matched_path_text] = annotation
        csv_temporary = _write_bundle_csv_temporary(cases_path, fieldnames, rows)
        try:
            json_temporary = _write_json_temporary(annotations_path, existing)
        except Exception:
            csv_temporary.unlink(missing_ok=True)
            raise
        _publish_bundle_files_atomically(
            [
                (csv_temporary, cases_path),
                (json_temporary, annotations_path),
            ]
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
