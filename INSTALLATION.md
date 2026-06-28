# HemaFrag Diagnostics — Installation Guide

This guide walks you through a one-time setup so that running
`start.bat` (or directly `qt_app.py`) on Windows works without surprises.

The repository is on the `code-cleanup` branch (commit `c94bbc9`
and later). All split-module re-export fixes, the Rust PyO3+maturin
wheel scaffold, and the single-shot "[RUST ERROR]" logger are in.

---

## TL;DR (read this first)

```powershell
# 1. One-time setup (run in PowerShell from the repo root):
.\install.bat

# 2. Every time thereafter, double-click start.bat — or:
.\start.bat
```

The `install.bat` script:
- finds `C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe`
  (your real Python 3.12 install)
- creates a `.venv` next to the repo
- installs every line of `requirements.txt` into the venv
- installs the prebuilt `fraggler_kernels` wheel IF it's in the
  repo's `wheels/` folder (or re-builds it; see "Optional: Rust
  engine" below)
- leaves a `start.bat` shortcut next to `qt_app.py`

The `start.bat` script:
- activates `.venv`
- runs `qt_app.py` with the right working directory

You do **not** need Rust, cargo, or maturin installed on Windows to
run the app. Python 3.12 with PyQt6 is enough. The optional
`fraggler_kernels` wheel (the in-process Rust engine) installs only
if you've already built it once or downloaded one.

---

## Prerequisites

| Tool                | Required | Where to get                                                   |
|---------------------|----------|----------------------------------------------------------------|
| Python 3.11 or 3.12 | yes      | <https://www.python.org/downloads/> (tick "Add to PATH")        |
| Git (any recent)    | yes      | <https://git-scm.com/download/win>                             |
| Visual C++ runtime  | yes      | Already on Windows 10 / 11 ("Microsoft Visual C++ Redistributable") |
| Rust toolchain      | NO       | only needed if you want to *rebuild* the optional Rust wheel   |
| ~1.5 GB disk        | yes      | venv + docs + (optional) wheel                                 |

Tested with: Python 3.12.10 on Windows 10/11 (PowerShell).

---

## Step-by-step

### 1. Clone or update the repo

```powershell
cd C:\Users\molpa\Desktop\Hermes
git clone https://github.com/Christian-Bjornstad/HemaFrag-Diagnostics.git HemaFrag-Diagnostics-code-cleanup
cd HemaFrag-Diagnostics-code-cleanup
git checkout code-cleanup
git pull    # always do this BEFORE install.bat if you already have the repo
```

### 2. Run `install.bat`

From a PowerShell prompt in the repo root:

```powershell
.\install.bat
```

The script will print:
- `[venv] .venv created`
- `[pip] wheels installed: ...`
- `[inprocess] USING Python fallback` OR `[inprocess] INSTALLED fraggler_kernels wheel`

If anything fails the script exits with a clear error — read the
last 20 lines.

### 3. Launch the app

Double-click `start.bat`, or:

```powershell
.\start.bat
```

You should see the HemaFrag Diagnostics window within ~3 seconds.

### 4. (Optional) Enable the Rust engine in-process

If you want the `fraggler_kernels` wheel (Rust-accelerated FSA
decoding, faster ladder fitting, etc.):

#### 4a. If there's already a wheel in `wheels/`

If you (or a teammate) built the wheel previously, drop the file
into `wheels/fraggler_kernels-*.whl` at the repo root. `install.bat`
will pick it up automatically and install it into the venv.

You can verify it's active by launching the app and looking for
this in the log panel (or stdout):

```
[INFO] In-process Rust path is enabled
```

#### 4b. Build the wheel yourself on Windows

Only do this if step 4a doesn't apply. Requires a one-time Rust
toolchain install (~150 MB), and MSVC build tools.

```powershell
# Run from the repo root
.\install_rust_windows.bat
```

This installs:
- `rustup` + stable Rust toolchain
- MSVC C++ build tools (if not present)
- `maturin` Python package

Then it builds:

```powershell
.\build_wheel_windows.bat
```

Output: `wheels\fraggler_kernels-0.1.0-cp312-cp312-win_amd64.whl`

Re-run `install.bat` to pick up the freshly-built wheel.

#### 4c. The wheel is not needed for correctness

Without the wheel, the app uses a pure-Python fallback that's
slower but produces identical results. See "What you get without
Rust" below.

---

## What you get

### Without `fraggler_kernels` wheel (Python-only fallback)

- Full FLT3, clonality, and general analyses work
- Each FSA file processes ~5-15× slower than with the Rust engine
- You'll see **one** `[RUST WARNING]` per Python process (not one
  per file) warning that Rust isn't loaded; this is normal and
  expected

### With `fraggler_kernels` wheel (Rust in-process)

- All of the above, plus:
- 5-15× faster FSA parsing + ladder fitting on multi-file batches
- The `[RUST WARNING]` line does NOT appear (Rust is loaded)
- Same FSC file → same outputs → just faster

---

## Where things go

| Path                                           | Purpose                                    |
|------------------------------------------------|--------------------------------------------|
| `.venv/`                                       | The Python virtual environment             |
| `wheels/`                                      | Drop pre-built `fraggler_kernels` here     |
| `install.bat`                                  | First-time setup script                    |
| `start.bat`                                    | Quick-launch script                        |
| `install_rust_windows.bat`                     | (optional) Rust toolchain installer         |
| `build_wheel_windows.bat`                      | (optional) Wheel builder                   |
| `start.log`                                    | Last-run stdout/stderr from the GUI        |

---

## Troubleshooting

### "python is not recognized"

Your install of Python isn't on PATH. Either:
- Re-install Python with "Add to PATH" ticked (recommended), or
- Use the absolute path:
  `C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe install.bat`

### "ModuleNotFoundError: No module named 'PyQt6'"

Your venv didn't get built, or PyQt6 install failed. Re-run
`install.bat` and look for the `[pip] wheels installed` line.

### "Permission denied" on `start.bat`

Right-click → Properties → "Unblock" → OK. Or run from PowerShell:
`Unblock-File .\start.bat`.

### App opens but every job says "Collected 0 entries"

This is **the symptom of a missing-binary CLI in old versions.**
After commit `c94bbc9`/`5c7711f`/`c94bbc9`, `start.bat` will print
ONE `[RUST WARNING]` line per process — not dozens. If you see
many, the fix on this branch hasn't been pulled yet:

```powershell
git pull origin code-cleanup
.\start.bat
```

### Want the Rust engine but `install_rust_windows.bat` failed

Open PowerShell as Administrator, run:

```powershell
winget install Rustlang.Rustup
winget install Microsoft.VisualStudio.2022.BuildTools
```

Then re-run `.\install_rust_windows.bat` followed by
`.\build_wheel_windows.bat`.

---

## Removing the install

```powershell
cd C:\Users\molpa\Desktop\Hermes\HemaFrag-Diagnostics-code-cleanup
rmdir /s /q .venv
del start.log
```

Then `git pull` and re-run `install.bat` next time.

---

## For non-Windows hosts (macOS / Linux)

- `bash install.sh` does the same thing (created in a follow-up commit)
- The PyO3 wheel for non-Windows must be built on that OS
- See `fraggler-v2/crates/fraggler-kernels-py/README.md` for the
  standalone build instructions
