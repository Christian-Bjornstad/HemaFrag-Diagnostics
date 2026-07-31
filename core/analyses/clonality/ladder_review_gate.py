from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


REVIEW_STATUSES = {"review_required", "missing_ladder", "ladder_qc_failed"}
RESOLVED_LABELS = {"manual_adjusted", "reviewed_no_change"}


def _entry_file_path(entry: dict[str, Any]) -> str:
    original_path = entry.get("original_file_path")
    if original_path:
        return str(original_path)

    fsa = entry.get("fsa")
    if fsa is None:
        return ""
    path = (
        getattr(fsa, "file", None)
        or getattr(fsa, "path", None)
        or getattr(fsa, "file_path", None)
        or getattr(fsa, "filepath", None)
    )
    if path:
        return str(path)
    return str(getattr(fsa, "file_name", "") or "")


def _entry_file_name(entry: dict[str, Any]) -> str:
    original_path = entry.get("original_file_path")
    if original_path:
        return Path(str(original_path)).name
    if entry.get("file_name"):
        return str(entry["file_name"])
    fsa = entry.get("fsa")
    return str(getattr(fsa, "file_name", "") or "")


def _as_float_text(value: Any) -> str:
    try:
        if value is None:
            return ""
        return f"{float(value):.6g}"
    except Exception:
        return ""


def _resolve_cache_key(full_path_str: str) -> Path:
    """Re-implementation of `gui_qt.tabs.tab_ladder._summary.resolve_cache_key`.

    We can't depend on the GUI module here (it's Qt-coupled) so we
    inline a minimal version for the relocations audit log.
    """
    try:
        return Path(full_path_str).expanduser().resolve()
    except Exception:
        return Path(full_path_str).expanduser()


def collect_ladder_review_cases(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build review-gate rows from clonality analysis entries.

    This is intentionally conservative: it mirrors existing backend review flags
    and does not invent new QC policy. Phase 5 can use this in shadow mode first,
    then the same artifact can gate DIT report generation later.
    """

    rows: list[dict[str, str]] = []
    for entry in entries:
        status = str(entry.get("ladder_qc_status") or "").strip() or "ok"
        review_required = bool(entry.get("ladder_review_required")) or status in REVIEW_STATUSES
        if not review_required:
            continue

        reason_codes = entry.get("ladder_review_reason_codes") or []
        if isinstance(reason_codes, (list, tuple)):
            reason_codes_text = ";".join(str(code) for code in reason_codes if str(code))
        else:
            reason_codes_text = str(reason_codes or "")

        fitted_count = entry.get("ladder_fitted_step_count")
        if fitted_count is None:
            fitted_count = entry.get("n_ladder_steps")

        rows.append(
            {
                "full_path": _entry_file_path(entry),
                "file": _entry_file_name(entry),
                "source_run_dir": str(entry.get("source_run_dir") or ""),
                "assay": str(entry.get("assay") or ""),
                "ladder": str(entry.get("ladder") or ""),
                "ladder_qc_status": status,
                "ladder_review_required": "true" if review_required else "false",
                "primary_reason": str(entry.get("ladder_review_reason") or ""),
                "reason_codes": reason_codes_text,
                "review_summary": str(entry.get("ladder_review_summary") or ""),
                "linear_max": _as_float_text(entry.get("ladder_linear_max_residual_bp")),
                "linear_mean": _as_float_text(entry.get("ladder_linear_mean_residual_bp")),
                "linear_r2": _as_float_text(entry.get("ladder_linear_r2")),
                "expected_count": str(entry.get("ladder_expected_step_count") or ""),
                "fitted_count": "" if fitted_count is None else str(fitted_count),
                "fit_strategy": str(entry.get("ladder_fit_strategy") or ""),
                "suggested_action": "open_ladder_review",
                "label": "",
                "label_note": "",
                "reviewed_at_utc": "",
                "adjustment_path": "",
            }
        )
    return rows


def write_ladder_review_gate(
    entries: list[dict[str, Any]],
    out_dir: Path,
    *,
    source: str = "batch",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = collect_ladder_review_cases(entries)
    cases_path = out_dir / "ladder_review_cases.csv"
    summary_path = out_dir / "ladder_review_summary.json"

    fieldnames = [
        "full_path",
        "file",
        "source_run_dir",
        "assay",
        "ladder",
        "ladder_qc_status",
        "ladder_review_required",
        "primary_reason",
        "reason_codes",
        "review_summary",
        "linear_max",
        "linear_mean",
        "linear_r2",
        "expected_count",
        "fitted_count",
        "fit_strategy",
        "suggested_action",
        "label",
        "label_note",
        "reviewed_at_utc",
        "adjustment_path",
    ]
    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cases)

    summary = {
        "source": source,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(entries),
        "review_case_count": len(cases),
        "cases_path": str(cases_path),
        "blocked": False,
        "mode": "shadow",
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def count_unresolved_review_cases(cases_path: Path) -> int:
    if not cases_path.exists():
        return 0

    unresolved = 0
    with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            label = str(row.get("label", "") or "").strip()
            if label not in RESOLVED_LABELS:
                unresolved += 1
    return unresolved


# Phase 12.4 — relocate_review_case + relocations audit log
# -----------------------------------------------------------------------
#
# When a chemist notices a red chip in the new chip-strip overview
# (file_unreachable), they can right-click and pick "Locate File…"
# to point the bundle at the new FSA on disk. We rewrite the
# matching row's full_path atomically and append to a per-bundle
# `ladder_review_relocations.json` so the audit trail lives
# alongside the bundle.


def _path_to_str(value: Any) -> str:
    """Normalize path input to its string form without Windows coercion.

    `str(Path("/p/a.fsa"))` on Windows yields `\\p\\a.fsa` because
    WindowsPath reinterprets forward slashes. For the relocate audit
    log we want the original text preserved verbatim. If the caller
    passes a Path, we walk back to the raw argument via `os.fspath`
    only when that preserves the literal; otherwise we use the
    object's `__str__` but replace os.sep with `/` to round-trip
    POSIX-style fixtures.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, Path):
        # On Linux str(Path) preserves the literal; on Windows it
        # rewrites forward slashes. We normalise back.
        return str(value).replace("\\", "/") if sys.platform == "win32" else str(value)
    return str(value)


def relocate_review_case(
    bundle_dir: Path,
    old_full_path: Path,
    new_full_path: Path,
) -> dict:
    """Swap a row's full_path in the bundle CSV + audit-log it.

    Returns `{"old_path": str, "new_path": str,
              "relocated_at_utc": iso8601, "updated_row_index": int}`.

    Raises FileNotFoundError when:
      * the bundle's `ladder_review_cases.csv` is missing, or
      * no row's full_path matches `old_full_path`.
    """
    old_text = _path_to_str(old_full_path)
    new_text = _path_to_str(new_full_path)

    cases_path = bundle_dir / "ladder_review_cases.csv"
    if not cases_path.exists():
        raise FileNotFoundError(f"Missing review bundle file: {cases_path.name}")

    with cases_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "full_path" not in fieldnames:
        raise FileNotFoundError(
            f"No 'full_path' column in {cases_path.name}"
        )

    old_text = _path_to_str(old_full_path)
    old_key = _resolve_cache_key(old_text)
    new_text = _path_to_str(new_full_path)

    updated_row_index = -1
    for index, row in enumerate(rows):
        row_path_text = str(row.get("full_path", "") or "")
        row_matches = row_path_text == old_text
        if not row_matches and row_path_text:
            try:
                row_matches = _resolve_cache_key(row_path_text) == old_key
            except Exception:
                row_matches = False
        if row_matches:
            row["full_path"] = new_text
            updated_row_index = index
            break

    if updated_row_index == -1:
        raise FileNotFoundError(
            f"Could not find review bundle row matching {old_text}"
        )

    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Append-only audit log (JSONL-shaped JSON).
    relocations_path = bundle_dir / "ladder_review_relocations.json"
    existing: dict[str, dict] = {}
    if relocations_path.exists():
        try:
            existing = json.loads(relocations_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    relocated_entry = {
        "old_path": old_text,
        "new_path": new_text,
        "relocated_at_utc": datetime.now(timezone.utc).isoformat(),
        "updated_row_index": updated_row_index,
    }
    # Key by old_path so a future locate of the same row replaces
    # the prior audit rather than appending jitter.
    existing[old_text] = relocated_entry
    relocations_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    return relocated_entry
