# HemaFrag Windows Transfer

This zip is a clean source transfer for setting up HemaFrag on a Windows PC.

Included under `HemaFrag/`:
- HemaFrag source code, tests, scripts, packaging files, and Obsidian project notes.
- Rust engine source under `fraggler-v2/`.
- Windows build/run documentation under `packaging/`.

Included under `WindowsApp/` when available on T7:
- `HemaFrag_Windows.zip`, the ready-made Windows app bundle.
- `HemaFrag_Windows_PC_Guide.md`, the Windows PC setup guide.

Excluded on purpose:
- Raw data folders, generated reports, caches, Python/Rust build outputs, `dist/`, `build/`, `local_triage/`, and `artifacts/`.
- The `.git` folder is excluded from the transfer zip because the latest source is pushed to GitHub.

Use on Windows:
1. Extract the zip.
2. Install Python and Rust if you want to develop/build from source.
3. For the ready-made app, extract `WindowsApp/HemaFrag_Windows.zip` if present.
4. For repeatable Windows build notes, read `packaging/WINDOWS_RELEASE_RUNBOOK.md`.
