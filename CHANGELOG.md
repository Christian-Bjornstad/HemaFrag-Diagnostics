# Changelog

## Unreleased

- Include configured operator in reports and tracking rows.
- Use a single optional tracking workbook per analysis, including archive runs;
  remove secondary master publication and automatic yearly/monthly workbooks.
- Avoid new Excel table objects and synchronize existing table column metadata.
- Preserve distinct FLT3 assays when patient and well identifiers match.
- Make supplemental FLT3 diagnostic CSV exports opt-in.

## 1.2.1 — 2026-10-22

### Fixed

- Preserve original source identity for same-named FSA files from different runs.
- Stop final aggregate publication after a halted batch and record unstarted jobs.
- Analyze only selected FLT3 inputs and restore reports for exact-folder runs.
- Honor General profile channels and assay identity throughout sizing and retries.
- Reject native results whose ladder or channel differs from the requested profile.
- Prefer the configured FLT3 ROX channel and support the LIZ DATA5 fallback.
- Validate malformed ABIF sample counts and numeric payload sizes.
- Allow Python/GUI work to continue during native Rust analysis.
- Preserve literal comments and manual peaks when saving/reopening HTML reports.
- Initialize the SL manual peak editor with its intended 20 bp area window.
- Update FLT3 tracking after review without writing to Clonality destinations.
- Include repository notices and upstream license text in Python/desktop builds.
- Prevent unrelated ICU DLLs on the build machine's PATH from breaking packaged
  Qt startup.

### Changed

- Support Windows 10 and 11 x64; remove macOS/Linux packaging and the experimental
  Rust desktop shell. The PyQt6 app is the supported interface.
- Update the Windows native engine to 0.1.3 and verify it in Windows CI.
- Remove obsolete plans, personal session logs, and retired design inventories.
- Replace historical setup notes with current user, architecture, and build guides.

### Security

- Update `crossbeam-epoch` to 0.9.20 for
  [RUSTSEC-2026-0204](https://rustsec.org/advisories/RUSTSEC-2026-0204) and `anyhow`
  to 1.0.103 for [RUSTSEC-2026-0190](https://rustsec.org/advisories/RUSTSEC-2026-0190).
- Audit Python and Rust dependencies in Windows CI.
