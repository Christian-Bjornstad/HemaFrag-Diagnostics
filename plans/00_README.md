# HemaFrag Review & Roadmap — `code-cleanup` branch

> **Status**: review plans complete 2026-06-27.
> **Source-of-truth branch**: `code-cleanup` (off `codex-clonality-ladder-finalize-2026-05-14`).
> **Test baseline bar**: `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests` reports `Ran 33 tests, OK`.

This folder holds detailed review plans produced after the `code-cleanup`
campaign landed (13 commits). Each plan is **durable, actionable, and
isolated** — no plan should change behavior outside its documented
scope, and each provides acceptance criteria so we can verify post-merge.

## Per-track plans

| # | Track | Plan file | One-line summary |
|---|---|---|---|
| 01 | FLT3 pipeline | `01_flt3_pipeline_review.md` | Core FLT3 ladder/QC/peak-reporting surface (production-busy). |
| 02 | Analysis + Rust bridge | `02_analysis_and_rust_review.md` | Ladder-fit primitives + hybrid Rust engine fallback. |
| 03 | Plotting + GUI | `03_plotting_gui_review.md` | Plotly HTML reports, Qt tabs/dialogs, ladder dialogs. |
| 04 | Clonality (parked) | `04_clonality_parked_review.md` | Parked subsystem — structure-only, no behavior changes. |
| 05 | Scripts & packaging | `05_scripts_and_packaging_review.md` | CLI runners, Docker/Windows build chain, requirements, CI. |
| 06 | Tests & hygiene | `06_tests_and_hygiene_review.md` | Test coverage gaps, post-cleanup workspace hygiene. |
| 07 | Performance optimization | `07_optimization_essentials.md` | Essentials-preserving perf: shrink per-patient Resultater.html from ~5 MB to ~10 KB by externalizing plotly JS. |

## Cross-cutting concerns

These themes appear in **multiple** plans and look like the lowest-cost
high-value follow-ups across the campaign:

### 1. CI does not exercise the full test suite (Plans 05 + 06)

Plan 05 Task 1/2/3 and Plan 06 Task 1/2/3 all converge on:
- `.github/workflows/ci.yml` only runs two test files today
  (`tests/test_ladder_review_gate.py`, `tests/test_water_filter.py`).
- The same CI workflow's `py_compile` step references the
  pre-Phase-5 file paths `gui_qt/tabs/tab_batch.py`,
  `gui_qt/tabs/tab_ladder.py`, `gui_qt/dialogs/ladder_dialog.py`
  — all three are now packages; `py_compile` would silently skip
  them.

Action: one consolidated PR fixing CI:
- Replace two-test list with `python3 -m unittest discover -s tests`.
- Update py_compile targets to current paths (or use a glob).
- Set `QT_QPA_PLATFORM=offscreen` for the test step.
- Suggested PR title: `ci: align with code-cleanup branch (full tests + package paths)`
- Estimated effort: **S** (single-file `.github/workflows/ci.yml` change).

### 2. Silent ImportError-fallback swallows in two GUI tabs (Plans 01 + 03)

Plans 01 Task 6 and 03 Task 2 both flag this. Two tabs in
`gui_qt/tabs/{tab_archive_runner.py,tab_flt3_validation.py}`
swallow ImportError on optional helper scripts and silently
mark features unavailable:

- `scripts/run_flt3_backfill_validation.py` (missing)
- `scripts/run_clonality_yearly` (missing)
- `scripts/combine_clonality_yearly_overview` (missing)

After deletion in Phase 1, those modules *correctly* log a
fallback, but the user clicking those tabs gets no surfaced notice.

Action: one consolidated PR adding `print_warning`/tab-banner
notifications in both files.
- Estimated effort: **S** per file.

### 3. Sub-splits of large `_legacy.py` files (Plans 01 + 02 + 03)

Phase 5/6/2a + 3 produced eight `_legacy.py` modules of size
> 1000 lines:

| Subclass | Size | Plan mentioning |
|---|---|---|
| `core/analysis/_legacy.py`         | 4906 lines | Plan 02 Tasks 1/2 |
| `core/analyses/flt3/pipeline/_legacy.py` | 6904 lines | Plan 01 Tasks 3/4 |
| `core/rust_bridge/_legacy.py`      | 1181 lines | Plan 02 Task 5 (type hints) |
| `core/plotting_plotly/_legacy.py`  | 2039 lines | Plan 03 Task 3 |
| `core/html_reports/_legacy.py`     | 1597 lines | Plan 03 Task 4 |
| `gui_qt/tabs/tab_batch/_legacy.py` | 1646 lines | Plan 03 Task 1 |
| `gui_qt/tabs/tab_ladder/_legacy.py`| 1742 lines | (out of scope per Phase 5 wrap-up) |
| `gui_qt/dialogs/ladder_dialog/_legacy.py` | 2023 lines | (out of scope) |

These are the lowest-cost, highest-coverage wins. Each `_legacy.py`
split is mechanical after the package conversion (facade re-export).

Action: 4-6 follow-up PRs over multiple sessions, each iterating
on one `_legacy.py` partition that fits a reviewable scope.
- Pattern documented in CLEANUP_PLAYBOOK.md.

### 4. Test coverage gaps for new code (Plans 01-05 + 06)

Today's 33 tests lean heavily on FLT3 surface (8 test files,
~1570 lines). The post-Phase 7 wiring is not directly tested:

- No end-to-end smoke for `run_pipeline` (Plan 01 Task 5).
- `_validate_rust_anchor_selection` lacks boundary cases (Plan 02 Task 6).
- Empty/stale/missing entries for HTML reports (Plan 03 Task 6).
- `KNOWN_CLONALITY_BACKFILL_SKIP_FILES` filter (Plan 04 Task 4).
- `NONSPECIFIC_PEAKS` exclusion (Plan 04 Task 5).

If we ship Plans 01-05 without test gaps, the next refactor cycle
loses regression coverage. Action: when picking up a Phase-7x
task, prefer to add a test in the same PR as the refactor.

### 5. Documentation: empty `__init__.py` files (Plans 01 + 03)

- `core/analyses/flt3/__init__.py` — 0 bytes (Plan 01 Task 1).
- `core/analyses/__init__.py` — 0 bytes (Plan 01 Task 2).

Cost: a single PR adding the docstrings.

### 6. Hygiene: app.py / HemaFrag.spec (Plans 01 + 05)

- `app.py` referenced by `HemaFrag.spec:8` as a PyInstaller data file.
- Python-import analysis shows zero `import app` callers.
- If confirmed safe to remove, bundle size reduces.

## How to use this folder

1. Pick the track whose file you want to action.
2. Each task is ordered smallest/safest first; risks rise further down.
3. Each task has an acceptance criterion tied to a verification command.
4. The "Verification" section at the bottom of each plan is the audit trail.

## Author conventions used across plans

- file:line references: always real, never invented.
- "no findings" beats fabricated findings.
- Tech debt called out as INTENTIONAL when it serves a current goal.
- Risk: `low` (cosmetic), `medium` (one-file refactor under facade),
  `high` (cross-cutting, requires test rewrite or behavior risk).
- Effort: `S` < 30 min, `M` 30-90 min, `L` 2-4 hours, `XL` > 4 h.

## Branch state at the time of writing

13 commits on `code-cleanup` (off `codex-clonality-ladder-finalize-2026-05-14`):

```
37112cb Phase 0 — env + verification recipe
109a9b4 Phase 1 — delete legacy modules
2f96668 Phase 1 notes — log/memory capture
f860086 Phase 2a — core/analysis.py → package
33e8c82 Phase 3 — core/analyses/flt3/pipeline.py → package
df86408 Phase 4 — clonality structural tidy
12a1baa Phase 5a — gui_qt/tabs/tab_batch.py → package
c1348a8 Phase 5b — gui_qt/tabs/tab_ladder.py → package
c9f8228 Phase 5c — gui_qt/dialogs/ladder_dialog.py → package
508138e Phase 6a — core/rust_bridge.py → package
3a95391 Phase 6b — core/plotting_plotly.py → package
ed36357 Phase 6c — core/html_reports.py → package
2cab6e3 Phase 7 fix — repair tab_ladder docstring + final hygiene + push
```

Latest commit on origin: `2cab6e3`. Branch: `code-cleanup`.

## Suggested next-2-PR sequence (smallest first)

- **PR A** — Plans 05 + 06 together: `ci: align with code-cleanup branch`
  - covers Plans 05 Tasks 1-3, 06 Tasks 1-3
  - Effort: **S**. Risk: low. Highest leverage.
- **PR B** — Plans 01 + 03 together: `fix(gui): surface silent ImportError fallback`
  - covers Plans 01 Task 6 + 03 Task 2
  - Effort: **S**. Risk: low. User-visible.

Beyond that, each Plan task stands on its own and ships in a small PR.
