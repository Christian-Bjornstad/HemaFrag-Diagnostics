# Plan 02 — Analysis + Rust bridge review

> Branch: `code-cleanup` (off `codex-clonality-ladder-finalize-2026-05-14`).
> Test baseline: `Ran 33 tests, OK` via
> `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests`.
> Reviewer responsibility: **real findings only**.

This plan covers the core ladder-fit logic and the hybrid Rust engine
bridge — the heart of the analysis pipeline.

---

## 1. Architecture summary

- **Two-gear ladder fit**: Python `core/analysis/_legacy.py` runs a
  detailed candidate search (peak combinations, GS500ROX refinement
  attempts, ROX bounded search, missing-step rescue). When a fit is
  committed, `core/rust_bridge/run_ladder_fit_hybrid`
  (`_legacy.py:946`) consults the Rust engine (`fraggler-cli`) as
  primary; Python can rescue via `_legacy.py` ladder fallback unless
  the strict-Rust opt-in switch is set.
- **Family-aware ROX profiles** enforced via `_constants.py`
  constants `LADDER_FIT_PROFILE_CLONALITY_LIZ500`,
  `LADDER_FIT_PROFILE_CLONALITY_ROX400HD`,
  `LADDER_FIT_PROFILE_FLT3_GS500ROX`.
- **Rust worker lifecycle**:
  - `_RustSizingModel` (L37-71) — data-class wrapper.
  - `_RustPrimitiveWorker` (L234-351) — owns the `subprocess.Popen`
    to `fraggler-cli`.
  - `_get_rust_worker` / `_get_rust_worker_pool` /
    `prime_rust_worker_results` — composition entry points.
- **Threading / locks**: `_RUST_WORKER_LOCK`,
  `_RUST_PREWARM_WORKERS_LOCK`, `_RUST_RESULT_CACHE_LOCK`,
  `_RUST_ENGINE_STATS_LOCK`; `_RUST_RESULT_CACHE` is an OrderedDict
  capped at `_RUST_RESULT_CACHE_MAX = 2048`. *Windowed Windows builds
  must not use the persistent worker* (per
  `ObsidianVault/01_Project_Memory.md` *Hygiene*).
- **Strict-Rust opt-in**: `core/engine_flags.strict_rust_ladder_enabled`
  is the single switch (`HEMAFRAG_STRICT_RUST_LADDER=1` OR
  `HEMAFRAG_RUST_ONLY=1` OR `engine.strict_rust_ladder=true`).
- **Windows CLI fallback**: `_run_cli_once` is the one-shot hidden
  CLI for windowed Windows builds; `select()` on persistent worker
  pipes raises `WinError 10038` on those builds.
- **Validation surface**: `_validate_rust_anchor_selection` (L712+)
  + `_allow_guardrail_review_hydration` (L834+) decide whether a
  fitted ladder survives under narrow review-band criteria.
- **Cross-module constant dependencies** for `core/analysis/_constants.py`:
  - `numpy` (used for `GS500_FAMILY_STEPS`, `ROX400HD_FAMILY_STEPS`)
  - `fraggler.fraggler` (`FsaFile`, `baseline_arPLS`, …)
  - `core.assay_config` (`DEFAULT_LIZ_LADDER`, `MIN_DISTANCE_BETWEEN_PEAKS_*`,
    `SL_WINDOW_BP`, …)
  - `core.engine_flags` (`strict_rust_ladder_enabled`)

## 2. File inventory (verbatim `wc -l`)

```
   22  core/analysis/__init__.py
  234  core/analysis/_constants.py
 4906  core/analysis/_legacy.py
   15  core/rust_bridge/__init__.py
   94  core/rust_bridge/_constants.py
 1181  core/rust_bridge/_legacy.py
 6452  total
```

## 3. Cross-reference map

External callers of `core.analysis` (verbatim `grep -rn`):

- `core/analyses/clonality/candidate_artifacts.py` imports
  `get_ladder_candidates`.
- `core/analyses/clonality/pipeline.py` imports ladder profile
  constants + `analyse_fsa_liz`, `analyse_fsa_rox`,
  `auto_detect_sl_peaks`, `compute_ladder_qc_metrics`,
  `compute_sl_area_metrics`.
- `core/analyses/flt3/pipeline/_legacy.py` (the big consumer)
  imports profile keys, `_select_best_ladder_candidate`,
  `apply_manual_ladder_mapping`, `analyse_fsa_liz`, `analyse_fsa_rox`,
  `compute_ladder_qc_metrics`, `estimate_running_baseline`,
  `get_ladder_candidates`.
- `core/analyses/general/pipeline.py` imports `analyse_fsa_liz`,
  `analyse_fsa_rox`, `compute_ladder_qc_metrics`.
- `core/plotting_plotly/_legacy.py` imports `estimate_running_baseline`
  + `BASELINE_BIN_SIZE`, `BASELINE_QUANTILE`, `YMAX_PADDING_FACTOR`.
- `core/qc/qc_markers.py` + `core/qc/qc_plots.py` import
  `estimate_running_baseline`.
- `gui_qt/dialogs/ladder_dialog/_legacy.py` imports
  `get_ladder_candidates`, `apply_manual_ladder_mapping`,
  `compute_ladder_qc_metrics`.
- `gui_qt/ladder_utils.py` imports profiles + `analyse_fsa_liz`,
  `analyse_fsa_rox`.
- `gui_qt/tabs/tab_ladder/_legacy.py` imports `load_ladder_adjustment`,
  `save_ladder_adjustment`.
- `scripts/run_flt3_liz500_qc_all_injections.py` imports
  `compute_ladder_qc_metrics`.
- `fraggler/fraggler.py` (the upstream package wrapper) provides
  `FsaFile`, `baseline_arPLS`, `fit_size_standard_to_ladder`
  consumed by `core/rust_bridge/_legacy.py`.

## 4. Intentional tech debt (do not churn)

- `_windows_subprocess_kwargs()` — produces `creationflags`,
  `startupinfo`, `SW_HIDE` for windowed Windows builds. Per
  Project Memory *Hygiene*, frozen Windows runtime is `None`-tolerant
  for `sys.stdout`/`sys.stderr`; this helper is part of that
  contract.
- Persistent Rust worker + prewarm — disabled on Windows by
  Project Memory mandate. Helpers stay in place; callers skip them
  via `core/engine_flags` and platform check.
- Strict-Rust opt-in switch — opt-in, must NOT auto-enable.
- Hybrid mode where Rust preview is primary but Python rescue is
  fallback unless strict — current behavior; do not invert.
- `OrderedDict` result cache size 2048 — chosen for memory
  footprint; not a hot spot to tune.

## 5. Actionable task list

### Task 1 — Sub-split: extract ROX ladder candidate-fit module
- **Scope**: pull ~25 ROX-specific ladder search functions
  (`_build_bounded_rox_candidate_specs`, `_append_rox_seeded_anchor_specs`,
  `_round_to_monotonic_indices`, `_build_partial_rox_step_assignments`,
  `_select_best_bounded_ladder_fit`, `_try_rox_shifted_family_tail_repair`,
  `_try_rox_edge_family_repair`, `_try_rox_baseline_family_rebuild`,
  and the `_try_rox400hd_local_refinement` family) out of
  `_legacy.py` into a new `core/analysis/_rox_fit_search.py`. They
  form a coherent ~1000-line search orchestration.
- **Why**: the ladder search code is the dominant reason `_legacy.py`
  is 4906 lines; splitting makes the next-phase sub-splits cheaper.
- **Acceptance**: facade re-export; no behavior change; tests
  still 33/33.
- **Commit**: `refactor(analysis): split ROX ladder search into _rox_fit_search.py`
- **Risk**: medium (high cross-function references).  **Effort**: L.

### Task 2 — Sub-split: extract GS500 ladder refinement module
- **Scope**: pull `_try_gs500_family_local_refinement`,
  `_local_refinement_options`, `_trace_peak_options`, the 29-something
  `_gs500_*_*` family into a new
  `core/analysis/_gs500_refinement.py`.
- **Why**: same reason as Task 1.
- **Acceptance**: facade re-export.
- **Commit**: `refactor(analysis): split GS500 ladder refinement into _gs500_refinement.py`
- **Risk**: medium.  **Effort**: L.

### Task 3 — Constant module: introduce `_engine_flags` submodule
- **Scope**: `core/engine_flags.py` (~15 lines today) moves into the
  `core/engine_flags` package with `_machinery.py` (the env-var
  parser) and `__init__.py` (the public `strict_rust_ladder_enabled`).
- **Why** (optional): the current layout is fine but a package
  version of `engine_flags` matches the pattern set by Analysis Rust
  etc.
- **Acceptance**: tests still 33/33.
- **Commit**: `refactor: convert engine_flags.py to small package`
- **Risk**: low.  **Effort**: S.

### Task 4 — Rust bridge: document the worker engine-stat contract
- **Scope**: add a docstring block to `_RUST_ENGINE_STATS` (in
  `core/rust_bridge/_constants.py`) enumerating
  `cache_hits`, `worker_hits`, `cli_hits`, `failures`,
  `prewarm_cached` and their semantic meaning. Today the dict
  initialization is the only place the keys are listed.
- **Why**: callers like `format_rust_engine_stats` rely on the
  full key set; one forgotten key silently reports 0.
- **Acceptance**: docstring in place; observability consistent.
- **Commit**: `docs(rust-bridge): document RUST_ENGINE_STATS key contract`
- **Risk**: low.  **Effort**: S.

### Task 5 — Type hint sweep: harden `core/rust_bridge/_legacy.py`
- **Scope**: add `from __future__ import annotations` is already
  present. Add explicit `Optional[X]` vs `X | None` consistency,
  add `# type: ignore[specific]` only where genuinely needed (not for
  cosmetic notes).
- **Why**: the file is heavily relied upon and `_legacy.py` lacks
  many parameter-typing patterns that would catch bugs at lint time.
- **Acceptance**: `mypy --no-strict` passes on the file (if added
  to CI as Plan 06 may propose).
- **Commit**: `chore(rust-bridge): tighten type hints on top-level helpers`
- **Risk**: low (typing-only).  **Effort**: M.

### Task 6 — Test gap: cover `_validate_rust_anchor_selection`
  - family boundaries
- **Scope**: extend `tests/test_gs500rox_guardrail.py` with targeted
  cases for rejected-first-anchor and accepted-first-anchor cases
  (e.g., the documented 1600-1725 late-first-anchor guardrail per
  Project Memory).
- **Why**: today the guardrail tests are concentrated; Project Memory
  describes many sub-cases worth checking.
- **Acceptance**: tests run cleanly.
- **Commit**: `test(guardrail): lock first-anchor family boundaries`
- **Risk**: low.  **Effort**: M.

### Task 7 — Defensive: document the threading invariants
- **Scope**: add a docstring to `_RUST_WORKER_LOCK` /
  `_RUST_RESULT_CACHE_LOCK` / `_RUST_PREWARM_WORKERS_LOCK` /
  `_RUST_ENGINE_STATS_LOCK` annotating the order in which they may
  be acquired, to prevent future deadlock via acquisition-order
  inversion.
- **Why**: four locks exist; any future code that nests two of them
  needs to know the canonical acquisition order.
- **Acceptance**: docstrings in place.
- **Commit**: `docs(rust-bridge): annotate lock acquisition order`
- **Risk**: low.  **Effort**: S.

## 6. Verification

```
$ wc -l /workspace/hemafrag/core/analysis/*.py \
        /workspace/hemafrag/core/rust_bridge/*.py
   22  core/analysis/__init__.py
  234  core/analysis/_constants.py
 4906  core/analysis/_legacy.py
   15  core/rust_bridge/__init__.py
   94  core/rust_bridge/_constants.py
 1181  core/rust_bridge/_legacy.py
 6452  total

$ grep -cE '^[A-Z_]+ *=' core/analysis/_constants.py core/rust_bridge/_constants.py \
                                          core/analyses/flt3/pipeline/_constants.py
   26  # analysis
   19  # rust_bridge
    2  # flt3 pipeline (most constants live in _legacy.py)

$ QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
Ran 33 tests in 2.534s
OK
```
