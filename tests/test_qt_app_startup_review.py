from __future__ import annotations

from pathlib import Path

import pytest

from qt_app import parse_startup_options


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
