from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

import core.tracking_workbook_io as tracking_workbook_io
from core.tracking_workbook_io import (
    publish_workbook_contents,
    upsert_frame,
    write_tracking_frames,
)


@pytest.mark.parametrize("missing_value", [None, float("nan"), pd.NA])
def test_upsert_clears_missing_generated_values_without_touching_falsy_values_or_user_formulas(
    missing_value,
):
    workbook = Workbook()
    upsert_frame(
        workbook,
        "Runs",
        pd.DataFrame([{"ID": "A", "Value": 42, "Zero": 1, "Flag": True}]),
        key_columns=["ID"],
    )
    sheet = workbook["Runs"]
    sheet["E1"] = "UserFormula"
    sheet["E2"] = "=B2+C2"

    upsert_frame(
        workbook,
        "Runs",
        pd.DataFrame(
            [{"ID": "A", "Value": missing_value, "Zero": 0, "Flag": False}]
        ),
        key_columns=["ID"],
    )

    assert sheet["B2"].value is None
    assert sheet["C2"].value == 0
    assert sheet["D2"].value is False
    assert sheet["E2"].value == "=B2+C2"


def test_tracking_rows_upsert_and_extend_user_formula_columns(tmp_path):
    path = tmp_path / "tracking.xlsx"
    first = pd.DataFrame(
        [{"IdentityKey": "one", "Value": 2}]
    )
    write_tracking_frames(path, (("Runs", first, ("IdentityKey",)),))

    workbook = load_workbook(path)
    sheet = workbook["Runs"]
    sheet.cell(1, 3, "DoubleValue")
    sheet.cell(2, 3, "=B2*2")
    workbook.save(path)
    workbook.close()

    updated = pd.DataFrame(
        [
            {"IdentityKey": "one", "Value": 3},
            {"IdentityKey": "two", "Value": 5},
        ]
    )
    write_tracking_frames(path, (("Runs", updated, ("IdentityKey",)),))

    workbook = load_workbook(path, data_only=False)
    sheet = workbook["Runs"]
    assert sheet["B2"].value == 3
    assert sheet["C2"].value == "=B2*2"
    assert sheet["B3"].value == 5
    assert sheet["C3"].value == "=B3*2"
    assert list(sheet.tables.values())[0].ref == "A1:C3"
    workbook.close()


def test_publish_replace_permission_error_preserves_original_and_cleans_staging(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "tracking.xlsx"
    original = b"old workbook bytes"
    destination.write_bytes(original)
    staged = tmp_path / ".tracking.staged.xlsx"
    staged.write_bytes(b"new workbook bytes")

    def fail_replace(_source, _target):
        raise PermissionError("destination is locked")

    monkeypatch.setattr(tracking_workbook_io, "_IS_WINDOWS", False, raising=False)
    monkeypatch.setattr("core.tracking_workbook_io.os.replace", fail_replace)

    with pytest.raises(PermissionError, match="locked"):
        publish_workbook_contents(staged, destination)

    assert destination.read_bytes() == original
    assert not staged.exists()


def test_publish_successfully_replaces_existing_workbook_and_cleans_staging(tmp_path):
    destination = tmp_path / "tracking.xlsx"
    destination.write_bytes(b"old workbook bytes")
    staged = tmp_path / ".tracking.staged.xlsx"
    replacement = b"new workbook bytes"
    staged.write_bytes(replacement)

    publish_workbook_contents(staged, destination)

    assert destination.read_bytes() == replacement
    assert not staged.exists()


def test_publish_fsync_failure_happens_before_replace_and_preserves_original(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "tracking.xlsx"
    original = b"old workbook bytes"
    destination.write_bytes(original)
    staged = tmp_path / ".tracking.staged.xlsx"
    staged.write_bytes(b"new workbook bytes")
    replace_called = False

    def fail_fsync(_descriptor):
        raise OSError("injected fsync failure")

    def record_replace(_source, _target):
        nonlocal replace_called
        replace_called = True

    monkeypatch.setattr("core.tracking_workbook_io.os.fsync", fail_fsync)
    monkeypatch.setattr("core.tracking_workbook_io.os.replace", record_replace)

    with pytest.raises(OSError, match="fsync failure"):
        publish_workbook_contents(staged, destination)

    assert destination.read_bytes() == original
    assert replace_called is False
    assert not staged.exists()


def test_publish_posix_syncs_file_then_replacement_then_parent_directory(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "tracking.xlsx"
    destination.write_bytes(b"old workbook bytes")
    staged = tmp_path / ".tracking.staged.xlsx"
    staged.write_bytes(b"new workbook bytes")
    events = []
    directory_descriptor = 9876
    real_replace = tracking_workbook_io.os.replace

    def record_fsync(descriptor):
        events.append(
            "directory fsync" if descriptor == directory_descriptor else "file fsync"
        )

    def record_replace(source, target):
        events.append("replace")
        real_replace(source, target)

    def record_directory_open(path, flags):
        events.append(("directory open", Path(path), flags))
        return directory_descriptor

    def record_directory_close(descriptor):
        events.append(("directory close", descriptor))

    monkeypatch.setattr(tracking_workbook_io, "_IS_WINDOWS", False, raising=False)
    monkeypatch.setattr(tracking_workbook_io.os, "fsync", record_fsync)
    monkeypatch.setattr(tracking_workbook_io.os, "replace", record_replace)
    monkeypatch.setattr(tracking_workbook_io.os, "open", record_directory_open)
    monkeypatch.setattr(tracking_workbook_io.os, "close", record_directory_close)

    publish_workbook_contents(staged, destination)

    assert events == [
        "file fsync",
        "replace",
        (
            "directory open",
            tmp_path,
            tracking_workbook_io.os.O_RDONLY
            | getattr(tracking_workbook_io.os, "O_DIRECTORY", 0),
        ),
        "directory fsync",
        ("directory close", directory_descriptor),
    ]
    assert destination.read_bytes() == b"new workbook bytes"


def test_publish_parent_directory_fsync_failure_is_reported_after_replace(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "tracking.xlsx"
    destination.write_bytes(b"old workbook bytes")
    staged = tmp_path / ".tracking.staged.xlsx"
    replacement = b"new workbook bytes"
    staged.write_bytes(replacement)
    directory_descriptor = 9876
    fsync_count = 0
    closed_descriptors = []

    def fail_second_fsync(descriptor):
        nonlocal fsync_count
        fsync_count += 1
        if descriptor == directory_descriptor:
            raise OSError("injected parent directory fsync failure")

    monkeypatch.setattr(tracking_workbook_io, "_IS_WINDOWS", False, raising=False)
    monkeypatch.setattr(tracking_workbook_io.os, "fsync", fail_second_fsync)
    monkeypatch.setattr(
        tracking_workbook_io.os,
        "open",
        lambda _path, _flags: directory_descriptor,
    )
    monkeypatch.setattr(
        tracking_workbook_io.os,
        "close",
        lambda descriptor: closed_descriptors.append(descriptor),
    )

    with pytest.raises(OSError, match="parent directory fsync failure"):
        publish_workbook_contents(staged, destination)

    assert fsync_count == 2
    assert closed_descriptors == [directory_descriptor]
    assert destination.read_bytes() == replacement
    assert not staged.exists()


def test_publish_windows_requests_atomic_write_through_replacement(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "tracking.xlsx"
    destination.write_bytes(b"old workbook bytes")
    staged = tmp_path / ".tracking.staged.xlsx"
    staged.write_bytes(b"new workbook bytes")
    calls = []

    class FakeMoveFileEx:
        argtypes = None
        restype = None

        def __call__(self, source, target, flags):
            calls.append((source, target, flags))
            tracking_workbook_io.os.replace(source, target)
            return 1

    fake_move_file_ex = FakeMoveFileEx()

    class FakeKernel32:
        MoveFileExW = fake_move_file_ex

    class FakeCtypes:
        c_wchar_p = object()
        c_uint32 = object()
        c_int = object()

        @staticmethod
        def WinDLL(name, *, use_last_error):
            assert (name, use_last_error) == ("kernel32", True)
            return FakeKernel32()

    monkeypatch.setattr(tracking_workbook_io, "_IS_WINDOWS", True, raising=False)
    monkeypatch.setattr(tracking_workbook_io, "ctypes", FakeCtypes, raising=False)

    publish_workbook_contents(staged, destination)

    assert calls == [(str(staged), str(destination), 0x1 | 0x8)]
    assert destination.read_bytes() == b"new workbook bytes"
    assert not staged.exists()


def test_publish_windows_replace_failure_preserves_original_without_fallback(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "tracking.xlsx"
    original = b"old workbook bytes"
    destination.write_bytes(original)
    staged = tmp_path / ".tracking.staged.xlsx"
    staged.write_bytes(b"new workbook bytes")

    class FailingMoveFileEx:
        argtypes = None
        restype = None

        def __call__(self, _source, _target, _flags):
            return 0

    class FakeKernel32:
        MoveFileExW = FailingMoveFileEx()

    class FakeCtypes:
        c_wchar_p = object()
        c_uint32 = object()
        c_int = object()

        @staticmethod
        def WinDLL(_name, *, use_last_error):
            assert use_last_error is True
            return FakeKernel32()

        @staticmethod
        def get_last_error():
            return 5

        @staticmethod
        def WinError(error_code):
            assert error_code == 5
            return PermissionError("destination is locked")

    monkeypatch.setattr(tracking_workbook_io, "_IS_WINDOWS", True)
    monkeypatch.setattr(tracking_workbook_io, "ctypes", FakeCtypes)
    monkeypatch.setattr(
        tracking_workbook_io.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("must not fall back to direct replacement")
        ),
    )

    with pytest.raises(PermissionError, match="locked"):
        publish_workbook_contents(staged, destination)

    assert destination.read_bytes() == original
    assert not staged.exists()


def test_publish_rejects_staging_path_that_is_destination(tmp_path):
    workbook_path = tmp_path / "tracking.xlsx"
    original = b"only good workbook"
    workbook_path.write_bytes(original)

    with pytest.raises(ValueError, match="must differ"):
        publish_workbook_contents(workbook_path, workbook_path)

    assert workbook_path.read_bytes() == original
