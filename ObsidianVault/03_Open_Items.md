# HemaFrag Open Items

## FLT3 First

- Mark missing/weak ladder rows as data quality/fail, not motor training.
- Review the 6 remaining FLT3 GS500ROX `REVIEW` rows from `local_triage/flt3_rox500_residual6_2000_2025_2026_2026-05-14`.
- Do not broaden GS500ROX thresholds beyond the current residual-only cleanup without annotation support.
- Compare any remaining true GS500ROX `35/50` start-family failures against visually good rows before implementing a family-aware repair.

## Plan 15 Operator Verification

- Pull the final Plan 15 branch on the Python 3.14 work computer and rerun the private LIZ, ROX, FLT3, and combined reference scenarios; compare counts, selected ladder anchors, review cases, report completeness, and timings with the Plan 13 manifest.
- Recreate the Windows shortcut with `packaging/create_windows_shortcut.ps1`, then visually verify title-bar, Alt-Tab, taskbar, and newly pinned shortcut icons. Unpin stale shortcuts if Windows retains an old cached icon.

## Keep Parked

- Clonality ladder/motor work is parked unless explicitly requested.
- Do not pull old clonality learning back into active context by default.

## Hygiene

- Do not stage generated `artifacts/`, `local_triage/`, caches, raw data, build outputs, or scratch review bundles.
