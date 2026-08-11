# Rust Ladder Staged-Rescue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve automatic LIZ and ROX ladder fitting with deterministic two-second and ten-second rescue tiers, then prove the change with 40 reviewed development files and 60 locked blind validation files in HemaFrag.

**Architecture:** Preserve the current fitter as Tier 0 and as an arbiter finalist. Add a focused local-search Tier 1 and a bounded global beam-search Tier 2 in a new Rust module, score every candidate through one shared arbiter, and expose tier diagnostics without breaking existing consumers. A separate Python experiment module owns patient-only 40/60 selection, blind bundle publication, freeze enforcement, finalization, and promotion reporting.

**Tech Stack:** Rust 2024 workspace (`fraggler-core`, `fraggler-cli`), Python 3.11, PyQt6, SQLite adjustment store, JSON/CSV/NDJSON, pytest, Cargo test.

## Global Constraints

- Use patient-clonality files only.
- Use raw data only from `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, and `D:\DATA\2026_data`.
- Never enumerate, read, copy, or derive records from `D:\DATA\backup`.
- Keep raw and archive inputs read-only.
- Write generated research artifacts only below `D:\HemaFrag_Research\ladder\current`.
- Preserve deterministic results, existing safety checks, complete monotonic ladders, and current exact fits.
- Do not lower acceptance thresholds merely to reduce manual review.
- LIZ requires exactly 16 strictly increasing anchors; ROX requires exactly 21.
- Tier 1 has a deterministic operation budget plus a two-second watchdog; Tier 2 has a deterministic operation budget plus a ten-second watchdog.
- An incomplete watchdog-interrupted tier is discarded; return the last completed deterministic tier.
- The 60-file validation wave cannot be opened, finalized, benchmarked as gold, or used for tuning before a candidate freeze manifest exists.
- All behavior changes use strict red-green-refactor cycles.

## Locked real-pool quotas

The refreshed 2026-08-11 canonical inventory, after patient filtering and exclusion of round-one and round-two hashes, contains 145 unique control-LIZ runs, 18 control-ROX runs, 8 suspicious-LIZ runs, and 9 suspicious-ROX runs. One ROX run is shared between the control and suspicious strata, so the globally disjoint quota leaves one ROX slot unused and assigns it to control LIZ:

| Wave | Control LIZ | Control ROX | Suspicious LIZ | Suspicious ROX | Total |
|---|---:|---:|---:|---:|---:|
| Development | 25 | 8 | 3 | 4 | 40 |
| Validation | 41 | 9 | 5 | 5 | 60 |

Selection occurs jointly across both waves so all 100 content hashes and normalized physical-run keys are globally unique. Prefer exclusive scarce-group runs before shared runs, then maximize year, assay, reason-signature, and search-tier diversity.

---

### Task 1: Fit-Improvement Experiment Contracts and Joint Selector

**Files:**
- Create: `core/research/ladder/fit_improvement.py`
- Create: `tests/test_ladder_fit_improvement.py`

**Interfaces:**
- Consumes: normalized inventory and diagnostics rows, reviewed/excluded content hashes, seed `20260811`.
- Produces: `WaveQuota`, `FitImprovementCase`, `FitImprovementSelection`, `DEVELOPMENT_QUOTAS`, `VALIDATION_QUOTAS`, and `select_fit_improvement_waves(...) -> FitImprovementSelection`.

- [ ] **Step 1: Write failing patient, quota, isolation, and determinism tests**

```python
def test_select_fit_improvement_waves_is_patient_only_balanced_and_globally_disjoint():
    selected = select_fit_improvement_waves(
        diagnostics,
        inventory,
        excluded_hashes=prior_review_hashes,
        seed=20260811,
    )
    assert Counter((c.wave, c.cohort_group, c.ladder) for c in selected.cases) == {
        ("development", "control", "LIZ"): 25,
        ("development", "control", "ROX"): 8,
        ("development", "suspicious", "LIZ"): 3,
        ("development", "suspicious", "ROX"): 4,
        ("validation", "control", "LIZ"): 41,
        ("validation", "control", "ROX"): 9,
        ("validation", "suspicious", "LIZ"): 5,
        ("validation", "suspicious", "ROX"): 5,
    }
    assert {c.sample_kind for c in selected.cases} == {"patient"}
    assert len({c.content_sha256 for c in selected.cases}) == 100
    assert len({c.physical_run_key.casefold() for c in selected.cases}) == 100
    assert not prior_review_hashes & {c.content_sha256 for c in selected.cases}

def test_select_fit_improvement_waves_is_input_order_independent():
    expected = select_fit_improvement_waves(diagnostics, inventory, excluded_hashes=set())
    random.Random(7).shuffle(diagnostics)
    random.Random(9).shuffle(inventory)
    assert select_fit_improvement_waves(
        diagnostics, inventory, excluded_hashes=set()
    ) == expected
```

Add shortage tests for each exact stratum, case-insensitive physical-run conflicts, diagnostic/inventory hash mismatch, non-patient rows, prior-review hashes, missing year, and joint cross-wave run conflicts.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_ladder_fit_improvement.py -q`

Expected: collection fails because `core.research.ladder.fit_improvement` does not exist.

- [ ] **Step 3: Implement immutable contracts and deterministic joint backtracking**

```python
@dataclass(frozen=True)
class WaveQuota:
    wave: str
    cohort_group: str
    ladder: str
    count: int

DEVELOPMENT_QUOTAS = (
    WaveQuota("development", "control", "LIZ", 25),
    WaveQuota("development", "control", "ROX", 8),
    WaveQuota("development", "suspicious", "LIZ", 3),
    WaveQuota("development", "suspicious", "ROX", 4),
)
VALIDATION_QUOTAS = (
    WaveQuota("validation", "control", "LIZ", 41),
    WaveQuota("validation", "control", "ROX", 9),
    WaveQuota("validation", "suspicious", "LIZ", 5),
    WaveQuota("validation", "suspicious", "ROX", 5),
)
```

Normalize paths, hashes, runs, sample kind, ladder, year, assay, reason signature, search tier, and current preview. Select all eight strata in one bounded backtracking pass. Use SHA-256 tie-breaks derived from `fit-improvement-v1|seed|wave|group|ladder|content_hash`, then independently blind-order each wave before assigning public IDs.

- [ ] **Step 4: Run focused and round-two selector tests**

Run: `python -m pytest tests/test_ladder_fit_improvement.py tests/test_ladder_research_round_two.py -q`

Expected: PASS with round-two behavior unchanged.

- [ ] **Step 5: Commit**

```powershell
git add core/research/ladder/fit_improvement.py tests/test_ladder_fit_improvement.py
git commit -m "feat: select ladder fit improvement waves"
```

### Task 2: Blind Wave Publication, Finalization, and Freeze Contracts

**Files:**
- Modify: `core/research/ladder/fit_improvement.py`
- Modify: `core/research/ladder/review_bundle.py`
- Modify: `scripts/build_ladder_research_corpus.py`
- Modify: `tests/test_ladder_fit_improvement.py`
- Modify: `tests/test_ladder_research_cli.py`

**Interfaces:**
- Produces: `prepare_fit_improvement_experiment(workspace, seed=20260811)`, `finalize_fit_improvement_wave(workspace, wave)`, `freeze_fit_candidate(workspace, binary, configuration)`, `assert_validation_unlocked(workspace)`, and CLI commands `prepare-fit-improvement`, `finalize-fit-development`, `freeze-fit-candidate`, `finalize-fit-validation`.

- [ ] **Step 1: Write failing publication, blindness, freeze, and finalization tests**

```python
def test_prepare_fit_improvement_publishes_two_blind_waves_atomically(tmp_path):
    result = prepare_fit_improvement_experiment(workspace, seed=7, roots=fixture_roots)
    assert result.development.case_count == 40
    assert result.validation.case_count == 60
    assert not (result.development.bundle_dir / "ladder_adjustments.sqlite3").exists()
    assert not (result.validation.bundle_dir / "ladder_adjustments.sqlite3").exists()
    public = read_all_public_bundle_text(result.development.bundle_dir)
    assert "cohort_group" not in public
    assert "selection_reason" not in public

def test_validation_requires_hash_bound_freeze_manifest(tmp_path):
    with pytest.raises(ValueError, match="frozen candidate"):
        finalize_fit_improvement_wave(workspace, "validation", roots=fixture_roots)
```

Also test exact 40/60 counts, unique hashes/runs across both waves, copy containment, byte re-hashing, no sidecars, existing-target refusal, rollback after copy/hash failure, unresolved rows, incomplete anchors, exclusion contradictions, and freeze binary/configuration hash validation.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_ladder_fit_improvement.py tests/test_ladder_research_cli.py -q`

- [ ] **Step 3: Implement atomic experiment publication**

Publish below `workspace / "rust_fit_improvement"`:

```text
development_40/
validation_60/
development_selection_withheld.json
validation_selection_withheld.json
experiment_manifest.json
```

The public CSV fields remain the established blind-bundle fields. The experiment manifest stores source inventory/diagnostic fingerprints and exact quotas, but not app-facing cohort allocation. Stage both bundles and both withheld manifests before publishing any target.

- [ ] **Step 4: Implement strict wave finalization and candidate freeze**

Development finalization accepts exactly 40 resolved rows. Validation finalization accepts exactly 60 and calls `assert_validation_unlocked`. The freeze command hashes the release CLI, records the Cargo/git revision and configuration fingerprint, verifies a completed development outcome, and writes `candidate_freeze_manifest.json` atomically.

- [ ] **Step 5: Add CLI parser routes and help tests**

```powershell
python scripts/build_ladder_research_corpus.py prepare-fit-improvement --help
python scripts/build_ladder_research_corpus.py finalize-fit-development --help
python scripts/build_ladder_research_corpus.py freeze-fit-candidate --help
python scripts/build_ladder_research_corpus.py finalize-fit-validation --help
```

- [ ] **Step 6: Run research tests**

Run: `python -m pytest tests/test_ladder_fit_improvement.py tests/test_ladder_research_review_bundle.py tests/test_ladder_research_round_two.py tests/test_ladder_research_cli.py -q`

- [ ] **Step 7: Commit**

```powershell
git add core/research/ladder/fit_improvement.py core/research/ladder/review_bundle.py scripts/build_ladder_research_corpus.py tests/test_ladder_fit_improvement.py tests/test_ladder_research_cli.py
git commit -m "feat: publish blinded ladder improvement waves"
```

### Task 3: Ladder Studio Wave Progress and Validation Lock

**Files:**
- Modify: `qt_app.py`
- Modify: `gui_qt/tabs/tab_ladder/_io.py`
- Modify: `gui_qt/tabs/tab_ladder/_legacy.py`
- Modify: `gui_qt/tabs/tab_ladder/_summary.py`
- Modify: `tests/test_qt_app_startup.py`
- Modify: `tests/test_tab_ladder_submodules.py`

**Interfaces:**
- Consumes: `experiment_wave` and optional `freeze_manifest` from bundle summary metadata.
- Produces: `assert_review_bundle_open_allowed(bundle_dir)`, a visible `Reviewed N / Total — Remaining M` banner, and refusal to open `validation_60` before freeze.

- [ ] **Step 1: Write failing startup-lock and progress tests**

```python
def test_validation_bundle_cannot_open_before_candidate_freeze(tmp_path):
    bundle = write_fit_wave_bundle(tmp_path, wave="validation", frozen=False)
    with pytest.raises(ValueError, match="frozen candidate"):
        assert_review_bundle_open_allowed(bundle)

def test_review_progress_text_counts_exclusions_as_resolved():
    rows = [{"label": "manual_adjusted"}, {"label": ""},
            {"label": "excluded_missing_ladder_signal"}]
    assert review_progress_text(rows) == "Reviewed 2 / 3 — Remaining 1"
```

Add a startup test proving the validation check runs before `QApplication`, while the bundle-local adjustment DB override remains intact.

- [ ] **Step 2: Run focused GUI tests and verify RED**

Run: `python -m pytest tests/test_qt_app_startup.py tests/test_tab_ladder_submodules.py -q`

- [ ] **Step 3: Implement validation lock and progress banner**

Keep all cohort fields withheld. Refresh the banner after bundle load, manual save, reviewed-no-change, exclusion, and rerun-status updates. Reuse `is_review_resolved` so future labels work without UI membership changes.

- [ ] **Step 4: Run focused GUI and label-policy tests**

Run: `python -m pytest tests/test_qt_app_startup.py tests/test_tab_ladder_submodules.py tests/test_ladder_review_labels.py tests/test_ladder_review_gate.py -q`

- [ ] **Step 5: Commit**

```powershell
git add qt_app.py gui_qt/tabs/tab_ladder/_io.py gui_qt/tabs/tab_ladder/_legacy.py gui_qt/tabs/tab_ladder/_summary.py tests/test_qt_app_startup.py tests/test_tab_ladder_submodules.py
git commit -m "feat: guide locked ladder review waves"
```

### Task 4: Publish and Review the Real Development Wave

**Files:**
- Generated: `D:\HemaFrag_Research\ladder\current\rust_fit_improvement\development_40`
- Generated: `D:\HemaFrag_Research\ladder\current\rust_fit_improvement\validation_60`
- Generated: withheld manifests and `experiment_manifest.json` in the same experiment directory.

**Interfaces:**
- Consumes: fresh provenance-safe diagnostics and the canonical patient inventory.
- Produces: one audited 40-case app review and one unopened 60-case locked validation bundle.

- [ ] **Step 1: Refresh inventory and diagnostics under canonical production contracts**

```powershell
python scripts/build_ladder_research_corpus.py refresh-inventory --workspace D:\HemaFrag_Research\ladder\current
python scripts/build_ladder_research_corpus.py diagnose --workspace D:\HemaFrag_Research\ladder\current --cli C:\Users\molpa\Documents\HemaFrag\fraggler-v2\target\release\fraggler-cli.exe --max-workers 3 --timeout-seconds 30 --resume
```

- [ ] **Step 2: Publish the real experiment**

Run: `python scripts/build_ladder_research_corpus.py prepare-fit-improvement --workspace D:\HemaFrag_Research\ladder\current --seed 20260811`

- [ ] **Step 3: Independently audit both waves**

Require exact quotas, 100 globally unique hashes/runs, patient-only identity, three-year coverage in each wave, zero prior-review overlap, zero sidecars, zero copied-file hash mismatches, blank labels, no adjustment DB, and zero missing paths through `load_review_bundle_worker`. Confirm `validation_60` refuses app startup before freeze.

- [ ] **Step 4: Run the complete Python suite**

Run: `python -m pytest tests -q`

- [ ] **Step 5: Launch only `development_40`**

```powershell
Start-Process python -ArgumentList @(
  'qt_app.py',
  '--ladder-review-bundle',
  'D:\HemaFrag_Research\ladder\current\rust_fit_improvement\development_40'
) -WorkingDirectory 'C:\Users\molpa\Documents\HemaFrag\.worktrees\ladder-fitting-historical-research'
```

- [ ] **Step 6: Pause for the chemist to resolve all 40 cases**

Do not open validation, infer labels, click, adjust, or finalize on the user's behalf.

### Task 5: Finalize Development Gold and Build the Real Regression Harness

**Files:**
- Modify: `core/research/ladder/fit_improvement.py`
- Modify: `scripts/benchmark_rust_ladder.py`
- Modify: `tests/test_ladder_fit_improvement.py`
- Modify: `tests/test_rust_ladder_benchmark.py`
- Generated: `rust_fit_improvement/development_outcomes.json`
- Generated: `rust_fit_improvement/approved_fit_gold_manifest.json`
- Generated: `rust_fit_improvement/baseline_benchmark.json`

**Interfaces:**
- Produces: `build_approved_fit_gold(round_two_outcomes, development_outcomes, approvals)`, with every expected sequence bound to patient identity and source SHA-256.

- [ ] **Step 1: Write failing approval and benchmark-manifest tests**

```python
def test_fit_gold_contains_only_usable_explicitly_approved_complete_ladders():
    manifest = build_approved_fit_gold(round_two, development, approvals)
    assert all(r["sample_kind"] == "patient" for r in manifest["records"])
    assert all(r["approved_for_fit_gold"] is True for r in manifest["records"])
    assert all(len(r["expected_scan_indices"]) in {16, 21} for r in manifest["records"])
    assert all(r["content_sha256"] in approvals for r in manifest["records"])
```

Test that exclusions, incomplete adjustments, unapproved records, changed bytes, duplicate runs/hashes, and path-only joins are rejected before a Rust subprocess starts.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_ladder_fit_improvement.py tests/test_rust_ladder_benchmark.py -q`

- [ ] **Step 3: Implement approved-gold export and exact-anchor metrics**

Extend benchmark output with exact sequence equality, anchors changed, mean/max absolute scan delta, and major wrong-sequence classification. Keep human-dependent outcome taxonomy N/A.

- [ ] **Step 4: Finalize the real development wave and freeze the baseline**

```powershell
python scripts/build_ladder_research_corpus.py finalize-fit-development --workspace D:\HemaFrag_Research\ladder\current
python scripts/benchmark_rust_ladder.py --manifest D:\HemaFrag_Research\ladder\current\rust_fit_improvement\approved_fit_gold_manifest.json --cli C:\Users\molpa\Documents\HemaFrag\fraggler-v2\target\release\fraggler-cli.exe --repeats 3 --timeout-seconds 10 --output D:\HemaFrag_Research\ladder\current\rust_fit_improvement\baseline_benchmark.json
```

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_ladder_fit_improvement.py tests/test_rust_ladder_benchmark.py -q`

```powershell
git add core/research/ladder/fit_improvement.py scripts/benchmark_rust_ladder.py tests/test_ladder_fit_improvement.py tests/test_rust_ladder_benchmark.py
git commit -m "feat: lock reviewed ladder fitting gold"
```

### Task 6: Rust Rescue Contracts, Diagnostics, and Deterministic Budgets

**Files:**
- Create: `fraggler-v2/crates/fraggler-core/src/ladder_search.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/lib.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs`

**Interfaces:**
- Produces: `FitTier`, `SearchBudget`, `SearchDiagnostics`, `SearchCandidate`, `SearchOutcome`, `completed_tier_or_previous(...)`, and additive `LadderFitPreview` fields with serde defaults.

- [ ] **Step 1: Read `superpowers:test-driven-development/writing-good-tests.md` completely**

- [ ] **Step 2: Write failing Rust tests for serialization, stable ordering, budgets, and watchdog fallback**

```rust
#[test]
fn interrupted_deep_tier_returns_last_completed_tier() {
    let fast = candidate(FitTier::Fast, &[100, 200, 300]);
    let outcome = completed_tier_or_previous(Some(fast.clone()), None, true).unwrap();
    assert_eq!(outcome.candidate, fast);
    assert!(outcome.diagnostics.watchdog_reached);
}

#[test]
fn search_candidate_order_is_score_then_scan_sequence() {
    let mut values = vec![candidate_with_score(&[10, 30], 4.0),
                          candidate_with_score(&[10, 20], 4.0)];
    values.sort_by(SearchCandidate::stable_cmp);
    assert_eq!(values[0].scan_indices, vec![10, 20]);
}
```

- [ ] **Step 3: Run the focused Rust tests and verify RED**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core ladder_search -- --nocapture`

- [ ] **Step 4: Implement contracts and additive preview fields**

```rust
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FitTier { Fast, Rescue2s, DeepRescue10s }

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SearchDiagnostics {
    pub fit_tier: FitTier,
    pub expansions_used: usize,
    pub expansion_limit: usize,
    pub elapsed_us: u64,
    pub complete_candidate_count: usize,
    pub best_score: Option<f64>,
    pub runner_up_score: Option<f64>,
    pub score_margin: Option<f64>,
    pub rescue_triggers: Vec<String>,
    pub watchdog_reached: bool,
}
```

Use `#[serde(default)]` on the optional/additive preview diagnostics so older stored JSON remains readable.

- [ ] **Step 5: Run core and CLI contract tests**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core -p fraggler-cli`

- [ ] **Step 6: Commit**

```powershell
git add fraggler-v2/crates/fraggler-core/src/ladder_search.rs fraggler-v2/crates/fraggler-core/src/lib.rs fraggler-v2/crates/fraggler-core/src/primitives.rs
git commit -m "feat: define deterministic ladder rescue tiers"
```

### Task 7: Shared Candidate Score and Tier-1 LIZ Rescue

**Files:**
- Modify: `fraggler-v2/crates/fraggler-core/src/ladder_search.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs`

**Interfaces:**
- Produces: `score_candidate_sequence`, `liz_local_rescue_candidates`, and `arbiter_select_candidate`.
- Consumes: expected ladder basepairs, detected `Peak` features, current scan sequence, and `SearchBudget`.

- [ ] **Step 1: Add characterization tests for the two exact reviewed sequence shapes and current arbiter guards**

The production change that makes these tests fail is any alteration to existing exact-candidate preference or stable tie-breaking.

- [ ] **Step 2: Write failing synthetic LIZ rescue tests**

```rust
#[test]
fn liz_rescue_replaces_wrong_first_anchor_without_moving_stable_interior() {
    let input = liz_fixture_with_wrong_first_anchor(1505, 1544);
    let outcome = liz_local_rescue_candidates(&input, SearchBudget::tier_one()).unwrap();
    assert_eq!(outcome.best.scan_indices[0], 1544);
    assert_eq!(&outcome.best.scan_indices[1..], &input.expected_scans[1..]);
}
```

Add separate cases for a two-anchor prefix shift, a correct weak first anchor that must not move, baseline-foot versus apex, and deterministic budget exhaustion.

- [ ] **Step 3: Verify RED**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core liz_rescue -- --nocapture`

- [ ] **Step 4: Extract one shared score and implement bounded LIZ neighborhoods**

Score geometry residuals, spacing, peak prominence/purity, height-family consistency, baseline/shoulder penalties, skipped strong peaks, and sequence span. Generate replacements only within evidence-triggered prefix or weak-anchor windows. Keep the current sequence in the candidate list.

- [ ] **Step 5: Verify focused, core, and nine-case manifest benchmarks**

```powershell
cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core
cargo build --manifest-path fraggler-v2/Cargo.toml -p fraggler-cli --release
python scripts/benchmark_rust_ladder.py --manifest D:\HemaFrag_Research\ladder\current\rust_fit_improvement\approved_fit_gold_manifest.json --cli fraggler-v2\target\release\fraggler-cli.exe --repeats 1 --timeout-seconds 10 --output D:\HemaFrag_Research\ladder\current\rust_fit_improvement\candidate_liz.json
```

Require the two exact cases unchanged and every known LIZ case exact or strictly closer with no newly changed correct anchor.

- [ ] **Step 6: Commit**

```powershell
git add fraggler-v2/crates/fraggler-core/src/ladder_search.rs fraggler-v2/crates/fraggler-core/src/primitives.rs
git commit -m "feat: rescue LIZ edge anchor fits"
```

### Task 8: Tier-1 ROX Shift Search

**Files:**
- Modify: `fraggler-v2/crates/fraggler-core/src/ladder_search.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs`

**Interfaces:**
- Produces: `rox_local_rescue_candidates`, covering prefix shifts, one insertion/deletion, compressed families, and alternate tails.

- [ ] **Step 1: Write failing ROX tests for all three reviewed error geometries**

```rust
#[test]
fn rox_rescue_considers_one_step_insertion_after_stable_prefix() {
    let input = rox_fixture_shifted_after_anchor_five();
    let outcome = rox_local_rescue_candidates(&input, SearchBudget::tier_one()).unwrap();
    assert_eq!(outcome.best.scan_indices, input.expected_scans);
}
```

Add a displaced full-family test, an early compressed-family test, a correct ROX control that must remain unchanged, and an ambiguous equal-margin case that stays review-required.

- [ ] **Step 2: Verify RED**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core rox_rescue -- --nocapture`

- [ ] **Step 3: Implement bounded ROX hypotheses through the shared score**

Enumerate only evidence-supported prefix offsets, one skipped/inserted candidate, tail alternatives, and alternate start windows. Deduplicate by scan vector and preserve stable ordering.

- [ ] **Step 4: Run Rust tests and real reviewed benchmark**

Require existing exact cases unchanged, no new major wrong sequence, and every known ROX error exact or materially closer.

- [ ] **Step 5: Commit**

```powershell
git add fraggler-v2/crates/fraggler-core/src/ladder_search.rs fraggler-v2/crates/fraggler-core/src/primitives.rs
git commit -m "feat: rescue shifted ROX ladder sequences"
```

### Task 9: Tier-2 Global Beam Search and Staged Integration

**Files:**
- Modify: `fraggler-v2/crates/fraggler-core/src/ladder_search.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs` tests module

**Interfaces:**
- Produces: `deep_rescue_candidates`, `rescue_triggers`, and staged integration from `build_ladder_fit_preview_with_arbiter`.

- [ ] **Step 1: Write failing beam-search and trigger tests**

Cover complete monotonic recovery, deterministic pruning, expansion ceiling, discarded interrupted tier, alternative-start family, small-margin ambiguity, and no Tier-1/Tier-2 invocation for a clean high-confidence fast result.

- [ ] **Step 2: Verify RED**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core deep_rescue -- --nocapture`

- [ ] **Step 3: Implement the deterministic beam state and transitions**

```rust
struct BeamState {
    step_index: usize,
    peak_position: usize,
    scan_indices: Vec<usize>,
    accumulated_score: f64,
    skipped_peak_count: usize,
    stable_tie_break: Vec<usize>,
}
```

Prune by deterministic score/tie-break order at a fixed beam width and expansion count. Recompute the full shared score for complete candidates before arbitration.

- [ ] **Step 4: Integrate tiers into the existing arbiter**

Fast output remains the first finalist. Invoke Tier 1 only from explicit triggers; invoke Tier 2 only if Tier 1 remains incomplete, review-required, or below the configured score margin. A rescue candidate cannot bypass existing complete-count, monotonicity, scan-window, or QC guards.

- [ ] **Step 5: Run deterministic repeats and full Rust suite**

```powershell
cargo fmt --manifest-path fraggler-v2/Cargo.toml -- --check
cargo clippy --manifest-path fraggler-v2/Cargo.toml --workspace --all-targets -- -D warnings
cargo test --manifest-path fraggler-v2/Cargo.toml --workspace
```

Run the approved real manifest three times and require identical anchors, tier, expansion count, and trigger codes.

- [ ] **Step 6: Commit**

```powershell
git add fraggler-v2/crates/fraggler-core/src/ladder_search.rs fraggler-v2/crates/fraggler-core/src/primitives.rs
git commit -m "feat: add bounded deep ladder rescue"
```

### Task 10: Candidate Benchmark, Development Tuning, and Freeze

**Files:**
- Modify: `scripts/benchmark_rust_ladder.py`
- Modify: `tests/test_rust_ladder_benchmark.py`
- Generated: candidate benchmark/comparison and freeze manifest.

**Interfaces:**
- Produces: per-tier latency distributions, invocation/watchdog counts, exact-fit deltas, major-error deltas, and `promotion_gate` results.

- [ ] **Step 1: Write failing tier-metric and promotion-gate tests**

```python
def test_promotion_gate_requires_exact_controls_and_no_major_regression():
    gate = evaluate_fit_candidate(baseline, candidate)
    assert gate["existing_exact_preserved"] is True
    assert gate["major_wrong_sequence_regressions"] == 0
    assert gate["promotable"] is True
```

Add failures for changed exact controls, non-deterministic repeats, watchdog overflow, slower fast-path p95, and improved average hiding a ladder-family regression.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_rust_ladder_benchmark.py -q`

- [ ] **Step 3: Implement tier-aware comparison and promotion gates**

Report all-repeat latency percentiles overall and by tier/ladder. Separate exact, limited-anchor, major-sequence, excluded, and N/A outcomes.

- [ ] **Step 4: Tune only against approved round-two plus `development_40` gold**

Every scoring or budget change requires a failing synthetic or approved-real regression first. Do not inspect validation outcomes or use validation paths in benchmark commands.

- [ ] **Step 5: Run full verification and freeze the release candidate**

```powershell
cargo test --manifest-path fraggler-v2/Cargo.toml --workspace
python -m pytest tests -q
cargo build --manifest-path fraggler-v2/Cargo.toml -p fraggler-cli --release
python scripts/build_ladder_research_corpus.py freeze-fit-candidate --workspace D:\HemaFrag_Research\ladder\current --cli fraggler-v2\target\release\fraggler-cli.exe
```

- [ ] **Step 6: Commit**

```powershell
git add scripts/benchmark_rust_ladder.py tests/test_rust_ladder_benchmark.py
git commit -m "feat: gate Rust ladder fit promotion"
```

### Task 11: Open, Finalize, and Score the Locked Validation Wave

**Files:**
- Generated: validation adjustment DB, outcomes, comparison, benchmark, and promotion report below `rust_fit_improvement`.

**Interfaces:**
- Consumes: frozen CLI/configuration manifest and 60 manually reviewed validation cases.
- Produces: unbiased baseline-versus-candidate evidence and final promotion verdict.

- [ ] **Step 1: Verify the validation bundle and freeze hashes before launch**

Require unchanged 60 source/copy hashes, candidate CLI hash matching the freeze manifest, 60 blank labels, no pre-existing adjustment DB, and zero prior development-outcome access from the validation command.

- [ ] **Step 2: Launch HemaFrag on `validation_60`**

```powershell
Start-Process python -ArgumentList @(
  'qt_app.py',
  '--ladder-review-bundle',
  'D:\HemaFrag_Research\ladder\current\rust_fit_improvement\validation_60'
) -WorkingDirectory 'C:\Users\molpa\Documents\HemaFrag\.worktrees\ladder-fitting-historical-research'
```

- [ ] **Step 3: Pause for the chemist to resolve all 60 cases**

Do not reveal strata or baseline/candidate comparison until all labels are resolved.

- [ ] **Step 4: Finalize and benchmark validation**

```powershell
python scripts/build_ladder_research_corpus.py finalize-fit-validation --workspace D:\HemaFrag_Research\ladder\current
python scripts/benchmark_rust_ladder.py --manifest D:\HemaFrag_Research\ladder\current\rust_fit_improvement\validation_gold_manifest.json --cli fraggler-v2\target\release\fraggler-cli.exe --repeats 3 --timeout-seconds 10 --output D:\HemaFrag_Research\ladder\current\rust_fit_improvement\validation_candidate_benchmark.json
```

- [ ] **Step 5: Evaluate the frozen promotion gates**

Require baseline exact-fit improvement of at least 15 percentage points on usable validation, no increase in major wrong-sequence rate for LIZ or ROX, deterministic repeats, preserved exact regression cases, and respected watchdogs. Report the 90% usable exact-fit product target separately from the minimum promotion gate.

- [ ] **Step 6: Run final complete verification**

```powershell
cargo fmt --manifest-path fraggler-v2/Cargo.toml -- --check
cargo clippy --manifest-path fraggler-v2/Cargo.toml --workspace --all-targets -- -D warnings
cargo test --manifest-path fraggler-v2/Cargo.toml --workspace
python -m pytest tests -q
git diff --check
```

- [ ] **Step 7: Request final code review before integration**

Use `superpowers:requesting-code-review`, resolve load-bearing findings through test-first fixes, rerun the full verification commands, then use `superpowers:finishing-a-development-branch` to present merge/PR/keep/discard options.
