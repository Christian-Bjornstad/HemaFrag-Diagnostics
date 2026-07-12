"""Plan 13 / Phase C tests - trainer --annotations-jsonl merge."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.train_clonality_interpretation_models import (
    _load_annotations_jsonl,
)


class TestLoadAnnotationsJsonl:
    def test_returns_records_by_assay_and_total(self, tmp_path):
        jsonl = tmp_path / "x.jsonl"
        jsonl.write_text(
            json.dumps({
                "dit": "24OUM20364", "assay": "FR1",
                "annotation_class": "monoklonal"
            }) + "\n"
            + json.dumps({
                "dit": "25OUM99999", "assay": "TCRbA",
                "annotation_class": "polyklonal"
            }) + "\n"
            + json.dumps({
                "dit": "26OUM00001", "assay": "FR1",
                "annotation_class": ""  # blank
            }) + "\n",
            encoding="utf-8",
        )
        records, by_assay, total = _load_annotations_jsonl(jsonl)
        assert len(records) == 2
        assert total == 3
        assert by_assay == {"FR1": 1, "TCRbA": 1}

    def test_missing_file_returns_empty(self, tmp_path):
        records, by_assay, total = _load_annotations_jsonl(tmp_path / "missing.jsonl")
        assert records == []
        assert by_assay == {}
        assert total == 0

    def test_none_path_returns_empty(self):
        records, by_assay, total = _load_annotations_jsonl(None)
        assert records == []
        assert by_assay == {}
        assert total == 0

    def test_skips_malformed_lines(self, tmp_path):
        jsonl = tmp_path / "x.jsonl"
        jsonl.write_text(
            "this is not json\n"
            + "[1, 2, 3]\n"
            + json.dumps({"assay": "FR1", "annotation_class": "monoklonal"}) + "\n",
            encoding="utf-8",
        )
        records, by_assay, total = _load_annotations_jsonl(jsonl)
        # Only the last valid record counts (no dit but assay+class ok)
        assert total == 1
        assert len(records) == 1


class TestTrainerMainArgAdded:
    def test_argparse_accepts_annotations_jsonl(self):
        """Smoke check: the new flag exists and is optional."""
        import sys
        # Avoid heavy imports by parsing in-process with a stub
        from scripts.train_clonality_interpretation_models import _parse_args
        # We can't run main() without real xlsx, but we CAN parse args.
        args = _parse_args([
            "--xls", "D:/tmp.xlsx",  # path doesn't have to exist for parsing
            "--annotations-jsonl", "D:/tmp.jsonl",
        ])
        assert args.annotations_jsonl == Path("D:/tmp.jsonl")

        # Default -> None
        args2 = _parse_args(["--xls", "D:/tmp.xlsx"])
        assert args2.annotations_jsonl is None
