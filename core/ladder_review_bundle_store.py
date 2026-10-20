"""Crash-recoverable publication for ladder review bundle metadata.

The CSV and its optional JSON companion are one logical revision.  A save
stages and fsyncs both files, copies the last committed files to revisioned
backups, and publishes a journal containing the old/new content hashes before
replacing either target.  Removing the journal is the commit point.

If a process stops while the journal exists, the next bundle read/save restores
the previous complete revision.  A save that returned successfully therefore
always published the whole requested revision; an interrupted save is never
mistaken for a completed one.
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
from typing import Any
from uuid import uuid4


_JOURNAL_VERSION = 1
_LOGGER = logging.getLogger(__name__)
_WRITE_LOCK = threading.RLock()
_LOCK_STATE = threading.local()
_REVISION_PATTERN = re.compile(r"[0-9a-f]{32}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ALLOWED_COMPANION_NAMES = frozenset(
    {
        "ladder_review_summary.json",
        "ladder_review_annotations.json",
        "ladder_review_relocations.json",
    }
)
_DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0


class ReviewBundleLockTimeout(TimeoutError):
    """Raised when another process owns a review bundle for too long."""


def _lexical_file_path(path: Path | str) -> Path:
    """Resolve the parent directory without following the final component."""

    candidate = Path(path).expanduser()
    if candidate.name in {"", ".", ".."}:
        raise RuntimeError("Review bundle file path has no safe final component")
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.parent.resolve() / candidate.name


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _is_reparse_point(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _validate_regular_single_link(
    path: Path,
    purpose: str,
    *,
    allow_missing: bool,
) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise RuntimeError(f"{purpose} is missing: {path}") from None
    if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
        raise RuntimeError(f"{purpose} must not be a symlink or reparse point: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{purpose} must be a regular file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"{purpose} must not have multiple hard links: {path}")
    return metadata


def _validate_open_fd_identity(path: Path, descriptor: int, purpose: str) -> None:
    path_metadata = _validate_regular_single_link(
        path,
        purpose,
        allow_missing=False,
    )
    descriptor_metadata = os.fstat(descriptor)
    if not stat.S_ISREG(descriptor_metadata.st_mode):
        raise RuntimeError(f"{purpose} descriptor is not a regular file: {path}")
    if descriptor_metadata.st_nlink != 1:
        raise RuntimeError(f"{purpose} descriptor has multiple hard links: {path}")
    if path_metadata is None or not os.path.samestat(path_metadata, descriptor_metadata):
        raise RuntimeError(f"{purpose} changed while it was being opened: {path}")


def _open_validated_descriptor(
    path: Path,
    flags: int,
    purpose: str,
    *,
    allow_missing: bool,
    mode: int = 0o666,
) -> int:
    """Open one basename without following it where the platform permits."""

    _validate_regular_single_link(path, purpose, allow_missing=allow_missing)
    safe_flags = flags
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        safe_flags |= getattr(os, flag_name, 0)
    try:
        descriptor = os.open(path, safe_flags, mode)
    except OSError:
        if _path_entry_exists(path):
            _validate_regular_single_link(path, purpose, allow_missing=False)
        raise
    try:
        _validate_open_fd_identity(path, descriptor, purpose)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@contextmanager
def _open_existing_binary(path: Path, purpose: str):
    descriptor = _open_validated_descriptor(
        path,
        os.O_RDONLY,
        purpose,
        allow_missing=False,
    )
    with os.fdopen(descriptor, "rb") as handle:
        yield handle


@contextmanager
def _create_exclusive_text(
    path: Path,
    purpose: str,
    *,
    newline: str | None = None,
):
    descriptor = _open_validated_descriptor(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        purpose,
        allow_missing=True,
    )
    with os.fdopen(
        descriptor,
        "w",
        encoding="utf-8",
        newline=newline,
    ) as handle:
        yield handle


def _safe_unlink(path: Path, purpose: str) -> None:
    if not _path_entry_exists(path):
        return
    _validate_regular_single_link(path, purpose, allow_missing=False)
    path.unlink()


def _journal_path(cases_path: Path) -> Path:
    return cases_path.with_name(f".{cases_path.name}.transaction.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _open_existing_binary(path, "Review bundle hash input") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    """Persist directory metadata on platforms that expose directory fds."""

    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact_path(target: Path, revision: str, kind: str) -> Path:
    return target.with_name(f".{target.name}.{revision}.{kind}")


def _write_csv_staging(
    target: Path,
    revision: str,
    rows: list[dict],
    fieldnames: list[str],
) -> Path:
    staged = _artifact_path(target, revision, "staged")
    created = False
    try:
        with _create_exclusive_text(
            staged,
            "Review bundle CSV staging artifact",
            newline="",
        ) as handle:
            created = True
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        return staged
    except BaseException:
        if created:
            _safe_unlink(staged, "Review bundle CSV staging artifact")
        raise


def _write_json_staging(target: Path, revision: str, value: dict) -> Path:
    staged = _artifact_path(target, revision, "staged")
    created = False
    try:
        with _create_exclusive_text(
            staged,
            "Review bundle JSON staging artifact",
        ) as handle:
            created = True
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        return staged
    except BaseException:
        if created:
            _safe_unlink(staged, "Review bundle JSON staging artifact")
        raise


def _write_journal(path: Path, value: dict, revision: str) -> None:
    staged = _artifact_path(path, revision, "staged")
    created = False
    try:
        with _create_exclusive_text(
            staged,
            "Review bundle journal staging artifact",
        ) as handle:
            created = True
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        if _path_entry_exists(path):
            _validate_regular_single_link(
                path,
                "Review bundle transaction journal",
                allow_missing=False,
            )
            raise RuntimeError(f"Review bundle transaction journal already exists: {path}")
        _validate_regular_single_link(
            staged,
            "Review bundle journal staging artifact",
            allow_missing=False,
        )
        os.replace(staged, path)
        created = False
        _fsync_directory(path.parent)
    finally:
        if created:
            _safe_unlink(staged, "Review bundle journal staging artifact")


def _lock_file_path(cases_path: Path) -> Path:
    return cases_path.with_name(".ladder_review_bundle.lock")


def _try_lock_file(handle) -> None:  # noqa: ANN001
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:  # noqa: ANN001
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _interprocess_bundle_lock(
    cases_path: Path,
    *,
    timeout_seconds: float,
):
    timeout = max(0.0, float(timeout_seconds))
    lock_path = _lock_file_path(cases_path)
    descriptor = _open_validated_descriptor(
        lock_path,
        os.O_RDWR | os.O_CREAT,
        "Review bundle lock file",
        allow_missing=True,
    )
    handle = os.fdopen(descriptor, "r+b")
    acquired = False
    try:
        _validate_open_fd_identity(lock_path, handle.fileno(), "Review bundle lock file")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())

        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock_file(handle)
                acquired = True
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise ReviewBundleLockTimeout(
                        "Could not lock review bundle within "
                        f"{timeout:g} seconds: {cases_path}"
                    ) from error
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            _unlock_file(handle)
        handle.close()


@contextmanager
def review_bundle_transaction(
    cases_path: Path,
    *,
    timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
):
    """Serialize one bundle's full read/mutate/publish operation.

    The lock is process-wide and re-entrant in the owning thread.  Recovery is
    completed while the lock is held before the caller can read bundle state.
    The yielded boolean reports whether an interrupted revision was recovered.
    """

    canonical_cases = _lexical_file_path(cases_path)
    key = os.path.normcase(str(canonical_cases))
    _validate_regular_single_link(
        canonical_cases,
        "Review bundle CSV target",
        allow_missing=True,
    )
    with _WRITE_LOCK:
        active = getattr(_LOCK_STATE, "active", None)
        if active is None:
            active = {}
            _LOCK_STATE.active = active
        if key in active:
            active[key] += 1
            try:
                yield False
            finally:
                active[key] -= 1
            return

        with _interprocess_bundle_lock(
            canonical_cases,
            timeout_seconds=timeout_seconds,
        ):
            active[key] = 1
            try:
                recovered = _recover_review_bundle_locked(canonical_cases)
                yield recovered
            finally:
                active.pop(key, None)


def _validated_journal_entries(cases_path: Path, journal: dict) -> list[dict[str, Any]]:
    if journal.get("version") != _JOURNAL_VERSION:
        raise RuntimeError("Unsupported review bundle transaction journal")
    revision = str(journal.get("revision") or "")
    entries = journal.get("entries")
    if not _REVISION_PATTERN.fullmatch(revision):
        raise RuntimeError("Invalid review bundle transaction revision")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 2:
        raise RuntimeError("Invalid review bundle transaction journal")

    expected_parent = cases_path.parent.resolve()
    canonical_cases = _lexical_file_path(cases_path)
    allowed_companions = {
        expected_parent / name for name in _ALLOWED_COMPANION_NAMES
    }
    validated: list[dict[str, Any]] = []
    seen_targets: set[Path] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise RuntimeError("Invalid review bundle transaction entry")
        entry = dict(raw_entry)
        target = _lexical_file_path(str(entry.get("target") or ""))
        staged = _lexical_file_path(str(entry.get("staged") or ""))
        backup = _lexical_file_path(str(entry.get("backup") or ""))
        if target in seen_targets:
            raise RuntimeError("Review bundle transaction targets must be distinct")
        seen_targets.add(target)
        if index == 0 and target != canonical_cases:
            raise RuntimeError("Review bundle transaction does not target its canonical CSV")
        if index == 1 and target not in allowed_companions:
            raise RuntimeError("Review bundle transaction has an unpermitted JSON companion target")

        expected_staged = _artifact_path(target, revision, "staged")
        expected_backup = _artifact_path(target, revision, "backup")
        if staged != expected_staged or backup != expected_backup:
            raise RuntimeError(
                "Review bundle transaction artifact names do not match their target revision"
            )

        existed = entry.get("existed")
        old_sha256 = entry.get("old_sha256")
        new_sha256 = entry.get("new_sha256")
        if not isinstance(existed, bool):
            raise RuntimeError("Review bundle transaction existence flag is invalid")
        if not isinstance(new_sha256, str) or not _SHA256_PATTERN.fullmatch(new_sha256):
            raise RuntimeError("Review bundle transaction has an invalid new SHA-256")
        if existed:
            if not isinstance(old_sha256, str) or not _SHA256_PATTERN.fullmatch(old_sha256):
                raise RuntimeError("Review bundle transaction has an invalid old SHA-256")
        elif old_sha256 != "":
            raise RuntimeError("Review bundle transaction has an invalid absent-file SHA-256")
        _validate_regular_single_link(
            target,
            "Review bundle transaction target",
            allow_missing=True,
        )
        _validate_regular_single_link(
            staged,
            "Review bundle transaction staging artifact",
            allow_missing=True,
        )
        _validate_regular_single_link(
            backup,
            "Review bundle transaction backup artifact",
            allow_missing=True,
        )
        entry.update({"target": target, "staged": staged, "backup": backup})
        validated.append(entry)
    return validated


def _recover_review_bundle_locked(cases_path: Path) -> bool:
    journal_path = _journal_path(cases_path)
    journal_metadata = _validate_regular_single_link(
        journal_path,
        "Review bundle transaction journal",
        allow_missing=True,
    )
    if journal_metadata is None:
        return False

    try:
        with _open_existing_binary(
            journal_path,
            "Review bundle transaction journal",
        ) as handle:
            journal = json.load(handle)
    except Exception as error:
        raise RuntimeError("Could not read review bundle transaction journal") from error
    if not isinstance(journal, dict):
        raise RuntimeError("Review bundle transaction journal must be an object")
    entries = _validated_journal_entries(cases_path, journal)

    for entry in entries:
        target: Path = entry["target"]
        backup: Path = entry["backup"]
        existed = entry["existed"]
        old_sha256 = entry["old_sha256"]
        if existed:
            if _path_entry_exists(backup):
                if _sha256(backup) != old_sha256:
                    raise RuntimeError("Review bundle rollback backup failed integrity validation")
                _validate_regular_single_link(
                    target,
                    "Review bundle transaction target",
                    allow_missing=True,
                )
                _validate_regular_single_link(
                    backup,
                    "Review bundle transaction backup artifact",
                    allow_missing=False,
                )
                os.replace(backup, target)
            elif not _path_entry_exists(target) or _sha256(target) != old_sha256:
                raise RuntimeError("Review bundle rollback backup is missing")
        else:
            _safe_unlink(target, "Review bundle transaction target")

    _fsync_directory(cases_path.parent)
    for entry in entries:
        _safe_unlink(entry["staged"], "Review bundle transaction staging artifact")
        _safe_unlink(entry["backup"], "Review bundle transaction backup artifact")
    _safe_unlink(journal_path, "Review bundle transaction journal")
    _fsync_directory(cases_path.parent)
    return True


def save_review_bundle(
    cases_path: Path,
    rows: list[dict],
    fieldnames: list[str],
    summary_path: Path | None,
    summary: dict,
) -> None:
    """Publish one complete review CSV/JSON revision or raise.

    ``summary_path=None`` publishes a CSV-only revision through the same
    crash-recovery protocol.  The optional JSON companion can be a bundle
    summary, Ladder annotation map, or relocation audit; both files are
    committed as one revision.
    """

    cases_path = _lexical_file_path(cases_path)
    resolved_summary = (
        _lexical_file_path(summary_path) if summary_path is not None else None
    )
    if resolved_summary is not None and resolved_summary.parent != cases_path.parent:
        raise ValueError("Review bundle CSV and JSON companion must share a directory")
    if (
        resolved_summary is not None
        and resolved_summary.name not in _ALLOWED_COMPANION_NAMES
    ):
        raise ValueError("Review bundle JSON companion name is not permitted")

    with review_bundle_transaction(cases_path):
        _save_review_bundle_locked(
            cases_path,
            rows,
            fieldnames,
            resolved_summary,
            summary,
        )


def _save_review_bundle_locked(
    cases_path: Path,
    rows: list[dict],
    fieldnames: list[str],
    summary_path: Path | None,
    summary: dict,
) -> None:
    revision = uuid4().hex
    journal_path = _journal_path(cases_path)
    staged_paths: list[Path] = []
    backup_paths: list[Path] = []
    entries: list[dict[str, Any]] = []
    journal_published = False
    committed = False

    try:
        _validate_regular_single_link(
            cases_path,
            "Review bundle CSV target",
            allow_missing=True,
        )
        if summary_path is not None:
            _validate_regular_single_link(
                summary_path,
                "Review bundle JSON target",
                allow_missing=True,
            )
        csv_staged = _write_csv_staging(
            cases_path,
            revision,
            list(rows),
            list(fieldnames),
        )
        staged_paths.append(csv_staged)
        targets: list[tuple[Path, Path]] = [(cases_path, csv_staged)]
        if summary_path is not None:
            summary_staged = _write_json_staging(
                summary_path,
                revision,
                dict(summary),
            )
            staged_paths.append(summary_staged)
            targets.append((summary_path, summary_staged))

        for target, staged in targets:
            target_metadata = _validate_regular_single_link(
                target,
                "Review bundle publication target",
                allow_missing=True,
            )
            existed = target_metadata is not None
            backup = _artifact_path(target, revision, "backup")
            old_sha256 = ""
            if existed:
                backup_created = False
                try:
                    with _open_existing_binary(
                        target,
                        "Review bundle publication target",
                    ) as source:
                        backup_descriptor = _open_validated_descriptor(
                            backup,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            "Review bundle backup artifact",
                            allow_missing=True,
                        )
                        backup_created = True
                        backup_paths.append(backup)
                        with os.fdopen(backup_descriptor, "wb") as destination:
                            shutil.copyfileobj(source, destination)
                            destination.flush()
                            os.fsync(destination.fileno())
                except BaseException:
                    if backup_created:
                        _safe_unlink(backup, "Review bundle backup artifact")
                    raise
                old_sha256 = _sha256(backup)
            entries.append(
                {
                    "target": str(target),
                    "staged": str(staged),
                    "backup": str(backup),
                    "existed": existed,
                    "old_sha256": old_sha256,
                    "new_sha256": _sha256(staged),
                }
            )

        _write_journal(
            journal_path,
            {
                "version": _JOURNAL_VERSION,
                "revision": revision,
                "entries": entries,
            },
            revision,
        )
        journal_published = True

        for target, staged in targets:
            _validate_regular_single_link(
                target,
                "Review bundle publication target",
                allow_missing=True,
            )
            _validate_regular_single_link(
                staged,
                "Review bundle staging artifact",
                allow_missing=False,
            )
            os.replace(staged, target)
            _fsync_directory(target.parent)

        _safe_unlink(journal_path, "Review bundle transaction journal")
        _fsync_directory(cases_path.parent)
        journal_published = False
        committed = True
    except Exception:
        if journal_published or _path_entry_exists(journal_path):
            try:
                _recover_review_bundle_locked(cases_path)
            except Exception as recovery_error:
                raise RuntimeError(
                    "Review bundle publication failed and rollback could not complete"
                ) from recovery_error
        raise
    finally:
        if not _path_entry_exists(journal_path):
            for artifact in [*staged_paths, *backup_paths]:
                try:
                    _safe_unlink(artifact, "Review bundle transaction artifact")
                except OSError as error:
                    if not committed:
                        raise
                    # The journal is gone and both targets are durable. A
                    # locked backup must not report this completed save as failed.
                    _LOGGER.warning(
                        "Review bundle saved; could not remove artifact %s: %s",
                        artifact,
                        error,
                    )


__all__ = [
    "ReviewBundleLockTimeout",
    "review_bundle_transaction",
    "save_review_bundle",
]
