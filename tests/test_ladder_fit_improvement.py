from __future__ import annotations

import random
from collections import Counter

import pytest

from core.research.ladder.fit_improvement import (
    DEVELOPMENT_QUOTAS,
    VALIDATION_QUOTAS,
    select_fit_improvement_waves,
)


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
            ("validation", "control", "LIZ"): 40,
            ("validation", "control", "ROX"): 9,
            ("validation", "suspicious", "LIZ"): 5,
            ("validation", "suspicious", "ROX"): 6,
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
