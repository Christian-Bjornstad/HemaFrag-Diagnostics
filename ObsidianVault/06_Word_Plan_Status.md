# Word Plan Status - 2026-05-05

Source documents:
- `/Volumes/T7 Shield/Oversikt_algoritmer_size_standard_baseline_peakvalg.docx`
- `/Volumes/T7 Shield/Plan_test_implementering_klonalitet_size_baseline_peakdetection.docx`

## Current Status

The Word plan is mostly in phase 3-5 now, not phase 0. The strongest remaining gap was phase 1: a unified manifest/fasit layer that separates benchmark controls, real training pairs, review candidates, and operator/bad-ladder cases.

That gap is now started with `scripts/build_ladder_learning_manifest.py`, which writes:
- `artifacts/ladder_learning_manifest/current_manifest.tsv`
- `artifacts/ladder_learning_manifest/current_manifest.json`
- `artifacts/ladder_learning_manifest/summary.json`

The first standard manifest delta-eval is also started with `scripts/run_ladder_manifest_delta_eval.py`, which writes:
- `artifacts/ladder_manifest_delta_eval_manual_2026-05-05/case_results.tsv`
- `artifacts/ladder_manifest_delta_eval_manual_2026-05-05/watchlist.tsv`
- `artifacts/ladder_manifest_delta_eval_manual_2026-05-05/summary.json`

Current manifest snapshot:
- `2048` unique 2025/2026 rows
- `2011` benchmark controls
- `27` usable manual training pairs
- `8` non-regression controls from reviewed-no-change cases
- `2` excluded operator/bad-ladder cases

## Phase Mapping

| Word phase | Status | HemaFrag state | Next action |
|---|---:|---|---|
| Phase 0: Document current pipeline/debug outputs | Mostly done | Rust/Qt flow, review gate, eval scripts, and memory notes exist. | Keep updating session log after major changes. |
| Phase 1: Test library + truth/manifest | In progress | Benchmark cases and manual review bundles existed separately; unified manifest is now added. | Expand manifest with more manual review labels and curated good/bad controls. |
| Phase 2: Offline benchmark runner | In progress | `ladder_learning_benchmark.py`, broad live evals, time-template analysis, live Rust evals, and manifest delta-eval now exist. | Harden the delta report and run it on broader control cohorts before each engine promotion. |
| Phase 3: Module screening | In progress | Baseline methods, candidate methods, apex recentering, ROX/LIZ repairs, templates, and sizing comparisons have been tested. | Continue module tests through manifest cohorts, not only handpicked files. |
| Phase 4: Combined pipeline / arbiter | In progress | Default-plus-side-lane architecture is established; LIZ/ROX behave differently. | Promote only gated repairs/lanes that improve bad cohorts without regressing controls. |
| Phase 5: Shadow production / review gate | Mostly implemented | Batch writes review bundles; Qt popup and Ladder Studio review workflow exist; Run tab owns finalization. | Polish UX and run more real batch shadow tests. |
| Phase 6: Controlled rollout | Not started | Hard gate exists but default is off. | Start only after several clean shadow runs on real folders. |

## Practical Direction

Use the manifest as the source of truth for learning:
- `training_pair`: manual-adjusted files with `.ladder_adj.json`; useful for auto-vs-manual learning.
- `non_regression_control`: user-approved fits; must not become worse.
- `benchmark_control`: broad good/mid/bad files from 2025/2026; used for aggregate stability.
- `exclude_from_motor_training`: missing ladder, bad ladder, broken file, or operator error; useful for QC but not motor optimization.

The next implementation target from the Word plan is to use the standard delta-eval output as the promotion gate:
- run `scripts/run_ladder_manifest_delta_eval.py` on manual pairs and non-regression controls after every ladder-engine change
- run the same command on broader benchmark controls before any default/side-lane promotion
- inspect `watchlist.tsv` before accepting changes

This gives a repeatable promotion gate for future changes like LIZ bounded side-lanes, ROX minwin-side-lanes, and reverse-DP/tail-to-front repairs.

## First Delta-Eval Snapshot

Command:
`python3 scripts/run_ladder_manifest_delta_eval.py --out-dir artifacts/ladder_manifest_delta_eval_manual_2026-05-05 --include-uses training_pair,non_regression_control --timeout 60`

Result:
- `35/35` rows analyzed, `0` errors
- `27` training-pairs and `8` non-regression controls
- `11` current Rust review flags
- `31` watchlist rows after filtering invalid non-scan manifest references

Interpretation:
- The manual-pair set is doing its job: many rows still differ from user-approved `.ladder_adj.json`, so they are useful learning targets.
- The non-regression set is also valuable: some `reviewed_no_change` rows still have high linear QC or changed selected peaks, so we need to distinguish "visually accepted but QC hard" from true engine regressions before tightening gates.

## First Triage Snapshot

Added:
- `scripts/triage_ladder_delta_watchlist.py`
- `scripts/render_ladder_delta_triage_images.py`

Outputs:
- `artifacts/ladder_delta_triage_manual_2026-05-05/triage.tsv`
- `artifacts/ladder_delta_triage_manual_2026-05-05/actionable.tsv`
- `artifacts/ladder_delta_triage_manual_2026-05-05/report.md`
- `artifacts/ladder_delta_triage_manual_2026-05-05/images/`

Triage result:
- `5` P0 rows
- `12` P1 rows
- `15` P2 rows
- `3` P3 rows

Most important interpretation:
- Do not use `qc_tolerance_manual_match` rows for peak-selection tuning; current Rust already matches manual, so those are QC/review-gate calibration cases.
- Real P0 motor targets are mainly LIZ blob/sequence cases: `25OUM12332`, `25OUM13218`, `25OUM16288_B03`, and `26OUM05318_IGK`.
- `25OUM11795_FR2` is P0 by numbers, but should be treated cautiously because previous review notes flagged it as weak/unclear.

## Gated LIZ Anchor Rescue Snapshot

Added in Rust:
- suspicious-only LIZ hardcase anchor rescue for weak `35/50`-area micropeaks and `490/500`-area tail anchors
- pre-blob noise rejection before `1350` when enough post-blob LIZ candidates exist
- gating so the extra pool is not applied to normal/good LIZ files

Manual/non-regression delta after this patch:
- `35/35` ok, `0` errors
- total review `10 -> 7` compared with the previous reverse-DP snapshot
- LIZ review reduced to `1`, and that row is `25OUM12848` which remains a visual/data-quality case
- P0 triage reduced to `1`: only ROX `25OUM11795_FR2`

Broad LIZ smoke:
- `250/250` benchmark-control LIZ rows ok
- `0` review
- max linear max ca `5.10 bp`
- no rows over `6 bp` linear max or `3 bp` linear mean

Next plan step:
- Treat LIZ anchor rescue as provisionally promoted.
- Move the next motor focus to ROX P0/P1 cases, especially `25OUM11795_FR2` cautiously, `25OUM00537_TRB_mixB`, and minor ROX anchor/apex shifts.
- Separately clean up stale Rust LIZ repair tests before relying on broad `cargo test -p fraggler-core liz` as a hard gate.
