# Architecture

HemaFrag is a local PyQt6 application for Windows 10 and 11. Python owns job
orchestration, assay processing, review, and reporting. Rust provides numerical
analysis through the in-process `fraggler_native` extension and a recovery CLI.

## Analysis flow

1. `qt_app.py` initializes application identity/resources and `gui_qt.main_window`.
2. `gui_qt.tabs.tab_batch` discovers input, captures settings, and starts worker
   tasks. `gui_qt.operation_coordinator` tracks active operations and shutdown.
3. `core.batch` constructs deterministic jobs and writes a batch manifest.
   `core.runner` dispatches exact input cohorts and preserves original source
   identities even when staging files with identical basenames.
4. `core.analyses` selects Clonality, FLT3, or General. `core.fsa_artifact`
   shares decoded, immutable FSA data within a process.
5. `core.analysis` applies assay/channel configuration and valid manual
   corrections. `core.rust_bridge` prefers the native wheel, checks returned
   ladder/channel contracts and QC, and records engine provenance.
6. Ambiguous or rejected ladders become review entries. Ladder Studio saves
   validated, source-specific adjustments; reruns verify them before use.
7. `core.html_reports`, `core.plotting_plotly`, and `core.qc` generate output.
   Assay-specific tracking writers publish to one explicitly configured workbook.

## Boundaries that must remain explicit

- FLT3 defaults to GS500ROX/DATA4; LIZ is an explicit alternative.
- General profiles carry their own analysis identity, ladder, and size-standard
  channel. Native output that disagrees with the requested profile is rejected.
  Automatic Rust selection still infers its profile; custom General profiles can
  require manual review when inference differs from the requested configuration.
- Legacy Python ladder recovery is opt-in. Strict Rust modes surface native
  failures rather than silently switching algorithms.
- A halted batch records unsubmitted jobs as `unprocessed` and does not publish
  a partial aggregate as its final report. Cancellation and failure remain distinct.
- Manual peak edits are stored in reports. HTML/JavaScript serialization must
  preserve literal text and prevent user-derived strings from becoming script.
- Report finalization updates the active assay's tracking destination using the
  captured settings. FLT3 review must not write the Clonality master workbook.
- Clonality rule interpretation remains available; the retired ML training and
  inference subsystems are absent.

## State and output

Settings default to `%USERPROFILE%\.hemafrag_gui.yaml`. Legacy configuration can
be migrated from `.fraggler_gui.yaml`. `HEMAFRAG_SETTINGS_PATH` redirects settings,
and `HEMAFRAG_LADDER_ADJUSTMENT_DB` redirects the local adjustment database.
Tests isolate these paths from operator state.

Run manifests retain membership, stages, completion state, output paths, hashes,
and failure reasons. Adjustment records retain source/profile provenance. Excel
and report writers use guarded/atomic publication where implemented; workbook
locks and unavailable shared paths must remain visible failures.

## Development tools

`core.research`, `core.precision`, and validation/benchmark scripts support
engineering comparisons and corpus review. Their output is local and ignored.
They do not establish clinical performance or replace assay validation.
