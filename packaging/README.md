# Windows packaging

HemaFrag supports Windows 10 and Windows 11 on x64. `qt_app.py` is the
application entry point; `build_qt.py` builds the PyInstaller bundle and ZIP.

## Build prerequisites

- 64-bit Python 3.12–3.14 on Windows.
- Rust/MSVC toolchain matching `fraggler-v2/rust-toolchain.toml`, with Visual Studio
  C++ build tools and the Windows SDK.
- Network access or approved cached wheels for runtime and build dependencies.

From the repository root in Command Prompt or PowerShell:

```powershell
.\packaging\build_windows.bat
```

The wrapper creates `.venv-build`, installs runtime/build requirements and the
checked-in native engine, verifies the native version, and stops on any failed
step. The build always invokes Cargo with `--locked` so the recovery CLI matches
the source. Build-tool requirements are in `packaging/build-requirements.txt`.

Outputs:

| Path | Purpose |
|---|---|
| `dist/HemaFrag_Windows/HemaFrag.exe` | Desktop launcher |
| `dist/HemaFrag_Windows/_internal/` | Python, Qt, native engine, assets, and recovery CLI |
| `dist/releases/HemaFrag_Windows.zip` | Portable distribution |

The ZIP contains the entire portable folder. Do not distribute the executable
alone. Clinical input, local settings, reports, and private validation datasets
are excluded from the bundle.

## Verify a build

```powershell
python -m zipfile -t dist\releases\HemaFrag_Windows.zip
Get-FileHash dist\releases\HemaFrag_Windows.zip -Algorithm SHA256
```

Extract it into a separate directory, launch `HemaFrag.exe`, and verify the
version, icon, About notices, and a representative analysis/review/report
workflow. Repeat on the intended Windows 10/11 machine before operational use.
CI runs source tests on Windows; it does not replace this packaged-app check.

The runtime hook prevents extra GUI launches from Python multiprocessing and
keeps the legacy Panel server disabled by default. Windowed launches provide
safe stdout/stderr streams. Native Rust analysis runs in process; the bundled
CLI is the recovery path.

## Approved Python source deployment

If the work computer uses an approved Python environment, follow the root
[README](../README.md#quick-start). No new HemaFrag executable is required.
Create its shortcut with:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\create_windows_shortcut.ps1 `
  -PythonPath "C:\path\to\approved-python\python.exe"
```

If Windows retains an old pinned icon, unpin that shortcut, launch through the
new shortcut, and pin the running HemaFrag window again.

## Updating or rolling back

Install a new portable bundle in its own directory and retain the previous
validated bundle. Close HemaFrag before switching versions. Preserve the
operator's settings, adjustment database, raw input, and outputs; these are
separate from application binaries. Reverting source changes uses normal Git
revert commits rather than rewriting shared history.
