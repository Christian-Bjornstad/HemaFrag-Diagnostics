# LIZ Core-First Ladder Fitting Design

## Goal

Improve automatic patient-clonality LIZ ladder fitting by preventing the less-important 35 bp anchor from moving an otherwise better 50–500 bp core fit.

## Scope

- Patient clonality only.
- LIZ500_250 only; preserve the current ROX rescue behavior unchanged.
- Preserve the existing 16-anchor output and all existing public data structures.
- Add no 35 bp status, warning, field, UI element, or separate report.
- Do not use `D:\DATA\backup`.

## Fitting behavior

1. Evaluate and lock the ordered 50–500 bp LIZ core independently of 35 bp.
2. Predict the expected 35 bp scan from the locked core sizing relationship.
3. Select the best plausible existing peak near that prediction using peak quality and geometric consistency.
4. Prepend the selected 35 bp peak to produce the same 16-anchor ladder consumed today.
5. Never allow the selected 35 bp peak to alter, replace, or reject the locked 50–500 bp core.
6. If no new 35 bp candidate is clearly preferable, retain the current fit's 35 bp anchor while leaving the core locked.

## Safety and scoring

- Core comparisons exclude only the 35 bp anchor; every 50–500 bp anchor remains strict.
- Promotion requires zero regression in previously exact 50–500 bp core sequences.
- A changed core sequence must become exact or strictly closer to manual gold.
- The existing deterministic 2-second rescue and 10-second deep-rescue ceilings remain unchanged.
- Candidate ordering and tie-breaking remain deterministic.

## Evidence strategy

The completed development and validation reviews may be used as tuning evidence because their outcomes are now known. They are no longer independent validation evidence for the next candidate.

Before production integration, create a fresh patient-clonality holdout with no overlap by physical run or content hash. Evaluate strict full-ladder accuracy, 50–500 bp core accuracy, exact-control preservation, major core errors, determinism, and latency. The 35 bp anchor remains part of the ordinary ladder output but is not exposed through any new reporting surface.

## Acceptance criteria

- Existing 16-anchor consumers require no changes.
- No previously exact 50–500 bp core fit regresses in reviewed evidence.
- No increase in major 50–500 bp sequence errors for LIZ or ROX.
- ROX improvements from the frozen candidate remain intact.
- Three repeated runs produce identical anchor sequences.
- No run exceeds the configured rescue ceiling.
- A fresh blind holdout confirms improvement before merging into production.
