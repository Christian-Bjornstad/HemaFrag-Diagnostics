# Plan 12 — Ladder Studio remodel

> Branch: `ml-clonality-interpretation-2026-06-27`.
> Window: 2026-07-08 +.
> Status: re-implementing in this branch after a container session's
> Plan 12 work was lost (never pushed). Skill file
> `~/.hermes/skills/lab-workflow/hemafrag-diagnostics-lab/SKILL.md`
> holds the consolidated design.

## Context

Chemists complain: "sometimes when I do a batch run, the ladder fitting
fails... it will make a bundle which have the failed ladders, but the
ladder editor does not find the bundle or kinda works."

Root cause: `_load_review_bundle_worker` silently drops any row whose FSA
path doesn't exist at CSV-load time (`if not full_path.exists(): continue`).
On the chemist's machine, every unreachable T7 path vanishes. The editor
"kinda works" because the load completes with 0 rows and no error.

The big-picture problem is that the **Ladder Studio** tab +
**Ladder Adjustment** dialog are two ~1700-line monolithic files that
grew by accretion. Hard to navigate, hard to test, and several UX flows
mislead the chemist.

## Goals

1. Drop the "kinda works" silent filter — every bundled case shows in the
   list, with reachable/unreachable tag.
2. Phase-wise split of `tab_ladder` and the dialog into modular
   subpackage siblings that mirror `gui_qt/dialogs/ladder_dialog/`.
3. Single-screen overview (chip strip) so the chemist sees all bundled
   cases at one glance.
4. Locate-File re-entry so an unreachable chip is recoverable without
   re-running the batch.
5. Keyboard-first loop so triage doesn't require mouse clicks.
6. Audit JSONL stream for Plan 11 Phase 7's feedback loop.

Everything else is split-module refactors. No new core analysis
features in this plan.

## File map (current state)

| File | Lines | What | Pain |
|---|---|---|---|
| `gui_qt/tabs/tab_ladder/_legacy.py` | 1742 | tab body | monolith, cache + worker + UI all interleaved |
| `gui_qt/dialogs/ladder_dialog/_legacy.py` | ~2000 | modal editor | trace plot + table + candidates + QC + style all in one QDialog |
| `gui_qt/dialogs/ladder_dialog/_constants.py` | small | inline thresholds + pyqtgraph import | OK |
| `gui_qt/dialogs/ladder_dialog/__init__.py` | facade | star-reexport | OK |

## Phases

- **12.0** — fix silent-drop in `_load_review_bundle_worker`. Keep every
  row whose `full_path` is non-empty; tag unreachable rows. Surface count
  to status bar so "0 cases" never silently happens.
- **12.1** — split `tab_ladder/` into `_constants.py`, `_summary.py`,
  `_io.py`, `_workers.py`, `_legacy.py` package with star-reexport facade.
- **12.2** — split `dialogs/ladder_dialog/` into `_style.py`,
  `_matches.py`, `_candidates.py`, `_qc.py`. Mechanical.
- **12.3** — chip-strip overview widget with four-state precedence
  (Reviewed / Needs review / File unreachable / Untouched).
- **12.4** — Locate File re-entry. `relocate_review_case` in core.
- **12.5** — keyboard loop in dialog (J / K next-missing, ← / → nav).
- **12.6** — Alt+J / Alt+K / Ctrl+. chip-strip nav on the tab.
- **12.7** — chip-strip filter (apply_filter_rows, dim non-matching).
- **12.8** — "Mark Visible Reviewed" bulk button.
- **12.9** — audit JSONL stream (`ladder_review_audit.jsonl`).
- **12.10** — drop-row hook (chip context menu).
- **12.11** — DIT prefix filter (chip frame).
- **12.12** — bundle summary banner.
- **12.13** — Ctrl+R mark-current-reviewed keyboard shortcut.
- **12.14** — dialog preview header adds sample + assay + ladder.
- **12.15** — rerun-rationale JSONL (`ladder_review_rationale.jsonl`).
- **12.16** — bundle import/export zip.
- **12.17** — audit-trail mini panel under summary banner.

Tests target: 181 baseline → 250-260 passed, 1 skipped, 0 regressions.

## Cadence

One atomic commit per phase. Helper(s) + tests + GUI wiring + Obsidian
status update, all in one commit. Push immediately after each so a
container restart can't lose the work again.

## Verification

```bash
QT_QPA_PLATFORM=offscreen python -m pytest --tb=no -q
```

Baseline count on this branch: **181 passed, 3 skipped, 2 failed**
(2 pre-existing Windows path-mangling failures unrelated to Plan 12 —
`/tmp/review.fsa` POSIX-style fixture on Windows OS, and a tempfile
Win32 file-lock on FLT3 workbook cleanup).
