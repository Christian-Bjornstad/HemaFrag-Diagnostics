# Final review fix report

## Scope and safety

- Review findings addressed: 1–10 from `final-review-findings.md`.
- Implementation base: `5257f3afaeb3aaa95f87b0c9292f049721a415b7`.
- No Rust fitting behavior was changed.
- The quarantined round-two bundle and withheld manifest were not enumerated, read, copied, altered, regenerated, or launched.
- `D:\DATA\backup` was not enumerated, read, copied, or modified. All new tests use synthetic temporary data and injected fixture roots.
- No replacement real bundle was generated and the application was not launched. Real re-publication and chemist re-review remain controller actions.

## Finding-to-fix traceability

| Finding | Fix | Principal regression evidence | Commit |
|---|---|---|---|
| 1. Public ordinals exposed quota allocation | Added a domain-separated deterministic hash order after quota selection and before assigning public case IDs/copies. Selection remains input-order independent while the public sequence no longer follows quota groups. | `test_round_two_public_order_does_not_encode_quota_groups`; `test_round_two_selection_is_independent_of_input_order` | `3e9e82c` |
| 2. Caller/manifest-defined production roots and unsafe output placement | Production orchestration now requires the exact canonical raw/archive/output/backup roots and exact `ladder/current` workspace. Output workspaces under any protected input descendant are rejected. Fixture-root injection remains available only through explicit library-call parameters used by isolated tests. | `test_inventory_cli_rejects_caller_defined_roots_before_scanning`; `test_workspace_rejects_descendants_of_protected_inputs`; `test_finalize_orchestration_requires_exact_production_workspace`; round-two canonical-workspace tests | `f7e6764` |
| 3. Review launch could use a decoy/default adjustment store | `--ladder-review-bundle` now overrides `HEMAFRAG_LADDER_ADJUSTMENT_DB` with the bundle-local database before `QApplication` and window construction. Default startup remains unchanged. | `test_review_bundle_startup_overrides_decoy_adjustment_store` plus existing startup argument tests | `e1d58cb` |
| 4. Non-patient candidates and single-year controls | Inventory retains canonical sample kind; selector admits only `sample_kind == patient`; controls must independently span multiple years. | `test_round_two_selector_rejects_non_patient_candidates`; `test_round_two_controls_must_span_multiple_years`; inventory sample-kind regression | `3e9e82c` |
| 5. Path-only diagnostic resume/join | Diagnostic records now carry source SHA-256, physical-run key, CLI SHA-256, settings/schema fingerprint, and success state. Resume reuses only successful exact matches, retries failures, and selection requires diagnostic/inventory content-hash equality. | `test_diagnostic_resume_reuses_only_exact_successful_provenance`; `test_diagnostic_resume_invalidates_changed_cli_and_settings`; `test_diagnostic_resume_retries_failed_records`; `test_round_two_selector_rejects_stale_diagnostic_content_hash` | `f7e6764` |
| 6. Under-validated round-two finalization | Finalization requires exactly 18 contiguous cases, exact 6/6 and 3/3 quotas, unique valid hashes and normalized physical runs, unique bundle copies, bundle/case-directory containment, file existence and re-hash equality, row/manifest identity agreement, and complete contiguous strictly increasing 16-step LIZ or 21-step ROX manual mappings. | exact-count, quota, duplicate hash/run, case-insensitive run, containment/missing/mutation, and complete-mapping tests in `test_ladder_research_round_two.py` | `c644a3e`, `c5c3859` |
| 7. Contradictory exclusion state and split annotation writes | Missing-ladder exclusion is allowed only from an unresolved row without adjustment evidence. The bundle-local DB and sidecar are checked. Local caches, consumption state, corrected paths, session entries, and stored batch-job file lists are unregistered. CSV and annotation JSON are staged and published as one rollback-capable pair; a material backup is retained if rollback itself fails. Finalization independently rejects exclusion/no-change contradictions and requires exclusion note/timestamp. | adjusted-row/DB-record rejection; second-publication and backup fault injection; rollback-backup preservation; full rerun-state removal; finalizer contradiction and note/timestamp tests | `e1d58cb`, `c5c3859` |
| 8. Unlocked, unbounded, misleading benchmark | Inputs are re-hashed and duplicate paths/content rejected before subprocess execution. Runs use `--deterministic` and a timeout. Per-file/group/overall p95 uses all measured repeats. Human-label-dependent taxonomy is N/A and other mismatches are explicit model transitions. CLI SHA/configuration are recorded. | hash mismatch/duplicate tests; `test_ladder_benchmark_runner_is_deterministic_and_bounded`; taxonomy comparison test; `test_ladder_benchmark_reports_all_repeat_tail_latency` | `df85100` |
| 9. Historical corrections automatically became gold and v2 scope was ignored | v2 `analysis_id`, patient identity, and sample kind are retained and validated. Technically valid historical corrections remain provisional and never self-approve. Gold, locked/release manifests, and programmatic gold benchmarking require explicit reviewed patient-clonality approval bound to a valid content hash and identity. Provisional and approved records share one leakage-safe partition assignment. | non-clonality/non-patient/provisional correction tests; `test_finalize_requires_explicit_review_approval_for_gold`; gold/identity/hash partition tests; unapproved manifest and programmatic benchmark tests | `c67769b` |
| 10. Markdown table corruption | Markdown cells escape backslashes, pipes, backticks, and line breaks in count, case, and repeated-pattern output. | `test_round_two_comparison_escapes_markdown_table_content` | `c644a3e` |

## Controller-supplied migration evidence

The migration helper consumes only controller-supplied rows and joins them to the new selection exclusively by exact content SHA-256; it does not read source or quarantined paths. For the supplied 18-row evidence shape:

- 8 `manual_adjusted` and 1 `reviewed_no_change` rows are classified as `resolved_decision_evidence`.
- 9 blank rows are classified as `excluded_error_evidence`.
- Every migrated row is marked `requires_re_review=true` and `gold_eligible=false`.
- No migrated decision becomes fitting/ML truth until it is independently re-reviewed in a newly published blind bundle.

Regression evidence: `test_controller_supplied_migration_is_matched_by_hash_and_never_gold` and `test_controller_supplied_migration_requires_exact_unique_selection_hashes`.

## Verification

- Finding 9 focused set: 55 passed.
- Broader ladder-research set: 133 passed before the final audit additions.
- Final code-state suite: **714 passed, 3 skipped, 2 warnings** in 75.95 seconds.
- The two warnings are unchanged third-party/deprecation warnings from scikit-learn classification metrics and pandas downcasting behavior.

## Implementation commits

- `3e9e82c` — `fix: blind and constrain round-two cohort`
- `f7e6764` — `fix: enforce research provenance boundaries`
- `e1d58cb` — `fix: isolate and transact review exclusions`
- `c644a3e` — `fix: harden round-two finalization`
- `df85100` — `fix: validate and bound ladder benchmarks`
- `c67769b` — `fix: require reviewed ladder gold evidence`
- `c5c3859` — `fix: close ladder review audit edge cases`

## Residual operational step

There is no known code blocker from findings 1–10. The controller must publish a fresh versioned round-two bundle/withheld pair, repeat the scoped independent audit, and only then relaunch chemist review with the enforced bundle-local adjustment database. The quarantined artifacts must remain unused.
