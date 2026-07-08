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
from pathlib import Path
from typing import Any

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

    return {
        "bundle_dir": bundle_dir,
        "cases_path": cases_path,
        "rows": rows,
        "missing_paths": missing_paths,
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

    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

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


# Phase 12.8 — bulk save helper (Mark Visible Reviewed button).
# -----------------------------------------------------------------------
#
# `bulk_save_review_bundle_annotations` is the multi-row counterpart of
# `save_review_bundle_annotation_worker`. It reads the bundle CSV, applies
# a list of new row annotations, and re-emits the CSV once with all
# changes atomically.
#
# It also accumulates the latest annotation per row into
# `ladder_review_annotations.json` so a future read can reconstruct
# the chemist's last bulk save.
#
# Returns the count of rows whose label *actually changed*. Rows
# that were already in the new state are NOT counted — the chemist
# wants the bulk-button's status string to read "12 cases reviewed"
# rather than "37 cases touched." This is the pitfall-averting bullet
# from the Plan 12 recipe.

def bulk_save_review_bundle_annotations(
    bundle_dir: Path, new_rows: list[dict]
) -> int:
    """Apply a list of row annotations to the bundle CSV atomically.

    Each row in ``new_rows`` must carry at least ``full_path`` plus
    any of ``label``, ``label_note``, ``reviewed_at_utc``,
    ``adjustment_path``. The row is matched against the bundle CSV
    by ``full_path`` text equality.

    Returns the number of rows whose stored label *changed* as a
    result of this call (zero-count rows still get their
    ``reviewed_at_utc`` updated though, because the chemist's
    intent with "no change" is still a fresh save event).

    Raises FileNotFoundError when the bundle CSV is missing so the
    GUI's worker error signal can surface the miss.
    """
    if not new_rows:
        return 0
    cases_path = bundle_dir / "ladder_review_cases.csv"
    if not cases_path.exists():
        raise FileNotFoundError(f"Missing review bundle file: {cases_path.name}")

    fieldnames, rows = _read_bundle_csv(cases_path)

    for field in ("label", "label_note", "reviewed_at_utc", "adjustment_path", "_path_unreachable"):
        if field not in fieldnames and any(field in r for r in rows):
            fieldnames.append(field)
        if field not in fieldnames:
            fieldnames.append(field)

    # Build a {full_path_text: row} index for fast lookup. We keep
    # text equality on the path string because the bundle CSV writes
    # POSIX-style paths verbatim; if a future caller needs cache-key
    # resolution, that's a separate function.
    rows_by_path: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row.get("full_path", "") or "")
        if key:
            rows_by_path.setdefault(key, []).append(row)

    annotations_path = bundle_dir / "ladder_review_annotations.json"
    existing: dict[str, dict] = {}
    if annotations_path.exists():
        try:
            existing = json.loads(annotations_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    changed_count = 0

    for new_row in new_rows:
        # Phase 12.8 pitfall: only rows with a truthy new label
        # count toward the "actually changed" tally. Empty label
        # (chemist cleared the field by accident) must NOT inflate
        # the count. Tests pin this contract.
        new_label = (new_row.get("label") or "").strip()
        full_path_text = str(new_row.get("full_path", "") or "")
        if not full_path_text:
            continue
        target = rows_by_path.get(full_path_text)
        if not target:
            # Path not found in bundle — skip with no error.
            # The bulk button only marks "visible" rows which
            # were already filtered into the bundle.
            continue

        for stored_row in target:
            previous_label = (stored_row.get("label") or "").strip().lower()
            if new_label:
                if new_label.lower() != previous_label:
                    changed_count += 1
            for f in ("label", "label_note", "reviewed_at_utc", "adjustment_path"):
                if f in new_row:
                    stored_row[f] = new_row[f]

        annotations = dict(new_row)
        annotations.pop("full_path", None)
        existing[full_path_text] = annotations

    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    annotations_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=True), encoding="utf-8"
    )

    return changed_count
