# Dependencies Decision — Plan 11

> Audit of every Python dep Plan 11 (Clonality Interpretation Assist) might need, drawn from the current `requirements.txt` of HemaFrag. Goal: keep zero new third-party packages past scikit-learn + joblib. Anything new needs explicit approval.

## Already in requirements.txt (verified 2026-06-28)

- **joblib** ≥ 1.5 — model serialization (already in pytest extras; will be promoted to runtime for Phase 3 onward)
- **numpy** ≥ 1.26 — array ops
- **pandas** ≥ 2.2 — entry feature frames
- **pandas-flavor** ≥ 0.6 — entry feature helpers
- **scikit-learn** ≥ 1.5 — RandomForest, GradientBoosting, QDA, Platt scaling
- **scipy** ≥ 1.13 — neighbour / sparse features

## Optional, NOT currently in requirements.txt

- **xgboost** ≥ 2.0 — would replace RF as a stronger baseline. Decision: deferred. If by Phase 3 we observe RandomForest rare-class F1 < 0.85 on any assay, we add xgboost. Tracking at `ObsidianVault/Clonality_ML_Log/decisions/xgboost_pending.md` (TODO).
- **lightgbm** ≥ 4.0 — same reason as xgboost; deferred.
- **tabpfn** — tabular prior-fitted networks. Decision: explicitly OUT. Off-the-shelf doesn't fit per-assay calibration cleanly, and the dep is heavier than sklearn. If chemist later asks, that's a Phase 7+ research question.
- **tensorboard / wandb** — no training-of-deep-models in scope; keep these OUT.

## Coding env (already present)

- **pytest** ≥ 7 — runtime tests, including new `tests/test_clonality_interpretation_*` files.
- **pandas.read_parquet** with `[pyarrow]` could be a Phase 5+ requirement if we export per-batch datasets to parquet for tabular models. **Decision: defer; CSV/TSV for the first shipped model, parquet in Phase 5* if a chemist asks for speed.**
- **pyo3-based** `fraggler_native` wheel — already shipped (commit `b54d644`). NOT used by Plan 11 directly, but Plan 16 (FLT3) and Plan 12 (clonality) reference signal-extraction features extracted at this layer.

## Phasing policy

- **Phase 0 / 1 / 2**: zero deps. (Today.)
- **Phase 3**: promote `joblib` from `pytest` extra to runtime, since we'll be saving models. (One-line change in `requirements.txt`.)
- **Phase 4**: zero deps. (sklearn's `CalibratedClassifierCV` handles Platt scaling internally.)
- **Phase 5**: zero deps. (just `joblib` save/load + JSON metadata.)
- **Phase 6**: zero deps. (writes existing tracking_excel columns plus a few ML columns; no new package.)
- **Phase 7**: zero deps. (in-process `model.predict_proba`; no service.)
- **Latest conceivable horizon (`Phase 8+`)**: if a chemist asks to use TITAN / ImmuneML for sequence-aware features, that's a large refactor — DO NOT install automatically; talk first.

## Promotion triggers

`joblib` listed in `requirements.txt`'s braces in `[dev]` extras (pytest side). Move to runtime by:
1. Removing from `[dev]` extras.
2. Adding `joblib==X.Y` to the main install list.
3. Re-running `pip install -e .`; any subsequent `import joblib` works for end users, not just testers.

Pin `joblib` to current minor version to avoid ABI drift. The scikit-learn `joblib` is fine for the project version.
