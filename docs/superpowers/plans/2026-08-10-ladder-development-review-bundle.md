# Ladder Development Review Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a validated blind-first three-case ladder review bundle and launch HemaFrag directly into Ladder Studio with that bundle loaded.

**Architecture:** Add a pure research bundle module that validates the development manifest, copies each FSA into an isolated case directory, and writes the existing app-compatible review artifacts. Extend the Qt entry point with one optional startup argument that routes through the existing `MainWindow._open_archive_ladder_review` method after the window is shown.

**Tech Stack:** Python 3, pathlib/shutil/hashlib/csv/json, PyQt6, pytest.

## Global Constraints

- Read only the three allowed raw year roots and the current research manifests.
- Never enumerate or read the excluded backup corpus.
- Never place historical adjustment sidecars beside the copied review files.
- Write the bundle only below `D:\HemaFrag_Research\ladder\current`.
- Refuse to overwrite a non-empty bundle.
- Verify every copied FSA against the manifest SHA-256 before publication.
- Launch the app from the isolated worktree and open exactly the generated bundle.

---

### Task 1: Blind Development Bundle Builder

**Files:**
- Create: `core/research/ladder/review_bundle.py`
- Modify: `scripts/build_ladder_research_corpus.py`
- Create: `tests/test_ladder_research_review_bundle.py`

**Interfaces:**
- Consumes: `ResearchRoots`, `assert_allowed_raw_path`, and `development_manifest.json`.
- Produces: `prepare_development_review_bundle(manifest_path: Path, bundle_dir: Path, roots: ResearchRoots) -> ReviewBundleResult` and the `prepare-review` CLI command.

- [ ] **Step 1: Write failing bundle safety and artifact tests**

```python
def test_prepare_bundle_copies_fsa_without_historical_sidecar(tmp_path):
    result = prepare_development_review_bundle(manifest, bundle, roots)
    assert result.case_count == 3
    assert not list(bundle.rglob("*.ladder_adj.json"))
    assert len(load_review_bundle_worker(bundle)["rows"]) == 3


def test_prepare_bundle_rejects_manifest_hash_mismatch(tmp_path):
    with pytest.raises(ValueError, match="SHA-256"):
        prepare_development_review_bundle(bad_manifest, bundle, roots)


def test_prepare_bundle_refuses_nonempty_destination(tmp_path):
    bundle.mkdir()
    (bundle / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError, match="non-empty"):
        prepare_development_review_bundle(manifest, bundle, roots)
```

- [ ] **Step 2: Run the focused test and confirm missing-module failure**

Run: `python -m pytest tests/test_ladder_research_review_bundle.py -q`

- [ ] **Step 3: Implement validated copying and app-compatible artifacts**

Each case uses `files/<ordinal>/<original-name>.fsa`, preserving the original basename while avoiding collisions. Write `ladder_review_cases.csv` with blank labels and review-required status, `ladder_review_summary.json`, `research_case_map.json`, and `README.md`. Use a staging sibling and atomic directory rename.

- [ ] **Step 4: Add the `prepare-review` CLI route**

```powershell
python scripts/build_ladder_research_corpus.py prepare-review `
  --workspace D:\HemaFrag_Research\ladder\current
```

- [ ] **Step 5: Run focused and existing Ladder Studio I/O tests**

Run: `python -m pytest tests/test_ladder_research_review_bundle.py tests/test_tab_ladder_submodules.py -q`

- [ ] **Step 6: Commit**

```powershell
git add core/research/ladder/review_bundle.py scripts/build_ladder_research_corpus.py tests/test_ladder_research_review_bundle.py
git commit -m "feat: prepare blind ladder review bundle"
```

### Task 2: Open Bundle at Qt Startup

**Files:**
- Modify: `qt_app.py`
- Create: `tests/test_qt_app_startup_review.py`

**Interfaces:**
- Consumes: `--ladder-review-bundle <directory>` and the existing `MainWindow._open_archive_ladder_review(analysis_id, bundle_path)` method.
- Produces: `parse_startup_options(argv: list[str]) -> StartupOptions`, with Qt arguments preserved separately.

- [ ] **Step 1: Write failing argument-parsing tests**

```python
def test_parse_startup_review_bundle_removes_custom_args_from_qt_argv(tmp_path):
    options = parse_startup_options([
        "qt_app.py", "--ladder-review-bundle", str(tmp_path), "-style", "Fusion"
    ])
    assert options.review_bundle == tmp_path.resolve()
    assert options.qt_argv == ("qt_app.py", "-style", "Fusion")


def test_parse_startup_review_bundle_requires_existing_cases_csv(tmp_path):
    with pytest.raises(FileNotFoundError, match="ladder_review_cases.csv"):
        parse_startup_options(["qt_app.py", "--ladder-review-bundle", str(tmp_path)])
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `python -m pytest tests/test_qt_app_startup_review.py -q`

- [ ] **Step 3: Implement startup option parsing and delayed navigation**

Parse the custom option before `QApplication`, pass only `qt_argv` to Qt, then use `QTimer.singleShot(0, ...)` after `window.show()` to call `_open_archive_ladder_review("clonality", bundle)`.

- [ ] **Step 4: Run focused Qt and archive navigation tests**

Run: `python -m pytest tests/test_qt_app_startup_review.py tests/test_clonality_archive_runner.py tests/test_tab_ladder_submodules.py -q`

- [ ] **Step 5: Commit**

```powershell
git add qt_app.py tests/test_qt_app_startup_review.py
git commit -m "feat: open ladder review bundle at startup"
```

### Task 3: Generate, Validate, and Launch

**Files:**
- Generated: `D:\HemaFrag_Research\ladder\current\development_review_bundle`

**Interfaces:**
- Consumes: the frozen development manifest and the worktree `qt_app.py`.
- Produces: a running HemaFrag window positioned in Ladder Studio with three reachable unresolved cases.

- [ ] **Step 1: Generate the real bundle**

Run: `python scripts/build_ladder_research_corpus.py prepare-review --workspace D:\HemaFrag_Research\ladder\current`

- [ ] **Step 2: Validate hashes, case count, sidecar absence, and app loading**

Run a read-only verification that requires three copied FSA files, three reachable CSV rows, zero neighboring sidecars, and matching source/copy SHA-256 values.

- [ ] **Step 3: Run the complete Python suite**

Run: `python -m pytest tests -q`

- [ ] **Step 4: Launch HemaFrag visibly**

```powershell
Start-Process python `
  -ArgumentList @('qt_app.py', '--ladder-review-bundle', 'D:\HemaFrag_Research\ladder\current\development_review_bundle') `
  -WorkingDirectory '<isolated-worktree>'
```

- [ ] **Step 5: Confirm the process started and hand off the three-case review**

Do not save, click, or resolve cases on behalf of the chemist. The operator performs all ladder decisions manually.
