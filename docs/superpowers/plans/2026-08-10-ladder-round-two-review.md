# Ladder Round-Two Blind Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit no-ladder/human-error outcome, select a deterministic blind 12-suspicious-plus-6-control cohort, publish it safely, and launch Ladder Studio for round-two review.

**Architecture:** A pure label-policy module becomes the single source of truth for review resolution, rerun, fitting, and ML eligibility. A separate research cohort module joins existing diagnostics and inventory artifacts, performs deterministic stratified selection, writes a withheld allocation manifest, and delegates copying to a generalized blind-bundle publisher. Ladder Studio records exclusions through the existing annotation path without opening or saving a ladder adjustment.

**Tech Stack:** Python 3.11, dataclasses, pathlib/csv/json/hashlib, pandas, PyQt6, SQLite adjustment store, pytest.

## Global Constraints

- Use only patient-clonality FSA files from `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, and `D:\DATA\2026_data`.
- Never enumerate, read, copy, or derive records from `D:\DATA\backup`.
- Keep raw data and archive inputs read-only.
- Write generated research artifacts only below `D:\HemaFrag_Research\ladder\current`.
- Round two contains exactly 12 suspicious cases (6 LIZ, 6 ROX) and 6 controls (3 LIZ, 3 ROX).
- Every selected case has a unique content hash and physical run; exclude all three round-one hashes.
- Keep cohort allocation out of app-facing bundle artifacts until post-review finalization.
- Do not modify Rust fitting behavior or admit unresolved/excluded cases to ML training.
- Use test-first red-green cycles for every behavior change.

---

### Task 1: Central Review Label Policy

**Files:**
- Create: `core/analyses/clonality/ladder_review_labels.py`
- Modify: `core/analyses/clonality/ladder_review_gate.py`
- Modify: `gui_qt/tabs/tab_ladder/_summary.py`
- Modify: `gui_qt/tabs/tab_archive_runner.py`
- Modify: `gui_qt/tabs/tab_batch/_legacy.py`
- Test: `tests/test_ladder_review_labels.py`
- Test: `tests/test_ladder_review_gate.py`
- Test: `tests/test_tab_ladder_submodules.py`

**Interfaces:**
- Produces: `ReviewLabelPolicy`, `review_label_policy(label)`, `is_review_resolved(label)`, `is_review_rerunnable(label)`, `is_review_fitting_eligible(label)`, `is_review_ml_eligible(label)`, `RESOLVED_LABELS`, and `RERUNNABLE_LABELS`.
- Consumes: raw CSV label strings; lookup is whitespace-trimmed and case-insensitive.

- [ ] **Step 1: Write failing policy and consumer tests**

```python
def test_missing_ladder_policy_resolves_but_never_reruns_or_trains():
    label = "excluded_missing_ladder_signal"
    assert is_review_resolved(label)
    assert not is_review_rerunnable(label)
    assert not is_review_fitting_eligible(label)
    assert not is_review_ml_eligible(label)

def test_review_gate_counts_missing_ladder_exclusion_as_resolved(tmp_path):
    cases = tmp_path / "ladder_review_cases.csv"
    cases.write_text("full_path,label\na.fsa,excluded_missing_ladder_signal\n", encoding="utf-8")
    assert count_unresolved_review_cases(cases) == 0

def test_chip_state_treats_missing_ladder_exclusion_as_reviewed():
    assert chip_state({"label": "excluded_missing_ladder_signal"}) == "reviewed"
```

- [ ] **Step 2: Run the focused tests and verify the new label fails in all consumers**

Run: `python -m pytest tests/test_ladder_review_labels.py tests/test_ladder_review_gate.py tests/test_tab_ladder_submodules.py -q`

- [ ] **Step 3: Implement the frozen policy registry**

```python
@dataclass(frozen=True)
class ReviewLabelPolicy:
    resolved: bool
    rerunnable: bool
    fitting_eligible: bool
    ml_eligible: bool

REVIEW_LABEL_POLICIES = {
    "manual_adjusted": ReviewLabelPolicy(True, True, True, True),
    "reviewed_no_change": ReviewLabelPolicy(True, True, True, True),
    "excluded_missing_ladder_signal": ReviewLabelPolicy(True, False, False, False),
}
```

Derive exported sets from this mapping. Replace consumer membership checks with the semantic helpers, retaining the derived `RESOLVED_LABELS` export for compatibility.

- [ ] **Step 4: Run focused tests and the batch/archive tests**

Run: `python -m pytest tests/test_ladder_review_labels.py tests/test_ladder_review_gate.py tests/test_tab_ladder_submodules.py tests/test_clonality_archive_runner.py -q`

- [ ] **Step 5: Commit**

```powershell
git add core/analyses/clonality/ladder_review_labels.py core/analyses/clonality/ladder_review_gate.py gui_qt/tabs/tab_ladder/_summary.py gui_qt/tabs/tab_archive_runner.py gui_qt/tabs/tab_batch/_legacy.py tests/test_ladder_review_labels.py tests/test_ladder_review_gate.py tests/test_tab_ladder_submodules.py
git commit -m "feat: centralize ladder review label policy"
```

### Task 2: No-Ladder/Human-Error Action in Ladder Studio

**Files:**
- Modify: `gui_qt/tabs/tab_ladder/_legacy.py`
- Modify: `gui_qt/tabs/tab_ladder/_io.py`
- Test: `tests/test_tab_ladder_submodules.py`

**Interfaces:**
- Consumes: `excluded_missing_ladder_signal` policy from Task 1 and the existing bundle annotation writer.
- Produces: `build_review_annotation(label, note, *, reviewed_at_utc, adjustment_path="") -> dict`, `save_missing_ladder_exclusion_worker(bundle_dir, full_path, *, note, reviewed_at_utc) -> dict`, `TabLadder._exclude_current_missing_ladder_signal()`, and a `No ladder / human error` button.

- [ ] **Step 1: Write failing annotation and rerun-filter tests**

```python
def test_missing_ladder_annotation_has_no_adjustment_path():
    annotation = build_review_annotation(
        "excluded_missing_ladder_signal",
        "No usable ladder signal; preparation error.",
        reviewed_at_utc="2026-08-10T00:00:00+00:00",
    )
    assert annotation["label"] == "excluded_missing_ladder_signal"
    assert annotation["adjustment_path"] == ""

def test_missing_ladder_action_writes_no_adjustment_record(tmp_path, monkeypatch):
    fsa = tmp_path / "no-ladder.fsa"
    fsa.write_bytes(b"fsa")
    bundle = write_bundle(tmp_path, fsa)
    isolated_db = tmp_path / "adjustments.sqlite3"
    monkeypatch.setenv("HEMAFRAG_LADDER_ADJUSTMENT_DB", str(isolated_db))
    saved = save_missing_ladder_exclusion_worker(
        bundle,
        fsa,
        note="No usable ladder signal; preparation error.",
        reviewed_at_utc="2026-08-10T00:00:00+00:00",
    )
    assert saved["label"] == "excluded_missing_ladder_signal"
    assert saved["adjustment_path"] == ""
    assert load_ladder_adjustment_record(fsa) is None
    assert not isolated_db.exists()

def test_resolved_bundle_files_skip_missing_ladder_exclusion(tmp_path):
    # Construct a lightweight TabLadder-compatible object with one adjusted row
    # and one excluded row; only the adjusted path may be returned for rerun.
    files, missing, unresolved = TabLadder._resolved_review_bundle_files(fake_tab)
    assert files == [adjusted_fsa.resolve()]
    assert missing == []
    assert unresolved == 0
```

- [ ] **Step 2: Run tests and verify exclusion is currently unresolved/rerunnable or unsupported**

Run: `python -m pytest tests/test_tab_ladder_submodules.py -q`

- [ ] **Step 3: Implement annotation construction and the confirmed UI action**

Add the button beside the existing editor/rerun controls. Enable it only when the selected file belongs to a loaded review bundle. The handler asks `QMessageBox.question` for confirmation, then persists an explicit exclusion annotation through the existing worker. It must not open the ladder editor, call `save_ladder_adjustment`, create a sidecar, or add the file to `_recent_reviewed_files`.

- [ ] **Step 4: Run Ladder Studio, gate, and batch tests**

Run: `python -m pytest tests/test_tab_ladder_submodules.py tests/test_ladder_review_gate.py tests/test_run_manifest.py -q`

- [ ] **Step 5: Commit**

```powershell
git add gui_qt/tabs/tab_ladder/_legacy.py gui_qt/tabs/tab_ladder/_io.py tests/test_tab_ladder_submodules.py
git commit -m "feat: resolve missing ladder review cases"
```

### Task 3: Deterministic Mixed Cohort Selector

**Files:**
- Create: `core/research/ladder/round_two.py`
- Test: `tests/test_ladder_research_round_two.py`

**Interfaces:**
- Consumes: diagnostics records, inventory records, hashes with discovered manual corrections, three excluded round-one hashes, and seed `20260810`.
- Produces: `RoundTwoSelection`, `select_round_two_cohort(diagnostics, inventory_rows, manual_content_hashes, excluded_hashes, *, seed=20260810) -> RoundTwoSelection`, and `load_round_two_inputs(workspace: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]`.

- [ ] **Step 1: Write failing deterministic balance and isolation tests**

```python
def test_round_two_selection_is_balanced_blind_and_isolated():
    result = select_round_two_cohort(
        diagnostics, inventory, manual_hashes, first_round_hashes, seed=7
    )
    counts = Counter((case["cohort_group"], case["ladder"]) for case in result.cases)
    assert counts == {
        ("suspicious", "LIZ"): 6,
        ("suspicious", "ROX"): 6,
        ("control", "LIZ"): 3,
        ("control", "ROX"): 3,
    }
    assert len({case["content_sha256"] for case in result.cases}) == 18
    assert len({case["physical_run_key"] for case in result.cases}) == 18
    assert not first_round_hashes & {case["content_sha256"] for case in result.cases}
    assert not manual_hashes & {
        case["content_sha256"] for case in result.cases if case["cohort_group"] == "control"
    }
    assert len({case["year"] for case in result.cases}) >= 2
```

Add a second test that shuffles both inputs and requires identical selected hashes, plus shortage tests for every required group.

- [ ] **Step 2: Run the focused test and verify the selector module is missing**

Run: `python -m pytest tests/test_ladder_research_round_two.py -q`

- [ ] **Step 3: Implement normalization and deterministic diverse selection**

Join diagnostics to inventory by normalized resolved source path. Suspicious candidates require `outcome=fit_rejected_with_usable_signal`. Controls require `accepted=true`, `review_required=false`, and no manual-correction hash. Use a stable SHA-256 tie-break derived from seed, group, ladder, and content hash; greedily prefer underrepresented years, reason signatures, and assays while blocking already selected hashes and runs.

- [ ] **Step 4: Run selector and existing partition tests**

Run: `python -m pytest tests/test_ladder_research_round_two.py tests/test_ladder_research_partitions.py -q`

- [ ] **Step 5: Commit**

```powershell
git add core/research/ladder/round_two.py tests/test_ladder_research_round_two.py
git commit -m "feat: select mixed ladder review cohort"
```

### Task 4: Blind Round-Two Bundle and CLI

**Files:**
- Modify: `core/research/ladder/review_bundle.py`
- Modify: `core/research/ladder/round_two.py`
- Modify: `scripts/build_ladder_research_corpus.py`
- Modify: `tests/test_ladder_research_review_bundle.py`
- Modify: `tests/test_ladder_research_round_two.py`

**Interfaces:**
- Consumes: `RoundTwoSelection`, `ResearchRoots`, and the current research workspace.
- Produces: `prepare_blind_review_bundle(records, bundle_dir, roots, *, bundle_name, public_case_fields) -> ReviewBundleResult`, `prepare_round_two_review(workspace, *, seed=20260810) -> RoundTwoReviewResult`, and CLI command `prepare-round-two`.

- [ ] **Step 1: Write failing publication and blindness tests**

```python
def test_round_two_publication_keeps_allocation_outside_bundle(tmp_path):
    result = prepare_round_two_review(workspace, seed=7)
    assert result.case_count == 18
    assert result.withheld_manifest == workspace / "round_2_selection_withheld.json"
    public_paths = list(result.bundle_dir.glob("*.json")) + [
        result.bundle_dir / "ladder_review_cases.csv"
    ]
    public_text = "\n".join(path.read_text(encoding="utf-8") for path in public_paths)
    assert "cohort_group" not in public_text
    assert "selection_reason" not in public_text
    assert not list(result.bundle_dir.rglob("*.ladder_adj.json"))
```

Add tests that refuse a non-empty bundle or existing withheld manifest, retain the existing three-case development wrapper, and leave no published artifacts after a hash failure.

- [ ] **Step 2: Run focused tests and verify round-two publication is unavailable**

Run: `python -m pytest tests/test_ladder_research_review_bundle.py tests/test_ladder_research_round_two.py -q`

- [ ] **Step 3: Generalize the existing atomic publisher and implement round-two orchestration**

The app CSV contains only copied path, filename, case ID, assay, ladder, generic blind-review reason, and blank annotation fields. The public case map contains identity/join fields but no cohort group, risk, outcome, failure family, or selection rationale. Write the complete allocation and baseline preview scans only to `round_2_selection_withheld.json`.

- [ ] **Step 4: Add and exercise the CLI parser route**

Run: `python scripts/build_ladder_research_corpus.py prepare-round-two --help`

- [ ] **Step 5: Run research and Ladder Studio I/O tests**

Run: `python -m pytest tests/test_ladder_research_review_bundle.py tests/test_ladder_research_round_two.py tests/test_tab_ladder_submodules.py -q`

- [ ] **Step 6: Commit**

```powershell
git add core/research/ladder/review_bundle.py core/research/ladder/round_two.py scripts/build_ladder_research_corpus.py tests/test_ladder_research_review_bundle.py tests/test_ladder_research_round_two.py
git commit -m "feat: prepare round-two ladder review bundle"
```

### Task 5: Post-Review Outcome Processor

**Files:**
- Modify: `core/ladder_adjustment_store.py`
- Modify: `core/research/ladder/round_two.py`
- Modify: `scripts/build_ladder_research_corpus.py`
- Modify: `tests/test_manual_ladder_rerun.py`
- Modify: `tests/test_ladder_research_round_two.py`

**Interfaces:**
- Consumes: a fully resolved round-two CSV, withheld selection manifest, and bundle-local adjustment database.
- Produces: optional `database_path` parameter on `load_ladder_adjustment_record`, `finalize_round_two_review(workspace: Path) -> RoundTwoOutcomeResult`, `round_2_review_outcomes.json`, `round_2_review_comparison.md`, and CLI command `finalize-round-two`.

- [ ] **Step 1: Write failing database isolation and outcome tests**

```python
def test_adjustment_loader_can_target_bundle_database(tmp_path):
    save_ladder_adjustment_record(fsa, payload)
    assert load_ladder_adjustment_record(fsa, database_path=isolated_db) is None

def test_finalize_round_two_excludes_missing_ladder_from_metrics(tmp_path):
    result = finalize_round_two_review(workspace)
    assert result.total_count == 18
    assert result.excluded_count == 1
    assert result.fitting_evaluation_count == 17
    assert result.ml_eligible_count == 17
```

Add a test requiring finalization to fail while any row is unresolved and a test that manual anchors come from the isolated database rather than the user's default store.

- [ ] **Step 2: Run focused tests and verify missing APIs fail**

Run: `python -m pytest tests/test_manual_ladder_rerun.py tests/test_ladder_research_round_two.py -q`

- [ ] **Step 3: Implement explicit database loading and finalization**

For `manual_adjusted`, read fresh scan indices from verified `selected_peaks`. For `reviewed_no_change`, use the withheld current Rust preview. For `excluded_missing_ladder_signal`, emit an empty anchor list and exclude it from fitting/ML denominators. Reveal cohort groups only in the generated post-review files.

- [ ] **Step 4: Add the finalize CLI route and run focused tests**

Run: `python -m pytest tests/test_manual_ladder_rerun.py tests/test_ladder_research_round_two.py tests/test_ladder_review_gate.py -q`

- [ ] **Step 5: Commit**

```powershell
git add core/ladder_adjustment_store.py core/research/ladder/round_two.py scripts/build_ladder_research_corpus.py tests/test_manual_ladder_rerun.py tests/test_ladder_research_round_two.py
git commit -m "feat: finalize mixed ladder review outcomes"
```

### Task 6: Real-Data Publication, Verification, and Launch

**Files:**
- Generated: `D:\HemaFrag_Research\ladder\current\round_2_selection_withheld.json`
- Generated: `D:\HemaFrag_Research\ladder\current\round_2_review_bundle`

**Interfaces:**
- Consumes: current inventory, diagnostics, manual corrections, round-one outcomes, and the isolated worktree app.
- Produces: one live HemaFrag window loaded with 18 blank, reachable round-two cases.

- [ ] **Step 1: Generate the real cohort and bundle**

Run: `python scripts/build_ladder_research_corpus.py prepare-round-two --workspace D:\HemaFrag_Research\ladder\current --seed 20260810`

- [ ] **Step 2: Independently validate the real artifacts**

Require exactly 18 CSV rows and FSA copies, 12/6 withheld allocation, 6/6 suspicious ladder balance, 3/3 control ladder balance, 18 unique hashes and runs, zero first-round hashes, zero sidecars, zero hash mismatches, 18 blank labels, and no pre-existing bundle adjustment database. Load the bundle through `load_review_bundle_worker` and require zero missing paths.

- [ ] **Step 3: Run the complete suite**

Run: `python -m pytest tests -q`

- [ ] **Step 4: Launch HemaFrag with the isolated store**

```powershell
$bundle = 'D:\HemaFrag_Research\ladder\current\round_2_review_bundle'
$env:HEMAFRAG_LADDER_ADJUSTMENT_DB = Join-Path $bundle 'ladder_adjustments.sqlite3'
Start-Process python -ArgumentList @('qt_app.py', '--ladder-review-bundle', $bundle) -WorkingDirectory 'C:\Users\molpa\Documents\HemaFrag\.worktrees\ladder-fitting-historical-research'
```

- [ ] **Step 5: Confirm the visible process and hand off review**

Verify the HemaFrag window is responding and the CSV still has 18 blank labels. Do not click, classify, adjust, reveal the withheld manifest, or finalize outcomes on behalf of the chemist.
