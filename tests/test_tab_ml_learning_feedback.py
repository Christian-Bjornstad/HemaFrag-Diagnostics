"""Plan 13 / Phase C tests - JSONL feedback loop + dedup."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui_qt.tabs.tab_ml_learning._feedback import (
    annotations_summary,
    feedback_paths,
    harvest_to_records,
    import_one,
    import_id_for,
    load_jsonl_records,
    record_dedupe_key,
)


# ---- harvest -------------------------------------------------------------


def _example_record(cls="monoklonal", raw_path="/x/foo.fsa"):
    return {
        "raw_path": raw_path,
        "file": "foo.fsa",
        "assay": "FR1",
        "dit": "24OUM20364",
        "annotation_class": cls,
        "control_flag": "",
        "note": "single dominant peak",
        "annotated_at_utc": "2026-07-12T20:00:00+00:00",
        "schema_version": 1,
    }


class TestHarvest:
    def test_skips_blank_class(self):
        records = harvest_to_records([
            {"annotation_class": "", "raw_path": "/x"},
            _example_record("polyklonal"),
        ])
        assert len(records) == 1
        assert records[0]["annotation_class"] == "polyklonal"

    def test_stamps_when_no_annotated_at(self):
        records = harvest_to_records([_example_record()])
        rec = records[0]
        assert rec["annotated_at_utc"]  # auto-stamped
        assert rec["schema_version"] == 1

    def test_only_keeps_trainer_relevant_fields(self):
        records = harvest_to_records([_example_record()])
        record = records[0]
        assert "annotation_class" in record
        assert "control_flag" in record
        assert "dit" in record
        # Make sure we don't leak decorative fields
        assert "dominated_x_label" not in record


class TestRecordDedupeKey:
    def test_stable_for_same_raw_and_time(self):
        rec = _example_record()
        k1 = record_dedupe_key(rec)
        k2 = record_dedupe_key(dict(rec))
        assert k1 == k2

    def test_different_raw_paths_different_keys(self):
        a = record_dedupe_key(_example_record(raw_path="/x/a.fsa"))
        b = record_dedupe_key(_example_record(raw_path="/x/b.fsa"))
        assert a != b

    def test_different_times_different_keys(self):
        a = _example_record()
        a["annotated_at_utc"] = "2026-07-12T10:00:00Z"
        b = _example_record()
        b["annotated_at_utc"] = "2026-07-12T20:00:00Z"
        assert record_dedupe_key(a) != record_dedupe_key(b)


# ---- import flow --------------------------------------------------------


class TestImportOne:
    def _paths(self, root):
        p = feedback_paths(root)
        p["imports_dir"].parent.mkdir(parents=True, exist_ok=True)
        return p

    def test_first_write_persists_records(self, tmp_path):
        paths = self._paths(tmp_path)
        payload = [_example_record("monoklonal"), _example_record("polyklonal", "/x/b.fsa")]
        src = tmp_path / "exp1.json"
        src.write_text(json.dumps(payload), encoding="utf-8")

        counts = import_one(source_path=src, payload=payload, paths=paths)
        assert counts["imported"] == 2
        assert counts["skipped"] == 0

        records = load_jsonl_records(paths["annotations_jsonl"])
        assert len(records) == 2
        assert records[0]["annotation_class"] in ("monoklonal", "polyklonal")

    def test_repeat_import_idempotent(self, tmp_path):
        paths = self._paths(tmp_path)
        payload = [_example_record()]
        src = tmp_path / "exp1.json"
        src.write_text(json.dumps(payload), encoding="utf-8")

        # First import
        import_one(source_path=src, payload=payload, paths=paths)
        # Second import same file
        counts2 = import_one(source_path=src, payload=payload, paths=paths)
        # Manifest dedupes by import_id (file content fingerprint).
        # All rows reported as skipped because we already saw this source.
        assert counts2["imported"] == 0
        assert counts2["skipped"] == 1

        records = load_jsonl_records(paths["annotations_jsonl"])
        assert len(records) == 1

    def test_skips_blank_class_in_payload(self, tmp_path):
        paths = self._paths(tmp_path)
        payload = [
            _example_record(),                  # OK
            {**_example_record(), "annotation_class": ""},  # blank
        ]
        src = tmp_path / "x.json"
        src.write_text(json.dumps(payload), encoding="utf-8")
        counts = import_one(source_path=src, payload=payload, paths=paths)
        assert counts["imported"] == 1
        assert counts["total"] == 2

    def test_empty_payload_no_row_written(self, tmp_path):
        paths = self._paths(tmp_path)
        src = tmp_path / "x.json"
        src.write_text("[]", encoding="utf-8")
        counts = import_one(source_path=src, payload=[], paths=paths)
        assert counts["imported"] == 0
        # Manifest tracks the empty import (so a re-import still skips it)
        assert paths["imports_manifest"].exists() is True
        # The annotations jsonl is left empty (or absent) - no records
        if paths["annotations_jsonl"].exists():
            assert load_jsonl_records(paths["annotations_jsonl"]) == []


class TestLoadJsonlRecords:
    def test_reads_round_trip_records(self, tmp_path):
        path = tmp_path / "x.jsonl"
        path.write_text(
            json.dumps(_example_record()) + "\n"
            + json.dumps(_example_record("polyklonal", "/y.fsa")) + "\n",
            encoding="utf-8",
        )
        out = load_jsonl_records(path)
        assert len(out) == 2

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "x.jsonl"
        path.write_text("[not json]\n" + "[1, 2]\n", encoding="utf-8")
        out = load_jsonl_records(path)
        assert out == []  # both lines fail (not dicts / not JSON)

    def test_missing_returns_empty(self, tmp_path):
        assert load_jsonl_records(tmp_path / "missing.jsonl") == []


class TestAnnotationsSummary:
    def test_counts_per_assay_and_per_class(self):
        recs = [
            _example_record("monoklonal"),
            {**_example_record("polyklonal", "/x/b.fsa"), "assay": "TCRbA"},
            {**_example_record("usikker_review", "/x/c.fsa"), "assay": "TCRbA"},
        ]
        s = annotations_summary(recs)
        assert s["total"] == 3
        assert s["by_class"]["monoklonal"] == 1
        assert s["by_class"]["polyklonal"] == 1
        assert s["by_assay"]["FR1"] == 1
        assert s["by_assay"]["TCRbA"] == 2


def test_import_id_for_stable():
    a = import_id_for(Path("/x/exp1.json"), [{"a": 1}])
    b = import_id_for(Path("/x/exp1.json"), [{"a": 1}])
    assert a == b


def test_feedback_paths_layout(tmp_path):
    p = feedback_paths(tmp_path)
    assert p["imports_dir"] == tmp_path / "imports"
    assert p["imports_manifest"] == tmp_path / "imports" / "_imported.jsonl"
    assert p["annotations_jsonl"] == tmp_path / "annotations" / "learning.jsonl"
