from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.diagnostics import normalize_rust_result
from scripts.build_ladder_research_corpus import (
    finalize_stage,
    inventory_stage,
    diagnose_stage,
)


EXPECTED_ARTIFACTS = {
    "inventory.csv",
    "reconciliation.json",
    "manual_corrections.csv",
    "manual_reconciliation.json",
    "review_cases.csv",
    "diagnostics.ndjson",
    "failure_summary.csv",
    "review_queue.csv",
    "gold_records.json",
    "development_manifest.json",
    "locked_validation_manifest.json",
    "release_manifest.json",
    "run_manifest.json",
}


@pytest.mark.parametrize(
    "script_name",
    ("build_ladder_research_corpus.py", "benchmark_rust_ladder.py"),
)
def test_direct_script_startup_can_import_project_modules(tmp_path, script_name):
    script = Path(__file__).resolve().parents[1] / "scripts" / script_name

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def fixture_roots(tmp_path: Path) -> ResearchRoots:
    data = tmp_path / "DATA"
    raw_roots = tuple(data / name for name in ("2024_DATA", "2025_data", "2026_data"))
    for root in raw_roots:
        root.mkdir(parents=True)
    return ResearchRoots(
        raw_roots=raw_roots,
        archive_root=tmp_path / "archive",
        output_root=tmp_path / "research",
        excluded_backup_root=data / "backup",
    )


def test_end_to_end_builder_excludes_backup_and_writes_all_artifacts(tmp_path):
    roots = fixture_roots(tmp_path)
    run = roots.raw_roots[0] / "run-a"
    run.mkdir()
    source = run / "sample.fsa"
    source.write_bytes(b"allowed-fsa")
    source.with_suffix(".ladder_adj.json").write_text(
        json.dumps(
            {
                "mapping": {str(index): index for index in range(16)},
                "mapping_times": {str(index): 100 + index * 10 for index in range(16)},
                "manual_candidates": [100 + index * 10 for index in range(16)],
            }
        ),
        encoding="utf-8",
    )
    backup = roots.excluded_backup_root / "forbidden.fsa"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"forbidden-sentinel")

    workbook = roots.archive_root / "2024" / "track-clonality-2024-overview.xlsx"
    workbook.parent.mkdir(parents=True)
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "IdentityKey": "run-a::sample.fsa",
                    "File": "sample.fsa",
                    "SourceRunDir": "run-a",
                    "Assay": "TCRgA",
                    "Ladder": "LIZ",
                    "LadderExpectedStepCount": 16,
                    "ManualAdjustmentUsed": True,
                }
            ]
        ).to_excel(writer, sheet_name="Runs", index=False)

    gate = (
        roots.archive_root
        / "2024"
        / "run-a"
        / "reports_backfill"
        / "ladder_review_gate"
    )
    gate.mkdir(parents=True)
    with (gate / "ladder_review_cases.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "full_path",
                "file",
                "source_run_dir",
                "assay",
                "ladder",
                "ladder_qc_status",
                "ladder_review_required",
                "primary_reason",
                "reason_codes",
                "label",
                "adjustment_path",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "full_path": r"F:\DATA\2024_DATA\run-a\sample.fsa",
                "file": "sample.fsa",
                "source_run_dir": "run-a",
                "assay": "TCRgA",
                "ladder": "LIZ",
                "ladder_qc_status": "review_required",
                "ladder_review_required": "true",
                "primary_reason": "rejected",
                "reason_codes": "rust_ladder_fit_rejected",
                "label": "manual_adjusted",
                "adjustment_path": r"F:\DATA\2024_DATA\run-a\sample.ladder_adj.json",
            }
        )

    workspace = roots.output_root / "fixture-run"
    inventory_stage(roots, workspace)

    def fake_diagnostic(_cli, input_file, **kwargs):
        return normalize_rust_result(
            {
                "ladder": "LIZ500_250",
                "ladder_peak_count": 20,
                "ladder_fit_preview": {},
                "ladder_review_assessment": {
                    "suggested_review": True,
                    "reason_codes": ["candidate_space_capped"],
                },
            },
            source_path=input_file,
            configured_ladder=kwargs["configured_ladder"],
            reviewed_label=kwargs.get("reviewed_label", ""),
        )

    fake_cli = tmp_path / "fraggler-cli.exe"
    fake_cli.write_bytes(b"fake")
    diagnose_stage(
        workspace,
        cli=fake_cli,
        roots=roots,
        max_workers=1,
        timeout_seconds=3,
        resume=True,
        diagnostic_runner=fake_diagnostic,
    )
    finalize_stage(workspace, seed=20260810)

    assert EXPECTED_ARTIFACTS <= {path.name for path in workspace.iterdir()}
    assert len(pd.read_csv(workspace / "inventory.csv")) == 1
    gold = json.loads((workspace / "gold_records.json").read_text(encoding="utf-8"))
    assert gold["record_count"] == 1
    assert gold["records"][0]["truth_source"] == "manual_legacy"
    for artifact in workspace.iterdir():
        if artifact.suffix.casefold() not in {".csv", ".json", ".ndjson"}:
            continue
        assert "forbidden-sentinel" not in artifact.read_text(
            encoding="utf-8", errors="ignore"
        )
