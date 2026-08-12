from pathlib import Path

import pytest

from core.research.ladder.contracts import (
    INVENTORY_SCHEMA_VERSION,
    LadderOutcome,
    ResearchRoots,
    assert_allowed_raw_path,
    stable_json_fingerprint,
)


def test_default_roots_include_only_allowed_year_directories():
    roots = ResearchRoots.default()

    assert roots.raw_roots == (
        Path(r"D:\DATA\2024_DATA"),
        Path(r"D:\DATA\2025_data"),
        Path(r"D:\DATA\2026_data"),
    )
    assert roots.excluded_backup_root == Path(r"D:\DATA\backup")


def test_backup_path_is_rejected():
    roots = ResearchRoots.default()

    with pytest.raises(ValueError, match="backup"):
        assert_allowed_raw_path(Path(r"D:\DATA\backup\x.fsa"), roots)


def test_allowed_year_path_is_accepted():
    roots = ResearchRoots.default()

    accepted = assert_allowed_raw_path(
        Path(r"D:\DATA\2025_data\run\x.fsa"), roots
    )

    assert accepted == Path(r"D:\DATA\2025_data\run\x.fsa").resolve()


def test_path_outside_allowed_roots_is_rejected():
    roots = ResearchRoots.default()

    with pytest.raises(ValueError, match="allowed raw roots"):
        assert_allowed_raw_path(Path(r"D:\DATA\other\x.fsa"), roots)


def test_fingerprint_is_key_order_independent():
    assert stable_json_fingerprint({"a": 1, "b": 2}) == stable_json_fingerprint(
        {"b": 2, "a": 1}
    )


def test_fingerprint_changes_when_nested_content_changes():
    assert stable_json_fingerprint({"a": [1, 2]}) != stable_json_fingerprint(
        {"a": [1, 3]}
    )


def test_outcome_vocabulary_is_fixed_and_extensible_at_consumers():
    assert {outcome.value for outcome in LadderOutcome} == {
        "missing_ladder_signal",
        "wrong_ladder_or_channel",
        "fit_rejected_with_usable_signal",
        "fit_accepted_but_wrong",
        "fit_correct_review_only",
        "unresolved",
    }
    assert INVENTORY_SCHEMA_VERSION == "1.0"
