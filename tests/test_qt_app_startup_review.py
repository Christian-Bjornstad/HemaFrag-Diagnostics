from __future__ import annotations

import os
from pathlib import Path

import pytest

from qt_app import configure_review_bundle_adjustment_store, parse_startup_options


def test_parse_startup_review_bundle_removes_custom_args_from_qt_argv(tmp_path: Path):
    (tmp_path / "ladder_review_cases.csv").write_text(
        "full_path,label\n", encoding="utf-8"
    )

    options = parse_startup_options(
        ["qt_app.py", "--ladder-review-bundle", str(tmp_path), "-style", "Fusion"]
    )

    assert options.review_bundle == tmp_path.resolve()
    assert options.qt_argv == ("qt_app.py", "-style", "Fusion")


def test_parse_startup_review_bundle_requires_existing_cases_csv(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="ladder_review_cases.csv"):
        parse_startup_options(["qt_app.py", "--ladder-review-bundle", str(tmp_path)])


def test_parse_startup_review_bundle_requires_an_argument():
    with pytest.raises(ValueError, match="requires a directory"):
        parse_startup_options(["qt_app.py", "--ladder-review-bundle"])


def test_review_bundle_startup_overrides_decoy_adjustment_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "ladder_review_cases.csv").write_text(
        "full_path,label\n", encoding="utf-8"
    )
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB",
        str(tmp_path.parent / "decoy-default" / "ladder_adjustments.sqlite3"),
    )
    options = parse_startup_options(
        ["qt_app.py", "--ladder-review-bundle", str(tmp_path)]
    )

    configured = configure_review_bundle_adjustment_store(options)

    expected = (tmp_path / "ladder_adjustments.sqlite3").resolve()
    assert configured == expected
    assert Path(os.environ["HEMAFRAG_LADDER_ADJUSTMENT_DB"]).resolve() == expected
    assert not expected.exists()
