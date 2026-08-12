# Ladder-Fitting Historical Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible historical ladder-research pipeline that inventories the allowed corpus, imports manual corrections, diagnoses canonical review cases, produces a reviewed-anchor queue, and gates later Rust changes on locked gold evidence.

**Architecture:** Add a focused `core/research/ladder` package whose pure modules handle path policy, archive ingestion, correction import, diagnostic classification, and partitioning. A single CLI orchestrates those modules and writes versioned artifacts only below `D:\HemaFrag_Research\ladder`; existing raw data, archive outputs, and annual workbooks remain read-only. Rust changes and historical workbook rebuilding are later tasks gated by the reviewed gold corpus produced by the first execution stage.

**Tech Stack:** Python 3, pandas/openpyxl for existing tracking-workbook compatibility, stdlib CSV/JSON/hashlib/pathlib/subprocess, existing Rust CLI, pytest, Rust cargo tests.

## Global Constraints

- Read only `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, and `D:\DATA\2026_data` as raw roots.
- Never enumerate, read, hash, copy, or write anything below `D:\DATA\backup`.
- Treat `D:\Klonalitet_Archive` as immutable input.
- Write research artifacts only below `D:\HemaFrag_Research\ladder`.
- Preserve exact identifiers and paths; SHA-256 is for provenance and leakage control, not anonymization.
- Count only run-level `reports_backfill/ladder_review_gate` bundles as canonical.
- Do not change Rust acceptance behavior before reviewed development, locked-validation, and release manifests exist.
- Never overwrite original FSA files, adjustment sidecars, archive files, or annual workbooks.

---

## File Structure

- Create `core/research/__init__.py`: research package marker.
- Create `core/research/ladder/__init__.py`: public ladder-research interfaces.
- Create `core/research/ladder/contracts.py`: schemas, allowed roots, outcome vocabulary, dataclasses, and stable serialization.
- Create `core/research/ladder/inventory.py`: raw/archive/workbook discovery, path resolution, hashing, canonical joins, and reconciliation.
- Create `core/research/ladder/corrections.py`: legacy/v2 manual-correction parsing and reconciliation.
- Create `core/research/ladder/diagnostics.py`: Rust CLI execution, normalized diagnostic records, and deterministic taxonomy.
- Create `core/research/ladder/partitions.py`: run/content-safe development, validation, and release manifests.
- Create `scripts/build_ladder_research_corpus.py`: end-to-end CLI and versioned artifact publication.
- Create `tests/test_ladder_research_contracts.py`: policy and schema tests.
- Create `tests/test_ladder_research_inventory.py`: path, archive, and reconciliation tests.
- Create `tests/test_ladder_research_corrections.py`: legacy/v2 correction tests.
- Create `tests/test_ladder_research_diagnostics.py`: CLI normalization and taxonomy tests.
- Create `tests/test_ladder_research_partitions.py`: leakage and determinism tests.
- Modify `scripts/benchmark_rust_ladder.py`: consume the research manifest and report taxonomy/gold agreement.
- Modify `fraggler-v2/crates/fraggler-core/src/primitives.rs`: only after the gold checkpoint, expose or improve failure-directed evidence and fitting behavior.
- Modify `fraggler-v2/crates/fraggler-core/src/contract.rs`: version Rust diagnostic fields added after the checkpoint.
- Modify `core/rust_bridge/_legacy.py`: hydrate new diagnostic fields after Rust contract changes.
- Modify `scripts/combine_clonality_yearly_overview.py`: support the validated versioned rerun root without altering historical workbooks.

---

### Task 1: Research Contracts and Hard Path Policy

**Files:**
- Create: `core/research/__init__.py`
- Create: `core/research/ladder/__init__.py`
- Create: `core/research/ladder/contracts.py`
- Test: `tests/test_ladder_research_contracts.py`

**Interfaces:**
- Produces: `ResearchRoots`, `LadderOutcome`, `assert_allowed_raw_path(path, roots)`, `stable_json_fingerprint(value)`, and schema constants.
- Consumes: no new project interfaces.

- [ ] **Step 1: Write failing path-policy and serialization tests**

```python
def test_backup_path_is_rejected():
    roots = ResearchRoots.default()
    with pytest.raises(ValueError, match="backup"):
        assert_allowed_raw_path(Path(r"D:\DATA\backup\x.fsa"), roots)


def test_allowed_year_path_is_accepted():
    roots = ResearchRoots.default()
    assert_allowed_raw_path(Path(r"D:\DATA\2025_data\run\x.fsa"), roots)


def test_fingerprint_is_key_order_independent():
    assert stable_json_fingerprint({"a": 1, "b": 2}) == stable_json_fingerprint({"b": 2, "a": 1})
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `python -m pytest tests/test_ladder_research_contracts.py -q`

Expected: FAIL because `core.research.ladder.contracts` does not exist.

- [ ] **Step 3: Implement frozen contracts and canonical outcome values**

```python
class LadderOutcome(str, Enum):
    MISSING_LADDER_SIGNAL = "missing_ladder_signal"
    WRONG_LADDER_OR_CHANNEL = "wrong_ladder_or_channel"
    FIT_REJECTED_WITH_USABLE_SIGNAL = "fit_rejected_with_usable_signal"
    FIT_ACCEPTED_BUT_WRONG = "fit_accepted_but_wrong"
    FIT_CORRECT_REVIEW_ONLY = "fit_correct_review_only"
    UNRESOLVED = "unresolved"
```

`assert_allowed_raw_path` resolves the candidate, rejects anything within the excluded backup root, and accepts only descendants of the three explicit allowed roots.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_ladder_research_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/research tests/test_ladder_research_contracts.py
git commit -m "feat: define ladder research contracts"
```

### Task 2: Canonical Inventory and Archive Reconciliation

**Files:**
- Create: `core/research/ladder/inventory.py`
- Test: `tests/test_ladder_research_inventory.py`

**Interfaces:**
- Consumes: `ResearchRoots`, `assert_allowed_raw_path`, schema constants.
- Produces: `resolve_archived_path`, `discover_raw_runs`, `load_canonical_review_cases`, `load_tracking_index`, `build_inventory`, and `InventoryResult`.

- [ ] **Step 1: Write failing tests for old-drive resolution and canonical bundle selection**

```python
def test_resolve_archived_f_drive_to_allowed_d_root(tmp_path):
    roots = fake_roots(tmp_path)
    target = roots.raw_2024 / "run-a" / "sample.fsa"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fsa")
    resolved = resolve_archived_path(r"F:\DATA\2024_DATA\run-a\sample.fsa", roots)
    assert resolved == target.resolve()


def test_only_reports_backfill_bundle_is_canonical(tmp_path):
    make_review_bundle(tmp_path / "run" / "reports_backfill", rows=2)
    make_review_bundle(tmp_path / "run" / "ASSAY_REPORTS", rows=2)
    rows = load_canonical_review_cases(tmp_path, fake_roots(tmp_path))
    assert len(rows) == 2
```

- [ ] **Step 2: Write failing reconciliation tests**

Verify that raw-only, tracking-only, archive-only, nested logical-run, and duplicate-content records receive explicit issue codes and never disappear.

- [ ] **Step 3: Run tests and confirm failure**

Run: `python -m pytest tests/test_ladder_research_inventory.py -q`

Expected: FAIL because inventory functions do not exist.

- [ ] **Step 4: Implement read-only discovery and joins**

Use direct top-level raw directories as `PhysicalRunKey`, recursive FSA discovery beneath each, annual `Runs` sheets for tracking, and canonical review CSVs beneath `reports_backfill`. Hash files through a chunked SHA-256 helper. Return data frames plus a reconciliation summary; do not write from the library module.

- [ ] **Step 5: Run focused and existing workbook tests**

Run: `python -m pytest tests/test_ladder_research_inventory.py tests/test_tracking_workbook_io.py tests/test_clonality_archive_runner.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add core/research/ladder/inventory.py tests/test_ladder_research_inventory.py
git commit -m "feat: build canonical ladder corpus inventory"
```

### Task 3: Manual-Correction Import and Reconciliation

**Files:**
- Create: `core/research/ladder/corrections.py`
- Test: `tests/test_ladder_research_corrections.py`

**Interfaces:**
- Consumes: inventory identities and allowed-path policy.
- Produces: `parse_adjustment_sidecar`, `discover_adjustments`, `reconcile_manual_evidence`, and normalized `ManualCorrectionRecord` dictionaries.

- [ ] **Step 1: Write failing legacy, v2, partial, and missing-sidecar tests**

```python
def test_legacy_partial_mapping_preserves_missing_step(tmp_path):
    payload = {
        "mapping": {"0": 0, "1": 1, "3": 2},
        "mapping_times": {"0": 100.0, "1": 200.0, "3": 400.0},
        "manual_candidates": [100.0, 200.0, 400.0],
    }
    record = parse_adjustment_sidecar(write_sidecar(tmp_path, payload), matching_fsa(tmp_path))
    assert record.selected_steps == (0, 1, 3)
    assert record.complete is False


def test_v2_hash_mismatch_is_not_gold_eligible(tmp_path):
    record = parse_adjustment_sidecar(v2_sidecar(tmp_path, source_hash="0" * 64), matching_fsa(tmp_path))
    assert record.gold_eligible is False
    assert "source_hash_mismatch" in record.issue_codes
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_ladder_research_corrections.py -q`

- [ ] **Step 3: Implement normalization without modifying sidecars**

Legacy ladder identity is inferred only when expected-step count and inventory configuration agree. V2 source hash, ladder, channel, selected peaks, review metadata, and validation state are retained. Annotation-only and workbook-consumption evidence is emitted even when its sidecar is missing.

- [ ] **Step 4: Run focused and existing manual-adjustment tests**

Run: `python -m pytest tests/test_ladder_research_corrections.py tests/test_manual_ladder_rerun.py tests/test_analysis_provenance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/research/ladder/corrections.py tests/test_ladder_research_corrections.py
git commit -m "feat: import manual ladder correction evidence"
```

### Task 4: Diagnostic Runner and Failure Taxonomy

**Files:**
- Create: `core/research/ladder/diagnostics.py`
- Test: `tests/test_ladder_research_diagnostics.py`

**Interfaces:**
- Consumes: canonical review-case records and `fraggler-cli analyze --compact-json`.
- Produces: `run_rust_diagnostic`, `normalize_rust_result`, `classify_ladder_outcome`, and `DiagnosticRecord`.

- [ ] **Step 1: Write failing taxonomy tests**

```python
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"ladder_peak_count": 0, "reason_codes": ["no_ladder_signal"]}, "missing_ladder_signal"),
        ({"configured_ladder": "LIZ500_250", "detected_ladder": "ROX400HD"}, "wrong_ladder_or_channel"),
        ({"ladder_peak_count": 22, "fitted_count": 0, "reason_codes": ["candidate_space_capped"]}, "fit_rejected_with_usable_signal"),
        ({"reviewed_label": "reviewed_no_change", "review_required": True}, "fit_correct_review_only"),
    ],
)
def test_outcome_taxonomy(payload, expected):
    assert classify_ladder_outcome(payload).value == expected
```

- [ ] **Step 2: Write a mocked CLI normalization test**

Assert command arguments, timeout handling, summary-shape validation, retained preview/candidate/QC/timing fields, and a non-generic underlying reason requirement.

- [ ] **Step 3: Run tests and confirm failure**

Run: `python -m pytest tests/test_ladder_research_diagnostics.py -q`

- [ ] **Step 4: Implement bounded CLI execution and normalization**

Use a temporary output directory per file, `--deterministic`, configurable timeout, and captured stderr. Return transport failure separately from algorithm outcome. Preserve the best preview even when the final fit is rejected.

- [ ] **Step 5: Run focused and Rust benchmark tests**

Run: `python -m pytest tests/test_ladder_research_diagnostics.py tests/test_rust_ladder_benchmark.py tests/test_strict_rust_ladder_mode.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add core/research/ladder/diagnostics.py tests/test_ladder_research_diagnostics.py
git commit -m "feat: classify historical ladder diagnostics"
```

### Task 5: Leakage-Safe Gold and Review Partitions

**Files:**
- Create: `core/research/ladder/partitions.py`
- Test: `tests/test_ladder_research_partitions.py`

**Interfaces:**
- Consumes: inventory, correction, diagnostic, and review records.
- Produces: `build_gold_records`, `assign_partitions`, `validate_partition_isolation`, and manifest dictionaries accepted by `scripts/benchmark_rust_ladder.py`.

- [ ] **Step 1: Write failing evidence-rank and isolation tests**

```python
def test_v2_manual_beats_consensus_for_same_content():
    records = build_gold_records([consensus_record(), v2_manual_record()])
    assert records[0]["truth_source"] == "manual_v2"


def test_physical_run_never_crosses_partitions():
    assigned = assign_partitions(records_with_shared_run(), seed=20260810)
    by_run = assigned.groupby("physical_run_key")["partition"].nunique()
    assert by_run.max() == 1
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_ladder_research_partitions.py -q`

- [ ] **Step 3: Implement deterministic assignment**

Prioritize manual truth, create a small failure-family-covering development set, then allocate whole physical-run/content groups to locked validation and release using a fixed seed. Reject conflicting gold mappings for identical content.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_ladder_research_partitions.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/research/ladder/partitions.py tests/test_ladder_research_partitions.py
git commit -m "feat: create ladder gold corpus partitions"
```

### Task 6: End-to-End Corpus Builder and Real Historical Audit

**Files:**
- Create: `scripts/build_ladder_research_corpus.py`
- Modify: `scripts/benchmark_rust_ladder.py`
- Test: extend the five new ladder-research test files with CLI smoke coverage.

**Interfaces:**
- Consumes: all `core.research.ladder` modules.
- Produces below the requested output root: `inventory.csv`, `reconciliation.json`, `manual_corrections.csv`, `manual_reconciliation.json`, `review_cases.csv`, `diagnostics.ndjson`, `failure_summary.csv`, `review_queue.csv`, `gold_records.json`, `development_manifest.json`, `locked_validation_manifest.json`, `release_manifest.json`, and `run_manifest.json`.

- [ ] **Step 1: Write a failing end-to-end fixture test**

The fixture includes an allowed raw file, an excluded backup sentinel, an old `F:` review path, a legacy correction, and a fake Rust result. Assert that all expected artifacts are written and the backup sentinel is absent from every artifact.

- [ ] **Step 2: Run the test and confirm failure**

Run: `python -m pytest tests/test_ladder_research_contracts.py tests/test_ladder_research_inventory.py tests/test_ladder_research_corrections.py tests/test_ladder_research_diagnostics.py tests/test_ladder_research_partitions.py -q`

- [ ] **Step 3: Implement the staged CLI**

```powershell
python scripts/build_ladder_research_corpus.py inventory `
  --archive-root D:\Klonalitet_Archive `
  --raw-root D:\DATA\2024_DATA `
  --raw-root D:\DATA\2025_data `
  --raw-root D:\DATA\2026_data `
  --output-root D:\HemaFrag_Research\ladder
```

Separate `inventory`, `diagnose`, and `finalize` commands allow resumable execution. Publication uses a timestamped staging directory and an atomic final-directory rename.

- [ ] **Step 4: Run all focused tests**

Run: `python -m pytest tests/test_ladder_research_*.py tests/test_rust_ladder_benchmark.py -q`

Expected: PASS.

- [ ] **Step 5: Run inventory against the real corpus**

Run the command above and verify 555 physical top-level runs, 53,390 FSA files, 552 canonical processed runs, 32,843 canonical entries, 1,155 canonical review cases, and 28 surviving sidecars. Differences must be explicit reconciliation issues rather than silently normalized.

- [ ] **Step 6: Run diagnostics against canonical review cases**

```powershell
python scripts/build_ladder_research_corpus.py diagnose `
  --workspace D:\HemaFrag_Research\ladder\current `
  --cli .\fraggler-v2\target\release\fraggler-cli.exe `
  --max-workers 3 `
  --timeout-seconds 30 `
  --resume
```

- [ ] **Step 7: Finalize review and initial gold artifacts**

Run: `python scripts/build_ladder_research_corpus.py finalize --workspace D:\HemaFrag_Research\ladder\current`

Expected: sidecar-backed gold records are populated; annotation-only missing-sidecar cases remain review-required; unreviewed diagnostic cases enter `review_queue.csv`.

- [ ] **Step 8: Commit**

```powershell
git add scripts/build_ladder_research_corpus.py scripts/benchmark_rust_ladder.py tests/test_ladder_research_*.py
git commit -m "feat: run historical ladder corpus research"
```

### Checkpoint A: Human Review Required

- [ ] Review the generated manual-correction reconciliation report.
- [ ] Recover or freshly review the two missing 2024 sidecars.
- [ ] Review the development queue across every failure family.
- [ ] Confirm `reviewed_no_change`, full correction, partial correction, missing signal, and wrong configuration labels.
- [ ] Freeze development, locked-validation, and release manifests.

Rust behavior must not change before this checkpoint is approved.

### Task 7: Rust Diagnostic Contract and Failure-Directed Improvements

**Files:**
- Modify: `fraggler-v2/crates/fraggler-core/src/primitives.rs`
- Modify: `fraggler-v2/crates/fraggler-core/src/contract.rs`
- Modify: `core/rust_bridge/_legacy.py`
- Modify: `scripts/benchmark_rust_ladder.py`
- Test: Rust tests beside the changed primitives plus `tests/test_strict_rust_ladder_mode.py` and `tests/test_rust_ladder_benchmark.py`.

**Interfaces:**
- Consumes: frozen development and locked-validation manifests.
- Produces: versioned precise failure reasons, preserved rejected previews, bounded repair evidence, and changed fit behavior only where gold evidence supports it.

- [ ] **Step 1: Add failing Rust contract tests for the observed top failure family**

Use the reviewed development records to construct exact anchor and outcome assertions. Preserve the current candidate as a finalist and require deterministic ordering.

- [ ] **Step 2: Confirm failures against the baseline engine**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml -p fraggler-core --all-targets`

- [ ] **Step 3: Implement the smallest failure-directed change**

Do not lower global acceptance thresholds. Add or route only the repair category supported by the reviewed evidence, while exposing candidate counts, alternatives, search budget, and underlying reason codes.

- [ ] **Step 4: Run Rust and Python bridge tests**

Run: `cargo test --manifest-path fraggler-v2/Cargo.toml --workspace --all-targets`

Run: `python -m pytest tests/test_strict_rust_ladder_mode.py tests/test_rust_ladder_benchmark.py tests/test_rust_in_process_wheel.py tests/test_ladder_rejection_review.py -q`

- [ ] **Step 5: Benchmark development then locked validation**

Run the development manifest first. Proceed to locked validation only after development improves with no known-good regression. Record exact-match, false-acceptance, review-rate, failure-family coverage, and latency distributions.

- [ ] **Step 6: Repeat one reviewed failure family at a time**

Each family receives its own tests, implementation, benchmark comparison, and atomic commit.

### Task 8: Versioned Historical Rerun and Workbook Publication

**Files:**
- Modify: `scripts/combine_clonality_yearly_overview.py`
- Create: `scripts/validate_ladder_research_release.py`
- Test: `tests/test_clonality_archive_runner.py`, `tests/test_tracking_workbook_io.py`, and new release-validation tests.

**Interfaces:**
- Consumes: released Rust engine, canonical inventory, and frozen release manifest.
- Produces: versioned historical output root, validated annual workbooks, and before/after release report.

- [ ] **Step 1: Add failing release-validation tests**

Assert unique `IdentityKey`, complete raw-run accounting, patient/control/assay/ladder reconciliation, accepted manual-provenance retention, and original-workbook immutability.

- [ ] **Step 2: Implement versioned rerun and validation commands**

All output goes below `D:\HemaFrag_Research\ladder\releases\<engine-fingerprint>`. Never target `D:\Klonalitet_Archive` or a raw-data root.

- [ ] **Step 3: Run the historical rerun**

Run year-by-year with resume manifests and three workers. Keep failed runs explicit and rerunnable.

- [ ] **Step 4: Generate and visually verify annual workbooks**

Validate values/formulas and render every sheet before publication. Compare counts and ladder outcomes against the canonical inventory.

- [ ] **Step 5: Run final release gates**

Require zero unexplained manual-gold regressions, zero new false automatic acceptances, deterministic transport equivalence, explicit missing-ladder outcomes, bounded runtime, and complete workbook reconciliation.

- [ ] **Step 6: Commit code and documentation**

```powershell
git add scripts/combine_clonality_yearly_overview.py scripts/validate_ladder_research_release.py tests docs
git commit -m "feat: validate historical ladder research release"
```

---

## Final Verification

- [ ] `python -m pytest tests/test_ladder_research_*.py -q`
- [ ] `python -m pytest tests -q`
- [ ] `cargo test --manifest-path fraggler-v2/Cargo.toml --workspace --all-targets`
- [ ] Real inventory counts reconcile or have explicit issue records.
- [ ] Every manual correction is imported, rejected with cause, or queued for fresh review.
- [ ] Backup-path scan returns zero occurrences outside documented exclusion text.
- [ ] Original data, archive, sidecars, and annual workbook hashes are unchanged.
- [ ] Research artifacts contain code/settings/data fingerprints and exact commands.
