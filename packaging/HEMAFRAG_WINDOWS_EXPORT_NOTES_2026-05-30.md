# HemaFrag Windows Export Notes - 2026-05-30

Build:
- App: HemaFrag Diagnostics 1.2.0
- Git commit: 61bcc70
- Built on macOS with Docker/Wine for Windows.
- Windows package includes `HemaFrag.exe` and bundled `fraggler-cli.exe`.

What is included:
- `HemaFrag_Windows.zip`: portable Windows app bundle.
- `HemaFrag_Windows/`: extracted portable folder for direct copy/testing.
- `HemaFrag_Windows.zip.sha256`: checksum for the zip.

Recent engine/report updates included:
- Rust-assisted clonality tracking now uses Rust channel previews and ladder anchors before Python fallback.
- Rust result caching reduces repeated primitive calls.
- Rust worker telemetry is logged for FLT3 and clonality runs.
- HTML report fragment caching reduces repeated Plotly/HTML generation work.
- Plotly remains embedded in generated HTML reports so reports can be opened or sent as standalone attachments.

Windows use:
1. Copy `HemaFrag_Windows.zip` to the Windows PC.
2. Right-click the zip and choose "Extract All".
3. Open the extracted `HemaFrag_Windows` folder.
4. Start `HemaFrag.exe`.
5. Keep the whole extracted folder together. Do not move only the `.exe`, because `_internal` contains Python, Qt, Plotly, and the Rust engine.

If Windows blocks the app:
- Choose "More info" and then "Run anyway" if SmartScreen appears.
- If antivirus quarantines `fraggler-cli.exe`, restore/allow it. This file is the bundled Rust analysis engine.
- If the app opens but analysis fails with missing runtime DLL errors, install/update "Microsoft Visual C++ Redistributable 2015-2022 x64" and retry.

Build notes:
- The build produced normal Wine/PyInstaller warnings about Windows API DLLs while cross-building on macOS.
- The Windows zip was still produced successfully.
- Best final validation is to start `HemaFrag.exe` on the target Windows PC and run one small FLT3/clonality test folder.
