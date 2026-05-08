from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
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
                "fitted_count": str(entry.get("ladder_fitted_step_count") or entry.get("n_ladder_steps") or ""),
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
