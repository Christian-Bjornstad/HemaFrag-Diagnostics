# HemaFrag Project Memory

## Current Focus

HemaFrag is now focused on FLT3 work. Clonality is considered parked for a while and should not drive new context unless explicitly requested.

## Source Of Truth

- Primary app: `qt_app.py`
- Primary GUI: `gui_qt/`
- Analysis code: `core/`
- FLT3 pipeline: `core/analyses/flt3/`
- Rust engine: `fraggler-v2/`
- Runtime fallback binary: `bin/fraggler-cli`

## FLT3 Contract

- Normal/default FLT3 size standard is user-facing `ROX500` with internal ladder `GS500ROX`.
- Normal FLT3 `ROX500`/`GS500ROX` must use size-standard channel `DATA4`.
- Explicit `LIZ500`/`LIZ500_250` override is separate and uses `DATA105`.
- Old FLT3 ROX500 runs that mixed `DATA4` and `DATA105` are useful for visual learning only, not final channel-validated statistics.
- `SizeStandard`, `InternalLadder`, and `SizeStandardChannel` must be written explicitly in FLT3 QC outputs.

## FLT3 Architecture

- Rust owns FLT3 `GS500ROX` ladder family selection and sizing.
- Python orchestrates QC, control classification, output writing, and GUI workflow.
- Python ladder-rescue/template fallback for FLT3 `GS500ROX` is legacy opt-in only via `HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE`.
- QC-only ROX500 runner should not generate DIT clinical reports or treat sample peak calls as final truth.
- Operator/manual review chooses FLT3 sample peaks; HemaFrag should provide correct sizing and ratio calculation from explicit peak choices.

## FLT3 Runner

- GUI FLT3 tab should use `scripts.run_flt3_rox500_qc_all_injections.run_qc`.
- Compatibility code may delegate to the shared QC implementation, but command/UI names should say ROX500.
- ROX500 QC runner should analyze all non-water FLT3 injection candidates, write CSV/XLSX/HTML/JSON, and include review rows.
- Keep run-name filter optional for `/Volumes/T7 Shield/DATA/flt3`.
- Typical worker count on this machine should stay around `4-6` unless measured otherwise.

## FLT3 Controls And QC

- `NTC` is a negative control, same practical class as `NK`.
- Water/MQ/MilliQ files should be filtered as water/blank controls.
- Missing or weak ladder is data/prep quality, not motor training.
- Panel rows `1-8` from the prior H9C0VADZ review are missing/weak ladder and should be `FAIL`/data quality, not GS500ROX training cases.
- `missing_ladder_fail` should remain separate from fitting regressions.

## Current FLT3 Learning

- Many visually reviewed FLT3 ROX500 rows were already good or acceptable.
- Remaining real fitting problem is mainly GS500ROX start-family placement.
- Important observed pattern: in several bad rows, current `35 bp`/`50 bp` mapping is shifted; often the desired `35 bp` is near where current `50 bp` sits, and `50 bp` should move to the next correct peak.
- Do not promote residual-only `35/50` repairs. Any start repair should be family-aware and protect visually good/perfect rows.
- Current GS500ROX start-family prior has two explicit modes:
  - `simple_shift`: current 50 becomes proposed 35; proposed 50 is a peak 60-90 scans later.
  - `35_earlier`: proposed 50 is locked first, then proposed 35 is searched 55-95 scans before it.
- Start-family prior remaps may only be applied for review when the proposed full ladder is inside review-band linear QC (`max <= 6 bp`, `mean <= 3 bp`, `R2 >= 0.9985`) or the simple-shift review-only apply band (`max <= 8.6 bp`, `mean <= 3.3 bp`, `R2 >= 0.9993`). Applied remaps must still stay `REVIEW`, not automatic `PASS`.
- Latest FLT3 annotation split shows most normal 35/50 starts are fixed; remaining `wrong_35_50` rows are hard cases. They usually need a constrained start-block candidate (`35,50,75,100,139`) rather than just swapping 35/50. Do not solve these by simply loosening the existing simple-shift band.
- For the hardest GS500ROX 35/50 rows, pure residual ranking and reverse-anchor ranking can still pick baseline/shoulder/blob candidates. Stable-region projection from `340/350` or tail anchors is useful for narrowing the search window, but the next learning unit should be per-anchor apex selection (`35/50/75/100/139` candidates), not one automatic residual-winning remap.
- A narrow GS500ROX `reverse_pair_*` prior is allowed for hard 35/50 cases: project from stable tail/`340/350`, take two real peaks in the projected `50 bp` window, and map them to `35/50`. It may apply only when the resulting ladder is inside normal review band; otherwise it should stay as a proposal.
- For low-end GS500ROX relabel families, global linear residual can be a bad visual-quality guardrail. User-confirmed good examples can have linear max around `9-11 bp` while quadratic/cubic residuals are excellent (`~2-4 bp` quadratic max and `~1-2 bp` cubic max). HemaFrag now exports a review-only `GS500ROXStartPriorCurvedReviewBand` signal for these proposals; this can show better review candidates but must not be treated as automatic PASS.
- Minor comments about `100`, `150`, `300`, `340`, and `350` are downstream anchor/apex-placement issues and should be handled separately from 35/50 start-family learning.
- For adaptive CWT/beam low-end GS500ROX proposals, `35 bp` must not be accepted independently: require a plausible start-block geometry across `35->50`, `50->75`, `75->100`, and `100->139`. Tiny compressed early clusters or very large `75->100` jumps are blob/shoulder failure signatures even when residuals look attractive.

## Current Verification Baseline

- 2026-05-14: FLT3 channel contract fixed in code.
- `flt3_size_standard_mode()` default returns `ROX500` / `GS500ROX` / `DATA4`.
- Explicit LIZ override returns `LIZ500_250` / `LIZ500_250` / `DATA105`.
- 2026-05-14: FLT3 GS500ROX residual-only review threshold relaxed for otherwise good linear fits:
  - GS500ROX auto-accept now allows max residual up to `6.0 bp`.
  - GS500ROX linear review remains `max <= 6.0 bp`, `mean <= 3.0 bp`, `r2 >= 0.9985`.
  - Known weak/missing ladder rows still fail; do not use this to rescue missing ladder.
- Test added: `tests/test_flt3_size_standard_contract.py`.
- Last relevant verification:
  - Python compile smoke: ok.
  - `python3 -m unittest tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py tests/test_water_filter.py tests/test_gs500rox_guardrail.py`: ok.
  - Qt offscreen FLT3 tab smoke: ok; command preview shows `preferred channel=DATA4`.
  - 2000-file FLT3 ROX500 rerun after residual threshold change: `PASS=1986`, `REVIEW=6`, `FAIL=8`; channel counts `DATA4=1952`, `DATA105=48`.

## Hygiene

- Keep generated outputs, `artifacts/`, `local_triage/`, caches, raw `.fsa`, build outputs, and scratch review bundles out of clean source commits.
- Keep HemaFrag as the canonical project name.
