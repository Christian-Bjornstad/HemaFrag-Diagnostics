from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.diagnostics import normalize_rust_result
from scripts import build_ladder_research_corpus as corpus_module
from scripts.build_ladder_research_corpus import (
    _assert_workspace,
    _inventory_command,
    _load_manual_correction_approvals,
    finalize_stage,
    inventory_stage,
    diagnose_stage,
    refresh_inventory_stage,
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


def diagnostic_workspace(
    tmp_path: Path,
) -> tuple[ResearchRoots, Path, Path, Path]:
    roots = fixture_roots(tmp_path)
    source = roots.raw_roots[0] / "run-a" / "sample.fsa"
    source.parent.mkdir()
    source.write_bytes(b"source-v1")
    workspace = roots.output_root / "fixture-run"
    workspace.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "raw_path": str(source.resolve()),
                "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "physical_run_key": "2024_DATA/run-a",
                "sample_kind": "patient",
            }
        ]
    ).to_csv(workspace / "inventory.csv", index=False)
    pd.DataFrame(
        [
            {
                "record_kind": "review_case",
                "resolved_full_path": str(source.resolve()),
                "source_run_dir": "run-a",
                "assay": "TCRgA",
                "ladder": "LIZ",
                "label": "",
                "primary_reason": "rejected",
                "reason_codes": "candidate_space_capped",
            }
        ]
    ).to_csv(workspace / "review_cases.csv", index=False)
    (workspace / "run_manifest.json").write_text(
        json.dumps(
            {
                "roots": {
                    "raw_roots": [str(path) for path in roots.raw_roots],
                    "archive_root": str(roots.archive_root),
                    "output_root": str(roots.output_root),
                    "excluded_backup_root": str(roots.excluded_backup_root),
                }
            }
        ),
        encoding="utf-8",
    )
    cli = tmp_path / "fraggler-cli.exe"
    cli.write_bytes(b"cli-v1")
    return roots, workspace, source, cli


def successful_diagnostic(input_file: Path, kwargs: dict[str, object]):
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
        configured_ladder=str(kwargs["configured_ladder"]),
        reviewed_label=str(kwargs.get("reviewed_label") or ""),
    )


def test_inventory_cli_rejects_caller_defined_roots_before_scanning(
    tmp_path, monkeypatch
):
    called = False

    def unexpected_inventory(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "scripts.build_ladder_research_corpus.inventory_stage",
        unexpected_inventory,
    )
    data = tmp_path / "DATA"
    args = SimpleNamespace(
        raw_root=[data / "2024_DATA", data / "backup"],
        archive_root=tmp_path / "archive",
        output_root=tmp_path / "research",
    )

    with pytest.raises(ValueError, match="canonical production roots"):
        _inventory_command(args)

    assert called is False


def test_workspace_rejects_descendants_of_protected_inputs(tmp_path):
    roots = fixture_roots(tmp_path)
    roots = ResearchRoots(
        raw_roots=roots.raw_roots,
        archive_root=roots.archive_root,
        output_root=tmp_path,
        excluded_backup_root=roots.excluded_backup_root,
    )

    with pytest.raises(ValueError, match="protected input"):
        _assert_workspace(roots.raw_roots[0] / "nested-output", roots)


def test_finalize_orchestration_requires_exact_production_workspace(tmp_path):
    roots, workspace, _source, _cli = diagnostic_workspace(tmp_path)

    with pytest.raises(ValueError, match="canonical production workspace"):
        finalize_stage(workspace)

    assert roots.output_root != ResearchRoots.default().output_root


def test_diagnostic_resume_reuses_only_exact_successful_provenance(tmp_path):
    roots, workspace, source, cli = diagnostic_workspace(tmp_path)
    calls: list[Path] = []

    def runner(_cli, input_file, **kwargs):
        calls.append(input_file)
        return successful_diagnostic(input_file, kwargs)

    first = diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        timeout_seconds=7,
        resume=True,
        diagnostic_runner=runner,
    )
    unchanged = diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        timeout_seconds=7,
        resume=True,
        diagnostic_runner=runner,
    )

    assert first["new_record_count"] == 1
    assert unchanged["new_record_count"] == 0
    assert calls == [source.resolve()]
    record = json.loads((workspace / "diagnostics.ndjson").read_text(encoding="utf-8"))
    assert record["source_sha256"] == hashlib.sha256(b"source-v1").hexdigest()
    assert record["physical_run_key"] == "2024_DATA/run-a"
    assert record["cli_sha256"] == hashlib.sha256(b"cli-v1").hexdigest()
    assert record["diagnostic_settings_fingerprint"]
    assert record["diagnostic_success"] is True

    source.write_bytes(b"source-v2")
    inventory = pd.read_csv(workspace / "inventory.csv", keep_default_na=False)
    inventory.loc[0, "content_sha256"] = hashlib.sha256(b"source-v2").hexdigest()
    inventory.to_csv(workspace / "inventory.csv", index=False)

    stale_source = diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        timeout_seconds=7,
        resume=True,
        diagnostic_runner=runner,
    )

    assert stale_source["new_record_count"] == 1
    assert calls == [source.resolve(), source.resolve()]


def test_diagnostic_resume_invalidates_changed_cli_and_settings(tmp_path):
    roots, workspace, source, cli = diagnostic_workspace(tmp_path)
    calls: list[Path] = []

    def runner(_cli, input_file, **kwargs):
        calls.append(input_file)
        return successful_diagnostic(input_file, kwargs)

    diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        timeout_seconds=7,
        resume=True,
        diagnostic_runner=runner,
    )
    cli.write_bytes(b"cli-v2")
    changed_cli = diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        timeout_seconds=7,
        resume=True,
        diagnostic_runner=runner,
    )
    changed_settings = diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        timeout_seconds=8,
        resume=True,
        diagnostic_runner=runner,
    )

    assert changed_cli["new_record_count"] == 1
    assert changed_settings["new_record_count"] == 1
    assert calls == [source.resolve(), source.resolve(), source.resolve()]


def test_diagnostic_resume_retries_failed_records(tmp_path):
    roots, workspace, source, cli = diagnostic_workspace(tmp_path)
    calls = 0

    def runner(_cli, input_file, **kwargs):
        nonlocal calls
        calls += 1
        record = successful_diagnostic(input_file, kwargs)
        if calls == 1:
            return replace(
                record,
                transport_status="timeout",
                issue_codes=("transport_timeout",),
            )
        return record

    diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        resume=True,
        diagnostic_runner=runner,
    )
    retried = diagnose_stage(
        workspace,
        cli=cli,
        roots=roots,
        resume=True,
        diagnostic_runner=runner,
    )

    assert retried["new_record_count"] == 1
    assert calls == 2
    record = json.loads((workspace / "diagnostics.ndjson").read_text(encoding="utf-8"))
    assert record["diagnostic_success"] is True


@pytest.mark.parametrize(("approved", "gold_count"), ((False, 0), (True, 1)))
def test_finalize_requires_explicit_review_approval_for_gold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    approved: bool,
    gold_count: int,
):
    roots, workspace, source, _cli = diagnostic_workspace(tmp_path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    pd.DataFrame(
        [
            {
                "schema_kind": "v2",
                "source_path": str(source),
                "source_sha256": source_hash,
                "ladder": "LIZ",
                "selected_times": json.dumps(list(range(100, 260, 10))),
                "sidecar_path": "",
                "analysis_id": "clonality",
                "identity_key": "patient-001",
                "sample_kind": "patient",
                "provisional_eligible": True,
                "gold_eligible": False,
            }
        ]
    ).to_csv(workspace / "manual_corrections.csv", index=False)
    (workspace / "diagnostics.ndjson").write_text(
        json.dumps(
            {
                "source_path": str(source),
                "transport_status": "ok",
                "configured_ladder": "LIZ",
                "outcome": "fit_rejected_with_usable_signal",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if approved:
        pd.DataFrame(
            [
                {
                    "content_sha256": source_hash,
                    "ladder": "LIZ",
                    "review_approved": True,
                    "review_label": "manual_adjusted",
                    "reviewed_at_utc": "2026-08-11T08:00:00+00:00",
                    "reviewed_by": "chemist",
                }
            ]
        ).to_csv(workspace / "manual_correction_approvals.csv", index=False)

    partition_calls = 0
    real_assign_partitions = corpus_module.assign_partitions

    def tracked_assign_partitions(records, *, seed):
        nonlocal partition_calls
        partition_calls += 1
        return real_assign_partitions(records, seed=seed)

    monkeypatch.setattr(corpus_module, "assign_partitions", tracked_assign_partitions)

    finalize_stage(workspace, roots=roots)

    gold = json.loads((workspace / "gold_records.json").read_text(encoding="utf-8"))
    development = json.loads(
        (workspace / "development_manifest.json").read_text(encoding="utf-8")
    )
    assert gold["record_count"] == gold_count
    assert partition_calls == 1
    assert development["file_count"] == 1
    assert development["files"][0]["review_approved"] is approved
    if approved:
        assert gold["records"][0]["truth_source"] == "reviewed_correction"
        assert gold["records"][0]["reviewed_by"] == "chemist"


def test_manual_correction_approval_rejects_non_hex_content_hash(tmp_path: Path):
    pd.DataFrame(
        [
            {
                "content_sha256": "g" * 64,
                "ladder": "LIZ",
                "review_approved": True,
                "review_label": "manual_adjusted",
                "reviewed_at_utc": "2026-08-11T08:00:00+00:00",
                "reviewed_by": "chemist",
            }
        ]
    ).to_csv(tmp_path / "manual_correction_approvals.csv", index=False)

    with pytest.raises(ValueError, match="valid content hash"):
        _load_manual_correction_approvals(tmp_path)


def test_end_to_end_builder_excludes_backup_and_writes_all_artifacts(tmp_path, monkeypatch):
    roots = fixture_roots(tmp_path)
    run = roots.raw_roots[0] / "run-a"
    run.mkdir()
    source = run / "sample.fsa"
    source.write_bytes(b"allowed-fsa")
    annotation_source = run / "annotation-only.fsa"
    annotation_source.write_bytes(b"annotation-fsa")
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
                    "SampleKind": "patient",
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
    (gate / "ladder_review_annotations.json").write_text(
        json.dumps(
            {
                r"F:\DATA\2024_DATA\run-a\annotation-only.fsa": {
                    "label": "manual_adjusted",
                    "adjustment_path": r"F:\DATA\2024_DATA\run-a\annotation-only.ladder_adj.json",
                }
            }
        ),
        encoding="utf-8",
    )

    workspace = roots.output_root / "fixture-run"
    inventory_stage(roots, workspace)
    monkeypatch.setattr(
        "core.research.ladder.inventory.discover_raw_runs",
        lambda _roots: (_ for _ in ()).throw(AssertionError("raw files were rescanned")),
    )
    refresh_inventory_stage(roots, workspace)

    diagnosed_paths = []

    def fake_diagnostic(_cli, input_file, **kwargs):
        diagnosed_paths.append(input_file)
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
    finalize_stage(workspace, seed=20260810, roots=roots)

    assert EXPECTED_ARTIFACTS <= {path.name for path in workspace.iterdir()}
    assert len(pd.read_csv(workspace / "inventory.csv")) == 2
    assert diagnosed_paths == [source.resolve()]
    gold = json.loads((workspace / "gold_records.json").read_text(encoding="utf-8"))
    assert gold["record_count"] == 0
    corrections = pd.read_csv(workspace / "manual_corrections.csv", keep_default_na=False)
    assert corrections.loc[0, "provisional_eligible"]
    assert not corrections.loc[0, "gold_eligible"]
    development = json.loads(
        (workspace / "development_manifest.json").read_text(encoding="utf-8")
    )
    assert development["file_count"] == 1
    assert development["files"][0]["review_approved"] is False
    for artifact in workspace.iterdir():
        if artifact.suffix.casefold() not in {".csv", ".json", ".ndjson"}:
            continue
        assert "forbidden-sentinel" not in artifact.read_text(
            encoding="utf-8", errors="ignore"
        )
