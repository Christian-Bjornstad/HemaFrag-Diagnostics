# Plan 05 — Scripts & packaging review

> Branch: `code-cleanup` (off \`codex-clonality-ladder-finalize-2026-05-14\`).
> Test baseline: \`Ran 33 tests, OK\` via
> \`QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests\`.
> Reviewer responsibility: **real findings only**.

This plan covers the four live runtime scripts, the Windows / Linux /
macOS packaging chain, the PyInstaller spec, and the existing
`.github/workflows/ci.yml`.

---

## 1. Architecture summary

- **Four live runtime scripts** (Phase 1 kept only these four):
  - `scripts/run_flt3_rox500_qc_all_injections.py` (the FLT3 ROX500
    wrapper).
  - `scripts/run_flt3_liz500_qc_all_injections.py` (the FLT3 LIZ500
    wrapper, 1172 lines).
  - `scripts/render_clonality_interpretation_annotation_html.py`
    (clonality interpretation annotation panel, 654 lines).
  - `scripts/train_clonality_interpretation_quick_model.py`
    (annotation training scaffold, 303 lines).

- **Packaging chain** (Project Memory *Hygiene* note):
  - Windows release: `packaging/build_windows.sh` + docker
    `packaging/Dockerfile.windows`. Cross-compiles
    `fraggler-cli.exe` via Rust + mingw before Wine + PyInstaller.
  - Windows windowed builds have no console streams; runtime must
    tolerate `sys.stdout`/`sys.stderr == None`.
  - Windows frozen runtime searches `fraggler-cli.exe` in
    `_MEIPASS`, beside `HemaFrag.exe`, or in `_internal`.
  - Linux wheels: `packaging/download_linux_wheels*.sh`.
  - Runtime hooks: `packaging/hooks/{hook-bokeh,hook-fraggler,hook-panel,
    runtime_desktop,patch_dis}.py`.

- **PyInstaller spec**: `HemaFrag.spec` (1.5 KB) - declares data
  copies for `assets/`, `app.py`, etc.

- **CI workflow**: `.github/workflows/ci.yml` (45 lines, two jobs):
  - `python` job on macOS-latest, Python 3.10, installs
    `requirements.txt`, runs py_compile on a list of files, and runs
    two test files (`tests/test_ladder_review_gate.py`,
    `tests/test_water_filter.py`).
  - `rust` job on macOS-latest, in `fraggler-v2/`: `cargo build
    --release` and `cargo test --workspace`.

## 2. File inventory

### Scripts (`scripts/`)

```
  654  scripts/render_clonality_interpretation_annotation_html.py
 1172  scripts/run_flt3_liz500_qc_all_injections.py
   13  scripts/run_flt3_rox500_qc_all_injections.py
  303  scripts/train_clonality_interpretation_quick_model.py
 2142  total
```

### Packaging

```
   41  packaging/build_linux.sh
   43  packaging/build_mac.sh
   31  packaging/build_windows.sh
   42  packaging/download_linux_wheels.sh
   40  packaging/download_linux_wheels_docker.sh
    8  packaging/hooks/hook-bokeh.py
    7  packaging/hooks/hook-fraggler.py
    9  packaging/hooks/hook-panel.py
   19  packaging/hooks/patch_dis.py
   39  packaging/hooks/runtime_desktop.py
   54  packaging/linux_system_deps.sh
  333  total
```

### Root files

```
   1094  AGENTS.md
   3570  CLEANUP_PLAYBOOK.md
   1486  HemaFrag.spec
   1760  README.md
   3244  THIRD_PARTY_NOTICES.md
    623  app.py
    166  app_meta.py
   9927  build_qt.py
  29138  config.py
    577  memory.md
   5720  qt_app.py
```

## 3. Cross-reference map

- `scripts/run_flt3_liz500_qc_all_injections.py` imports:
  - `core.analysis.compute_ladder_qc_metrics`
  - `core.analyses.flt3.pipeline` (test imports + the public surface)
  - `core.analyses.flt3.classification`
  - `core.analyses.flt3.qc_tracker.resolve_global_flt3_tracking_path`
  - `core.analyses.flt3.rox500_exclusions`
- `scripts/run_flt3_rox500_qc_all_injections.py` is imported by
  `gui_qt/tabs/tab_flt3_validation.py` (lazy).
- `scripts/render_clonality_interpretation_annotation_html.py` and
  `scripts/train_clonality_interpretation_quick_model.py` are
  imported by `tests/test_clonality_interpretation_v1.py`.

## 4. Intentional tech debt (do not churn)

- Windows frozen-runtime `sys.stdout`/`sys.stderr` None-tolerance
  contract (Project Memory *Hygiene*) is enforced across the whole
  frozen build. Don't remove; it's load-bearing.
- `packaging/hooks/patch_dis.py` mutates dis.dis to silence PyInstaller
  errors. Don't refactor without a Windows packaging test.
- `packaging/runtime_desktop.py` may be importable from
  `App/_internal/`. Don't introduce another runtime hook without
  testing Wine.
- `KNOWN_CLONALITY_BACKFILL_SKIP_FILES` allowlist in `core.batch` is
  curated (per Project Memory *Hygiene*). Don't auto-extend.

## 5. Actionable task list

### Task 1 — Fix `.github/workflows/ci.yml` for Phase 5/6 paths
- **Scope**: today CI references `gui_qt/tabs/tab_batch.py`,
  `gui_qt/tabs/tab_ladder.py`, `gui_qt/dialogs/ladder_dialog.py` —
  all three converted to packages in Phase 5, so the
  `py_compile` step silently misses them. Update the workflow's
  `py_compile` block to point at the new package paths or to a
  glob.
- **Why**: a CI matrix green today proves only what the PyInstaller
  reach can see, not the package versions.
- **Acceptance**: CI workflow updated; tests still 33/33 locally.
- **Commit**: `ci: update py_compile targets after Phase 5 package conversions`
- **Risk**: low (CI configuration only).  **Effort**: S.

### Task 2 — CI: add `core/analyses/clonality/__init__.py` and other package paths
- **Scope**: extend the workflow's py_compile targets to cover
  the new packages:
  - `core/analysis/__init__.py` + `core/analysis/_legacy.py` + `core/analysis/_constants.py`
  - `core/analyses/flt3/pipeline/_legacy.py`
  - `core/rust_bridge/_legacy.py` + `core/rust_bridge/_constants.py`
  - `core/plotting_plotly/_legacy.py` + `core/html_reports/_legacy.py`
  - `gui_qt/tabs/tab_batch/` etc.
- **Why**: keep CI compile-check honest.
- **Acceptance**: CI py_compile on full module set.
- **Commit**: `ci: enumerate package files in py_compile step`
- **Risk**: low.  **Effort**: S.

### Task 3 — Run all unittest tests in CI
- **Scope**: today CI runs only
  `tests/test_ladder_review_gate.py tests/test_water_filter.py`.
  Extend to `python3 -m unittest discover -s tests`.
- **Why**: Plan 01-06 add more tests; CI must exercise them.
- **Acceptance**: CI runs the full suite.
- **Commit**: `ci: run full unittest discover in CI`
- **Risk**: low.  **Effort**: S.

### Task 4 — Coverage gate (optional follow-up)
- **Scope**: today CI does not measure coverage. If/when desired,
  add `pip install coverage`, run `coverage run -m unittest discover
  -s tests`, and report on PRs.
- **Why**: Plan 06 identifies coverage gaps; CI enforcement would
  prevent regression.
- **Acceptance**: optional; tracked but not auto-applied.
- **Commit**: `ci: add coverage measurement workflow`
- **Risk**: low.  **Effort**: S.

### Task 5 — `scripts/run_flt3_rox500_qc_all_injections.py` docstring
- **Scope**: 13 lines. Add a top-of-file module docstring
  describing what this wrapper does, contract, command-line
  examples. Compare with the LIZ500 sibling's docstring (which is
  1172 lines of code; minimal docstring).
- **Why**: thin wrappers deserve an authoritative reference.
- **Acceptance**: docstring in place.
- **Commit**: `docs(scripts): add docstring to run_flt3_rox500_qc_all_injections.py`
- **Risk**: low.  **Effort**: S.

### Task 6 — PyInstaller spec: drop dead `app.py` reference
- **Scope**: `HemaFrag.spec` line 8 has `datas=[(..., ('app.py', '.'))]`.
  Cross-reference: Plan 01 Task 6 finds that `app.py` may be unused
  by Python imports; the spec line is potentially dead.
- **Why**: tightening the spec reduces bundle size.
- **Acceptance**: `app.py` is safely removable; spec line removed.
- **Commit**: `chore: drop dead app.py from HemaFrag.spec datas`
- **Risk**: medium (cross-cutting; verify Windows build).
  **Effort**: S.

### Task 7 — `requirements.txt`: pin Python 3.10 baseline
- **Scope**: `.github/workflows/ci.yml` uses Python 3.10; the local
  development uses 3.11. Both are currently in the requirements. Pin
  the lower bound `python_requires=">=3.10,<3.13"` (or similar) in
  a `setup.cfg`/`pyproject.toml` if/when added.
- **Why**: explicit Python-version support.
- **Acceptance**: Python version policy documented.
- **Commit**: `chore: document supported Python versions (3.10-3.12)`
- **Risk**: low.  **Effort**: S.

## 6. Verification

```
$ wc -l /workspace/hemafrag/scripts/*.py
   13  scripts/run_flt3_rox500_qc_all_injections.py
 1172  scripts/run_flt3_liz500_qc_all_injections.py
  654  scripts/render_clonality_interpretation_annotation_html.py
  303  scripts/train_clonality_interpretation_quick_model.py
 2142  total

$ wc -l /workspace/hemafrag/packaging
  333  total

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
