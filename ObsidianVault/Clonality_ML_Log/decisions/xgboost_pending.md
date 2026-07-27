# xgboost Pending Decision

> **Status (2026-06-28):** deferred, NOT in current scope. This file is a placeholder for the trigger criterion.

## Trigger to promote

If, after `scripts/train_clonality_interpretation_models.py` (Phase 3) ships for FR1 alone, the rare-class (`monoklonal`) F1 of the best scikit-learn model is **< 0.85 on OOF holdout**, then re-evaluate.

Specifically, the failure mode we'd observe:
- `monoklonal` recall high (lots of ops catching positive cases),
- `monoklonal` precision low (lots of false-positive polyphonal labels flipped to mono).
- A clear sign: a small handful of DITs have all-mono predictions across all 5+ assays, where the rule engine had flagged one or two of those as polyclonal — the disagreement rate is high.

If that happens, **add xgboost** as a second model and run a head-to-head against RandomForest per assay. Keep RF as the production choice UNTIL xgboost is empirically better by ≥3 F1 across all current-OOF rare-class performance.

If xgboost is added:
- Pin to 2.0+.
- Add `xgboost==2.<x>.<y>` to `requirements.txt` Main.
- Update this file to record which version, the date, the per-assay numbers, and chemist sign-off.
- Move this file to be archived-by-overwriting the first paragraph with "Implemented: <date>".

Otherwise this file is a marker for the trigger and stays as-is.
