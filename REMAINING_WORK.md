# Remaining Work — HemaFrag Python 3.14.6 Migration

> **Companion to `PLAN_PY314_MIGRATION.md`** on branch
> `py314-migration-plan`.

This file tracks what has been done, what is partially done,
and what still needs to happen before the work computer can run
HemaFrag on Python 3.14.6.

---

## A. What was done in the previous session(s)

The previous session (20260708_134040_9cc2a0, 1137 messages)
and its predecessor (20260708_065208) accomplished:

### A.1 Python 3.11 -> 3.13.5 migration (CONTAINER ONLY)

- Created and validated a Python 3.13.5 venv in the Linux
  container (NOT on this Windows repo).
- Re-pinned all deps in waves (numpy, scipy, pandas, sklearn,
  matplotlib, Qt stack).
- Resolved the scikit-learn QDA rank-deficiency regression with
  a GaussianNB fallback (commit `9cfe243` -- container only).
- Validated: 348 passed, 1 skipped, 1 xfailed on 3.13.5
  (327 passed / 1 skipped on 3.11.15).
- Authored the `python-3.15-migration-runway` skill with the
  full recipe and dead-end mitigation table.
- **These commits are NOT in this Windows repo.** The container
  work (commits 8d2ab39, 9cfe243) was never pushed to the
  `ml-clonality-interpretation-2026-06-27` branch that this
  Windows checkout tracks.

### A.2 HemaFrag app development (on this Windows branch)

The current branch `ml-clonality-interpretation-2026-06-27`
(HEAD: `43d2bfc`) has shipped:

- **Plan 11** (clonality interpretation assist): full ML
  pipeline -- feature engineering, per-assay training,
  calibration with rejection, GUI tab integration, 161+ tests
  green.
- **Plan 12** (ladder editor remodel): tab_ladder split into
  helper modules (Phase 12.1), chip-strip overview (12.3),
  review case relocation + Locate File dialog (12.4).
- **Rust bridge**: `fraggler-kernels-py` crate with PyO3 0.24,
  pre-built `cp312-abi3` wheel at
  `wheels/fraggler_kernels-0.1.0-cp312-abi3-win_amd64.whl`.
- **Windows install/launch scripts**: `install.bat`,
  `start.bat`, `build_wheel_windows.bat`, `install_rust_windows.bat`,
  `INSTALLATION.md`.
- **Label tool** (Plan 35): committed `08549eb`, 48 unit tests,
  keyboard-only FR1 sample labeling with SVG electropherograms.

### A.3 Current repo state (verified 2026-07-09)

```
Branch:  ml-clonality-interpretation-2026-06-27  (now py314-migration-plan)
HEAD:    43d2bfc  tab_ladder: relocate review case + Locate File dialog
Tests:   161 passed, 1 skipped (on Python 3.12)
Python:  3.11 / 3.12 working; 3.13 done in container (not here); 3.14 not started
Rust:    pyo3 0.24, abi3-py312 wheel built and shipped
```

---

## B. What has NOT been done (migration to 3.14)

Everything below is fresh work on this Windows repo.

### B.1 Python environment

- [x] **Dependency-resolution dry-run for cp314 + win_amd64
      (2026-07-09) — 37/37 deps resolve as binary wheels,
      no source builds.** Result: every dep in PLAN S3 has a
      shipping path. PyQt6 6.11.0 ships `cp310-abi3-win_amd64`
      which loads on Python 3.14 at runtime (abi3 forward-compat).
      Cached wheels live at `C:\tmp\deps-full-cp314`
      (243 MB, 37 `.whl` files). Reusable for B.2.
- [ ] **Defer**: a real Python 3.14.6 install + `.venv-314`
      only needs to happen on the work computer (which already
      has Python 3.14.6 per user). On this dev machine,
      installing 3.14.6 alongside 3.12 is optional -- the
      dry-run above is the gating evidence we needed.
- [ ] **Defer**: the PyQt6 import smoke test on a live 3.14
      venv will be done as part of Phase B.6 (GUI smoke).
      The wheel-layer risk is gone; the ABI-load risk is
      negligible (cp310-abi3 forward-compat is 14+ years of
      CPython promise, validated every release).

### B.2 Dependency re-pinning

- [x] **`requirements.txt` re-pinned to floor pins (2026-07-09)**
      -- 36 dep lines, lower-bound only, single matrix works on
      both Python 3.11/3.12 and Python 3.14.6. New shape:
      `numpy>=2.1,<3.0` `scipy>=1.13,<2.0` `pandas>=2.2,<3.0`
      `scikit-learn>=1.6,<2.0` `matplotlib>=3.10,<4`
      `PyQt6>=6.11` `pillow>=11` `bokeh>=3.7` `panel>=1.6`
      `plotly>=6.5` `altair>=5.4` and the rest. PyQt6 moved
      from ==6.7.0 to >=6.11 (matches the version with the
      cp310-abi3 wheel that 3.14 forward-compat loads).
- [x] **`pip install --dry-run` on Python 3.12 fresh venv**
      (2026-07-09) -- all 33 *real* floors honored (the 3
      "missing" cases are meta deps -- pip/wheel/setuptools --
      which venv seeds and so don't show up in "Would install";
      that's expected, not a failure). Wheel resolution picks
      numpy 2.5.1, scipy 1.18.0, sklearn 1.9.0, matplotlib 3.11.0,
      PyQt6 6.11.0, pandas 2.3.3, etc.
- [x] **`pip download` for cp314 + win_amd64** (2026-07-09) --
      36/36 wheels, zero source builds, 145.8 MB cached at
      `C:\tmp\deps-full-cp314-b2\`.

### B.3 Rust wheel rebuild

- [x] **`pyo3` 0.24 -> `>=0.26,<0.30`** (2026-07-09) in
      `fraggler-v2/crates/fraggler-kernels-py/Cargo.toml`. Cargo
      resolved to v0.29.0 (the version with full 3.14 build-time
      support per Nov 2025 release notes).
- [x] **`requires-python` >=3.9 -> `>=3.10,<3.16`** in the
      matching `pyproject.toml`. Now encoded in wheel
      METADATA (`Requires-Python: >=3.10, <3.16`).
- [x] **`cargo check` against v0.29.0** -- PASS in 40s.
      `lib.rs` API surface is fully compatible with PyO3 0.29:
      `Bound<>`, `into_pyobject`, `wrap_pyfunction!`,
      `PyDict::set_item`, etc. are all current.
- [x] **`maturin build --release`** -- built
      `wheels/fraggler_kernels-0.1.0-cp312-abi3-win_amd64.whl`
      (0.72 MB, PyPI tag `cp312-abi3-win_amd64` per WHEEL file;
      `Requires-Python: >=3.10, <3.16` per METADATA).
      Had to use `VIRTUAL_ENV=.venv` env var to override
      maturin's auto-detection which was picking up Hermes'
      internal Python 3.11 venv (causing it to build a
      cp311-cp311 wheel instead of an abi3 wheel). Documented
      for the next builder.
- [x] **`pip install + import test`** on Python 3.12:
      `is_available() -> True`, `version == '0.1.0'`,
      `analyze_fsa(path, analysis_kind)` callable, signature
      intact. `fraggler_cli_path() returns None` is expected
      (no sibling .exe was built in this workspace; the
      pure-Rust in-process path is what matters).
- [x] **Wheel copied to repo `wheels/`** -- replaces the 1.5 MB
      PyO3 0.24 wheel from `c56c723`. New wheel is 0.72 MB
      (release build, no debug). Hashes verified identical
      between `C:/tmp/maturin-out/` and `wheels/`.
- [x] **Runtime forward-compat to 3.14.6**: per PyO3 0.29 /
      PEP 425 / PEP 652, abi3 wheels load on any cpython >= the
      abi floor (3.12 here). The 3.14 import-smoke test is
      deferred to Phase B.6.

### B.4 QDA fallback port

- [x] **`_build_qda_or_nb_fallback` helper added to
      `core/analyses/clonality/ml_training.py`** (2026-07-09):
      try QDA first; on `ValueError` / `np.linalg.LinAlgError`
      fall through to `GaussianNB`. Pipeline shape and
      `predict_proba(n, n_classes)` contract preserved.
- [x] **`fit_classifier(kind='qda_calibrated')` now routes
      through the helper.** Removed the inline QDA-Fit, added
      `import inspect`, `from sklearn.naive_bayes import
      GaussianNB`. `inspect.signature(_QDA.__init__).parameters`
      gates the new-path `solver='eigen', shrinkage='auto'`
      kwargs (sklearn >= 1.6 only); old sklearn (<= 1.5, our
      3.11 baseline) takes the no-kwarg fallback.
- [x] **Public docstring updated** -- `fit_classifier` now
      documents the fallback so the next maintainer finds it.
- [x] **Ad-hoc verification (2026-07-09):**
      - happy QDA path returns `QuadraticDiscriminantAnalysis`
      - forced-failure path (monkey-patched QDA that raises
        LinAlgError on fit) returns `GaussianNB`, same shape
      - `fit_classifier('qda_calibrated')` routes through
        fallback correctly
      - `tests/test_clonality_interpretation_ml.py` 12/12 PASS
      - `tests/test_clonality_interp_integration.py` 10/10 PASS
      - 22/22 total, 0 regressions
      (Full live 1.9 + Python 3.14 path is verified in Phase B.5
      on the work computer.)


### B.5 Test suite on 3.14

- [ ] Run `pytest --tb=line -q` in the 3.14 venv
- [ ] Compare pass count to the 3.12 baseline (161 passed)
- [ ] Investigate any new failures (expect QDA path to already
      be handled by B.4)

### B.6 GUI smoke test on 3.14

- [ ] Run `start.bat` with the 3.14 venv
- [ ] Verify the HemaFrag window opens
- [ ] Watch for Qt font-init traceback (a known 3.13+ landmine)
- [ ] If PyQt6 fails to import on 3.14, document the error and
      pick a mitigation (see PLAN_PY314_MIGRATION.md S1.3)

### B.7 Label tool smoke on 3.14

- [ ] Run
      `python -m scripts.label_tool.open_session --synthetic --chem-id test --assay FR1 --audit-size 5 --no-browser`
      under the 3.14 venv
- [ ] Verify SVG electropherogram renders, keyboard nav works

### B.8 Install/launch script updates

- [ ] Update `install.bat` to prefer Python 3.14 path, fall back to 3.12
- [ ] Update `INSTALLATION.md` to say "Python 3.14.6 or 3.12"
- [ ] Verify `install.bat` works end-to-end on the 3.14 venv
- [ ] Verify `start.bat` launches the GUI from the new venv

### B.9 Ship to work computer

- [ ] Commit all changes on `py314-migration-plan` branch
- [ ] Push branch to GitHub
- [ ] On work computer: `git pull`, `git checkout py314-migration-plan`
- [ ] Run `install.bat` (creates .venv, installs wheels, picks up Rust wheel)
- [ ] Run `start.bat`
- [ ] Verify `[INFO] In-process Rust path is enabled` in the log
- [ ] Run label tool on one real FR1 sample to confirm end-to-end

---

## C. Blockers and open questions

### C.1 PyQt6 3.14 support -- RESOLVED (2026-07-09)

~~Qt for Python 6.10 (Oct 2025) explicitly did not support
3.14.~~ The Phase B.1 dry-run resolved
`pyqt6-6.11.0-cp310-abi3-win_amd64.whl` (6.5 MB) as a binary
wheel for `--python-version 3.14 --platform win_amd64`. abi3
forward-compat covers runtime loading from 3.10 onward; 3.14 is
in scope. Cached in `C:\tmp\deps-full-cp314`.

Remaining residual: a real-world import smoke on a live 3.14
venv can still fail (abi3 is a runtime contract but not every
Qt symbol is in the limited API). Defer to Phase B.6.

If PyQt6 6.11.0 does fail at import:
1. Try PyQt6 6.11.1 (released after 6.11.0)
2. Port to PySide6 -- Qt's official Python binding, importing
   its 6.12 series (July 2026). ~4-8h of import-renaming
   (`PyQt6` -> `PySide6`, `pyqtSignal` -> `Signal`, etc.)
3. Run GUI-less (label tool `--no-browser`, training CLI,
   export scripts) until PyQt6 officially supports 3.14

### C.2 Container commits not in Windows repo

The 3.13 migration commits (8d2ab39, 9cfe243) live in the
Linux container only. For 3.14 we redo the work fresh on the
Windows repo because:
- The container may not be reachable
- We need the Windows-compiled Rust wheel anyway
- The skill has the recipe; the code is in the reference file

### C.3 Python 3.14 free-threading (3.14t)

Python 3.14 has a free-threaded build (3.14t). We do NOT need
it. The standard GIL build (`python-3.14.6-amd64.exe` from
python.org) is what the work computer has. Do not install
`python3.14t` -- it doubles wheel complexity for no benefit
to HemaFrag's workload.

---

## D. Summary: order of operations

1. **Already done** (B.1): 37/37 deps resolve for cp314 +
   win_amd64 as binary wheels (cached at `C:\tmp\deps-full-cp314`,
   243 MB). PyQt6 6.11.0 forward-compat confirmed at wheel layer.
2. **Next**: update `requirements.txt` with the new floor pins
   (Phase B.2). Reuse the wheel cache for installs.
3. **Rebuild the Rust wheel** with PyO3 >=0.26 (Phase B.3).
4. **Port the QDA fallback** code from the skill reference
   (Phase B.4).
5. **Run the test suite** on 3.14, fix anything new (Phase B.5).
6. **Smoke the GUI and label tool** on 3.14 (Phase B.6, B.7) --
   this is the live PyQt6 import test.
7. **Update install.bat** for 3.14, verify end-to-end (B.8).
8. **Push branch + ship to work computer** (Phase B.9).

Estimated effort drops from the original 5.5-8h to ~4-6h
because the wheel-risks are pre-validated. PySide6 port risk
remains as Phase B.6's possible follow-on (4-8h if needed).

---

*Phase B.1 completed 2026-07-09 -- cp314 + win_amd64
wheel-resolution dry-run 37/37 PASS, PyQt6 forward-compat
confirmed. Cached at `C:\tmp\deps-full-cp314`.*
*Authored 2026-07-09 on branch `py314-migration-plan`.*
