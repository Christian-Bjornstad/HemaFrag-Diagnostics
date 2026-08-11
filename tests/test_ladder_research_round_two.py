from __future__ import annotations

import csv
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.ladder_adjustment_store import save_ladder_adjustment_record
from core.research.ladder import round_two as round_two_module
from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.round_two import (
    classify_controller_supplied_round_two_migration,
    load_round_two_inputs,
    select_round_two_cohort,
)
from scripts import build_ladder_research_corpus as research_cli


def _candidate_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    diagnostics: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []
    ordinal = 0
    for cohort_group, ladder, count in (
        ("suspicious", "LIZ", 8),
        ("suspicious", "ROX", 8),
        ("control", "LIZ", 5),
        ("control", "ROX", 5),
    ):
        for group_ordinal in range(count):
            ordinal += 1
            source = Path(f"C:/allowed/{2024 + group_ordinal % 3}/run-{ordinal}/case-{ordinal}.fsa")
            content_hash = f"hash-{ordinal:03d}"
            outcome = (
                "fit_rejected_with_usable_signal"
                if cohort_group == "suspicious"
                else "unresolved"
            )
            diagnostics.append(
                {
                    "source_path": str(source),
                    "source_sha256": content_hash,
                    "physical_run_key": f"run-{ordinal:03d}",
                    "configured_ladder": f"{ladder}500_250",
                    "outcome": outcome,
                    "accepted": cohort_group == "control",
                    "review_required": cohort_group == "suspicious",
                    "reason_codes": [f"reason-{group_ordinal % 3}"],
                    "assay": f"assay-{group_ordinal % 2}",
                    "preview_scan_indices": [100, 200, 300],
                }
            )
            inventory.append(
                {
                    "raw_path": str(source.resolve()),
                    "file": source.name,
                    "year": str(2024 + group_ordinal % 3),
                    "physical_run_key": f"run-{ordinal:03d}",
                    "content_sha256": content_hash,
                    "sample_kind": "patient",
                }
            )
    return diagnostics, inventory


def _round_two_workspace(tmp_path: Path, *, bad_hash: bool = False) -> Path:
    diagnostics, inventory = _candidate_rows()
    data_root = tmp_path / "DATA"
    raw_roots = tuple(data_root / f"{year}_DATA" for year in (2024, 2025, 2026))
    for ordinal, (diagnostic, inventory_row) in enumerate(
        zip(diagnostics, inventory), 1
    ):
        raw_root = raw_roots[(ordinal - 1) % len(raw_roots)]
        source = raw_root / f"run-{ordinal:03d}" / f"case-{ordinal:03d}.fsa"
        source.parent.mkdir(parents=True, exist_ok=True)
        payload = f"round-two-fixture-{ordinal}".encode()
        source.write_bytes(payload)
        source.with_suffix(".ladder_adj.json").write_text(
            "historical adjustment must not be copied", encoding="utf-8"
        )
        diagnostic["source_path"] = str(source)
        inventory_row["raw_path"] = str(source)
        inventory_row["file"] = source.name
        inventory_row["physical_run_key"] = f"run-{ordinal:03d}"
        inventory_row["content_sha256"] = (
            f"{ordinal:064x}"
            if bad_hash
            else hashlib.sha256(payload).hexdigest()
        )
        diagnostic["source_sha256"] = inventory_row["content_sha256"]
        diagnostic["physical_run_key"] = inventory_row["physical_run_key"]

    workspace = tmp_path / "research" / "current"
    workspace.mkdir(parents=True)
    (workspace / "diagnostics.ndjson").write_text(
        "".join(json.dumps(row) + "\n" for row in diagnostics), encoding="utf-8"
    )
    with (workspace / "inventory.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=inventory[0])
        writer.writeheader()
        writer.writerows(inventory)
    (workspace / "manual_corrections.csv").write_text(
        "source_sha256\n", encoding="utf-8"
    )
    (workspace / "development_manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {"content_sha256": "round-one-a"},
                    {"content_sha256": "round-one-b"},
                    {"content_sha256": "round-one-c"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (workspace / "run_manifest.json").write_text(
        json.dumps(
            {
                "roots": {
                    "raw_roots": [str(path) for path in raw_roots],
                    "archive_root": str(tmp_path / "archive"),
                    "output_root": str(tmp_path / "research"),
                    "excluded_backup_root": str(data_root / "backup"),
                }
            }
        ),
        encoding="utf-8",
    )
    return workspace


def _write_review_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def _workspace_roots(workspace: Path) -> ResearchRoots:
    manifest = json.loads(
        (workspace / "run_manifest.json").read_text(encoding="utf-8")
    )
    roots = manifest["roots"]
    return ResearchRoots(
        raw_roots=tuple(Path(value) for value in roots["raw_roots"]),
        archive_root=Path(roots["archive_root"]),
        output_root=Path(roots["output_root"]),
        excluded_backup_root=Path(roots["excluded_backup_root"]),
    )


def _resolved_round_two_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, str], dict[str, str]]:
    workspace = _round_two_workspace(tmp_path)
    published = round_two_module.prepare_round_two_review(
        workspace, seed=7, roots=_workspace_roots(workspace)
    )
    cases_path = published.bundle_dir / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        row["label"] = "reviewed_no_change"
        row["reviewed_at_utc"] = "2026-08-11T08:00:00+00:00"
    manual_row = rows[0]
    manual_row["label"] = "manual_adjusted"
    excluded_row = rows[-1]
    excluded_row["label"] = "excluded_missing_ladder_signal"
    excluded_row["label_note"] = "No usable ladder signal"
    _write_review_rows(cases_path, rows)

    expected_count = 16 if manual_row["ladder"] == "LIZ" else 21
    observed_times = [101.0, 198.0, 305.0] + [
        float(400 + 100 * index) for index in range(expected_count - 3)
    ]
    selected_peaks = [
        {
            "step_index": index,
            "candidate_index": index,
            "expected_bp": float(35 + 10 * index),
            "observed_time": observed_time,
        }
        for index, observed_time in enumerate(observed_times)
    ]
    payload = {
        "schema_version": "hemafrag_ladder_adjustment_v2",
        "selected_peaks": selected_peaks,
        "validation": {"save_verified": True},
    }
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB", str(published.adjustment_database)
    )
    stored_ladder = (
        "LIZ500_250" if manual_row["ladder"] == "LIZ" else "ROX400HD"
    )
    save_ladder_adjustment_record(
        Path(manual_row["full_path"]), payload, ladder=stored_ladder
    )

    default_database = tmp_path / "user-default" / "ladder_adjustments.sqlite3"
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(default_database))
    decoy_payload = {
        **payload,
        "selected_peaks": [
            {**peak, "observed_time": float(900 + index)}
            for index, peak in enumerate(selected_peaks)
        ],
    }
    save_ladder_adjustment_record(
        Path(manual_row["full_path"]),
        decoy_payload,
        ladder=stored_ladder,
    )
    return workspace, manual_row, excluded_row


def _classification(row: dict[str, object]) -> str:
    if row["outcome"] == "fit_rejected_with_usable_signal":
        return "suspicious"
    return "control"


def _append_candidate(
    diagnostics: list[dict[str, object]],
    inventory: list[dict[str, object]],
    key: str,
    *,
    cohort_group: str,
    ladder: str,
    run: str,
    year: str,
    reason: str,
    assay: str,
) -> None:
    source = Path(f"C:/allowed/{year or 'unknown'}/{run}/{key}.fsa")
    diagnostics.append(
        {
            "source_path": str(source),
            "source_sha256": f"{key}-hash",
            "physical_run_key": run,
            "configured_ladder": ladder,
            "outcome": (
                "fit_rejected_with_usable_signal"
                if cohort_group == "suspicious"
                else "unresolved"
            ),
            "accepted": cohort_group == "control",
            "review_required": cohort_group == "suspicious",
            "reason_codes": [reason] if reason else [],
            "assay": assay,
        }
    )
    inventory.append(
        {
            "raw_path": str(source.resolve()),
            "file": source.name,
            "year": year,
            "physical_run_key": run,
            "content_sha256": f"{key}-hash",
            "sample_kind": "patient",
        }
    )


def test_round_two_selection_is_balanced_blind_and_isolated():
    diagnostics, inventory = _candidate_rows()
    manual_hashes = {"hash-018"}
    first_round_hashes = {"hash-001", "round-one-b", "round-one-c"}

    result = select_round_two_cohort(
        diagnostics, inventory, manual_hashes, first_round_hashes, seed=7
    )

    counts = Counter((case["cohort_group"], case["ladder"]) for case in result.cases)
    assert counts == {
        ("suspicious", "LIZ"): 6,
        ("suspicious", "ROX"): 6,
        ("control", "LIZ"): 3,
        ("control", "ROX"): 3,
    }
    assert len({case["content_sha256"] for case in result.cases}) == 18
    assert len({case["physical_run_key"] for case in result.cases}) == 18
    assert not first_round_hashes & {
        case["content_sha256"] for case in result.cases
    }
    assert not manual_hashes & {
        case["content_sha256"]
        for case in result.cases
        if case["cohort_group"] == "control"
    }
    assert len({case["year"] for case in result.cases}) >= 2


def test_round_two_selection_is_independent_of_input_order():
    diagnostics, inventory = _candidate_rows()
    expected = select_round_two_cohort(
        diagnostics,
        inventory,
        {"hash-018"},
        {"hash-001", "round-one-b", "round-one-c"},
        seed=17,
    )
    random.Random(11).shuffle(diagnostics)
    random.Random(29).shuffle(inventory)

    shuffled = select_round_two_cohort(
        diagnostics,
        inventory,
        {"hash-018"},
        {"hash-001", "round-one-b", "round-one-c"},
        seed=17,
    )

    assert [case["content_sha256"] for case in shuffled.cases] == [
        case["content_sha256"] for case in expected.cases
    ]


def test_round_two_selection_treats_physical_run_keys_case_insensitively():
    diagnostics, inventory = _candidate_rows()
    requirements = {
        ("suspicious", "LIZ"): 6,
        ("suspicious", "ROX"): 6,
        ("control", "LIZ"): 3,
        ("control", "ROX"): 3,
    }
    kept_diagnostics: list[dict[str, object]] = []
    kept_inventory: list[dict[str, object]] = []
    counts: Counter[tuple[str, str]] = Counter()
    for diagnostic, inventory_row in zip(diagnostics, inventory):
        key = (
            _classification(diagnostic),
            str(diagnostic["configured_ladder"])[:3],
        )
        if counts[key] >= requirements[key]:
            continue
        counts[key] += 1
        kept_diagnostics.append(diagnostic)
        kept_inventory.append(inventory_row)
    kept_inventory[0]["physical_run_key"] = "2024_DATA/Run-A"
    kept_inventory[1]["physical_run_key"] = "2024_data/run-a"

    with pytest.raises(ValueError, match="globally disjoint"):
        select_round_two_cohort(
            kept_diagnostics,
            kept_inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


def test_round_two_public_order_does_not_encode_quota_groups():
    diagnostics, inventory = _candidate_rows()

    result = select_round_two_cohort(
        diagnostics,
        inventory,
        set(),
        {"round-one-a", "round-one-b", "round-one-c"},
        seed=7,
    )

    public_allocation = [
        (case["cohort_group"], case["ladder"]) for case in result.cases
    ]
    quota_allocation = [("suspicious", "LIZ")] * 6
    quota_allocation.extend(("suspicious", "ROX") for _ in range(6))
    quota_allocation.extend(("control", "LIZ") for _ in range(3))
    quota_allocation.extend(("control", "ROX") for _ in range(3))

    assert public_allocation != quota_allocation
    assert sum(
        left != right for left, right in zip(public_allocation, public_allocation[1:])
    ) > 3


def test_controller_supplied_migration_is_matched_by_hash_and_never_gold():
    selection_cases = [
        {
            "case_id": f"{index + 1:03d}",
            "content_sha256": f"{index + 1:064x}",
            "copied_path": f"C:/quarantined-name-{index + 1}.fsa",
        }
        for index in range(18)
    ]
    supplied_rows = []
    for index, case in enumerate(selection_cases):
        if index < 8:
            label = "manual_adjusted"
        elif index == 8:
            label = "reviewed_no_change"
        else:
            label = ""
        supplied_rows.append(
            {
                "content_sha256": case["content_sha256"],
                "label": label,
                "label_note": "controller supplied evidence",
                "full_path": f"D:/must-not-be-used/{index}.fsa",
            }
        )
    random.Random(42).shuffle(supplied_rows)

    normalized = classify_controller_supplied_round_two_migration(
        selection_cases,
        supplied_rows,
    )

    assert [row["content_sha256"] for row in normalized] == [
        case["content_sha256"] for case in selection_cases
    ]
    assert Counter(row["evidence_classification"] for row in normalized) == {
        "resolved_decision_evidence": 9,
        "excluded_error_evidence": 9,
    }
    assert Counter(row["label"] for row in normalized) == {
        "manual_adjusted": 8,
        "reviewed_no_change": 1,
        "": 9,
    }
    assert all(row["requires_re_review"] is True for row in normalized)
    assert all(row["gold_eligible"] is False for row in normalized)
    assert all("full_path" not in row and "copied_path" not in row for row in normalized)


def test_controller_supplied_migration_requires_exact_unique_selection_hashes():
    selection_cases = [
        {"case_id": "001", "content_sha256": "1" * 64},
        {"case_id": "002", "content_sha256": "2" * 64},
    ]

    with pytest.raises(ValueError, match="exactly match"):
        classify_controller_supplied_round_two_migration(
            selection_cases,
            [
                {"content_sha256": "1" * 64, "label": "manual_adjusted"},
                {"content_sha256": "3" * 64, "label": ""},
            ],
        )


def test_round_two_selector_rejects_non_patient_candidates():
    diagnostics, inventory = _candidate_rows()
    suspicious_liz_paths = {
        row["source_path"]
        for row in diagnostics
        if row["outcome"] == "fit_rejected_with_usable_signal"
        and str(row["configured_ladder"]).startswith("LIZ")
    }
    suspicious_liz_inventory = [
        row for row in inventory if str(row["raw_path"]) in suspicious_liz_paths
    ]
    suspicious_liz_inventory[0]["sample_kind"] = "pk"
    removed_paths = {
        str(suspicious_liz_inventory[-1]["raw_path"]),
        str(suspicious_liz_inventory[-2]["raw_path"]),
    }
    diagnostics = [
        row for row in diagnostics if str(row["source_path"]) not in removed_paths
    ]

    with pytest.raises(ValueError, match="suspicious LIZ"):
        select_round_two_cohort(
            diagnostics,
            inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


def test_round_two_selector_rejects_stale_diagnostic_content_hash():
    diagnostics, inventory = _candidate_rows()
    diagnostics[0]["source_sha256"] = "stale-content-hash"

    with pytest.raises(ValueError, match="diagnostic.*inventory.*SHA-256"):
        select_round_two_cohort(
            diagnostics,
            inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


def test_round_two_controls_must_span_multiple_years():
    diagnostics, inventory = _candidate_rows()
    control_paths = {
        str(row["source_path"])
        for row in diagnostics
        if row["accepted"] is True
    }
    for row in inventory:
        if str(row["raw_path"]) in control_paths:
            row["year"] = "2024"

    with pytest.raises(ValueError, match="control.*year"):
        select_round_two_cohort(
            diagnostics,
            inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


def test_round_two_backtracks_when_an_early_choice_blocks_a_feasible_group():
    diagnostics: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []
    for ordinal in range(6):
        _append_candidate(
            diagnostics,
            inventory,
            f"liz-private-{ordinal}",
            cohort_group="suspicious",
            ladder="LIZ",
            run=f"liz-private-run-{ordinal}",
            year="2024",
            reason="linear-fit",
            assay="TCRgA",
        )
    _append_candidate(
        diagnostics,
        inventory,
        "liz-shared",
        cohort_group="suspicious",
        ladder="LIZ",
        run="shared-required-rox-run",
        year="2026",
        reason="baseline-like",
        assay="IGH",
    )
    for ordinal in range(6):
        _append_candidate(
            diagnostics,
            inventory,
            "rox-required" if ordinal == 0 else f"rox-{ordinal}",
            cohort_group="suspicious",
            ladder="ROX",
            run=("shared-required-rox-run" if ordinal == 0 else f"rox-run-{ordinal}"),
            year="2025",
            reason="compressed-rox",
            assay="IGH",
        )
    for cohort_group, ladder, count in (
        ("control", "LIZ", 3),
        ("control", "ROX", 3),
    ):
        for ordinal in range(count):
            _append_candidate(
                diagnostics,
                inventory,
                f"{cohort_group}-{ladder}-{ordinal}",
                cohort_group=cohort_group,
                ladder=ladder,
                run=f"{cohort_group}-{ladder}-run-{ordinal}",
                year="2024" if ordinal % 2 == 0 else "2025",
                reason="",
                assay="TCRgA" if ordinal % 2 == 0 else "IGH",
            )

    result = select_round_two_cohort(
        diagnostics,
        inventory,
        set(),
        {"round-one-a", "round-one-b", "round-one-c"},
        seed=7,
    )

    selected_hashes = {case["content_sha256"] for case in result.cases}
    assert "liz-shared-hash" not in selected_hashes
    assert "rox-required-hash" in selected_hashes


def test_round_two_selection_meets_nonblank_diversity_contract():
    diagnostics, inventory = _candidate_rows()

    result = select_round_two_cohort(
        diagnostics,
        inventory,
        set(),
        {"round-one-a", "round-one-b", "round-one-c"},
        seed=7,
    )

    assert len({case["year"] for case in result.cases if case["year"]}) >= 2
    assert len(
        {
            case["reason_signature"]
            for case in result.cases
            if case["cohort_group"] == "suspicious"
            and case["reason_signature"] != "none"
        }
    ) >= 2
    assert len({case["assay"] for case in result.cases if case["assay"]}) >= 2


@pytest.mark.parametrize("insufficient_dimension", ("year", "reason", "assay"))
def test_round_two_rejects_impossible_nonblank_diversity(insufficient_dimension: str):
    diagnostics, inventory = _candidate_rows()
    if insufficient_dimension == "year":
        for row in inventory:
            row["year"] = "2024"
        inventory[0]["year"] = ""
    elif insufficient_dimension == "reason":
        for row in diagnostics:
            row["reason_codes"] = ["only-reason"]
    else:
        for row in diagnostics:
            row["assay"] = "only-assay"

    with pytest.raises(ValueError, match=rf"Diversity.*{insufficient_dimension}"):
        select_round_two_cohort(
            diagnostics,
            inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


@pytest.mark.parametrize(
    ("missing_group", "missing_ladder", "expected_message"),
    [
        ("suspicious", "LIZ", "suspicious LIZ"),
        ("suspicious", "ROX", "suspicious ROX"),
        ("control", "LIZ", "control LIZ"),
        ("control", "ROX", "control ROX"),
    ],
)
def test_round_two_selection_reports_each_group_shortage(
    missing_group: str, missing_ladder: str, expected_message: str
):
    diagnostics, inventory = _candidate_rows()
    kept_diagnostics = [
        row
        for row in diagnostics
        if not (
            _classification(row) == missing_group
            and str(row["configured_ladder"]).startswith(missing_ladder)
        )
    ]

    with pytest.raises(ValueError, match=expected_message):
        select_round_two_cohort(
            kept_diagnostics,
            inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


def test_load_round_two_inputs_reads_existing_research_artifacts(tmp_path: Path):
    diagnostics = [{"source_path": "C:/allowed/a.fsa", "outcome": "unresolved"}]
    (tmp_path / "diagnostics.ndjson").write_text(
        "".join(json.dumps(row) + "\n" for row in diagnostics), encoding="utf-8"
    )
    inventory = [
        {
            "raw_path": "C:/allowed/a.fsa",
            "content_sha256": "inventory-hash",
            "physical_run_key": "run-a",
        }
    ]
    with (tmp_path / "inventory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=inventory[0])
        writer.writeheader()
        writer.writerows(inventory)
    with (tmp_path / "manual_corrections.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=("source_sha256",))
        writer.writeheader()
        writer.writerow({"source_sha256": "manual-hash"})
    (tmp_path / "development_manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {"content_sha256": "round-one-a"},
                    {"content_sha256": "round-one-b"},
                    {"content_sha256": "round-one-c"},
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_round_two_inputs(tmp_path)

    assert loaded == (
        diagnostics,
        inventory,
        {"manual-hash"},
        {"round-one-a", "round-one-b", "round-one-c"},
    )


def test_round_two_publication_keeps_allocation_outside_bundle(tmp_path: Path):
    workspace = _round_two_workspace(tmp_path)

    result = round_two_module.prepare_round_two_review(
        workspace, seed=7, roots=_workspace_roots(workspace)
    )

    assert result.case_count == 18
    assert result.bundle_dir == workspace / "round_2_review_bundle"
    assert result.withheld_manifest == workspace / "round_2_selection_withheld.json"
    assert result.adjustment_database == (
        result.bundle_dir / "ladder_adjustments.sqlite3"
    )
    assert len(list(result.bundle_dir.rglob("*.fsa"))) == 18
    assert not list(result.bundle_dir.rglob("*.ladder_adj.json"))

    with (result.bundle_dir / "ladder_review_cases.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames == [
            "full_path",
            "file",
            "source_run_dir",
            "assay",
            "ladder",
            "primary_reason",
            "label",
            "label_note",
            "reviewed_at_utc",
            "adjustment_path",
        ]
    assert {row["primary_reason"] for row in rows} == {"blind_review"}
    assert all(
        not row[field]
        for row in rows
        for field in ("label", "label_note", "reviewed_at_utc", "adjustment_path")
    )

    public_paths = list(result.bundle_dir.glob("*.json")) + [
        result.bundle_dir / "ladder_review_cases.csv"
    ]
    public_text = "\n".join(
        path.read_text(encoding="utf-8") for path in public_paths
    )
    for withheld_field in (
        "cohort_group",
        "risk",
        "outcome",
        "failure_family",
        "preview_scan_indices",
        "selection_reason",
        "reason_signature",
    ):
        assert withheld_field not in public_text

    withheld = json.loads(result.withheld_manifest.read_text(encoding="utf-8"))
    assert withheld["seed"] == 7
    assert withheld["case_count"] == 18
    assert len(withheld["cases"]) == 18
    assert all(
        case["preview_scan_indices"] == [100, 200, 300]
        for case in withheld["cases"]
    )
    assert Counter(case["cohort_group"] for case in withheld["cases"]) == {
        "suspicious": 12,
        "control": 6,
    }


def test_round_two_orchestration_requires_canonical_production_workspace(
    tmp_path: Path,
):
    workspace = _round_two_workspace(tmp_path)

    with pytest.raises(ValueError, match="canonical production workspace"):
        round_two_module.prepare_round_two_review(workspace, seed=7)

    assert not (workspace / "round_2_review_bundle").exists()
    assert not (workspace / "round_2_selection_withheld.json").exists()


def test_round_two_publication_refuses_nonempty_bundle(tmp_path: Path):
    workspace = _round_two_workspace(tmp_path)
    bundle = workspace / "round_2_review_bundle"
    bundle.mkdir()
    marker = bundle / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="non-empty"):
        round_two_module.prepare_round_two_review(
            workspace, seed=7, roots=_workspace_roots(workspace)
        )

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (workspace / "round_2_selection_withheld.json").exists()


def test_round_two_publication_refuses_existing_withheld_manifest(tmp_path: Path):
    workspace = _round_two_workspace(tmp_path)
    withheld = workspace / "round_2_selection_withheld.json"
    withheld.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="withheld"):
        round_two_module.prepare_round_two_review(
            workspace, seed=7, roots=_workspace_roots(workspace)
        )

    assert withheld.read_text(encoding="utf-8") == "keep"
    assert not (workspace / "round_2_review_bundle").exists()


def test_round_two_hash_failure_leaves_no_published_artifacts(tmp_path: Path):
    workspace = _round_two_workspace(tmp_path, bad_hash=True)

    with pytest.raises(ValueError, match="SHA-256"):
        round_two_module.prepare_round_two_review(
            workspace, seed=7, roots=_workspace_roots(workspace)
        )

    assert not (workspace / "round_2_review_bundle").exists()
    assert not (workspace / "round_2_selection_withheld.json").exists()
    assert not list(workspace.glob(".round_2_review_bundle-*"))
    assert not list(workspace.glob(".round_2_selection_withheld.json.*"))


def test_finalize_round_two_refuses_unresolved_bundle(tmp_path: Path):
    workspace = _round_two_workspace(tmp_path)
    roots = _workspace_roots(workspace)
    published = round_two_module.prepare_round_two_review(
        workspace, seed=7, roots=roots
    )
    cases_path = published.bundle_dir / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows[:-1]:
        row["label"] = "reviewed_no_change"
    _write_review_rows(cases_path, rows)

    with pytest.raises(ValueError, match="unresolved"):
        round_two_module.finalize_round_two_review(workspace, roots=roots)

    assert not (workspace / "round_2_review_outcomes.json").exists()
    assert not (workspace / "round_2_review_comparison.md").exists()


def test_finalize_round_two_requires_canonical_production_workspace(tmp_path: Path):
    workspace = _round_two_workspace(tmp_path)
    round_two_module.prepare_round_two_review(
        workspace, seed=7, roots=_workspace_roots(workspace)
    )

    with pytest.raises(ValueError, match="canonical production workspace"):
        round_two_module.finalize_round_two_review(workspace)


def test_finalize_round_two_requires_exactly_eighteen_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    withheld_path = workspace / "round_2_selection_withheld.json"
    withheld = json.loads(withheld_path.read_text(encoding="utf-8"))
    removed = withheld["cases"].pop()
    withheld["case_count"] = 17
    withheld_path.write_text(json.dumps(withheld), encoding="utf-8")
    cases_path = workspace / "round_2_review_bundle" / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["source_run_dir"] != removed["case_id"]
        ]
    _write_review_rows(cases_path, rows)

    with pytest.raises(ValueError, match="exactly 18"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


def test_finalize_round_two_revalidates_withheld_quota_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    withheld_path = workspace / "round_2_selection_withheld.json"
    withheld = json.loads(withheld_path.read_text(encoding="utf-8"))
    case = next(
        item
        for item in withheld["cases"]
        if item["cohort_group"] == "suspicious" and item["ladder"] == "LIZ"
    )
    case["cohort_group"] = "control"
    withheld_path.write_text(json.dumps(withheld), encoding="utf-8")

    with pytest.raises(ValueError, match="quota"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


@pytest.mark.parametrize("field", ("content_sha256", "physical_run_key"))
def test_finalize_round_two_rejects_duplicate_hashes_and_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    withheld_path = workspace / "round_2_selection_withheld.json"
    withheld = json.loads(withheld_path.read_text(encoding="utf-8"))
    withheld["cases"][1][field] = withheld["cases"][0][field]
    withheld_path.write_text(json.dumps(withheld), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


def test_finalize_round_two_treats_physical_run_keys_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    withheld_path = workspace / "round_2_selection_withheld.json"
    withheld = json.loads(withheld_path.read_text(encoding="utf-8"))
    withheld["cases"][0]["physical_run_key"] = "2024_DATA/Run-A"
    withheld["cases"][1]["physical_run_key"] = "2024_data/run-a"
    withheld_path.write_text(json.dumps(withheld), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


@pytest.mark.parametrize(
    ("failure_mode", "message"),
    (
        ("outside", "contained"),
        ("missing", "exist"),
        ("changed", "SHA-256"),
    ),
)
def test_finalize_round_two_rehashes_contained_bundle_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    message: str,
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    withheld_path = workspace / "round_2_selection_withheld.json"
    withheld = json.loads(withheld_path.read_text(encoding="utf-8"))
    case = withheld["cases"][1]
    cases_path = workspace / "round_2_review_bundle" / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next(item for item in rows if item["source_run_dir"] == case["case_id"])
    copied_path = Path(row["full_path"])
    if failure_mode == "outside":
        outside = tmp_path / "outside-copy.fsa"
        outside.write_bytes(copied_path.read_bytes())
        row["full_path"] = str(outside)
        case["copied_path"] = str(outside)
        _write_review_rows(cases_path, rows)
        withheld_path.write_text(json.dumps(withheld), encoding="utf-8")
    elif failure_mode == "missing":
        copied_path.unlink()
    else:
        copied_path.write_bytes(b"changed after selection")

    with pytest.raises(ValueError, match=message):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


@pytest.mark.parametrize(
    ("failure_mode", "message"),
    (
        ("partial", "full contiguous"),
        ("noncontiguous", "full contiguous"),
        ("nonincreasing", "strictly increasing"),
    ),
)
def test_finalize_round_two_requires_complete_ordered_manual_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    message: str,
):
    workspace, manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    expected_count = 16 if manual_row["ladder"] == "LIZ" else 21
    count = 3 if failure_mode == "partial" else expected_count
    step_indices = list(range(count))
    if failure_mode == "noncontiguous":
        step_indices[-1] = expected_count
    observed_times = [float(100 + 10 * index) for index in range(count)]
    if failure_mode == "nonincreasing":
        observed_times[2] = observed_times[1]
    payload = {
        "selected_peaks": [
            {"step_index": step, "observed_time": observed}
            for step, observed in zip(step_indices, observed_times)
        ],
        "validation": {"save_verified": True},
    }
    database = workspace / "round_2_review_bundle" / "ladder_adjustments.sqlite3"
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(database))
    save_ladder_adjustment_record(
        Path(manual_row["full_path"]),
        payload,
        ladder=("LIZ500_250" if manual_row["ladder"] == "LIZ" else "ROX400HD"),
    )

    with pytest.raises(ValueError, match=message):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


@pytest.mark.parametrize("contradiction", ("adjustment_path", "database"))
def test_finalize_round_two_rejects_exclusion_with_adjustment_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contradiction: str,
):
    workspace, _manual_row, excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    cases_path = workspace / "round_2_review_bundle" / "ladder_review_cases.csv"
    if contradiction == "adjustment_path":
        with cases_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        row = next(
            item
            for item in rows
            if item["source_run_dir"] == excluded_row["source_run_dir"]
        )
        row["adjustment_path"] = str(cases_path.parent / "contradiction.sqlite3")
        _write_review_rows(cases_path, rows)
    else:
        database = cases_path.parent / "ladder_adjustments.sqlite3"
        monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(database))
        save_ladder_adjustment_record(
            Path(excluded_row["full_path"]),
            {"selected_peaks": [], "validation": {"save_verified": True}},
            ladder=(
                "LIZ500_250" if excluded_row["ladder"] == "LIZ" else "ROX400HD"
            ),
        )

    with pytest.raises(ValueError, match="excluded.*adjustment"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


@pytest.mark.parametrize("field", ("label_note", "reviewed_at_utc"))
def test_finalize_round_two_requires_exclusion_note_and_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
):
    workspace, _manual_row, excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    cases_path = workspace / "round_2_review_bundle" / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next(
        item
        for item in rows
        if item["source_run_dir"] == excluded_row["source_run_dir"]
    )
    row[field] = ""
    _write_review_rows(cases_path, rows)

    with pytest.raises(ValueError, match="note and review timestamp"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


def test_finalize_round_two_rejects_no_change_with_adjustment_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, manual_row, excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    cases_path = workspace / "round_2_review_bundle" / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next(
        item
        for item in rows
        if item["source_run_dir"]
        not in {manual_row["source_run_dir"], excluded_row["source_run_dir"]}
    )
    database = cases_path.parent / "ladder_adjustments.sqlite3"
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(database))
    save_ladder_adjustment_record(
        Path(row["full_path"]),
        {"selected_peaks": [], "validation": {"save_verified": True}},
        ladder=("LIZ500_250" if row["ladder"] == "LIZ" else "ROX400HD"),
    )

    with pytest.raises(ValueError, match="reviewed_no_change.*adjustment"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


def test_round_two_comparison_escapes_markdown_table_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    withheld_path = workspace / "round_2_selection_withheld.json"
    withheld = json.loads(withheld_path.read_text(encoding="utf-8"))
    case = withheld["cases"][0]
    case["assay"] = "A|B\nC"
    case["reason_signature"] = "reason|tick`\nnext"
    withheld_path.write_text(json.dumps(withheld), encoding="utf-8")
    cases_path = workspace / "round_2_review_bundle" / "ladder_review_cases.csv"
    with cases_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next(item for item in rows if item["source_run_dir"] == case["case_id"])
    row["assay"] = case["assay"]
    _write_review_rows(cases_path, rows)

    result = round_two_module.finalize_round_two_review(
        workspace, roots=_workspace_roots(workspace)
    )

    comparison = result.comparison_path.read_text(encoding="utf-8")
    assert "A\\|B<br>C" in comparison
    assert "reason\\|tick\\`<br>next" in comparison


def test_finalize_round_two_uses_label_specific_review_anchors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, manual_row, excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )

    result = round_two_module.finalize_round_two_review(
        workspace, roots=_workspace_roots(workspace)
    )

    payload = json.loads(result.outcomes_path.read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in payload["cases"]}
    manual_case = cases[manual_row["source_run_dir"]]
    excluded_case = cases[excluded_row["source_run_dir"]]
    unchanged_case = next(
        case for case in cases.values() if case["label"] == "reviewed_no_change"
    )

    expected_count = 16 if manual_row["ladder"] == "LIZ" else 21
    assert len(manual_case["review_scan_indices"]) == expected_count
    assert manual_case["review_scan_indices"][:3] == [101.0, 198.0, 305.0]
    assert [item["delta_scan"] for item in manual_case["anchor_deltas"][:3]] == [
        1.0,
        -2.0,
        5.0,
    ]
    assert unchanged_case["review_scan_indices"] == [100.0, 200.0, 300.0]
    assert [item["delta_scan"] for item in unchanged_case["anchor_deltas"]] == [
        0.0,
        0.0,
        0.0,
    ]
    assert excluded_case["review_scan_indices"] == []
    assert excluded_case["anchor_deltas"] == []
    assert excluded_case["fitting_evaluation_eligible"] is False
    assert excluded_case["ml_eligible"] is False


def test_finalize_round_two_ignores_newer_wrong_ladder_record_in_bundle_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    bundle_database = (
        workspace / "round_2_review_bundle" / "ladder_adjustments.sqlite3"
    )
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(bundle_database))
    wrong_ladder = "ROX400HD" if manual_row["ladder"] == "LIZ" else "LIZ500_250"
    save_ladder_adjustment_record(
        Path(manual_row["full_path"]),
        {
            "selected_peaks": [{"step_index": 0, "observed_time": 999.0}],
            "review": {"saved_at_utc": "2027-01-01T00:00:00+00:00"},
            "validation": {"save_verified": True},
        },
        ladder=wrong_ladder,
    )

    result = round_two_module.finalize_round_two_review(
        workspace, roots=_workspace_roots(workspace)
    )

    payload = json.loads(result.outcomes_path.read_text(encoding="utf-8"))
    manual_case = next(
        case for case in payload["cases"] if case["label"] == "manual_adjusted"
    )
    expected_count = 16 if manual_row["ladder"] == "LIZ" else 21
    assert len(manual_case["review_scan_indices"]) == expected_count
    assert manual_case["review_scan_indices"][:3] == [101.0, 198.0, 305.0]


def test_finalize_round_two_excludes_missing_ladder_from_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )

    result = round_two_module.finalize_round_two_review(
        workspace, roots=_workspace_roots(workspace)
    )

    assert result.total_count == 18
    assert result.excluded_count == 1
    assert result.fitting_evaluation_count == 17
    assert result.ml_eligible_count == 17
    payload = json.loads(result.outcomes_path.read_text(encoding="utf-8"))
    assert payload["counts"]["by_cohort_group"] == {
        "control": 6,
        "suspicious": 12,
    }
    comparison = result.comparison_path.read_text(encoding="utf-8")
    assert "Blind cohort group" in comparison
    assert "suspicious" in comparison
    assert "control" in comparison


def test_finalize_round_two_rejects_unverified_manual_selected_peaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    workspace, manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB",
        str(workspace / "round_2_review_bundle" / "ladder_adjustments.sqlite3"),
    )
    save_ladder_adjustment_record(
        Path(manual_row["full_path"]),
        {
            "selected_peaks": [
                {"step_index": 0, "observed_time": 111.0},
                {"step_index": 1, "observed_time": 222.0},
            ],
            "validation": {"save_verified": False},
        },
        ladder=("LIZ500_250" if manual_row["ladder"] == "LIZ" else "ROX400HD"),
    )

    with pytest.raises(ValueError, match="verified selected_peaks"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )


@pytest.mark.parametrize("preexisting", (False, True))
def test_finalize_round_two_rolls_back_both_outputs_when_second_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preexisting: bool,
):
    workspace, _manual_row, _excluded_row = _resolved_round_two_workspace(
        tmp_path, monkeypatch
    )
    outcomes_path = workspace / "round_2_review_outcomes.json"
    comparison_path = workspace / "round_2_review_comparison.md"
    prior_outcomes = b"prior outcomes\r\n\x00"
    prior_comparison = b"prior comparison\r\n\x00"
    if preexisting:
        outcomes_path.write_bytes(prior_outcomes)
        comparison_path.write_bytes(prior_comparison)
    real_replace = round_two_module.os.replace
    failed_once = False

    def fail_second_publication(source: Path, destination: Path) -> None:
        nonlocal failed_once
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            not failed_once
            and destination_path == comparison_path
            and source_path.suffix == ".tmp"
        ):
            failed_once = True
            raise OSError("injected second publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(round_two_module.os, "replace", fail_second_publication)

    with pytest.raises(OSError, match="injected second publication failure"):
        round_two_module.finalize_round_two_review(
            workspace, roots=_workspace_roots(workspace)
        )

    if preexisting:
        assert outcomes_path.read_bytes() == prior_outcomes
        assert comparison_path.read_bytes() == prior_comparison
    else:
        assert not outcomes_path.exists()
        assert not comparison_path.exists()
    assert not list(workspace.glob(".round_2_review_outcomes.json.*"))
    assert not list(workspace.glob(".round_2_review_comparison.md.*"))


def test_finalize_round_two_cli_exposes_workspace_option():
    script = Path(__file__).parents[1] / "scripts" / "build_ladder_research_corpus.py"

    completed = subprocess.run(
        [sys.executable, str(script), "finalize-round-two", "--help"],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--workspace" in completed.stdout


def test_prepare_round_two_cli_exposes_workspace_and_seed_options():
    script = Path(__file__).parents[1] / "scripts" / "build_ladder_research_corpus.py"

    completed = subprocess.run(
        [sys.executable, str(script), "prepare-round-two", "--help"],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--workspace" in completed.stdout
    assert "--seed" in completed.stdout


def test_prepare_review_cli_handler_retains_single_json_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    bundle = SimpleNamespace(
        bundle_dir=tmp_path / "development_review_bundle",
        case_count=3,
        adjustment_database=tmp_path / "ladder_adjustments.sqlite3",
    )
    monkeypatch.setattr(
        research_cli, "_production_roots_from_manifest", lambda _path: object()
    )
    monkeypatch.setattr(
        research_cli, "prepare_development_review_bundle", lambda *_args: bundle
    )

    research_cli._prepare_review_command(SimpleNamespace(workspace=tmp_path))

    assert json.loads(capsys.readouterr().out) == {
        "bundle_dir": str(bundle.bundle_dir),
        "case_count": 3,
        "adjustment_database": str(bundle.adjustment_database),
    }


def test_prepare_round_two_cli_handler_emits_one_json_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    bundle = SimpleNamespace(
        bundle_dir=tmp_path / "round_2_review_bundle",
        case_count=18,
        adjustment_database=tmp_path / "ladder_adjustments.sqlite3",
        withheld_manifest=tmp_path / "round_2_selection_withheld.json",
    )
    monkeypatch.setattr(
        research_cli, "prepare_round_two_review", lambda *_args, **_kwargs: bundle
    )

    research_cli._prepare_round_two_command(
        SimpleNamespace(workspace=tmp_path, seed=7)
    )

    assert json.loads(capsys.readouterr().out) == {
        "bundle_dir": str(bundle.bundle_dir),
        "case_count": 18,
        "adjustment_database": str(bundle.adjustment_database),
        "withheld_manifest": str(bundle.withheld_manifest),
    }


def test_finalize_round_two_cli_handler_emits_one_json_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    outcome = SimpleNamespace(
        outcomes_path=tmp_path / "round_2_review_outcomes.json",
        comparison_path=tmp_path / "round_2_review_comparison.md",
        total_count=18,
        excluded_count=1,
        fitting_evaluation_count=17,
        ml_eligible_count=17,
    )
    monkeypatch.setattr(
        research_cli, "finalize_round_two_review", lambda _workspace: outcome
    )

    research_cli._finalize_round_two_command(SimpleNamespace(workspace=tmp_path))

    assert json.loads(capsys.readouterr().out) == {
        "outcomes_path": str(outcome.outcomes_path),
        "comparison_path": str(outcome.comparison_path),
        "total_count": 18,
        "excluded_count": 1,
        "fitting_evaluation_count": 17,
        "ml_eligible_count": 17,
    }
