from __future__ import annotations

import random
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from core.research.ladder.fit_improvement import (
    DEVELOPMENT_QUOTAS,
    VALIDATION_QUOTAS,
    assert_validation_unlocked,
    build_approved_fit_gold,
    finalize_fit_improvement_wave,
    freeze_fit_candidate,
    prepare_fit_improvement_experiment,
    select_fit_improvement_waves,
)


def _reviewed_outcome(content_hash: str, *, ladder: str = "LIZ", run: str = "run-a"):
    count = 16 if ladder == "LIZ" else 21
    return {
        "content_sha256": content_hash,
        "physical_run_key": run,
        "sample_kind": "patient",
        "ladder": ladder,
        "label": "manual_adjusted",
        "reviewed_at_utc": "2026-08-11T12:00:00+00:00",
        "review_scan_indices": list(range(100, 100 + count)),
        "fitting_evaluation_eligible": True,
        "failure_signature": "fit_rejected_with_usable_signal",
    }


def _gold_approval(path: Path, content_hash: str, *, run: str = "run-a"):
    return {
        "path": str(path),
        "content_sha256": content_hash,
        "physical_run_key": run,
        "identity_key": f"patient:{run}",
        "sample_kind": "patient",
        "reviewed_by": "chemist",
        "approved_for_fit_gold": True,
    }


def test_fit_gold_contains_only_usable_explicitly_approved_complete_ladders(tmp_path):
    approved_file = tmp_path / "approved.fsa"
    approved_file.write_bytes(b"approved")
    approved_hash = hashlib.sha256(approved_file.read_bytes()).hexdigest()
    excluded_hash = "e" * 64
    outcomes = {
        "cases": [
            _reviewed_outcome(approved_hash),
            {
                **_reviewed_outcome(excluded_hash, run="run-excluded"),
                "label": "excluded_missing_ladder_signal",
                "review_scan_indices": [],
                "fitting_evaluation_eligible": False,
            },
        ]
    }

    manifest = build_approved_fit_gold(
        {"cases": []},
        outcomes,
        {approved_hash: _gold_approval(approved_file, approved_hash)},
    )

    assert manifest["record_count"] == 1
    assert all(record["sample_kind"] == "patient" for record in manifest["records"])
    assert all(record["approved_for_fit_gold"] is True for record in manifest["records"])
    assert all(len(record["expected_scan_indices"]) in {16, 21} for record in manifest["records"])
    assert all(record["content_sha256"] in {approved_hash} for record in manifest["records"])


def test_fit_gold_can_bind_locked_validation_provenance(tmp_path):
    approved_file = tmp_path / "validation.fsa"
    approved_file.write_bytes(b"validation")
    content_hash = hashlib.sha256(approved_file.read_bytes()).hexdigest()

    manifest = build_approved_fit_gold(
        {"cases": []},
        {"cases": [_reviewed_outcome(content_hash)]},
        {content_hash: _gold_approval(approved_file, content_hash)},
        development_truth_source="validation_review",
        partition="locked_validation_fit_gold",
    )

    assert manifest["records"][0]["truth_source"] == "validation_review"
    assert manifest["records"][0]["partition"] == "locked_validation_fit_gold"


def test_fit_gold_rejects_changed_bytes(tmp_path):
    approved_file = tmp_path / "changed.fsa"
    approved_file.write_bytes(b"changed")
    expected_hash = hashlib.sha256(b"original").hexdigest()

    with pytest.raises(ValueError, match="SHA-256"):
        build_approved_fit_gold(
            {"cases": []},
            {"cases": [_reviewed_outcome(expected_hash)]},
            {expected_hash: _gold_approval(approved_file, expected_hash)},
        )


def test_fit_gold_rejects_duplicate_physical_runs(tmp_path):
    files = [tmp_path / "one.fsa", tmp_path / "two.fsa"]
    for index, path in enumerate(files):
        path.write_bytes(f"case-{index}".encode())
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in files]
    outcomes = {"cases": [_reviewed_outcome(value, run="same-run") for value in hashes]}
    approvals = {
        value: _gold_approval(path, value, run="same-run")
        for value, path in zip(hashes, files)
    }

    with pytest.raises(ValueError, match="physical run"):
        build_approved_fit_gold({"cases": []}, outcomes, approvals)
from core.research.ladder.contracts import ResearchRoots


def _candidate_rows(*, extras_per_stratum: int = 0):
    diagnostics: list[dict] = []
    inventory: list[dict] = []
    serial = 1
    quotas = Counter()
    for quota in (*DEVELOPMENT_QUOTAS, *VALIDATION_QUOTAS):
        quotas[(quota.cohort_group, quota.ladder)] += quota.count

    for (group, ladder), count in quotas.items():
        for offset in range(count + extras_per_stratum):
            path = f"C:/allowed/{group}-{ladder}-{offset:03d}.fsa"
            content_hash = f"{serial:064x}"
            physical_run = f"run-{serial:04d}"
            year = str(2024 + (offset % 3))
            inventory.append(
                {
                    "resolved_full_path": path,
                    "raw_path": path,
                    "file": path.rsplit("/", 1)[-1],
                    "content_sha256": content_hash,
                    "physical_run_key": physical_run,
                    "sample_kind": "patient",
                    "year": year,
                    "assay": f"assay-{offset % 5}",
                }
            )
            diagnostics.append(
                {
                    "source_path": path,
                    "source_sha256": content_hash,
                    "configured_ladder": "LIZ500_250" if ladder == "LIZ" else "ROX400HD",
                    "outcome": (
                        "fit_rejected_with_usable_signal"
                        if group == "suspicious"
                        else "unresolved"
                    ),
                    "accepted": group == "control",
                    "review_required": group != "control",
                    "reason_codes": [f"reason-{offset % 4}"],
                    "search_tier": f"tier-{offset % 3}",
                    "preview_scan_indices": list(range(16 if ladder == "LIZ" else 21)),
                }
            )
            serial += 1
    return diagnostics, inventory


def _quota_counts(selection) -> Counter:
    return Counter(
        (case.wave, case.cohort_group, case.ladder) for case in selection.cases
    )


def test_select_fit_improvement_waves_is_patient_only_balanced_and_disjoint():
    diagnostics, inventory = _candidate_rows(extras_per_stratum=2)
    excluded_hash = inventory[0]["content_sha256"]
    inventory.append(
        {
            "resolved_full_path": "C:/allowed/not-patient.fsa",
            "raw_path": "C:/allowed/not-patient.fsa",
            "file": "not-patient.fsa",
            "content_sha256": "f" * 64,
            "physical_run_key": "run-not-patient",
            "sample_kind": "control",
            "year": "2026",
            "assay": "assay-x",
        }
    )
    diagnostics.append(
        {
            "source_path": "C:/allowed/not-patient.fsa",
            "source_sha256": "f" * 64,
            "configured_ladder": "LIZ500_250",
            "outcome": "fit_rejected_with_usable_signal",
        }
    )

    selected = select_fit_improvement_waves(
        diagnostics,
        inventory,
        excluded_hashes={excluded_hash},
        seed=20260811,
    )

    assert _quota_counts(selected) == Counter(
        {
            ("development", "control", "LIZ"): 25,
            ("development", "control", "ROX"): 8,
            ("development", "suspicious", "LIZ"): 3,
            ("development", "suspicious", "ROX"): 4,
            ("validation", "control", "LIZ"): 41,
            ("validation", "control", "ROX"): 9,
            ("validation", "suspicious", "LIZ"): 5,
            ("validation", "suspicious", "ROX"): 5,
        }
    )
    assert {case.sample_kind for case in selected.cases} == {"patient"}
    assert len({case.content_sha256 for case in selected.cases}) == 100
    assert len({case.physical_run_key.casefold() for case in selected.cases}) == 100
    assert excluded_hash not in {case.content_sha256 for case in selected.cases}
    assert "f" * 64 not in {case.content_sha256 for case in selected.cases}
    assert {case.year for case in selected.development_cases} == {"2024", "2025", "2026"}
    assert {case.year for case in selected.validation_cases} == {"2024", "2025", "2026"}


def test_select_fit_improvement_waves_is_input_order_independent():
    diagnostics, inventory = _candidate_rows(extras_per_stratum=2)
    expected = select_fit_improvement_waves(
        diagnostics, inventory, excluded_hashes=set(), seed=17
    )
    random.Random(7).shuffle(diagnostics)
    random.Random(9).shuffle(inventory)

    assert (
        select_fit_improvement_waves(
            diagnostics, inventory, excluded_hashes=set(), seed=17
        )
        == expected
    )


@pytest.mark.parametrize(
    ("group", "ladder"),
    [
        ("control", "LIZ"),
        ("control", "ROX"),
        ("suspicious", "LIZ"),
        ("suspicious", "ROX"),
    ],
)
def test_select_fit_improvement_waves_reports_exact_stratum_shortage(group, ladder):
    diagnostics, inventory = _candidate_rows()
    remove_path = next(
        row["source_path"]
        for row in diagnostics
        if (row["accepted"] is (group == "control"))
        and row["configured_ladder"].startswith(ladder)
    )
    diagnostics = [row for row in diagnostics if row["source_path"] != remove_path]
    inventory = [row for row in inventory if row["resolved_full_path"] != remove_path]

    with pytest.raises(ValueError, match=f"Insufficient unique candidates for {group} {ladder}"):
        select_fit_improvement_waves(
            diagnostics, inventory, excluded_hashes=set(), seed=17
        )


def test_select_fit_improvement_waves_rejects_diagnostic_inventory_hash_mismatch():
    diagnostics, inventory = _candidate_rows()
    diagnostics[0]["source_sha256"] = "a" * 64

    with pytest.raises(ValueError, match="diagnostic/inventory SHA-256 mismatch"):
        select_fit_improvement_waves(
            diagnostics, inventory, excluded_hashes=set(), seed=17
        )


def test_select_fit_improvement_waves_rejects_joint_case_insensitive_run_conflict():
    diagnostics, inventory = _candidate_rows()
    inventory[1]["physical_run_key"] = inventory[0]["physical_run_key"].upper()

    with pytest.raises(ValueError, match="globally disjoint"):
        select_fit_improvement_waves(
            diagnostics, inventory, excluded_hashes=set(), seed=17
        )


def test_select_fit_improvement_waves_excludes_missing_year():
    diagnostics, inventory = _candidate_rows()
    inventory[0]["year"] = ""

    with pytest.raises(ValueError, match="Insufficient unique candidates"):
        select_fit_improvement_waves(
            diagnostics, inventory, excluded_hashes=set(), seed=17
        )


def _published_workspace(tmp_path: Path):
    raw_roots = tuple(tmp_path / "raw" / year for year in ("2024", "2025", "2026"))
    for root in raw_roots:
        root.mkdir(parents=True)
    output_root = tmp_path / "research" / "ladder"
    workspace = output_root / "current"
    workspace.mkdir(parents=True)
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    excluded_backup = tmp_path / "raw" / "backup"
    roots = ResearchRoots(
        raw_roots=raw_roots,
        archive_root=archive_root,
        output_root=output_root,
        excluded_backup_root=excluded_backup,
    )
    (workspace / "run_manifest.json").write_text(
        json.dumps(
            {
                "roots": {
                    "raw_roots": [str(path) for path in raw_roots],
                    "archive_root": str(archive_root),
                    "output_root": str(output_root),
                    "excluded_backup_root": str(excluded_backup),
                }
            }
        ),
        encoding="utf-8",
    )

    diagnostics, inventory = _candidate_rows(extras_per_stratum=2)
    for serial, (diagnostic, row) in enumerate(zip(diagnostics, inventory), 1):
        source = raw_roots[(serial - 1) % len(raw_roots)] / row["file"]
        source.write_bytes(f"fsa-{serial}".encode())
        content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        row["resolved_full_path"] = str(source)
        row["raw_path"] = str(source)
        row["content_sha256"] = content_hash
        diagnostic["source_path"] = str(source)
        diagnostic["source_sha256"] = content_hash

    with (workspace / "inventory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=inventory[0].keys())
        writer.writeheader()
        writer.writerows(inventory)
    (workspace / "diagnostics.ndjson").write_text(
        "\n".join(json.dumps(row) for row in diagnostics) + "\n",
        encoding="utf-8",
    )
    (workspace / "development_manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {"content_sha256": f"{10_000 + index:064x}"}
                    for index in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    (workspace / "round_2_selection_withheld.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"content_sha256": f"{20_000 + index:064x}"}
                    for index in range(18)
                ]
            }
        ),
        encoding="utf-8",
    )
    return workspace, roots


def _public_bundle_text(bundle: Path) -> str:
    paths = [
        bundle / "ladder_review_cases.csv",
        bundle / "ladder_review_summary.json",
        bundle / "research_case_map.json",
        bundle / "README.md",
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_prepare_fit_improvement_publishes_two_blind_waves_atomically(tmp_path):
    workspace, roots = _published_workspace(tmp_path)

    result = prepare_fit_improvement_experiment(workspace, seed=7, roots=roots)

    assert result.development.case_count == 40
    assert result.validation.case_count == 60
    assert not result.development.adjustment_database.exists()
    assert not result.validation.adjustment_database.exists()
    assert len(list(result.development.bundle_dir.rglob("*.fsa"))) == 40
    assert len(list(result.validation.bundle_dir.rglob("*.fsa"))) == 60
    public = _public_bundle_text(result.development.bundle_dir)
    assert "cohort_group" not in public
    assert "selection_reason" not in public
    assert not list(result.experiment_dir.rglob("*.ladder_adj.json"))


def test_prepare_fit_improvement_rolls_back_both_waves_on_copy_failure(
    tmp_path, monkeypatch
):
    workspace, roots = _published_workspace(tmp_path)
    from core.research.ladder import fit_improvement as module

    real_prepare = module.prepare_blind_review_bundle
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected validation publication failure")
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(module, "prepare_blind_review_bundle", fail_second)

    with pytest.raises(RuntimeError, match="injected validation"):
        prepare_fit_improvement_experiment(workspace, seed=7, roots=roots)
    assert not (workspace / "rust_fit_improvement").exists()


def test_validation_requires_hash_bound_candidate_freeze(tmp_path):
    workspace, _roots = _published_workspace(tmp_path)
    experiment = workspace / "rust_fit_improvement"
    experiment.mkdir()
    (experiment / "development_outcomes.json").write_text(
        json.dumps({"total_count": 40}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="frozen candidate"):
        assert_validation_unlocked(workspace)

    binary = tmp_path / "fraggler-cli.exe"
    binary.write_bytes(b"candidate-v1")
    freeze = freeze_fit_candidate(
        workspace,
        binary=binary,
        configuration={"tier_1_expansions": 1000},
        git_revision="abc123",
    )
    assert freeze.binary_sha256 == hashlib.sha256(b"candidate-v1").hexdigest()
    assert_validation_unlocked(workspace)

    freeze_payload = json.loads(freeze.manifest_path.read_text(encoding="utf-8"))
    freeze_payload["configuration"]["tier_1_expansions"] = 9999
    freeze.manifest_path.write_text(json.dumps(freeze_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="configuration fingerprint"):
        assert_validation_unlocked(workspace)

    freeze_payload["configuration"]["tier_1_expansions"] = 1000
    freeze.manifest_path.write_text(json.dumps(freeze_payload), encoding="utf-8")
    binary.write_bytes(b"candidate-mutated")
    with pytest.raises(ValueError, match="binary SHA-256"):
        assert_validation_unlocked(workspace)


def _resolve_wave_as_no_change(bundle: Path) -> None:
    cases_path = bundle / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        row["label"] = "reviewed_no_change"
        row["reviewed_at_utc"] = "2026-08-11T12:00:00+00:00"
    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_finalize_fit_development_accepts_exactly_40_resolved_verified_cases(tmp_path):
    workspace, roots = _published_workspace(tmp_path)
    experiment = prepare_fit_improvement_experiment(workspace, seed=7, roots=roots)
    _resolve_wave_as_no_change(experiment.development.bundle_dir)

    result = finalize_fit_improvement_wave(
        workspace, "development", roots=roots
    )

    assert result.total_count == 40
    assert result.excluded_count == 0
    assert result.fitting_evaluation_count == 40
    assert result.outcomes_path == experiment.experiment_dir / "development_outcomes.json"
    payload = json.loads(result.outcomes_path.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 40
    assert all(case["review_scan_indices"] for case in payload["cases"])


def test_finalize_fit_wave_refuses_unresolved_or_mutated_copy(tmp_path):
    workspace, roots = _published_workspace(tmp_path)
    experiment = prepare_fit_improvement_experiment(workspace, seed=7, roots=roots)

    with pytest.raises(ValueError, match="unresolved"):
        finalize_fit_improvement_wave(workspace, "development", roots=roots)

    _resolve_wave_as_no_change(experiment.development.bundle_dir)
    copied = next(experiment.development.bundle_dir.rglob("*.fsa"))
    copied.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="SHA-256"):
        finalize_fit_improvement_wave(workspace, "development", roots=roots)


def test_finalize_validation_refuses_even_resolved_rows_before_freeze(tmp_path):
    workspace, roots = _published_workspace(tmp_path)
    experiment = prepare_fit_improvement_experiment(workspace, seed=7, roots=roots)
    _resolve_wave_as_no_change(experiment.validation.bundle_dir)

    with pytest.raises(ValueError, match="frozen candidate"):
        finalize_fit_improvement_wave(workspace, "validation", roots=roots)


@pytest.mark.parametrize(
    "command",
    [
        "prepare-fit-improvement",
        "finalize-fit-development",
        "freeze-fit-candidate",
        "finalize-fit-validation",
    ],
)
def test_fit_improvement_cli_routes_have_help(command):
    script = Path(__file__).parents[1] / "scripts" / "build_ladder_research_corpus.py"
    completed = subprocess.run(
        [sys.executable, str(script), command, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout
