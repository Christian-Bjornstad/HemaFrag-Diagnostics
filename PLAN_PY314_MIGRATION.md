# Plan — HemaFrag Python 3.14.6 Migration

> **Branch**: `py314-migration-plan`
> **Companion doc**: see `REMAINING_WORK.md` for the phase-by-phase
> status of what's done vs what still needs to happen.
> **Target**: Python 3.14.6 (released June 10, 2026) on the work
> computer that has only Python (no Rust toolchain, no build
> tools, no permission to run .exe installers beyond Python).
> **Current baseline repo state**:
> `ml-clonality-interpretation-2026-06-27` branch, commit
> `43d2bfc`. Python 3.11/3.12 working, 161+ tests green. The
> migration skill `python-3.15-migration-runway` documents the
> 3.11->3.13.5 run (347 passed, 1 skipped) done in the Linux
> container -- those commits (8d2ab39, 9cfe243) are NOT in this
> Windows repo; they live only in the container.

---

## 0. The constraint

The work computer has:
- Python 3.14.6 installed (system Python)
- No Rust / cargo / maturin toolchain
- No MSVC build tools
- Cannot run arbitrary .exe files (corporate lock-down)

Therefore:
- **Every dep must have a pre-built wheel** for cp314 (or an
  abi3 wheel forward-compatible to 3.14) on Windows win_amd64.
  No source builds.
- **The Rust wheel** (`fraggler_kernels`) must be pre-built
  elsewhere and shipped as a wheel file the install script drops
  into the venv. The work computer never compiles Rust.
- The install/launch scripts must be `.bat` (cmd.exe), not
  `.exe` -- they run inside the corporate policy.

---

## 1. Wheel availability audit (Python 3.14, win_amd64)

Research done 2026-07-09. All versions are the latest on PyPI
as of this date. "OK" = has a cp314 or forward-compatible abi3
wheel for win_amd64.

### 1.1 Pure-Python / scientific stack

| Package | Current pin | Target pin | 3.14 wheel | Notes |
|---------|-------------|------------|------------|-------|
| numpy | 1.26.4 | >=2.3,<3.0 | OK (2.5.x cp314 wheels) | 2.5 drops 3.11; we're on 3.14 so fine |
| pandas | 2.2.2 | >=2.3,<3.0 | OK (2.3.x / 3.0.x cp314) | 3.0.3 has cp314t too |
| scipy | 1.13.1 | >=1.16,<2.0 | OK (1.18.x cp314) | |
| matplotlib | 3.9.0 | >=3.11,<4 | OK (3.11.x cp314) | |
| scikit-learn | 1.5.0 | >=1.9,<2.0 | OK (1.9.0 cp314) | QDA fallback needed (see S4) |
| openpyxl | 3.1.5 | >=3.1.5 | OK (pure Python) | |
| contourpy | 1.3.2 | >=1.3.3 | OK | |
| pillow | 12.1.0 | >=12.3 | OK | |
| pyarrow | -- | >=24 | OK (cp314) | |
| plotly | 6.5.2 | >=6.8 | OK (pure Python) | CDN-blocked; inline only |
| bokeh | 3.4.3 | >=3.9 | OK | |
| panel | 1.4.4 | >=1.9 | OK | |
| altair | 5.3.0 | >=6.2 | OK (pure Python) | |

### 1.2 The Rust binding (fraggler-kernels-py)

**Current state:**
- `Cargo.toml`:
  `pyo3 = { version = "0.24", features = ["extension-module", "abi3-py312"] }`
- `pyproject.toml`: `requires-python = ">=3.9"`
- Built wheel: `wheels/fraggler_kernels-0.1.0-cp312-abi3-win_amd64.whl`

**Key question: does the existing cp312-abi3 wheel work on 3.14
at runtime?**

Yes, in principle. The abi3 (stable ABI) promise is that a
wheel built against CPython 3.12 limited API loads on any
3.12+ interpreter. CPython 3.14 maintains the abi3 contract.

**But**: PyO3 0.24 has a build-time check that rejects Python
3.14 ("newer than PyO3's maximum supported version"). That only
affects building, not loading. At runtime, PyO3's abi3 feature
restricts calls to the stable C API subset, so the compiled
`.pyd` should load fine on 3.14.

**Action items for the Rust crate:**
1. Upgrade `pyo3` from `0.24` to `>=0.26` (adds 3.14 support;
   Nov 2025 release). Needed if we ever rebuild on a 3.14 host.
2. Keep `abi3-py312` -- 3.12 is our minimum, abi3 covers 3.14.
3. Bump `requires-python` to `>=3.10,<3.16` in `pyproject.toml`.
4. **Rebuild the wheel** on this Windows dev machine (which HAS
   Rust) with the upgraded PyO3, producing a new
   `fraggler_kernels-0.2.0-cp312-abi3-win_amd64.whl`.
5. Ship that wheel to the work computer via `wheels/` + `install.bat`.

**Fallback**: if the wheel fails to load on 3.14 for any reason,
the app already has a pure-Python fallback path
(`rust_bridge.py` detects missing `fraggler_native`, logs one
`[RUST WARNING]` per process, then continues). So the Rust
wheel is NOT a blocker for 3.14 correctness -- only for speed.

### 1.3 The Qt GUI stack -- the most likely blocker

| Package | Current pin | 3.14 status | Notes |
|---------|-------------|-------------|-------|
| **PyQt6** | 6.11.0 | **Likely OK** -- 6.11.0 ships cp310-abi3 wheels; abi3 forward-compat to 3.14 | Verify with `pip install PyQt6 --dry-run` on 3.14 |
| **PyQt6-Qt6** | 6.11.1 | `py3-none-win_amd64.whl` (Python-agnostic) | Qt .dll payload is version-independent |
| pyqtgraph | 0.13.7 | >=0.14 (pure Python) | |

**Risk**: Qt for Python 6.10 (Oct 2025) explicitly did NOT
support 3.14. PyQt6 6.11.0 (Mar 2026) uses abi3 wheels
(cp310-abi3), which SHOULD load on 3.14. But Riverbank has not
publicly confirmed 3.14 support in release notes. This is the
single biggest unknown.

**Mitigation**: If PyQt6 6.11.0 fails to import on 3.14:
- Option A: try `PyQt6==6.11.1` (released after 6.11.0)
- Option B: switch to PySide6 (Qt's official Python binding).
  PySide6 6.12 (July 2026, per Qt wiki) is adapting to 6.12.
  Larger code change (import names differ: `PyQt6` -> `PySide6`,
  `pyqtSignal` -> `Signal`, etc.) -- reserve as Plan B.
- Option C: run the GUI-less pipeline only (label tool via
  `--no-browser`, training CLI, export scripts) and defer the
  Qt GUI to when PyQt6 officially supports 3.14.

---

## 2. Migration recipe (7 steps)

### Step 1 -- Create a 3.14 venv on this dev machine

This dev machine has Python 3.12. We need 3.14.6 here to test
before shipping to the work computer.

```
# Download python-3.14.6-amd64.exe from python.org
# Install to C:\Users\molpa\AppData\Local\Programs\Python\Python314\
# (do NOT replace the 3.12 install -- add alongside)

# Create venv:
C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe -m venv .venv-314
.venv-314\Scripts\python.exe -m pip install -U pip wheel setuptools
```

### Step 2 -- Re-pin requirements in waves

Do NOT run `pip install -r requirements.txt` -- the existing
pins (numpy==1.26.4, etc.) have no 3.14 wheels.

```bash
# Wave 1: numeric core
pip install 'numpy>=2.3,<3.0' 'scipy>=1.16,<2.0' \
            'pandas>=2.3,<3.0' 'scikit-learn>=1.9,<2.0'

# Wave 2: plotting
pip install 'matplotlib>=3.11,<4' 'contourpy>=1.3.3' \
            'bokeh>=3.9' 'panel>=1.9'

# Wave 3: Qt
pip install 'PyQt6>=6.11' 'pyqtgraph>=0.14'

# Wave 4: data IO + utils
pip install 'openpyxl>=3.1.5' 'xlsxwriter>=3.2'

# Wave 5: long tail (let pip resolve)
pip install -r requirements.txt --upgrade
```

Update `requirements.txt` in place with new floor pins (see S3).

### Step 3 -- Upgrade the Rust crate (PyO3 0.24 -> 0.26+)

In `fraggler-v2/crates/fraggler-kernels-py/Cargo.toml`:
```toml
# Before:
pyo3 = { version = "0.24", features = ["extension-module", "abi3-py312"] }

# After:
pyo3 = { version = ">=0.26", features = ["extension-module", "abi3-py312"] }
```

In `pyproject.toml`:
```toml
# Before:
requires-python = ">=3.9"

# After:
requires-python = ">=3.10,<3.16"
```

Check for PyO3 0.24->0.26 API changes in `lib.rs`. Run
`cargo check` before building.

### Step 4 -- Rebuild the Rust wheel

```bash
# On this dev machine (has Rust):
cd fraggler-v2/crates/fraggler-kernels-py
.venv-314\Scripts\python.exe -m maturin build --release \
    --interpreter .venv-314\Scripts\python.exe \
    --cargo-extra-args='-C lto=thin'
# Output: wheels\fraggler_kernels-0.2.0-cp312-abi3-win_amd64.whl
```

If PyO3 complains even with 0.26, set env var:
```
set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
```
This suppresses the "newer than supported" check for abi3 builds.

### Step 5 -- Test on this dev machine

```bash
# Unit tests (with Qt offscreen):
set QT_QPA_PLATFORM=offscreen
.venv-314\Scripts\python.exe -m pytest --tb=line -q

# Label tool smoke (synthetic):
.venv-314\Scripts\python.exe -m scripts.label_tool.open_session \
    --synthetic --chem-id test --assay FR1 \
    --audit-size 5 --no-browser

# Rust wheel load check:
.venv-314\Scripts\python.exe -c "import fraggler_native; print('OK')"
```

Watch for:
- **sklearn QDA LinAlgError** (expected -- see S4 for the fix
  recipe validated for 3.13; same applies to 3.14 sklearn 1.9)
- **PyQt6 import failure** (the big risk -- see S1.3)
- **Qt font-init traceback** (a known 3.13+ landmine that
  doesn't surface in unit tests)

### Step 6 -- Update install.bat / start.bat for 3.14

The current `install.bat` hardcodes Python 3.12 path. Change to
prefer 3.14, fall back to 3.12:
```bat
if exist "C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe" (
    set "PYTHON_EXE=C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe"
) else if exist "C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe"
) else (
    ...
)
```

### Step 7 -- Ship to work computer

1. Push this branch to GitHub.
2. On the work computer: `git pull`, `git checkout py314-migration-plan`.
3. Run `install.bat` -- creates .venv from Python 3.14.6, installs
   all deps from wheels (no source builds), picks up the
   pre-built Rust wheel from `wheels/`.
4. Run `start.bat` -- launches the GUI.
5. Verify: `[INFO] In-process Rust path is enabled` in the log.

---

## 3. Target requirements.txt shape (3.14)

```
numpy>=2.3,<3.0
scipy>=1.16,<2.0
pandas>=2.3,<3.0
scikit-learn>=1.9,<2.0
matplotlib>=3.11,<4
contourpy>=1.3.3
bokeh>=3.9
panel>=1.9
PyQt6>=6.11
pyqtgraph>=0.14
openpyxl>=3.1.5
xlsxwriter>=3.2
plotly>=6.8
pyarrow>=24
altair>=6.2
asteval>=1.0.9
attrs>=26.1.0
biopython>=1.87
Jinja2>=3.1.6
joblib>=1.5.3
jsonschema>=4.26.0
kiwisolver>=1.5.0
lmfit>=1.3.4
pillow>=12.3
pytz>=2026.2
PyYAML>=6.0.3
tornado>=6.5.7
uncertainties>=3.2.3
urllib3>=2.7.0
wheel>=0.47.0
xyzservices>=2026.3.0
```

Lower bound only, no upper cap except where a known break
exists. Same shape as the 3.13 migration skill's output.

---

## 4. Known algorithm regression -- sklearn QDA

**Same issue as 3.13 migration, documented in the
`python-3.15-migration-runway` skill.**

scikit-learn >=1.6 (and 1.9 is stricter) raises:
```
numpy.linalg.LinAlgError: covariance matrix of class X is not full rank
```
in `QuadraticDiscriminantAnalysis.fit` on rank-deficient
fixtures.

**Fix (validated for 3.13, applies unchanged to 3.14):**
Wrap QDA in `try/except (ValueError, np.linalg.LinAlgError)`,
fall back to `GaussianNB`. Use
`inspect.signature(_QDA.__init__)` to detect `solver` kwarg for
backwards-compat. See the skill's
`references/post-migration-3-13-findings.md` for the exact code
shape.

This fix was commit `9cfe243` in the container -- NOT in this
Windows repo. It needs to be re-applied here.

---

## 5. Risks and unknowns

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| PyQt6 6.11 fails to import on 3.14 | Medium | High (no GUI) | Test early; fallback to PySide6 or GUI-less mode |
| Rust wheel abi3 tag rejected by 3.14 at load time | Low | Medium | Pure-Python fallback already works; rebuild with pyo3 0.26 |
| numpy 2.x API changes break downstream | Low | Low | pandas/sklearn caught up to numpy 2.x by mid-2026 |
| plotly CDN blocked (403) on work computer | Certain | Low | Already known; use inline SVG/vanilla plots |
| sklearn QDA regression | Certain | Low | Fix recipe known and validated |
| `setuptools` drops `distutils` (gone in 3.14) | Certain | Low | Our code has zero distutils/imp/asyncore usage (pre-flight grep clean) |

---

## 6. Shipping checklist (what the work computer needs)

1. [ ] `requirements.txt` updated with 3.14-compatible floor pins
2. [ ] `install.bat` updated to prefer Python 3.14.6 path
3. [ ] `start.bat` unchanged (venv-agnostic)
4. [ ] `wheels/fraggler_kernels-0.2.0-cp312-abi3-win_amd64.whl`
      (rebuilt with PyO3 0.26+ on this dev machine)
5. [ ] `INSTALLATION.md` updated to say "Python 3.14.6 or 3.12"
6. [ ] QDA GaussianNB fallback code ported from container commit
7. [ ] All tests green on 3.14.6 venv on this dev machine
8. [ ] Label tool smoke test passes on 3.14.6 venv
9. [ ] GUI launches on 3.14.6 venv

The work computer receives: the git branch + the pre-built wheel.
No Rust, no MSVC, no .exe installers needed beyond Python itself.

---

## 7. Timeline estimate

| Phase | What | Est. effort |
|-------|------|------------|
| A | Install 3.14.6 on dev machine, create venv | 0.5h |
| B | Re-pin requirements in waves, install deps | 1h |
| C | Upgrade PyO3, rebuild Rust wheel | 1-2h |
| D | Port QDA fallback fix, run tests | 1h |
| E | Update install.bat, test install on 3.14 | 0.5h |
| F | GUI smoke test on 3.14 (the risk point) | 0.5-2h |
| G | Label tool + real-data smoke | 1h |
| Total | | 5.5-8h (one work day) |

If PyQt6 blocks (Phase F), add 4-8h for PySide6 port or
GUI-less-mode workaround.

---

*Authored 2026-07-09 on branch `py314-migration-plan`.*
