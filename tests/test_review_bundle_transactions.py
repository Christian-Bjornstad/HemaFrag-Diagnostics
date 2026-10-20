from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import pytest

from core.ladder_review_bundle_store import (
    ReviewBundleLockTimeout,
    review_bundle_transaction,
    save_review_bundle,
)
from gui_qt.tabs.tab_batch import TabBatch
from gui_qt.tabs.tab_ladder import _io as ladder_io


FIELDNAMES = ["full_path", "file", "label"]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise


def _annotate_in_process(
    bundle_text: str,
    file_text: str,
    label: str,
    ready,
    hold_seconds: float,
    result_queue,
) -> None:
    from gui_qt.tabs.tab_ladder import _io

    bundle = Path(bundle_text)
    try:
        if hold_seconds:
            original_read = _io._read_bundle_csv

            def delayed_read(cases_path):  # noqa: ANN001
                result = original_read(cases_path)
                ready.set()
                time.sleep(hold_seconds)
                return result

            _io._read_bundle_csv = delayed_read
        else:
            ready.wait(timeout=5)
        _io.save_review_bundle_annotation_worker(
            bundle,
            Path(file_text),
            {
                "label": label,
                "label_note": label,
                "reviewed_at_utc": "2026-09-22T00:00:00+00:00",
                "adjustment_path": "",
            },
        )
        result_queue.put(("ok", label))
    except BaseException as error:
        result_queue.put(("error", repr(error)))


def _annotate_after_release_in_process(
    bundle_text: str,
    file_text: str,
    ready,
    release,
    result_queue,
) -> None:
    from gui_qt.tabs.tab_ladder import _io

    try:
        original_read = _io._read_bundle_csv

        def coordinated_read(cases_path):  # noqa: ANN001
            result = original_read(cases_path)
            ready.set()
            if not release.wait(timeout=10):
                raise TimeoutError("annotation release was not signalled")
            return result

        _io._read_bundle_csv = coordinated_read
        _io.save_review_bundle_annotation_worker(
            Path(bundle_text),
            Path(file_text),
            {
                "label": "reviewed_no_change",
                "label_note": "concurrent annotation",
                "reviewed_at_utc": "2026-09-23T00:00:00+00:00",
                "adjustment_path": "",
            },
        )
        result_queue.put(("annotation", "ok"))
    except BaseException as error:
        result_queue.put(("annotation", repr(error)))


def _relocate_in_process(
    bundle_text: str,
    old_path_text: str,
    new_path_text: str,
    progress_queue,
    operation_complete,
    result_queue,
) -> None:
    from core.analyses.clonality import ladder_review_gate

    reported_progress = False

    def report_progress(stage: str) -> None:
        nonlocal reported_progress
        if not reported_progress:
            progress_queue.put(stage)
            reported_progress = True

    real_transaction = getattr(ladder_review_gate, "review_bundle_transaction", None)
    if real_transaction is not None:

        @contextmanager
        def reporting_transaction(*args, **kwargs):  # noqa: ANN002, ANN003
            report_progress("lock")
            with real_transaction(*args, **kwargs) as recovered:
                yield recovered

        ladder_review_gate.review_bundle_transaction = reporting_transaction

    real_reader = ladder_review_gate.csv.DictReader

    class ReportingReader:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self._reader = real_reader(*args, **kwargs)

        @property
        def fieldnames(self):  # noqa: ANN201
            return self._reader.fieldnames

        def __iter__(self):
            rows = list(self._reader)
            report_progress("read")
            return iter(rows)

    ladder_review_gate.csv.DictReader = ReportingReader
    try:
        ladder_review_gate.relocate_review_case(
            Path(bundle_text),
            Path(old_path_text),
            Path(new_path_text),
        )
        result_queue.put(("relocation", "ok"))
    except BaseException as error:
        result_queue.put(("relocation", repr(error)))
    finally:
        operation_complete.set()


def _write_csv(path: Path, *, label: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "full_path": str(path.parent / "sample.fsa"),
                "file": "sample.fsa",
                "label": label,
            }
        )


def _read_label(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return str(next(csv.DictReader(handle))["label"])


def test_csv_staging_failure_after_header_preserves_existing_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    summary_path = tmp_path / "ladder_review_summary.json"
    _write_csv(cases_path, label="old")
    summary_path.write_text(json.dumps({"state": "old"}), encoding="utf-8")
    original_cases = cases_path.read_bytes()
    original_summary = summary_path.read_bytes()

    real_writer = csv.DictWriter

    class HeaderOnlyWriter(real_writer):
        def writerows(self, rowdicts) -> None:  # noqa: ANN001
            raise OSError("injected failure after CSV header")

    monkeypatch.setattr(
        "core.ladder_review_bundle_store.csv.DictWriter",
        HeaderOnlyWriter,
    )

    with pytest.raises(OSError, match="after CSV header"):
        save_review_bundle(
            cases_path,
            [
                {
                    "full_path": str(tmp_path / "sample.fsa"),
                    "file": "sample.fsa",
                    "label": "new",
                }
            ],
            FIELDNAMES,
            summary_path,
            {"state": "new"},
        )

    assert cases_path.read_bytes() == original_cases
    assert summary_path.read_bytes() == original_summary
    assert not list(tmp_path.glob(".ladder_review_cases.csv.*"))


def test_next_bundle_read_recovers_interruption_after_first_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    summary_path = tmp_path / "ladder_review_summary.json"
    _write_csv(cases_path, label="old")
    summary_path.write_text(json.dumps({"state": "old"}), encoding="utf-8")
    original_cases = cases_path.read_bytes()
    original_summary = summary_path.read_bytes()
    real_replace = os.replace

    class SimulatedProcessStop(BaseException):
        pass

    def stop_before_summary_publish(source, destination):  # noqa: ANN001
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path == summary_path and source_path.suffix == ".staged":
            raise SimulatedProcessStop("process stopped after CSV publish")
        real_replace(source, destination)

    monkeypatch.setattr(
        "core.ladder_review_bundle_store.os.replace",
        stop_before_summary_publish,
    )

    with pytest.raises(SimulatedProcessStop):
        save_review_bundle(
            cases_path,
            [
                {
                    "full_path": str(tmp_path / "sample.fsa"),
                    "file": "sample.fsa",
                    "label": "new",
                }
            ],
            FIELDNAMES,
            summary_path,
            {"state": "new"},
        )

    assert _read_label(cases_path) == "new"
    assert json.loads(summary_path.read_text(encoding="utf-8")) == {"state": "old"}

    monkeypatch.setattr("core.ladder_review_bundle_store.os.replace", real_replace)
    loaded = ladder_io.load_review_bundle_worker(tmp_path)

    assert loaded["rows"][0]["label"] == "old"
    assert cases_path.read_bytes() == original_cases
    assert summary_path.read_bytes() == original_summary
    assert not list(tmp_path.glob(".ladder_review_cases.csv.*"))


def test_corrupt_journal_cannot_touch_unrelated_sibling(tmp_path: Path) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    summary_path = tmp_path / "ladder_review_summary.json"
    victim_path = tmp_path / "unrelated.json"
    _write_csv(cases_path, label="old")
    summary_path.write_text('{"state": "old"}', encoding="utf-8")
    victim_path.write_text('{"keep": true}', encoding="utf-8")
    original_cases = cases_path.read_bytes()
    original_victim = victim_path.read_bytes()
    revision = "a" * 32

    cases_backup = tmp_path / f".{cases_path.name}.{revision}.backup"
    cases_staged = tmp_path / f".{cases_path.name}.{revision}.staged"
    victim_backup = tmp_path / f".{victim_path.name}.{revision}.backup"
    victim_staged = tmp_path / f".{victim_path.name}.{revision}.staged"
    cases_backup.write_bytes(original_cases)
    cases_staged.write_bytes(original_cases)
    victim_backup.write_text('{"attacker": true}', encoding="utf-8")
    victim_staged.write_text('{"new": true}', encoding="utf-8")
    journal_path = tmp_path / ".ladder_review_cases.csv.transaction.json"
    journal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "entries": [
                    {
                        "target": str(cases_path.resolve()),
                        "staged": str(cases_staged.resolve()),
                        "backup": str(cases_backup.resolve()),
                        "existed": True,
                        "old_sha256": _sha256_bytes(original_cases),
                        "new_sha256": _sha256_bytes(original_cases),
                    },
                    {
                        "target": str(victim_path.resolve()),
                        "staged": str(victim_staged.resolve()),
                        "backup": str(victim_backup.resolve()),
                        "existed": True,
                        "old_sha256": _sha256_bytes(victim_backup.read_bytes()),
                        "new_sha256": _sha256_bytes(victim_staged.read_bytes()),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="companion|target"):
        ladder_io.load_review_bundle_worker(tmp_path)

    assert cases_path.read_bytes() == original_cases
    assert victim_path.read_bytes() == original_victim


def test_corrupt_journal_rejects_invalid_hash_before_recovery(tmp_path: Path) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    revision = "b" * 32
    backup = tmp_path / f".{cases_path.name}.{revision}.backup"
    staged = tmp_path / f".{cases_path.name}.{revision}.staged"
    backup.write_bytes(cases_path.read_bytes())
    staged.write_bytes(cases_path.read_bytes())
    (tmp_path / ".ladder_review_cases.csv.transaction.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "entries": [
                    {
                        "target": str(cases_path.resolve()),
                        "staged": str(staged.resolve()),
                        "backup": str(backup.resolve()),
                        "existed": True,
                        "old_sha256": "not-a-sha256",
                        "new_sha256": _sha256_bytes(staged.read_bytes()),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="SHA-256"):
        ladder_io.load_review_bundle_worker(tmp_path)

    assert _read_label(cases_path) == "old"


def test_corrupt_journal_rejects_artifact_not_tied_to_target_revision(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    original_cases = cases_path.read_bytes()
    revision = "c" * 32
    backup = tmp_path / f".{cases_path.name}.{revision}.backup"
    wrong_staged = tmp_path / f".different-target.{revision}.staged"
    backup.write_bytes(original_cases)
    wrong_staged.write_bytes(original_cases)
    (tmp_path / ".ladder_review_cases.csv.transaction.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "entries": [
                    {
                        "target": str(cases_path.resolve()),
                        "staged": str(wrong_staged.resolve()),
                        "backup": str(backup.resolve()),
                        "existed": True,
                        "old_sha256": _sha256_bytes(original_cases),
                        "new_sha256": _sha256_bytes(original_cases),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="artifact names"):
        ladder_io.load_review_bundle_worker(tmp_path)

    assert cases_path.read_bytes() == original_cases


def test_corrupt_journal_rejects_duplicate_targets(tmp_path: Path) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    original_cases = cases_path.read_bytes()
    revision = "d" * 32
    backup = tmp_path / f".{cases_path.name}.{revision}.backup"
    staged = tmp_path / f".{cases_path.name}.{revision}.staged"
    backup.write_bytes(original_cases)
    staged.write_bytes(original_cases)
    entry = {
        "target": str(cases_path.resolve()),
        "staged": str(staged.resolve()),
        "backup": str(backup.resolve()),
        "existed": True,
        "old_sha256": _sha256_bytes(original_cases),
        "new_sha256": _sha256_bytes(original_cases),
    }
    (tmp_path / ".ladder_review_cases.csv.transaction.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "entries": [entry, dict(entry)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="distinct"):
        ladder_io.load_review_bundle_worker(tmp_path)

    assert cases_path.read_bytes() == original_cases


def test_recovery_rejects_companion_symlink_without_touching_outside_file(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    outside = tmp_path / "outside"
    bundle.mkdir()
    outside.mkdir()
    cases_path = bundle / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    original_cases = cases_path.read_bytes()
    outside_summary = outside / "ladder_review_annotations.json"
    outside_summary.write_text('{"outside": true}', encoding="utf-8")
    original_outside = outside_summary.read_bytes()
    companion = bundle / "ladder_review_annotations.json"
    _symlink_or_skip(companion, outside_summary)
    revision = "e" * 32

    cases_backup = bundle / f".{cases_path.name}.{revision}.backup"
    cases_staged = bundle / f".{cases_path.name}.{revision}.staged"
    companion_backup = bundle / f".{companion.name}.{revision}.backup"
    companion_staged = bundle / f".{companion.name}.{revision}.staged"
    cases_backup.write_bytes(original_cases)
    cases_staged.write_bytes(original_cases)
    companion_backup.write_bytes(original_outside)
    companion_staged.write_bytes(b'{"new": true}')
    (bundle / ".ladder_review_cases.csv.transaction.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "entries": [
                    {
                        "target": str(cases_path.absolute()),
                        "staged": str(cases_staged.absolute()),
                        "backup": str(cases_backup.absolute()),
                        "existed": True,
                        "old_sha256": _sha256_bytes(original_cases),
                        "new_sha256": _sha256_bytes(original_cases),
                    },
                    {
                        "target": str(companion.absolute()),
                        "staged": str(companion_staged.absolute()),
                        "backup": str(companion_backup.absolute()),
                        "existed": True,
                        "old_sha256": _sha256_bytes(original_outside),
                        "new_sha256": _sha256_bytes(companion_staged.read_bytes()),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="link|reparse"):
        ladder_io.load_review_bundle_worker(bundle)

    assert cases_path.read_bytes() == original_cases
    assert outside_summary.read_bytes() == original_outside


def test_recovery_rejects_linked_backup_without_touching_outside_file(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    original_cases = cases_path.read_bytes()
    outside = tmp_path / "outside-backup.csv"
    outside.write_bytes(b"outside must survive")
    original_outside = outside.read_bytes()
    revision = "f" * 32
    backup = tmp_path / f".{cases_path.name}.{revision}.backup"
    staged = tmp_path / f".{cases_path.name}.{revision}.staged"
    _symlink_or_skip(backup, outside)
    staged.write_bytes(original_cases)
    (tmp_path / ".ladder_review_cases.csv.transaction.json").write_text(
        json.dumps(
            {
                "version": 1,
                "revision": revision,
                "entries": [
                    {
                        "target": str(cases_path.absolute()),
                        "staged": str(staged.absolute()),
                        "backup": str(backup.absolute()),
                        "existed": True,
                        "old_sha256": _sha256_bytes(original_outside),
                        "new_sha256": _sha256_bytes(original_cases),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="link|reparse"):
        ladder_io.load_review_bundle_worker(tmp_path)

    assert cases_path.read_bytes() == original_cases
    assert outside.read_bytes() == original_outside


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_process_lock_rejects_links_without_writing_outside_file(
    tmp_path: Path,
    link_kind: str,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    outside = tmp_path / "outside-lock.txt"
    outside.write_bytes(b"outside lock sentinel")
    original_outside = outside.read_bytes()
    lock_path = tmp_path / ".ladder_review_bundle.lock"
    if link_kind == "symlink":
        _symlink_or_skip(lock_path, outside)
    else:
        os.link(outside, lock_path)

    with pytest.raises(RuntimeError, match="lock.*link|link.*lock|reparse"):
        with review_bundle_transaction(cases_path, timeout_seconds=0.1):
            pass

    assert outside.read_bytes() == original_outside


def test_two_process_annotations_are_serialized_without_lost_updates(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    first_fsa = tmp_path / "first.fsa"
    second_fsa = tmp_path / "second.fsa"
    for source in (first_fsa, second_fsa):
        source.write_bytes(b"trace")
    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(
            [
                {"full_path": str(first_fsa), "file": first_fsa.name, "label": ""},
                {"full_path": str(second_fsa), "file": second_fsa.name, "label": ""},
            ]
        )

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    results = context.Queue()
    first = context.Process(
        target=_annotate_in_process,
        args=(str(tmp_path), str(first_fsa), "reviewed_no_change", ready, 0.5, results),
    )
    second = context.Process(
        target=_annotate_in_process,
        args=(str(tmp_path), str(second_fsa), "manual_adjusted", ready, 0.0, results),
    )
    first.start()
    assert ready.wait(timeout=10)
    second.start()
    first.join(timeout=15)
    second.join(timeout=15)

    assert first.exitcode == 0
    assert second.exitcode == 0
    process_results = sorted(results.get(timeout=2) for _ in range(2))
    results.close()
    results.join_thread()
    first.close()
    second.close()
    assert process_results == [
        ("ok", "manual_adjusted"),
        ("ok", "reviewed_no_change"),
    ]
    with cases_path.open("r", encoding="utf-8", newline="") as handle:
        rows = {row["file"]: row for row in csv.DictReader(handle)}
    annotations = json.loads(
        (tmp_path / "ladder_review_annotations.json").read_text(encoding="utf-8")
    )
    assert rows[first_fsa.name]["label"] == "reviewed_no_change"
    assert rows[second_fsa.name]["label"] == "manual_adjusted"
    assert set(annotations) == {str(first_fsa), str(second_fsa)}
    assert not (tmp_path / ".ladder_review_cases.csv.transaction.json").exists()


def test_relocation_and_annotation_are_serialized_without_lost_updates(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    relocated_source = tmp_path / "relocate-me.fsa"
    relocated_target = tmp_path / "relocated.fsa"
    annotated_source = tmp_path / "annotate-me.fsa"
    for source in (relocated_source, relocated_target, annotated_source):
        source.write_bytes(b"trace")
    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "full_path": str(relocated_source),
                    "file": relocated_source.name,
                    "label": "",
                },
                {
                    "full_path": str(annotated_source),
                    "file": annotated_source.name,
                    "label": "",
                },
            ]
        )

    context = multiprocessing.get_context("spawn")
    annotation_read = context.Event()
    release_annotation = context.Event()
    relocation_complete = context.Event()
    relocation_progress = context.Queue()
    results = context.Queue()
    annotation = context.Process(
        target=_annotate_after_release_in_process,
        args=(
            str(tmp_path),
            str(annotated_source),
            annotation_read,
            release_annotation,
            results,
        ),
    )
    relocation = context.Process(
        target=_relocate_in_process,
        args=(
            str(tmp_path),
            str(relocated_source),
            str(relocated_target),
            relocation_progress,
            relocation_complete,
            results,
        ),
    )

    annotation.start()
    assert annotation_read.wait(timeout=10)
    relocation.start()
    relocation_stage = relocation_progress.get(timeout=10)
    if relocation_stage == "read":
        assert relocation_complete.wait(timeout=10)
    else:
        assert relocation_stage == "lock"
    release_annotation.set()
    annotation.join(timeout=15)
    relocation.join(timeout=15)

    assert annotation.exitcode == 0
    assert relocation.exitcode == 0
    process_results = sorted(results.get(timeout=2) for _ in range(2))
    relocation_progress.close()
    relocation_progress.join_thread()
    results.close()
    results.join_thread()
    annotation.close()
    relocation.close()
    assert process_results == [("annotation", "ok"), ("relocation", "ok")]

    with cases_path.open("r", encoding="utf-8", newline="") as handle:
        rows = {row["file"]: row for row in csv.DictReader(handle)}
    assert rows[relocated_source.name]["full_path"] == relocated_target.as_posix()
    assert rows[annotated_source.name]["label"] == "reviewed_no_change"
    annotations = json.loads(
        (tmp_path / "ladder_review_annotations.json").read_text(encoding="utf-8")
    )
    relocations = json.loads(
        (tmp_path / "ladder_review_relocations.json").read_text(encoding="utf-8")
    )
    assert str(annotated_source) in annotations
    assert relocations[relocated_source.as_posix()]["new_path"] == relocated_target.as_posix()
    assert not (tmp_path / ".ladder_review_cases.csv.transaction.json").exists()


def test_relocation_audit_publication_failure_rolls_back_csv_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.analyses.clonality.ladder_review_gate import relocate_review_case

    cases_path = tmp_path / "ladder_review_cases.csv"
    source = tmp_path / "source.fsa"
    target = tmp_path / "target.fsa"
    _write_csv(cases_path, label="")
    with cases_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["full_path"] = str(source)
    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    relocations_path = tmp_path / "ladder_review_relocations.json"
    relocations_path.write_text(
        json.dumps({"sentinel": {"new_path": "keep"}}),
        encoding="utf-8",
    )
    original_cases = cases_path.read_bytes()
    original_relocations = relocations_path.read_bytes()
    real_replace = os.replace

    def fail_audit_publish(source_path, destination_path):  # noqa: ANN001
        if Path(destination_path) == relocations_path and str(source_path).endswith(
            ".staged"
        ):
            raise OSError("injected relocation audit publication failure")
        real_replace(source_path, destination_path)

    monkeypatch.setattr(
        "core.ladder_review_bundle_store.os.replace",
        fail_audit_publish,
    )

    with pytest.raises(OSError, match="relocation audit publication"):
        relocate_review_case(tmp_path, source, target)

    assert cases_path.read_bytes() == original_cases
    assert relocations_path.read_bytes() == original_relocations
    assert not (tmp_path / ".ladder_review_cases.csv.transaction.json").exists()
    assert not list(tmp_path.glob(".ladder_review_*.staged"))
    assert not list(tmp_path.glob(".ladder_review_*.backup"))


def test_corrupt_relocation_audit_fails_without_modifying_bundle(
    tmp_path: Path,
) -> None:
    from core.analyses.clonality.ladder_review_gate import relocate_review_case

    cases_path = tmp_path / "ladder_review_cases.csv"
    source = tmp_path / "source.fsa"
    target = tmp_path / "target.fsa"
    _write_csv(cases_path, label="")
    with cases_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["full_path"] = str(source)
    with cases_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    relocations_path = tmp_path / "ladder_review_relocations.json"
    relocations_path.write_bytes(b"{not valid json")
    original_cases = cases_path.read_bytes()
    original_relocations = relocations_path.read_bytes()

    with pytest.raises(RuntimeError, match="read relocation audit"):
        relocate_review_case(tmp_path, source, target)

    assert cases_path.read_bytes() == original_cases
    assert relocations_path.read_bytes() == original_relocations
    assert not (tmp_path / ".ladder_review_cases.csv.transaction.json").exists()


def test_process_lock_timeout_is_bounded_and_clear(tmp_path: Path) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="old")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    results = context.Queue()
    holder = context.Process(
        target=_annotate_in_process,
        args=(str(tmp_path), str(tmp_path / "sample.fsa"), "held", ready, 0.5, results),
    )
    holder.start()
    assert ready.wait(timeout=10)

    started = time.monotonic()
    with pytest.raises(ReviewBundleLockTimeout, match="within 0.1 seconds"):
        with review_bundle_transaction(cases_path, timeout_seconds=0.1):
            pass
    elapsed = time.monotonic() - started

    holder.join(timeout=15)
    assert holder.exitcode == 0
    assert results.get(timeout=2) == ("ok", "held")
    results.close()
    results.join_thread()
    holder.close()
    assert elapsed < 1.0


def test_run_carry_propagates_bundle_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    summary_path = tmp_path / "ladder_review_summary.json"
    _write_csv(cases_path, label="")
    summary_path.write_text(json.dumps({"review_case_count": 1}), encoding="utf-8")
    fsa_path = tmp_path / "sample.fsa"
    cache_key = str(TabBatch._resolve_cache_key(fsa_path))
    gate = {
        "cases_path": str(cases_path),
        "summary_path": str(summary_path),
        "review_case_count": 1,
    }
    original_cases = cases_path.read_bytes()
    original_summary = summary_path.read_bytes()

    def fail_save(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise OSError("injected summary publication failure")

    monkeypatch.setattr(
        "gui_qt.tabs.tab_batch._legacy.save_review_bundle",
        fail_save,
        raising=False,
    )

    with pytest.raises(OSError, match="summary publication"):
        TabBatch._carry_resolved_labels_to_gate(
            gate,
            {
                cache_key: {
                    "label": "reviewed_no_change",
                    "label_note": "checked",
                    "reviewed_at_utc": "2026-09-22T00:00:00+00:00",
                    "adjustment_path": "",
                }
            },
        )

    assert gate["review_case_count"] == 1
    assert "resolved_carried_from_previous_review" not in gate
    assert cases_path.read_bytes() == original_cases
    assert summary_path.read_bytes() == original_summary


def test_ladder_annotation_propagates_bundle_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases_path = tmp_path / "ladder_review_cases.csv"
    _write_csv(cases_path, label="")
    fsa_path = tmp_path / "sample.fsa"

    def fail_save(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise OSError("injected annotation publication failure")

    monkeypatch.setattr(ladder_io, "save_review_bundle", fail_save, raising=False)

    with pytest.raises(OSError, match="annotation publication"):
        ladder_io.save_review_bundle_annotation_worker(
            tmp_path,
            fsa_path,
            {
                "label": "reviewed_no_change",
                "label_note": "checked",
                "reviewed_at_utc": "2026-09-22T00:00:00+00:00",
                "adjustment_path": "",
            },
        )
