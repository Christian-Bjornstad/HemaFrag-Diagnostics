# Clonality ML — Model Changelog

> Each row is a single shipped artifact (model + template + per-assay threshold).
> Schema:
> - **ID** — stable name, e.g. `clonality-ml-v0.1.0-pa-fr1-rf` (per-assay / per-model / per-version).
> - **Date** — published.
> - **Driver** — what kicked off this timing of re-training (`chemist-review`, `feedback-recompute`, `temp-impl`).
> - **Per-assay metrics** — accuracy / recall / precision / F1 on OOF holdout. Always include `monoklonal` F1, that's the rare-class we care about most.
> - **Accept threshold (τ)** — value used in production, per-assay.
> - **Calibration dataset hash** — sha256 of the source-CSV parquet-export that fed training; matches an entry in `ObsidianVault/Clonality_ML_Log/data_manifest.csv`.
> - **Drift** — qualitative comment on what feels different from the prior version, if any.
> - **Signoff** — chemist name + date who accepted this version for production.

| ID  | Date | Driver | Per-assay metrics (acc / mono-F1 / poly-F1) | Accept τ | Calibration hash | Drift | Signoff |
|-----|------|--------|----------------------------------------------|-----------|---------------------|-------|---------|
| (template only — first row will arrive after Phase 3 ships) |||||||
| `clonality-ml-v0.1.0-pa-ml-learning-tab` | 2026-07-12 | GUI workflow landed | — | — | — | New: ML Learning tab in app sidebar + Plotly annotation panel + JSONL → trainer merge. Branch `feat/ml-learning-tab-2026-07-12`. Atomic commits 3ddd93a / a2c966a / 77da89a. | — |

## Maintenance rules

- **Never delete a row.** Add a row when shipped, even for hot-fix versions (`v0.1.1`).
- Archive only by marking `Archive: yes` in a footnote.
- `Date` is the published-date, not the train-start.
- The `Calibration hash` is what a future reviewer re-runs `train_*.py` against to verify the same numbers appear.
