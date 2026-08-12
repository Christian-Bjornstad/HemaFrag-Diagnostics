# LIZ Core-First Fitting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the LIZ 50–500 bp core fixed while selecting the 35 bp anchor afterward, improving automatic ladder fitting without new reporting or schema changes.

**Architecture:** Add one deterministic Rust helper that receives a complete LIZ sequence and candidate peaks, treats indices 1–15 as immutable, predicts the 35 bp scan from early core geometry, and replaces only index 0 when a candidate wins by a fixed margin. Extend the existing benchmark gate with a core-only metric, then create a new hash-disjoint blind holdout before production integration.

**Tech Stack:** Rust (`fraggler-core`), Python/pytest benchmark tooling, existing HemaFrag review bundle.

## Global Constraints

- Patient clonality only.
- Never read or enumerate `D:\DATA\backup`.
- Preserve the existing 16-anchor LIZ output and public JSON structures.
- Add no 35 bp status, warning, field, UI element, or separate runtime report.
- Preserve current ROX behavior.
- Keep deterministic 2-second and 10-second rescue ceilings.

---

### Task 1: Deterministic core-first 35 bp selector

**Files:**
- Modify: `fraggler-v2/crates/fraggler-core/src/ladder_search.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs`

**Interfaces:**
- Consumes: `LadderRescueInput`, current 16 scans, and existing `PeakEvidence` values.
- Produces: `select_liz_35_after_core(input: &LadderRescueInput) -> Option<SearchOutcome>`; returned candidates always preserve `current_scan_indices[1..]` byte-for-byte.

- [ ] **Step 1: Write failing Rust tests**

Add tests proving that the selector replaces a geometrically wrong 35 bp peak while preserving the core:

```rust
assert_eq!(outcome.candidate.scan_indices[1..], current[1..]);
assert_eq!(outcome.candidate.scan_indices[0], expected_35_scan);
```

Also test that a weak alternative does not replace the current anchor, candidates at or beyond 50 bp are rejected, ties are deterministic, and a missing plausible candidate returns the unchanged sequence.

- [ ] **Step 2: Verify RED**

```powershell
cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core liz_35_after_core -- --nocapture
```

Expected: compilation failure because `select_liz_35_after_core` does not exist.

- [ ] **Step 3: Implement the minimal selector**

Use the locked 50, 75, and 100 bp scans to estimate the 35 bp position. Rank peaks before the 50 bp scan by deterministic geometric distance plus existing purity/baseline evidence. Compare the best candidate with the current 35 bp anchor using a fixed improvement margin. Construct candidates only by cloning the current sequence and assigning `scans[0]`; never mutate `scans[1..]`.

- [ ] **Step 4: Integrate after LIZ core fitting**

Replace the first-anchor behavior inside `apply_liz_tier_one_rescue` with `select_liz_35_after_core`. Recompute the ordinary 16-anchor sizing model after attachment, but make promotion depend on the locked core and selector score. Keep all existing output fields unchanged.

- [ ] **Step 5: Verify Rust tests**

```powershell
cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core liz_35_after_core -- --nocapture
cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core
```

- [ ] **Step 6: Commit**

```powershell
git add fraggler-v2/crates/fraggler-core/src/ladder_search.rs fraggler-v2/crates/fraggler-core/src/primitives.rs
git commit -m "feat: fit LIZ core before attaching 35 bp"
```

### Task 2: Core-safety benchmark gate and tuning

**Files:**
- Modify: `scripts/benchmark_rust_ladder.py`
- Modify: `tests/test_rust_ladder_benchmark.py`

**Interfaces:**
- Produces research-only metrics `gold_core_exact_match`, `gold_core_anchors_changed`, and `gold_core_major_wrong_sequence`.
- Produces gate fields `existing_core_exact_preserved` and `core_major_wrong_sequence_regressions`.

- [ ] **Step 1: Write failing Python tests**

Use a LIZ example differing from gold only at index 0:

```python
assert row["gold_exact_match"] is False
assert row["gold_core_exact_match"] is True
assert row["gold_core_major_wrong_sequence"] is False
```

Add a gate test proving that movement at indices 1–15 fails core preservation, while index-0-only movement does not.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_rust_ladder_benchmark.py -q
```

- [ ] **Step 3: Implement core metrics without weakening strict metrics**

Keep all full-ladder metrics. For `LIZ500_250`, calculate core metrics from `selected[1:]` and `expected[1:]`; for ROX, core equals the complete sequence. Require zero exact-core regressions, zero new major core errors per ladder, deterministic repeats, and no watchdog overflow.

- [ ] **Step 4: Tune only on known reviewed evidence**

Build release Rust and benchmark both known gold manifests. Accept selector constants only when every changed 50–500 bp core is unchanged or closer and ROX outputs remain identical to commit `a7059a5`.

```powershell
cargo build --manifest-path fraggler-v2/Cargo.toml -p fraggler-cli --release
python scripts/benchmark_rust_ladder.py --manifest D:\HemaFrag_Research\ladder\current\rust_fit_improvement\approved_fit_gold_manifest.json --cli fraggler-v2\target\release\fraggler-cli.exe --repeats 3 --timeout-seconds 10 --output D:\HemaFrag_Research\ladder\current\rust_fit_improvement\core_first_development.json
python scripts/benchmark_rust_ladder.py --manifest D:\HemaFrag_Research\ladder\current\rust_fit_improvement\validation_gold_manifest.json --cli fraggler-v2\target\release\fraggler-cli.exe --repeats 3 --timeout-seconds 10 --output D:\HemaFrag_Research\ladder\current\rust_fit_improvement\core_first_known_validation.json
```

- [ ] **Step 5: Commit**

```powershell
git add scripts/benchmark_rust_ladder.py tests/test_rust_ladder_benchmark.py
git commit -m "test: gate ladder fitting on core anchors"
```

### Task 3: Fresh blind holdout and production decision

**Files:**
- Modify: `core/research/ladder/fit_improvement.py`
- Modify: `scripts/build_ladder_research_corpus.py`
- Modify: `tests/test_ladder_fit_improvement.py`
- Generated: `D:\HemaFrag_Research\ladder\current\rust_fit_improvement\core_first_holdout_40`

**Interfaces:**
- Produces a 40-case patient-only bundle disjoint from all prior reviewed content hashes and physical runs.
- Produces frozen binary evidence, finalized gold, matched benchmarks, and a promotion report.

- [ ] **Step 1: Write failing selection tests**

Assert exactly 40 patient cases, allowed roots only, three-year coverage, zero prior overlap by normalized run and SHA-256, blank labels, no sidecars, and no adjustment database.

- [ ] **Step 2: Implement transactional holdout publication**

Select without inspecting candidate results, hash every source and copy, refuse an existing destination, and withhold strata and comparisons until review finalization.

- [ ] **Step 3: Freeze and open HemaFrag**

Bind the exact release CLI hash and configuration, verify all 40 labels are blank, then launch the existing ladder-review UI for manual resolution.

- [ ] **Step 4: Finalize and benchmark**

Run baseline and candidate three times per usable case. Require identical repeats, zero core-exact regressions, zero new major core errors by ladder, preserved ROX gains, and no watchdog overflow. Report strict and core research metrics without adding runtime reporting.

- [ ] **Step 5: Production decision**

Merge only if the fresh blind holdout passes every core-safety gate. Otherwise retain the evidence and leave production unchanged.

- [ ] **Step 6: Verify and commit**

```powershell
cargo fmt --manifest-path fraggler-v2/Cargo.toml --all -- --check
cargo test --manifest-path fraggler-v2/Cargo.toml --workspace
python -m pytest tests -q
git diff --check
git add core/research/ladder/fit_improvement.py scripts/build_ladder_research_corpus.py tests/test_ladder_fit_improvement.py
git commit -m "feat: add blind core-first ladder holdout"
```

## Final checkpoint

- [ ] Existing consumers still receive the same 16-anchor LIZ structure.
- [ ] No new 35 bp UI or runtime reporting exists.
- [ ] Every known and fresh core-exact control is preserved.
- [ ] ROX behavior is unchanged or better.
- [ ] Full Rust and Python suites pass.
- [ ] Integration occurs only after the fresh holdout passes.
