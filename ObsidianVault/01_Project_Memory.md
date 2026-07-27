- 2026-06-27: `code-cleanup` full-remodel branch complete and pushed. 12 commits, 8 monolithic `.py` files converted into packages (facade + `_constants.py` + `_legacy.py`). Test baseline `Ran 33 tests, OK` preserved across every commit. Verification recipe and Phase pattern documented in `CLEANUP_PLAYBOOK.md`.
- 2026-06-27: `fraggler/`, `app_meta.py`, `app.py` are live, not legacy. They are referenced by 14 core modules and tests. The legacy space was `gui/` (replaced by `gui_qt/`) and 59 one-shot scripts under `scripts/`.
- 2026-06-27: Started `code-cleanup` full-remodel campaign. Branch baseline = `codex-clonality-ladder-finalize-2026-05-14`. Test baseline = 33 unittest tests passing (recorded in `CLEANUP_PLAYBOOK.md`).
- 2026-06-27: `fraggler/`, `app_meta.py`, `app.py` are live, not legacy. They are referenced by 14 core modules and tests. The legacy space was `gui/` (replaced by `gui_qt/`) and 59 one-shot scripts under `scripts/`.
# HemaFrag Project Memory

## Current Focus

HemaFrag is now focused on FLT3 work. Clonality is considered parked for a while and should not drive new context unless explicitly requested.
- 2026-07-26: User explicitly resumed clonality ML work from GitHub branch `clonality-ml-phase-5-real-data-2026-07-11`; local `master` now tracks that branch as the working baseline.

## Source Of Truth

- Primary app: `qt_app.py`
- Primary GUI: `gui_qt/`
- Analysis code: `core/`
- FLT3 pipeline: `core/analyses/flt3/`
- Rust engine: `fraggler-v2/`
- Runtime fallback binary: `bin/fraggler-cli`

## Logging Policy

- Keep Obsidian/session logging intentionally compact to reduce context and token load.
- For normal work sessions, log only durable decisions, final output paths, and unresolved next steps.
- Avoid long command transcripts, full annotation JSON, exhaustive file lists, repeated progress updates, and detailed per-file run notes in `02_Session_Log.md`.
- Put bulky generated details in local artifacts (`local_triage/`, JSON/TSV/XLSX) and reference only the path from memory.

## FLT3 Contract

- Normal/default FLT3 size standard is user-facing `ROX500` with internal ladder `GS500ROX`.
- Normal FLT3 `ROX500`/`GS500ROX` must use size-standard channel `DATA4`.
- Explicit `LIZ500`/`LIZ500_250` override is separate and uses `DATA105`.
- Old FLT3 ROX500 runs that mixed `DATA4` and `DATA105` are useful for visual learning only, not final channel-validated statistics.
- FLT3 `Leukostrat` run folders are LIZ500 files and should be ignored/excluded from ROX500/GS500ROX validation.
- `SizeStandard`, `InternalLadder`, and `SizeStandardChannel` must be written explicitly in FLT3 QC outputs.

## FLT3 Architecture

- Rust owns FLT3 `GS500ROX` ladder family selection and sizing.
- Python orchestrates QC, control classification, output writing, and GUI workflow.
- Python ladder-rescue/template fallback for FLT3 `GS500ROX` is legacy opt-in only via `HEMAFRAG_FLT3_ENABLE_PYTHON_LADDER_RESCUE`.
- QC-only ROX500 runner should not generate DIT clinical reports or treat sample peak calls as final truth.
- Operator/manual review chooses FLT3 sample peaks; HemaFrag should provide correct sizing and ratio calculation from explicit peak choices.
- FLT3 peak-area quantitation intentionally uses raw DATA-channel traces with mild local sideband baseline integration; stricter baseline correction may be used for ladder/peak detection but must not be reused for quantitative area, including Rust-preview WT/MUT/ITD peaks.

## FLT3 Runner

- GUI FLT3 tab should use `scripts.run_flt3_rox500_qc_all_injections.run_qc`.
- Compatibility code may delegate to the shared QC implementation, but command/UI names should say ROX500.
- ROX500 QC runner should analyze all non-water FLT3 injection candidates, write CSV/XLSX/HTML/JSON, and include review rows.
- Keep run-name filter optional for `/Volumes/T7 Shield/DATA/flt3`.
- FLT3 ROX500 QC runner supports comma/semicolon-separated `--exclude-run-name-contains` values, e.g. `LIZ,Leukostrat`, while requiring `3730`.
- FLT3 ROX500 QC runner must exclude `MP1_*.fsa` files before QC. User-reviewed FAIL panel showed these are human/operator plate errors, not ladder fitting cases, and they should not consume future validation slots or count as REVIEW/FAIL.
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
- Start-family prior remaps may only be applied when the proposed full ladder is inside review-band linear QC (`max <= 6 bp`, `mean <= 3 bp`, `R2 >= 0.9985`) or the simple-shift apply band (`max <= 8.6 bp`, `mean <= 3.3 bp`, `R2 >= 0.9993`). `35_earlier` and strict-band `simple_shift` can auto-pass; `reverse_pair_*`, `start_block_35_50_75_100_139`, and `late_50_after_current_50` stay review-only.
- User-reviewed DATA4 validation showed `35_earlier` GS500ROX start-prior remaps are usually clean enough to auto-pass when inside strict review band; reverse-pair/start-block/simple-shift modes must remain review-only because many still contain real `wrong_35_50` cases.
- Reverse-pair GS500ROX start-prior modes must not auto-apply to the fitted ladder; they are proposal/review material only until per-anchor candidate selection is learned.
- Latest FLT3 annotation split shows most normal 35/50 starts are fixed; remaining `wrong_35_50` rows are hard cases. They usually need a constrained start-block candidate (`35,50,75,100,139`) rather than just swapping 35/50. Do not solve these by simply loosening the existing simple-shift band.
- For the hardest GS500ROX 35/50 rows, pure residual ranking and reverse-anchor ranking can still pick baseline/shoulder/blob candidates. Stable-region projection from `340/350` or tail anchors is useful for narrowing the search window, but the next learning unit should be per-anchor apex selection (`35/50/75/100/139` candidates), not one automatic residual-winning remap.
- A narrow GS500ROX `reverse_pair_*` prior is allowed only as hard-case proposal/review evidence. It must not auto-apply to the fitted ladder, even when residuals are attractive.
- GS500ROX `reverse_pair_*` candidates must reject baseline peaks and first-blob/top-of-blob placements: both proposed `35/50` anchors need real peak support, a plausible `35->50` gap, and no huge height-ratio mismatch where one anchor is the dye blob and the other is a small local feature.
- For low-end GS500ROX relabel families, global linear residual can be a bad visual-quality guardrail. User-confirmed good examples can have linear max around `9-11 bp` while quadratic/cubic residuals are excellent (`~2-4 bp` quadratic max and `~1-2 bp` cubic max). HemaFrag now exports a review-only `GS500ROXStartPriorCurvedReviewBand` signal for these proposals; this can show better review candidates but must not be treated as automatic PASS.
- Minor comments about `100`, `150`, `300`, `340`, and `350` are downstream anchor/apex-placement issues and should be handled separately from 35/50 start-family learning.
- For adaptive CWT/beam low-end GS500ROX proposals, `35 bp` must not be accepted independently: require a plausible start-block geometry across `35->50`, `50->75`, `75->100`, and `100->139`. Tiny compressed early clusters or very large `75->100` jumps are blob/shoulder failure signatures even when residuals look attractive.
- 2026-05-16 annotation of `flt3_gs500rox_start_proposal_annotations (1).json` showed: `35_earlier` proposals were mostly correct (`6` proposal-correct, `1` close); `simple_shift` was proposal-correct in all `5` examples but remains review-only until broader validation; `reverse_pair_tail_200_500` (`5/5`) and `start_block_35_50_75_100_139` (`12/12`) were current-correct false positives.
- Stable-current GS500ROX starts should suppress hard `reverse_pair_*`/`start_block` proposals when current early geometry is coherent: `35->50` about `68-76` scans, `50->75` `132-150`, `75->100` `128-145`, `100->139` `205-230`, with current linear max `<=3.8 bp`, mean `<=1.75 bp`, and R2 `>=0.99983`. Residual-better proposals are not enough to move 35 left when this pattern is present.
- 2026-05-16 annotation of `flt3_gs500rox_prior_overlay_annotations.json` showed current was best in most remaining overlay examples: `current_correct=34`, `proposal_correct=5`, `proposal_close=1`. By mode: `35_earlier` remnants were mostly current-correct (`9/10`, one close note that 35 should sit where current 50 is), `simple_shift` remained proposal-correct (`5/5`), and `start_block_35_50_75_100_139` was current-correct (`25/25`).
- Preferred-current GS500ROX starts should suppress additional bad `35_earlier`/hard-start proposal noise when current geometry is broadly coherent: `35->50` `67-76`, `50->75` `128-152`, `75->100` `128-152`, `100->139` `205-235`, current linear max `<=4.9 bp`, mean `<=1.9 bp`, and R2 `>=0.99978`. This is a proposal-suppression rule, not a blanket PASS rule.
- 2026-05-18 re-annotation of the 40-row prior overlay confirmed the same split: `current_correct=34`, `proposal_correct=5`, `proposal_close=1`. `simple_shift` is now repeatedly proposal-correct and may auto-pass only inside its strict apply band; keep the rest as review.
- `late_50_after_current_50` is the hard GS500ROX case where current `50 bp` is visually the true `35 bp`, and the correct `50 bp` is a later peak between current `50` and `75`. This should be generated as review-only proposal evidence, not auto-applied.
- 2026-05-18 full 145-row review annotation showed `simple_shift` was proposal-correct again (`3/3` remaining rows) and the large hard-start proposal family was not proposal-correct: most `start_block_35_50_75_100_139` rows were `current_correct`, with only a few `proposal_close` notes where `50 bp` was right and `35 bp` should be slightly later. Suppress hard `reverse_pair_*`/`start_block` proposals when current is already inside normal GS500ROX review band and the early gaps match this mild current-correct family (`35->50` roughly `69-85`, `50->75` `136-165`, `75->100` `133-155`, `100->139` `214-250`).
- 2026-05-18 review cleanup after MP1 exclusion reduced a 250-file 3730/DATA4 smoke from `PASS=246`, `REVIEW=4`, `FAIL=0` to `PASS=249`, `REVIEW=1`, `FAIL=0`. Good compact `GS500ROX first anchor too late` rows may auto-pass only under a narrow late-first-anchor guardrail: 16 increasing anchors, first anchor about `1600-1725`, last anchor `>=4200`, plausible early gaps, linear max `<=4.8 bp`, mean `<=1.8 bp`, and R2 `>=0.99975`.
- Do not auto-pass the residual NTC late-first-anchor pattern where `35 bp` is tiny/near the dye blob or baseline and `35->50` is too large. User confirmed `NTC_ITD_1-10__100125_H01_C990RHLW.fsa` is a real minor review: `35 bp` is along baseline and should move later/right/up to the true peak, even though its global linear fit is good (`max ~3.0 bp`, mean `~1.29 bp`, R2 `~0.999895`).
- Suppress bad `35_earlier` proposal noise when current is in the reviewed current-correct hard-start band and the proposal is worse than current. Example `_r___G01_C990RI16.fsa` should stay current-correct/pass rather than appear as proposal review.
- 2026-05-18 follow-up review annotation showed the remaining start-family proposals were all `proposal_close`, not `current_correct`: the model was stopping slightly too far left. Add/keep review-only right-shift evidence for this class:
  - For the hard current-50-as-35 class, extend `late_50_after_current_50` so true `50 bp` can be a later real peak (example moved proposal from `1658/1695` toward `1658/1734`).
  - For broad `35->50` start-block rows, generate `right_shifted_start_review` proposals that favor the expected supported peak farther right for `35 bp`, and when needed move both `35` and `50` right.
- User annotation of `flt3_right_shift_learning_probe_v1` confirmed the new proposal direction: all 5 rows were marked `proposal_correct`. For `25OUM04778_p1_ITD_ufort__250324_A01_H9C0VADZ.fsa`, `50 bp` was correct but `35 bp` needed slightly farther right than the v1 proposal, so `right_shifted_start_review` now picks `35` relative to the newly selected `50`, not only relative to current `35`.
- User annotation of `flt3_right_shift_learning_probe_v2` confirmed all 5 learned right-shift proposals were `proposal_correct`. `late_50_after_current_50` and `right_shifted_start_review` may now auto-apply only when the learned curved-fit thresholds and confirmed current-gap families match; otherwise they remain proposal/review evidence. This is deliberately narrow and must still leave `NTC_ITD_1-10__100125_H01_C990RHLW.fsa` in review because its `35 bp` is baseline/too-late rather than a supported start-family right-shift.
- 2026-05-18 2500-file follow-up:
  - User confirmed the H9C0VADZ ratio/missing-ladder rows plus `IVS-0000_ITD__0300725_C01_H9C0ZJ88.fsa` and `25OUM11534_p2_TKD-kutting__240725_B05_H9C0VC6E.fsa` are human/operator/data-quality failures and should be excluded from future ROX500 validation batches.
  - User confirmed `IVS-0000_D835_KUTT__300525_E05_H9C0ZJ3G.fsa` and `NTC_RATIO__110625_H02_H9U0BDEO.fsa` were current-correct/good; bad `start_block`/`35_earlier` proposals must not turn these into review.
  - `start_block_35_50_75_100_139` is now treated as proposal evidence only and must not itself create a REVIEW row. A 2500-file 3730/DATA4 smoke after this cleanup produced `PASS=2492`, `REVIEW=8`, `FAIL=0`.
  - The 8 remaining review rows are the intended hard/minor set: two `GS500ROX first anchor too late` rows (`NTC_ITD_1-10__100125_H01_C990RHLW.fsa`, `25OUM08172_p2_ITD_ufort__220525_E02_H9C0ZJ3R.fsa`), one hard `35_earlier` blob/current-50-as-35 case (`25OUM08837_p1_RATIO__300525_C04_H9C0ZJ3G.fsa`), and five `right_shifted_start_review` proposal rows needing visual confirmation.
- 2026-05-19 full-night 291-row FLT3 review annotation:
  - The dominant remaining class is true `wrong_35_50`; do not broadly auto-pass `right_shifted_start_review` or curved-band proposals from this batch.
  - Several visually `good` rows still entered review from proposal-only start-prior noise, especially around repeated 2025-08/09 and 2026-04 runs; future cleanup should suppress proposal noise only when current ladder geometry is already coherent.
  - Repeated `minor` rows say `35 bp` is still too far left/on baseline and should move later/right onto a real peak; this is distinct from the learned hard right-shift class and must stay review until peak-support scoring improves.
  - User also noted isolated non-start issues (`150/160`, `300`, `340/350` anchor placement); keep these separate from 35/50 start-family learning.
- 2026-05-20 annotation of `supported_35_near_fixed50_probe_v3` showed the proposed 35/50 pair was correct in the reviewed examples. This mode may now auto-apply only when both anchors have peak support, current gaps match the reviewed broad 35/50 family, proposed `35->50` is about `65-85` scans, and the remapped ladder is inside strict linear review band or the narrow learned curved band.
- 2026-05-20 follow-up on the last 3 review rows promoted two final narrow GS500ROX start fixes:
  - `late_first_35_right_shift` handles `GS500ROX first anchor too late` rows where only `35 bp` is a baseline/shoulder pick and should move right onto a supported peak.
  - `right_shifted_35_50_75_review` handles the narrow curved class where `35/50/75` all need slight right shifts, with strict peak-support and cubic-fit guards.
- 2026-05-26 full-review annotation cleanup:
  - User-reviewed `operator_data` rows and the bad `2025_08_11_FLT3_ef_H9C0ZIZ2_2025-08-11_0067` ROX tail-missing run are excluded before FLT3 ROX500 QC candidate limiting.
  - Non-applied `35_earlier` and all selected `reverse_pair_*` proposals no longer force review on otherwise review-band current ladders; keep them as proposal metadata only.
  - A small user-confirmed good override list is allowed for visually accepted FLT3 ROX500 current ladders that remain review/analysis-failed outliers after proposal suppression.
  - Exact user-confirmed minor overrides may convert `analysis_failed` FLT3 ROX500 rows to `REVIEW` instead of `FAIL`; these are still visual-review cases, not PASS.
- 2026-05-26 proposal-overlay follow-up: only user-marked `proposal_correct` rows should promote to auto-apply; `proposal_close` stays review. Simple-shift may now use a narrow learned curved-fit apply band, and the extended `supported_35_near_fixed50` curved apply band is restricted to the confirmed broad-gap family. Current-correct `35_earlier`/start-block rows should suppress proposal noise, while downstream `200-500`, `340/350`, `150/160`, and `300` anchor issues remain separate review problems.

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
  - 2026-05-20 final GS500ROX start cleanup: focused FLT3 tests pass with `45` tests; 2000-file 3730/DATA4 smoke produced `PASS=2000`, `REVIEW=0`, `FAIL=0`.

## Hygiene

- Keep generated outputs, `artifacts/`, `local_triage/`, caches, raw `.fsa`, build outputs, and scratch review bundles out of clean source commits.
- Keep HemaFrag as the canonical project name.
- Windows release builds use `packaging/build_windows.sh` and `packaging/Dockerfile.windows`; the Docker build cross-compiles `fraggler-cli.exe` with Rust/mingw before Wine/PyInstaller packaging, then bundles it in `HemaFrag_Windows/_internal/`. Windowed Windows builds have no console streams, so startup/runtime code must tolerate `sys.stdout`/`sys.stderr` being `None`. Frozen Windows runtime resolution must search for `fraggler-cli.exe` in `_MEIPASS`, beside `HemaFrag.exe`, and in `_internal`. Windows packaged runtime must not use the persistent Rust worker/prewarm path because `select()` on subprocess pipes can raise `WinError 10038`; use one-shot hidden Rust CLI calls instead.
- Normal clonality batch output should produce max two Excel workbooks: one local run workbook in `reports_<date>/Clonality_Tracking.xlsx` and one global dashboard workbook at `/Volumes/T7 Shield/HemaFrag_Clonality_All_Runs.xlsx`. Patient, control/QC, and PK peak tracking belong in `Clonality_Tracking.xlsx`; do not recreate separate `HemaFrag_QC_Trends.xlsx` for aggregated clonality batch runs.
- Normal FLT3 output should produce max two Excel workbooks: one local run workbook (`FLT3_Tracking.xlsx` for normal pipeline or `FLT3_ROX500_QC_All_Injections.xlsx` for ROX500 QC validation) and one global workbook at `/Volumes/T7 Shield/HemaFrag_FLT3_All_Runs.xlsx`. Do not recreate separate `FLT3_QC_TRENDS.xlsx`/`FLT3_NPM1_QC_TRACKER.xlsx` pairs for normal FLT3 tracking.
- Clonality/FLT3 batch input defaults to `Latest run date`: when a broad parent folder is selected, HemaFrag parses direct run-folder dates (`YYYY_MM_DD` preferred, `YYYY-MM-DD` fallback), scans only folders from the newest date, and builds QC jobs from that same selected run set.
- Historical clonality backfill should not let one bad `.fsa` block a whole night run. Source/runtime backfills use `analyses.clonality.pipeline.file_timeout_seconds` (default `240`) to isolate each file in a child process and skip it on timeout. Known repeated hang files are filtered in `core.batch.KNOWN_CLONALITY_BACKFILL_SKIP_FILES`.
- Strict Rust ladder mode is opt-in with `HEMAFRAG_STRICT_RUST_LADDER=1`, `HEMAFRAG_RUST_ONLY=1`, or `engine.strict_rust_ladder=true`; it disables Python ladder fallback/rescue and clonality multiprocessing so failures surface as skipped/reviewed files under per-file timeout instead of hidden Python rescues.
- Clonality interpretation assistance is experimental and default-off. Annotation/training v1 uses `scripts/render_clonality_interpretation_annotation_html.py` for ~500-file panels with patient + PK/RK/NK controls, `scripts/train_clonality_interpretation_quick_model.py` for offline `scikit-learn` research models, and schema `clonality_interpretation_v1`; DIT/final report text must not change from this feature yet.
- SL interpretation in clonality v1 is DNA-quality oriented rather than clonality oriented: use area percentages for 100/200/300/400/600 bp, with `SLFragmentedPercent` based on 100+200 bp and compact quality classes such as `bra_kvalitet`, `litt_fragmentert`, and `mer_enn_50_prosent_fragmentert`.
- Clonality v1 marks `uspesifikke_topper` only for peaks matching the known `NONSPECIFIC_PEAKS` list in `core/analyses/clonality/config.py`; unknown out-of-reference peaks are not automatically called nonspecific. Known nonspecific peaks are metadata/exclusion evidence, not an annotation/model class, and must be excluded from peak ratios/share and trace-learning windows.
- Clonality patient sample interpretation uses a centralized `_ASSAY_DISPATCH` map to select dedicated helper functions (`_interpret_<assay>`) based on normalized assay name keys:
  - **DHJH_D**: Zero-peak patient samples map to `polyklonal` (broad reference range and polyclonal background often lead to no detectable peaks after filtering).
  - **DHJH_E**: Zero-peak patient samples map to `usikker_review` (narrow range, ambiguous quality vs. lack of rearrangement).
  - **TCRbA / TCRbC**: Zero-peak patient samples map to `polyklonal` (expected polyclonal TCR background has no discrete peaks).
  - **IGK**: Relaxed `polyklonal` threshold allows multi-peak profiles with ≥5 peaks and height share ≤ 0.48 to map to `polyklonal` (retains polyclonal status under high-peak density).
- Clonality learning should prefer reference-window trace-shape features from raw `.fsa` data, evaluated per DATA channel plus patient/assay replicate concordance; trace models remain research-only and must not drive app output until evaluation is acceptable across rare classes. Settings include a separate learning export mode that writes app-run annotation seed JSON/CSV for later supervised learning.
- Clonality chemist labeling is patient-assay based: show same-DIT same-assay parallels together and apply one label to the parallel group. Current chemist labels are `monoklonal`, `monoklonal_pa_poly`, `polyklonal`, `oligoklonal`, `irregulaer`, `lite_pcr_produkt`, `intet_pcr_produkt`, `qc_teknisk_fail`, and `usikker_review`; old `bi_oligoklonal` and `intet_pcr_produkt_darlig_dna` normalize forward. IKZF1 and Ktr-albumin are excluded from current ML labeling/training batches.
