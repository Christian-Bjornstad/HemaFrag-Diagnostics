# HemaFrag Open Items

## FLT3 First

- Mark missing/weak ladder rows as data quality/fail, not motor training.
- Review the 6 remaining FLT3 GS500ROX `REVIEW` rows from `local_triage/flt3_rox500_residual6_2000_2025_2026_2026-05-14`.
- Do not broaden GS500ROX thresholds beyond the current residual-only cleanup without annotation support.
- Compare any remaining true GS500ROX `35/50` start-family failures against visually good rows before implementing a family-aware repair.

## Keep Parked

- Clonality ladder/motor work is parked unless explicitly requested.
- Do not pull old clonality learning back into active context by default.

## Hygiene

- Do not stage generated `artifacts/`, `local_triage/`, caches, raw data, build outputs, or scratch review bundles.
