"""Unit tests for `gui_qt.tabs.tab_ladder._summary` + `_io` + `_workers`.

Phase 12.1 — these helpers were extracted from the previously-monolithic
TabLadder class. Each test exercises one helper without spinning up
a QApplication or constructing a TabLadder widget.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.ladder_adjustment_store import (
    load_ladder_adjustment_record,
    save_ladder_adjustment_record,
)

from gui_qt.tabs.tab_ladder._io import (
    build_review_annotation,
    load_review_bundle_worker,
    review_case_paths_from_bundle,
    save_missing_ladder_exclusion_worker,
    save_review_bundle_annotation_worker,
    save_review_bundle_rerun_status_worker,
)
from gui_qt.tabs.tab_ladder._summary import (
    chip_state,
    count_chip_states,
    entry_cache_key,
    entry_original_path,
    format_ladder_confidence_shadow,
    format_file_item,
    manual_adjustment_consumption,
    metadata_from_entry,
    resolve_cache_key,
)
from gui_qt.tabs.tab_ladder._workers import (
    find_report_matches_worker,
    scan_fsa_files_worker,
)


# Same POSIX-on-Windows helper as test_ladder_review_gate.py:
# PurePosixPath routes literal '/tmp/...' strings through str() unchanged on this OS.
def _posix_text(fake_path: str) -> str:
    if sys.platform == "win32":
        return str(PurePosixPath(fake_path))
    return fake_path


class TabLadderSummaryHelperTests(unittest.TestCase):
    """Pure helpers in `_summary.py`."""

    def test_resolve_cache_key_passes_through(self) -> None:
        # Use a relative path so Windows doesn't prefix with a drive.
        p = Path("tmp_xenon_test_42/foo.fsa")
        result = resolve_cache_key(p)
        # str-based comparison that ignores the leading "C:/..." Windows
        # prefix issue: both are resolved via the same mechanism.
        self.assertIsInstance(result, Path)

    def test_manual_adjustment_consumption_requires_successful_manual_entry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            fsa = Path(td) / "sample.fsa"
            fsa.write_bytes(b"trace")
            database = str(Path(td) / "adjustments.sqlite3")
            with patch.dict(
                os.environ,
                {"HEMAFRAG_LADDER_ADJUSTMENT_DB": database},
            ):
                save_ladder_adjustment_record(fsa, {})
                adjustment_hash = str(
                    load_ladder_adjustment_record(fsa)["payload_sha256"]
                )
                result = {
                    "failed_jobs": [],
                    "ladder_review_gate": {"review_case_count": 0},
                    "dit_report_entries": [
                        {
                            "original_file_path": str(fsa),
                            "ladder_fit_strategy": "manual_adjustment",
                            "analysis_provenance": {
                                "ladder_fit_strategy": "manual_adjustment",
                                "manual_adjustment_consumed": True,
                                "manual_adjustment_sha256": adjustment_hash,
                                "source_sha256": "b" * 64,
                            },
                        }
                    ],
                }

                status = manual_adjustment_consumption(result, fsa)

                self.assertTrue(status["consumed"])
                self.assertEqual(status["status"], "consumed")
                self.assertEqual(
                    status["manual_adjustment_sha256"],
                    adjustment_hash,
                )

                result["ladder_review_gate"]["review_case_count"] = 1
                status = manual_adjustment_consumption(result, fsa)
                self.assertFalse(status["consumed"])
                self.assertIn("review", status["reason"].lower())

    def test_format_ladder_confidence_shadow_is_explicitly_read_only(
        self,
    ) -> None:
        text = format_ladder_confidence_shadow(
            {
                "runtime_selected_rank": 1,
                "top1_top2_score_margin": 0.403,
                "stable_under_tested_thresholds": True,
            }
        )

        self.assertIn("Selected rank 1", text)
        self.assertIn("top-2 margin 0.403", text)
        self.assertIn("threshold stable", text)
        self.assertIn("shadow only", text)

    def test_resolve_cache_key_handles_unresolvable(self) -> None:
        # A non-existent file should still resolve via expanduser().
        p = Path("nope_xyz/foo.fsa")
        # Should not raise.
        resolve_cache_key(p)

    def test_entry_original_path_prefers_original_file_path(self) -> None:
        entry = {
            "original_file_path": _posix_text("/first.fsa"),
            "full_path": _posix_text("/second.fsa"),
        }
        self.assertEqual(
            str(entry_original_path(entry)).replace("\\", "/"), "/first.fsa"
        )

    def test_entry_original_path_falls_back_to_fsa(self) -> None:
        fsa = SimpleNamespace(file=_posix_text("/fsa_path.fsa"))
        self.assertEqual(
            str(entry_original_path({"fsa": fsa})).replace("\\", "/"),
            "/fsa_path.fsa",
        )

    def test_entry_original_path_returns_none(self) -> None:
        # No original_file_path, no full_path, no fsa → None.
        self.assertIsNone(entry_original_path({}))

    def test_entry_cache_key_chain(self) -> None:
        entry = {"original_file_path": _posix_text("/a.fsa")}
        self.assertIsNotNone(entry_cache_key(entry))

    def test_entry_cache_key_returns_none_for_missing_entry(self) -> None:
        self.assertIsNone(entry_cache_key({}))

    def test_format_file_item_bare_when_no_case(self) -> None:
        fp = Path(_posix_text("/tmp/abc.fsa"))
        self.assertEqual(format_file_item(fp, None), fp.name)

    def test_format_file_item_rich_when_case_provided(self) -> None:
        fp = Path(_posix_text("/tmp/abc.fsa"))
        case = {
            "assay": "FR1",
            "ladder": "ROX400HD",
            "linear_max": 2.5,
            "linear_r2": 0.9987,
            "ladder_qc": "ok",
        }
        rendered = format_file_item(fp, case)
        self.assertIn("abc.fsa", rendered)
        self.assertIn("FR1", rendered)
        self.assertIn("ROX400HD", rendered)
        self.assertIn("max 2.50", rendered)
        self.assertIn("ok", rendered)

    def test_metadata_from_entry_builds_complete_payload(self) -> None:
        from config import APP_SETTINGS

        previous_analysis = APP_SETTINGS.get("active_analysis")
        APP_SETTINGS["active_analysis"] = "clonality"
        try:
            entry = {
                "assay": "FR1",
                "ladder": "ROX400HD",
                "trace_channels": ["DATA1", "DATA2"],
                "bp_min": 80.0,
                "bp_max": 400.0,
            }
            meta = metadata_from_entry(Path(_posix_text("/p.fsa")), entry)
            self.assertEqual(meta["assay"], "FR1")
            self.assertEqual(meta["ladder"], "ROX400HD")
            self.assertEqual(meta["primary_peak_channel"], "DATA1")
            self.assertEqual(meta["sample_channel"], "DATA1")
            self.assertEqual(meta["trace_channels"], ["DATA1", "DATA2"])
            self.assertEqual(meta["bp_min"], 80.0)
            self.assertEqual(meta["bp_max"], 400.0)
        finally:
            APP_SETTINGS["active_analysis"] = previous_analysis


class TabLadderIOHelperTests(unittest.TestCase):
    """Pure helpers in `_io.py` — bundle CSV load/save plumbing."""

    def _write_csv(self, td, rows):
        cases_path = Path(td) / "ladder_review_cases.csv"
        fieldnames = ["full_path", "file", "label"]
        with cases_path.open("w", encoding="utf-8", newline="") as handle:
            writer = __import__("csv").DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return cases_path

    def test_load_review_bundle_worker_keeps_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(
                td,
                [
                    {"full_path": _posix_text("/missing/path.fsa"), "file": "ghost.fsa", "label": ""},
                    {"full_path": _posix_text(str(Path(td) / "real.fsa")), "file": "real.fsa", "label": ""},
                ],
            )
            # Create the real file so exactly one is reachable.
            real = Path(td) / "real.fsa"
            real.write_bytes(b"x")
            result = load_review_bundle_worker(Path(td))
            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual(len(result["missing_paths"]), 1)

    def test_load_review_bundle_worker_links_existing_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fsa = Path(td) / "real.fsa"
            fsa.write_bytes(b"x")
            self._write_csv(
                td,
                [{"full_path": str(fsa), "file": fsa.name, "label": ""}],
            )
            manifest = Path(td) / "hemafrag_run_test.json"
            manifest.write_text("{}", encoding="utf-8")
            (Path(td) / "ladder_review_summary.json").write_text(
                __import__("json").dumps({"run_manifest_path": str(manifest)}),
                encoding="utf-8",
            )

            result = load_review_bundle_worker(Path(td))

            self.assertEqual(result["run_manifest_path"], manifest)

    def test_load_review_bundle_worker_raises_when_csv_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                load_review_bundle_worker(Path(td))

    def test_review_case_paths_from_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._write_csv(
                td,
                [
                    {"full_path": _posix_text(str(Path(td) / "x.fsa")), "file": "x.fsa", "label": ""},
                ],
            )
            paths = review_case_paths_from_bundle(Path(td))
            self.assertEqual(len(paths), 1)
            self.assertIsInstance(next(iter(paths)), Path)

    def test_review_case_paths_from_bundle_empty_when_no_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(review_case_paths_from_bundle(Path(td)), set())

    def test_save_review_bundle_annotation_worker_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fsa = Path(td) / "x.fsa"
            fsa.write_bytes(b"x")
            self._write_csv(
                td,
                [
                    {"full_path": str(fsa), "file": "x.fsa", "label": ""},
                ],
            )
            annotation = {
                "label": "manual_adjusted",
                "label_note": "fixed in dialog",
                "reviewed_at_utc": "2026-07-08T10:00:00Z",
                "adjustment_path": str(fsa.with_suffix(".ladder_adj.json")),
                "action": "apply",
            }
            returned = save_review_bundle_annotation_worker(
                Path(td), fsa, annotation
            )
            self.assertEqual(returned["label"], "manual_adjusted")

            cases_path = Path(td) / "ladder_review_cases.csv"
            with cases_path.open("r", encoding="utf-8", newline="") as handle:
                reader = __import__("csv").DictReader(handle)
                rows = list(reader)
            self.assertEqual(rows[0]["label"], "manual_adjusted")
            self.assertEqual(rows[0]["label_note"], "fixed in dialog")

            annotations_path = Path(td) / "ladder_review_annotations.json"
            self.assertTrue(annotations_path.exists())

    def test_missing_ladder_annotation_has_no_adjustment_path(self) -> None:
        annotation = build_review_annotation(
            "excluded_missing_ladder_signal",
            "No usable ladder signal; preparation error.",
            reviewed_at_utc="2026-08-10T00:00:00+00:00",
        )

        self.assertEqual(annotation["label"], "excluded_missing_ladder_signal")
        self.assertEqual(annotation["adjustment_path"], "")

    def test_missing_ladder_action_writes_no_adjustment_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "no-ladder.fsa"
            fsa.write_bytes(b"fsa")
            self._write_csv(
                td,
                [{"full_path": str(fsa), "file": fsa.name, "label": ""}],
            )
            isolated_db = bundle / "adjustments.sqlite3"
            with patch.dict(
                os.environ,
                {"HEMAFRAG_LADDER_ADJUSTMENT_DB": str(isolated_db)},
            ):
                saved = save_missing_ladder_exclusion_worker(
                    bundle,
                    fsa,
                    note="No usable ladder signal; preparation error.",
                    reviewed_at_utc="2026-08-10T00:00:00+00:00",
                )

                self.assertEqual(saved["label"], "excluded_missing_ladder_signal")
                self.assertEqual(saved["adjustment_path"], "")
                self.assertIsNone(load_ladder_adjustment_record(fsa))
                self.assertFalse(isolated_db.exists())
                self.assertFalse(fsa.with_suffix(".ladder_adj.json").exists())

    def test_missing_ladder_exclusion_rejects_already_adjusted_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "adjusted.fsa"
            fsa.write_bytes(b"fsa")
            (bundle / "ladder_review_cases.csv").write_text(
                (
                    "full_path,file,label,adjustment_path\n"
                    f"{fsa},{fsa.name},manual_adjusted,{bundle / 'ladder_adjustments.sqlite3'}\n"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unresolved"):
                save_missing_ladder_exclusion_worker(
                    bundle,
                    fsa,
                    note="No usable ladder signal; preparation error.",
                    reviewed_at_utc="2026-08-10T00:00:00+00:00",
                )

    def test_missing_ladder_exclusion_rejects_bundle_local_adjustment_record(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "adjusted.fsa"
            fsa.write_bytes(b"fsa")
            self._write_csv(
                td,
                [{"full_path": str(fsa), "file": fsa.name, "label": ""}],
            )
            bundle_database = bundle / "ladder_adjustments.sqlite3"
            with patch.dict(
                os.environ,
                {"HEMAFRAG_LADDER_ADJUSTMENT_DB": str(bundle_database)},
            ):
                save_ladder_adjustment_record(fsa, {"selected_peaks": []})
            with patch.dict(
                os.environ,
                {
                    "HEMAFRAG_LADDER_ADJUSTMENT_DB": str(
                        bundle / "decoy-default.sqlite3"
                    )
                },
            ):
                with self.assertRaisesRegex(ValueError, "adjustment"):
                    save_missing_ladder_exclusion_worker(
                        bundle,
                        fsa,
                        note="No usable ladder signal; preparation error.",
                        reviewed_at_utc="2026-08-10T00:00:00+00:00",
                    )

    def test_annotation_pair_rolls_back_when_second_publication_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "sample.fsa"
            fsa.write_bytes(b"trace")
            cases_path = self._write_csv(
                td,
                [{"full_path": str(fsa), "file": fsa.name, "label": ""}],
            )
            annotations_path = bundle / "ladder_review_annotations.json"
            annotations_path.write_bytes(b'{"sentinel": true}\r\n')
            original_cases = cases_path.read_bytes()
            original_annotations = annotations_path.read_bytes()
            real_replace = os.replace
            failed_once = False

            def fail_second_publication(source, destination):
                nonlocal failed_once
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    not failed_once
                    and destination_path == annotations_path
                    and source_path.suffix == ".tmp"
                ):
                    failed_once = True
                    raise OSError("injected annotation publication failure")
                real_replace(source, destination)

            with patch(
                "gui_qt.tabs.tab_ladder._io.os.replace",
                side_effect=fail_second_publication,
            ):
                with self.assertRaisesRegex(
                    OSError, "injected annotation publication failure"
                ):
                    save_review_bundle_annotation_worker(
                        bundle,
                        fsa,
                        {
                            "label": "reviewed_no_change",
                            "label_note": "reviewed",
                            "reviewed_at_utc": "2026-08-10T00:00:00+00:00",
                            "adjustment_path": "",
                        },
                    )

            self.assertEqual(cases_path.read_bytes(), original_cases)
            self.assertEqual(annotations_path.read_bytes(), original_annotations)
            self.assertFalse(list(bundle.glob(".*.tmp")))
            self.assertFalse(list(bundle.glob(".*.backup")))

    def test_annotation_pair_preserves_inputs_when_second_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "sample.fsa"
            fsa.write_bytes(b"trace")
            cases_path = self._write_csv(
                td,
                [{"full_path": str(fsa), "file": fsa.name, "label": ""}],
            )
            annotations_path = bundle / "ladder_review_annotations.json"
            annotations_path.write_bytes(b'{"sentinel": true}\r\n')
            original_cases = cases_path.read_bytes()
            original_annotations = annotations_path.read_bytes()
            real_replace = os.replace

            def fail_second_backup(source, destination):
                if (
                    Path(source) == annotations_path
                    and Path(destination).suffix == ".backup"
                ):
                    raise OSError("injected annotation backup failure")
                real_replace(source, destination)

            with patch(
                "gui_qt.tabs.tab_ladder._io.os.replace",
                side_effect=fail_second_backup,
            ):
                with self.assertRaisesRegex(
                    OSError, "injected annotation backup failure"
                ):
                    save_review_bundle_annotation_worker(
                        bundle,
                        fsa,
                        {
                            "label": "reviewed_no_change",
                            "label_note": "reviewed",
                            "reviewed_at_utc": "2026-08-10T00:00:00+00:00",
                            "adjustment_path": "",
                        },
                    )

            self.assertEqual(cases_path.read_bytes(), original_cases)
            self.assertEqual(annotations_path.read_bytes(), original_annotations)
            self.assertFalse(list(bundle.glob(".*.tmp")))
            self.assertFalse(list(bundle.glob(".*.backup")))

    def test_annotation_pair_preserves_backup_when_rollback_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "sample.fsa"
            fsa.write_bytes(b"trace")
            cases_path = self._write_csv(
                td,
                [{"full_path": str(fsa), "file": fsa.name, "label": ""}],
            )
            annotations_path = bundle / "ladder_review_annotations.json"
            annotations_path.write_bytes(b'{"sentinel": true}\r\n')
            original_cases = cases_path.read_bytes()
            original_annotations = annotations_path.read_bytes()
            real_replace = os.replace
            publication_failed = False

            def fail_publication_and_csv_rollback(source, destination):
                nonlocal publication_failed
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    not publication_failed
                    and destination_path == annotations_path
                    and source_path.suffix == ".tmp"
                ):
                    publication_failed = True
                    raise OSError("injected annotation publication failure")
                if (
                    publication_failed
                    and destination_path == cases_path
                    and source_path.suffix == ".backup"
                ):
                    raise OSError("injected CSV rollback failure")
                real_replace(source, destination)

            with patch(
                "gui_qt.tabs.tab_ladder._io.os.replace",
                side_effect=fail_publication_and_csv_rollback,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "publication and rollback both failed"
                ):
                    save_review_bundle_annotation_worker(
                        bundle,
                        fsa,
                        {
                            "label": "reviewed_no_change",
                            "label_note": "reviewed",
                            "reviewed_at_utc": "2026-08-10T00:00:00+00:00",
                            "adjustment_path": "",
                        },
                    )

            backups = list(bundle.glob(".*.backup"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original_cases)
            self.assertFalse(cases_path.exists())
            self.assertEqual(annotations_path.read_bytes(), original_annotations)

    def test_save_review_bundle_annotation_worker_raises_on_unknown_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fsa = Path(td) / "x.fsa"
            fsa.write_bytes(b"x")
            self._write_csv(
                td,
                [{"full_path": str(fsa), "file": "x.fsa", "label": ""}],
            )
            with self.assertRaises(FileNotFoundError):
                save_review_bundle_annotation_worker(
                    Path(td),
                    Path(_posix_text("/never/seen.fsa")),
                    {"label": "reviewed_no_change"},
                )

    def test_save_review_bundle_rerun_status_worker_persists_consumption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            fsa = bundle / "sample.fsa"
            fsa.write_bytes(b"trace")
            cases = bundle / "ladder_review_cases.csv"
            cases.write_text(
                f"full_path,label\n{fsa},manual_adjusted\n",
                encoding="utf-8",
            )
            manifest = bundle / "run_manifest.json"
            manifest.write_text("{}", encoding="utf-8")

            updated = save_review_bundle_rerun_status_worker(
                bundle,
                {
                    str(fsa): {
                        "status": "consumed",
                        "manual_adjustment_sha256": "c" * 64,
                    }
                },
                run_manifest_path=manifest,
                rerun_at_utc="2026-07-28T12:00:00+00:00",
            )
            loaded = load_review_bundle_worker(bundle)["rows"][0]

            self.assertEqual(updated, 1)
            self.assertEqual(loaded["rerun_status"], "consumed")
            self.assertEqual(loaded["consumed_adjustment_sha256"], "c" * 64)
            self.assertEqual(
                loaded["rerun_manifest_path"],
                str(manifest.resolve()),
            )


class TabLadderRerunSelectionTests(unittest.TestCase):
    def test_run_tab_unregisters_excluded_case_from_review_session(self) -> None:
        from gui_qt.tabs.tab_batch import TabBatch

        cache_key = resolve_cache_key(Path("excluded-no-ladder.fsa"))
        retained_key = resolve_cache_key(Path("retained-adjustment.fsa"))
        fake_tab = SimpleNamespace(
            _review_session_active=True,
            _review_corrected_paths={cache_key},
            _review_session_entries_by_path={cache_key: {"entry": True}},
            _review_session_jobs=[
                {
                    "name": "shared-job",
                    "files": [cache_key, retained_key],
                }
            ],
            _resolve_cache_key=resolve_cache_key,
            _refresh_review_finalize_button=MagicMock(),
            _set_workflow_status=MagicMock(),
        )

        TabBatch.unregister_ladder_review_update(fake_tab, cache_key)

        self.assertNotIn(cache_key, fake_tab._review_corrected_paths)
        self.assertNotIn(cache_key, fake_tab._review_session_entries_by_path)
        self.assertEqual(
            fake_tab._review_session_jobs[0]["files"],
            [retained_key],
        )
        fake_tab._refresh_review_finalize_button.assert_called_once_with()

    def test_exclusion_clears_local_and_run_tab_rerun_state(self) -> None:
        from gui_qt.tabs.tab_ladder import TabLadder

        excluded_fsa = Path("excluded-no-ladder.fsa").resolve()
        cache_key = resolve_cache_key(excluded_fsa)
        review_case = {"full_path": str(excluded_fsa), "label": ""}
        run_tab = SimpleNamespace(
            unregister_ladder_review_update=MagicMock()
        )
        fake_tab = SimpleNamespace(
            _review_case_by_path={cache_key: review_case},
            _review_bundle_cases=[review_case],
            _recent_reviewed_files={cache_key},
            _review_session_entries_by_path={cache_key: {"entry": True}},
            _manual_rerun_consumption_by_path={cache_key: {"consumed": True}},
            _current_file=None,
            _resolve_cache_key=resolve_cache_key,
            _sync_chip_strip=MagicMock(),
            _rebuild_file_list=MagicMock(),
            _select_file=MagicMock(),
            _refresh_review_bundle_run_button=MagicMock(),
            _set_status=MagicMock(),
            _run_tab_for_review=lambda: run_tab,
        )
        annotation = {
            "label": "excluded_missing_ladder_signal",
            "label_note": "No usable ladder signal; preparation error.",
            "reviewed_at_utc": "2026-08-10T00:00:00+00:00",
            "adjustment_path": "",
        }

        TabLadder._on_missing_ladder_exclusion_saved(
            fake_tab, cache_key, annotation
        )

        self.assertNotIn(cache_key, fake_tab._recent_reviewed_files)
        self.assertNotIn(cache_key, fake_tab._review_session_entries_by_path)
        self.assertNotIn(cache_key, fake_tab._manual_rerun_consumption_by_path)
        run_tab.unregister_ladder_review_update.assert_called_once_with(cache_key)

    def test_excluded_bundle_case_is_not_rerun_ready_even_if_recent(self) -> None:
        from gui_qt.tabs.tab_ladder import TabLadder

        excluded_fsa = Path("excluded-no-ladder.fsa")
        fake_tab = SimpleNamespace(
            _review_bundle_cases=[
                {
                    "full_path": str(excluded_fsa),
                    "label": "excluded_missing_ladder_signal",
                }
            ],
            _recent_reviewed_files={resolve_cache_key(excluded_fsa)},
            _resolve_cache_key=resolve_cache_key,
        )

        rerunnable, recent_rerunnable = TabLadder._review_bundle_rerun_counts(
            fake_tab
        )

        self.assertEqual(rerunnable, 0)
        self.assertEqual(recent_rerunnable, 0)

    def test_excluded_bundle_case_disables_rerun_button(self) -> None:
        from PyQt6.QtWidgets import QApplication
        from gui_qt.tabs.tab_ladder import TabLadder

        app = QApplication.instance() or QApplication([])
        excluded_fsa = Path("excluded-no-ladder.fsa")
        tab = TabLadder()
        try:
            tab._review_bundle_dir = Path("review-bundle")
            tab._review_bundle_cases = [
                {
                    "full_path": str(excluded_fsa),
                    "label": "excluded_missing_ladder_signal",
                }
            ]
            tab._recent_reviewed_files = {resolve_cache_key(excluded_fsa)}

            tab._refresh_review_bundle_run_button()

            self.assertFalse(tab.btn_rerun_review_bundle.isEnabled())
            self.assertEqual(
                tab.btn_rerun_review_bundle.text(),
                "Run Reviewed Files + Reports",
            )
        finally:
            tab.close()
            app.processEvents()

    def test_resolved_bundle_files_skip_missing_ladder_exclusion(self) -> None:
        from gui_qt.tabs.tab_ladder import TabLadder

        with tempfile.TemporaryDirectory() as td:
            adjusted_fsa = Path(td) / "adjusted.fsa"
            excluded_fsa = Path(td) / "excluded.fsa"
            adjusted_fsa.write_bytes(b"fsa")
            excluded_fsa.write_bytes(b"fsa")
            fake_tab = SimpleNamespace(
                _review_bundle_cases=[
                    {"full_path": str(adjusted_fsa), "label": "manual_adjusted"},
                    {
                        "full_path": str(excluded_fsa),
                        "label": "excluded_missing_ladder_signal",
                    },
                ],
                _recent_reviewed_files=set(),
                _resolve_cache_key=resolve_cache_key,
            )

            files, missing, unresolved = TabLadder._resolved_review_bundle_files(
                fake_tab
            )

            self.assertEqual(files, [adjusted_fsa.resolve()])
            self.assertEqual(missing, [])
            self.assertEqual(unresolved, 0)


class TabLadderWorkersHelperTests(unittest.TestCase):
    """Pure helpers in `_workers.py` — file scan + report match."""

    def test_scan_fsa_files_worker_returns_sorted_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Create a couple of FSA files in arbitrary order.
            (Path(td) / "b.fsa").write_bytes(b"x")
            (Path(td) / "a.fsa").write_bytes(b"x")
            (Path(td) / "c.fsa").write_bytes(b"x")

            result = scan_fsa_files_worker(Path(td))
            names = [p.name for p in result]
            self.assertEqual(names, ["a.fsa", "b.fsa", "c.fsa"])

    def test_find_report_matches_worker_matches_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sub = Path(td) / "reports"
            sub.mkdir()
            # Stem of "/p/abcd.html.fsa" is "abcd.html" — present verbatim in
            # QC_REPORT_abcd.html/REPORT_abcd.html/etc.
            (sub / "QC_REPORT_seed1.html").write_text("<html>x</html>")
            (sub / "REPORT_seed1.html").write_text("<html>y</html>")
            (sub / "unrelated.html").write_text("<html>q</html>")

            fp = Path("seed1.fsa")
            result = find_report_matches_worker(fp, str(sub))
            names = [m.name for m in result["matches"]]
            self.assertIn("QC_REPORT_seed1.html", names)
            self.assertIn("REPORT_seed1.html", names)
            self.assertNotIn("unrelated.html", names)

    def test_find_report_matches_worker_missing_root_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            find_report_matches_worker(
                Path("p.fsa"), "no_such_dir_for_test_xyz"
            )


class ChipStateHelperTests(unittest.TestCase):
    """Phase 12.3 — chip_state precedence contract.

    The chip strip's four-state precedence:
       file_unreachable > reviewed > needs_review > untouched
    """

    def test_unreachable_wins_over_reviewed(self) -> None:
        # Even a "reviewed" labeled row counts as file_unreachable
        # because the chemist cannot actually access it.
        with tempfile.TemporaryDirectory() as td:
            ghost = "/no/such/path_xyz.fsa"
            row = {
                "full_path": ghost,
                "_path_unreachable": "true",
                "label": "manual_adjusted",
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row), "file_unreachable")

    def test_reviewed_label(self) -> None:
        for label in ("manual_adjusted", "reviewed_no_change"):
            row = {
                "full_path": str(Path("real.fsa")),
                "_path_unreachable": "false",
                "label": label,
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row), "reviewed")

    def test_chip_state_treats_missing_ladder_exclusion_as_reviewed(self) -> None:
        self.assertEqual(
            chip_state({"label": "excluded_missing_ladder_signal"}),
            "reviewed",
        )

    def test_needs_review_when_label_empty_and_flag_set(self) -> None:
        row = {
            "full_path": str(Path("real.fsa")),
            "_path_unreachable": "false",
            "label": "",
            "ladder_qc_status": "review_required",
            "ladder_review_required": "true",
            "primary_reason": "poor_linear_liz_fit",
        }
        self.assertEqual(chip_state(row), "needs_review")

    def test_needs_review_with_missing_ladder(self) -> None:
        row = {
            "full_path": str(Path("real.fsa")),
            "_path_unreachable": "false",
            "label": "",
            "ladder_qc_status": "missing_ladder",
        }
        self.assertEqual(chip_state(row), "needs_review")

    def test_untouched_when_nothing_set(self) -> None:
        row = {
            "full_path": str(Path("real.fsa")),
            "_path_unreachable": "false",
            "label": "",
            "ladder_qc_status": "ok",
        }
        self.assertEqual(chip_state(row), "untouched")

    def test_check_filesystem_true_returns_unreachable_when_path_missing(self) -> None:
        # Use a tag of "false" but force a filesystem check that has
        # to discover the path is missing anyway.
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.fsa"
            real.write_bytes(b"x")
            row = {
                "full_path": "/ghost/of/path_x.fsa",
                "_path_unreachable": "false",
                "label": "",
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row, check_filesystem=True), "file_unreachable")
            # And the same row with real_path + check_filesystem
            # returns untouched.
            row2 = {
                "full_path": str(real),
                "_path_unreachable": "false",
                "label": "",
                "ladder_qc_status": "ok",
            }
            self.assertEqual(chip_state(row2, check_filesystem=True), "untouched")

    def test_count_chip_states_tallies_each_bucket(self) -> None:
        rows = [
            {"full_path": "r1", "_path_unreachable": "false", "label": "manual_adjusted"},
            {"full_path": "r2", "_path_unreachable": "true"},
            {"full_path": "r3", "_path_unreachable": "false", "label": "", "ladder_qc_status": "review_required"},
            {"full_path": "r4", "_path_unreachable": "false", "label": ""},
            {"full_path": "r5", "_path_unreachable": "false", "label": ""},
        ]
        counts = count_chip_states(rows)
        self.assertEqual(counts["reviewed"], 1)
        self.assertEqual(counts["file_unreachable"], 1)
        self.assertEqual(counts["needs_review"], 1)
        self.assertEqual(counts["untouched"], 2)

    def test_count_chip_states_handles_empty(self) -> None:
        counts = count_chip_states([])
        for key in ("reviewed", "needs_review", "file_unreachable", "untouched"):
            self.assertEqual(counts[key], 0)


if __name__ == "__main__":
    unittest.main()
