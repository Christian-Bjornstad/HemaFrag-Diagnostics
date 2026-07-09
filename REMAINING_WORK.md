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

- [ ] Install Python 3.14.6 on this dev machine (alongside 3.12)
- [ ] Create `.venv-314` and install deps in waves
- [ ] Verify PyQt6 6.11.0 imports successfully on 3.14 (THE risk)

### B.2 Dependency re-pinning

- [ ] Update `requirements.txt` with 3.14-compatible floor pins
      (numpy>=2.3, pandas>=2.3, scipy>=1.16, sklearn>=1.9,
      matplotlib>=3.11, PyQt6>=6.11, etc.)
- [ ] Install each wave and confirm no source builds needed

### B.3 Rust wheel rebuild

- [ ] Upgrade `pyo3` 0.24 -> >=0.26 in
      `fraggler-v2/crates/fraggler-kernels-py/Cargo.toml`
- [ ] Bump `requires-python` to `>=3.10,<3.16` in
      `fraggler-v2/crates/fraggler-kernels-py/pyproject.toml`
- [ ] Run `cargo check` to catch PyO3 API changes
- [ ] Rebuild wheel: `maturin build --release` with 3.14 venv
- [ ] Verify new wheel loads: `python -c "import fraggler_native"`
- [ ] Copy new wheel to `wheels/` directory

### B.4 QDA fallback port

- [ ] Port the GaussianNB fallback code from the container
      commit `9cfe243` into this Windows repo (it's in the
      `python-3.15-migration-runway` skill's reference file
      -- paste the code shape from there).
- [ ] Verify the fallback triggers on sklearn 1.9 and produces
      identical `predict_proba` shape.

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

### C.1 PyQt6 3.14 support (HIGH RISK)

Qt for Python 6.10 (Oct 2025) explicitly did not support 3.14.
PyQt6 6.11.0 (Mar 2026) ships abi3 wheels that *should* load
on 3.14. Riverbank has not publicly confirmed 3.14 support.

This is the single biggest unknown. If PyQt6 6.11.0 fails to
import on 3.14, the options are:
1. Try PyQt6 6.11.1
2. Port to PySide6 (4-8h of import-renaming work)
3. Run GUI-less until PyQt6 officially supports 3.14

**Resolution**: Phase B.1 / Phase F of the plan tests this
early. Do NOT defer -- if this blocks, the rest of the
migration is moot for the GUI.

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

1. **First**: install 3.14.6 on this dev machine, create venv,
   try `pip install PyQt6`. If that fails, STOP and decide on
   mitigation -- this is the gating risk.
2. **If PyQt6 installs**: install all deps in waves, update
   `requirements.txt`.
3. **Rebuild the Rust wheel** with PyO3 >=0.26.
4. **Port the QDA fallback** code from the skill reference.
5. **Run the test suite** on 3.14, fix anything new.
6. **Smoke the GUI and label tool** on 3.14.
7. **Update install.bat**, verify end-to-end install.
8. **Push branch**, test on the work computer.

The whole thing should fit in one work day IF PyQt6 cooperates.
If not, add a day for the PySide6 port.

---

*Authored 2026-07-09 on branch `py314-migration-plan`.*
