from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.inventory import (
    build_inventory,
    discover_raw_runs,
    load_canonical_review_cases,
    resolve_archived_path,
)


REVIEW_COLUMNS = (
    "full_path",
    "file",
    "source_run_dir",
    "assay",
    "ladder",
    "ladder_qc_status",
    "ladder_review_required",
    "primary_reason",
    "reason_codes",
)


def fake_roots(tmp_path: Path) -> ResearchRoots:
    data = tmp_path / "DATA"
    raw_roots = (
        data / "2024_DATA",
        data / "2025_data",
        data / "2026_data",
    )
    for root in raw_roots:
        root.mkdir(parents=True)
    return ResearchRoots(
        raw_roots=raw_roots,
        archive_root=tmp_path / "archive",
        output_root=tmp_path / "research",
        excluded_backup_root=data / "backup",
    )


def write_review_bundle(bundle: Path, rows: list[dict[str, object]]) -> Path:
    gate = bundle / "ladder_review_gate"
    gate.mkdir(parents=True)
    path = gate / "ladder_review_cases.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def review_row(full_path: str, *, source_run_dir: str = "run-a") -> dict[str, object]:
    return {
        "full_path": full_path,
        "file": Path(full_path).name,
        "source_run_dir": source_run_dir,
        "assay": "TCRgA",
        "ladder": "LIZ",
        "ladder_qc_status": "review_required",
        "ladder_review_required": "true",
        "primary_reason": "rejected",
        "reason_codes": "rust_ladder_fit_rejected",
    }


def write_tracking_workbook(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Runs", index=False)


def test_resolve_archived_f_drive_to_allowed_d_root(tmp_path):
    roots = fake_roots(tmp_path)
    target = roots.raw_roots[0] / "run-a" / "sample.fsa"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fsa")

    resolved = resolve_archived_path(
        r"F:\DATA\2024_DATA\run-a\sample.fsa", roots
    )

    assert resolved == target.resolve()


def test_resolve_archived_path_rejects_backup_even_if_file_exists(tmp_path):
    roots = fake_roots(tmp_path)
    backup = roots.excluded_backup_root / "sample.fsa"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"do-not-read")

    with pytest.raises(ValueError, match="backup"):
        resolve_archived_path(r"F:\DATA\backup\sample.fsa", roots)


def test_only_reports_backfill_bundle_is_canonical(tmp_path):
    roots = fake_roots(tmp_path)
    target = roots.raw_roots[0] / "run-a" / "sample.fsa"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fsa")
    archived = r"F:\DATA\2024_DATA\run-a\sample.fsa"
    write_review_bundle(
        roots.archive_root / "run" / "reports_backfill", [review_row(archived)]
    )
    write_review_bundle(
        roots.archive_root / "run" / "ASSAY_REPORTS", [review_row(archived)]
    )

    rows = load_canonical_review_cases(roots.archive_root, roots)

    assert len(rows) == 1
    assert rows.iloc[0]["resolved_full_path"] == str(target.resolve())
    assert "reports_backfill" in rows.iloc[0]["review_bundle_path"]


def test_canonical_annotations_overlay_manual_review_fields(tmp_path):
    roots = fake_roots(tmp_path)
    target = roots.raw_roots[0] / "run-a" / "sample.fsa"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fsa")
    archived = r"F:\DATA\2024_DATA\run-a\sample.fsa"
    cases = write_review_bundle(
        roots.archive_root / "run" / "reports_backfill", [review_row(archived)]
    )
    (cases.parent / "ladder_review_annotations.json").write_text(
        json.dumps(
            {
                archived: {
                    "label": "manual_adjusted",
                    "adjustment_path": r"F:\DATA\2024_DATA\run-a\sample.ladder_adj.json",
                    "reviewed_at_utc": "2026-08-10T00:00:00Z",
                }
            }
        ),
        encoding="utf-8",
    )

    rows = load_canonical_review_cases(roots.archive_root, roots)

    assert rows.iloc[0]["label"] == "manual_adjusted"
    assert rows.iloc[0]["reviewed_at_utc"] == "2026-08-10T00:00:00Z"


def test_annotation_only_record_is_not_dropped_when_cases_csv_is_empty(tmp_path):
    roots = fake_roots(tmp_path)
    target = roots.raw_roots[0] / "run-a" / "sample.fsa"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fsa")
    archived = r"F:\DATA\2024_DATA\run-a\sample.fsa"
    cases = write_review_bundle(
        roots.archive_root / "run" / "reports_backfill", []
    )
    (cases.parent / "ladder_review_annotations.json").write_text(
        json.dumps({archived: {"label": "manual_adjusted"}}),
        encoding="utf-8",
    )

    rows = load_canonical_review_cases(roots.archive_root, roots)

    assert len(rows) == 1
    assert rows.iloc[0]["full_path"] == archived
    assert rows.iloc[0]["file"] == "sample.fsa"
    assert rows.iloc[0]["source_run_dir"] == "run-a"
    assert rows.iloc[0]["label"] == "manual_adjusted"


def test_discover_raw_runs_uses_top_level_physical_run_and_hashes_content(tmp_path):
    roots = fake_roots(tmp_path)
    target = roots.raw_roots[1] / "physical-run" / "nested-logical-run" / "sample.FSA"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"same-content")

    rows = discover_raw_runs(roots)

    assert len(rows) == 1
    assert rows.iloc[0]["physical_run_key"] == "2025_data/physical-run"
    assert rows.iloc[0]["logical_run_dir"] == "nested-logical-run"
    assert rows.iloc[0]["content_sha256"] == hashlib.sha256(b"same-content").hexdigest()


def test_build_inventory_keeps_unmatched_and_nested_records_explicit(tmp_path):
    roots = fake_roots(tmp_path)
    nested = roots.raw_roots[1] / "physical-run" / "nested-logical-run"
    nested.mkdir(parents=True)
    matched = nested / "matched.fsa"
    raw_only = nested / "raw-only.fsa"
    duplicate = roots.raw_roots[1] / "other-run" / "duplicate.fsa"
    duplicate.parent.mkdir()
    matched.write_bytes(b"matched")
    raw_only.write_bytes(b"duplicate-content")
    duplicate.write_bytes(b"duplicate-content")

    write_tracking_workbook(
        roots.archive_root / "2025" / "track-clonality-2025-overview.xlsx",
        [
            {
                "IdentityKey": "PT-opaque-patient-identity",
                "File": "matched.fsa",
                "SourceRunDir": "nested-logical-run",
                "Assay": "TCRgA",
                "Ladder": "LIZ",
                "SampleKind": "patient",
            },
            {
                "IdentityKey": "missing-run::tracking-only.fsa",
                "File": "tracking-only.fsa",
                "SourceRunDir": "missing-run",
                "Assay": "TCRgA",
                "Ladder": "LIZ",
            },
        ],
    )
    archived_only = r"F:\DATA\2025_data\gone-run\archive-only.fsa"
    write_review_bundle(
        roots.archive_root / "2025" / "run" / "reports_backfill",
        [review_row(archived_only, source_run_dir="gone-run")],
    )

    result = build_inventory(roots)
    issues = set(result.reconciliation["issue_code"])

    assert len(result.files) == 3
    assert "raw_only" in issues
    assert "tracking_only" in issues
    assert "archive_only" in issues
    assert "nested_logical_run" in issues
    assert "duplicate_content" in issues
    assert result.summary["raw_file_count"] == 3
    assert result.summary["tracking_entry_count"] == 2
    assert result.summary["canonical_review_case_count"] == 1
    matched_row = result.files[result.files["file"].eq("matched.fsa")].iloc[0]
    assert matched_row["tracking_identity_key"] == "PT-opaque-patient-identity"
    assert matched_row["sample_kind"] == "patient"
