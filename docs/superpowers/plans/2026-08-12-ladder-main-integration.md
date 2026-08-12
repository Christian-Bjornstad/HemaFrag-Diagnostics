# Ladder Improvements Main Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the complete validated historical ladder-fitting work into the current `main` line while preserving the merged Clinical Workbench UI and restoring the polished README.

**Architecture:** Merge `codex/ladder-fitting-historical-research` into an isolated branch created from `origin/main`. The ladder branch is authoritative for Rust fitting, research evidence, validation tests, and wheel version `0.1.2`; current `main` is authoritative for the original icon artwork, stable desktop identity, Labeling-first navigation, redesigned About page, and compact Ladder Editor presentation.

**Tech Stack:** Git, Rust/Cargo, PyO3/maturin ABI3 wheel, Python 3.11+, PyQt6, pytest.

## Global Constraints

- Never read from or test against `D:\DATA\backup`.
- Preserve all validated ladder research commits and their provenance files.
- Preserve the original committed HemaFrag icon artwork.
- Keep ML Training out of the application navigation; keep Labeling accessible.
- Rebuild the Windows Rust wheel after resolving Rust changes.
- Do not merge into `main` until Rust tests, Python tests, wheel verification, and a real patient Clonality smoke test pass.

---

### Task 1: Record integration baselines

**Files:**
- Create: `docs/superpowers/plans/2026-08-12-ladder-main-integration.md`

- [ ] Verify `origin/main` contains PR #4 and does not contain commit `0ad2783`.
- [ ] Verify the integration worktree is on `codex/restore-readme` and clean except for planned README/plan changes.
- [ ] Run `python -m pytest -q` on the pre-merge baseline and require zero failures.

### Task 2: Merge historical ladder work

**Files:**
- Merge all tracked files from `codex/ladder-fitting-historical-research`.
- Resolve conflicts only where both branches changed the same file.

- [ ] Commit the README/plan baseline so the merge starts from a recoverable save point.
- [ ] Run `git merge --no-ff codex/ladder-fitting-historical-research`.
- [ ] For Rust engine, ladder research, validation, and wheel conflicts, retain the historical branch implementation.
- [ ] For icon artwork and Clinical Workbench navigation/About conflicts, retain current-main behavior.
- [ ] For Ladder Editor conflicts, combine the historical fitting/review behavior with the current compact presentation.
- [ ] Confirm no conflict markers remain with `rg -n "^(<<<<<<<|=======|>>>>>>>)"`.

### Task 3: Reconcile user-facing contracts

**Files:**
- Modify: `README.md`
- Modify as needed: `app_meta.py`, `app_resources.py`, `qt_app.py`, `build_qt.py`
- Modify as needed: `gui_qt/main_window.py`, `gui_qt/tabs/tab_about.py`, `gui_qt/dialogs/ladder_dialog/_legacy.py`

- [ ] Restore the centered icon, badges, workflow, quick-start, packaging, repository map, and safety sections from the polished README.
- [ ] Document Labeling rather than ML Training in application navigation.
- [ ] Point Windows installation to the committed `fraggler_kernels-0.1.2-cp310-abi3-win_amd64.whl`.
- [ ] Check every local README link and image target exists.
- [ ] Confirm `assets/app_icon.png`, `.ico`, and `.icns` match the original icon artwork from PR #4.

### Task 4: Verify Rust and the wheel

**Files:**
- Verify: `fraggler-v2/**`
- Rebuild: `wheels/fraggler_kernels-0.1.2-cp310-abi3-win_amd64.whl`

- [ ] Run `cargo fmt --all -- --check` in `fraggler-v2`.
- [ ] Run `cargo test --workspace --all-targets` in `fraggler-v2`.
- [ ] Run `cargo check -p fraggler-kernels-py` in `fraggler-v2`.
- [ ] Build the ABI3 Windows wheel with the repository's established maturin command.
- [ ] Replace the committed `0.1.2` wheel only with the verified build and confirm `fraggler_native.is_available()` is true after installation in a temporary environment.

### Task 5: Verify the integrated application

**Files:**
- Test: `tests/**`

- [ ] Run focused ladder, resource, navigation, About, and editor-layout tests.
- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run `python -m compileall -q app_meta.py app_resources.py build_qt.py qt_app.py gui_qt core tests`.
- [ ] Load one patient Clonality `.fsa` outside `D:\DATA\backup`, inspect metadata, and open the Ladder Editor without saving.
- [ ] Confirm the real trace, QC panel, controls, and action bar render correctly.

### Task 6: Review and publish

**Files:**
- Review all changes relative to `origin/main`.

- [ ] Run `git diff --check origin/main` and inspect changed files for accidental data or generated scratch output.
- [ ] Confirm the ladder tip commit and wheel commit are ancestors of the integration branch.
- [ ] Conduct correctness, readability, architecture, security, and performance review.
- [ ] Commit conflict resolutions and verification updates with descriptive messages.
- [ ] Push `codex/restore-readme` and create a pull request against `main` summarizing ladder evidence, wheel build, UI preservation, and test results.
