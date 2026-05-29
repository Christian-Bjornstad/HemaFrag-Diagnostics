# HemaFrag Session Log

## 2026-05-14 - Context Reset Toward FLT3

- User confirmed clonality is parked for now.
- Long clonality-heavy project memory and session log were replaced with compact FLT3-focused notes to reduce future context/token load.
- Keep future logs short and only record durable FLT3/app decisions.

## 2026-05-14 - FLT3 ROX500 DATA4 Contract Fix

- Implemented the FLT3 channel contract:
  - Default FLT3 `ROX500` uses internal `GS500ROX`.
  - Default FLT3 `ROX500`/`GS500ROX` uses `SizeStandardChannel=DATA4`.
  - Explicit `LIZ500`/`LIZ500_250` override still uses `DATA105`.
- GUI FLT3 tab imports `scripts.run_flt3_rox500_qc_all_injections.run_qc` directly.
- ROX500 wrapper exposes both `main` and `run_qc`.
- QC summary now uses the configured channel contract for `preferred_size_standard_channel`.
- Added `tests/test_flt3_size_standard_contract.py`.

Verification:
- Python compile smoke: ok.
- `python3 -m unittest tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py tests/test_water_filter.py tests/test_gs500rox_guardrail.py`: ok.
- Qt offscreen FLT3 tab smoke: ok, command preview shows `preferred channel=DATA4`.
- Direct ROX500 runner import: ok.

## Next FLT3 Step

- Run a small DATA4 contract smoke on real FLT3 data before any large run.
- Confirm CSV/XLSX/HTML/JSON all show `SizeStandard=ROX500`, `InternalLadder=GS500ROX`, `SizeStandardChannel=DATA4`.
- Then regenerate a small review panel with channel visible and compare visually good rows against true `35/50` start-family failures.

## 2026-05-14 - FLT3 ROX500 2000-File QC Run

- Ran `scripts/run_flt3_rox500_qc_all_injections.py` on `/Volumes/T7 Shield/DATA/flt3` for years `2025` and `2026`, limit `2000`, workers `6`.
- Output directory: `local_triage/flt3_rox500_data4_2000_2025_2026_2026-05-14_201421`.
- Summary: `PASS=1957`, `REVIEW=35`, `FAIL=8`; `review_row_count=43`; `raw_fsa_count=2000`; `analyzed_fsa_count=2000`; `skipped_count=0`.
- Channel summary: `DATA4=1952`, `DATA105=48`. The `DATA105` rows all came from two run folders named `2025_02_27_FLT3_LIZ_ra_C9U07BS8_2025-02-27_0513` and `2025_02_27_FLT3_LIZ_ra_C9U07BS8_2025-02-27_0514`; all 48 passed.
- The 8 failures were `analysis_failed` rows from the known `H9C0VADZ` weak/missing-ladder ratio panel.
- Detached `nohup` launch died silently several times with empty logs, so the successful run was kept attached until completion.

## 2026-05-14 - FLT3 Review Annotation HTML

- Added `scripts/render_flt3_review_html.py`, modeled after the clonality browser annotation panel.
- Rendered the 43 DATA4 `REVIEW`/`FAIL` rows from the 2000-file ROX500 run into `local_triage/flt3_rox500_data4_2000_2025_2026_annotate_html/review_panel.html`.
- The panel includes `Good`, `Minor`, `Wrong 35/50`, `Weak/missing ladder`, `Operator/data`, and `Unclear` labels plus note export to JSON.
- Verification: 43 rows, 43 rendered PNGs, Python compile smoke ok.
- Fixed the FLT3 annotation HTML export script after first use exposed a JSON escaping bug in the embedded case payload. Export now reads labels/notes directly from the visible DOM and tolerates localStorage errors.

## 2026-05-14 - FLT3 GS500ROX Residual-Only Review Cleanup

- Implemented a narrow GS500ROX threshold cleanup for otherwise good ladder fits:
  - `core/analysis.py`: FLT3 GS500ROX auto-accept allows mean residual `<= 3.0 bp`, max residual `<= 6.0 bp`, linear max `<= 6.0 bp`.
  - `core/analyses/flt3/pipeline.py`: GS500ROX residual review limit is now `6.0 bp`; generic FLT3 residual limit remains `4.0 bp`.
- 43-row review rerun changed from `PASS=0`, `REVIEW=35`, `FAIL=8` to `PASS=29`, `REVIEW=6`, `FAIL=8`.
- 2000-file rerun output: `local_triage/flt3_rox500_residual6_2000_2025_2026_2026-05-14`.
- 2000-file summary after cleanup: `PASS=1986`, `REVIEW=6`, `FAIL=8`, `review_row_count=14`, `DATA4=1952`, `DATA105=48`.
- Remaining 8 fails are the known `H9C0VADZ` weak/missing-ladder ratio rows.
- Remaining 6 reviews include `blob_dominated_start` cases and a few Rust-review residual/start cases; leave them for manual review rather than broadening thresholds further.
- Verification: Python compile smoke ok; `python3 -m unittest tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py tests/test_water_filter.py tests/test_gs500rox_guardrail.py` ok.

## 2026-05-14 - FLT3 Overnight 3730-Only Full T7 Run

- Started a detached `screen` run for all FLT3 files on `/Volumes/T7 Shield/DATA/flt3` from years `2024`, `2025`, and `2026`, requiring run metadata/name to contain `3730`.
- Candidate count before launch: `7894` 3730 files total (`2024=311`, `2025=5611`, `2026=1972`).
- Excluded count check: `1784` 3130 files, all from `2024`.
- Output directory: `local_triage/flt3_rox500_residual6_all_3730_2024_2026_2026-05-14_214626`.
- Screen session: `flt3_3730_20260514_214626`.
- Initial verification: session was detached and active, log showed `7894/7894` queued and early completed rows were `PASS`.
- Check later with `tail -f local_triage/flt3_rox500_residual6_all_3730_2024_2026_2026-05-14_214626/run.log` and inspect `FLT3_ROX500_QC_summary.json` when complete.
- Completed at `2026-05-14T22:35:04`: `PASS=7555`, `REVIEW=57`, `FAIL=282`, `review_row_count=339`, `skipped_count=0`.
- Channel counts: `DATA4=7686`, `DATA105=208`; preferred ROX500 channel remained `DATA4`.
- Year/status split: `2024 PASS=184 REVIEW=0 FAIL=127`; `2025 PASS=5522 REVIEW=38 FAIL=51`; `2026 PASS=1849 REVIEW=19 FAIL=104`.
- Review/fail reasons: `analysis_failed=282`, `Rust ladder fit looks internally consistent=33`, `poor_gs500rox_linear_fit=12`, `blob_dominated_start=12`.

## 2026-05-15 - FLT3 3730 Review/Fail Annotation Panels

- Split the completed 3730-only full run review rows into separate annotation inputs:
  - `FLT3_ROX500_QC_REVIEW_Only.csv`: `57` rows (`DATA4=56`, `DATA105=1`).
  - `FLT3_ROX500_QC_FAIL_Only.csv`: `282` rows (`DATA4=282`).
- Rendered review panel: `local_triage/flt3_rox500_residual6_all_3730_review_html/review_panel.html` (`57` cards/images).
- Rendered fail panel: `local_triage/flt3_rox500_residual6_all_3730_fail_html/review_panel.html` (`282` cards/images).
- Removed an obsolete hardcoded `DATA105` exclusion from `scripts/render_flt3_review_html.py` so annotation panels match their input CSV rows.

## 2026-05-15 - FLT3 Fail Annotation Triage And Guardrail Hydration

- Read annotation exports from Downloads:
  - `flt3_rox500_review_annotations (1).json`: fail panel (`282` rows).
  - `flt3_rox500_review_annotations.json`: review panel (`57` rows; defer 35/50 work).
- Fail annotations: `266` blank/accepted-fail rows, `7` `wrong_35_50`, `5` `minor`, `3` `good`, `1` `weak_missing_ladder`.
- Root cause for annotated non-fail rows: Rust found candidate GS500ROX fits, but Python hard-rejected them before QC because guardrails returned `GS500ROX first anchor too late` or `GS500ROX anchor span too small`; CSV collapsed this to `analysis_failed`.
- Implemented a narrow GS500ROX guardrail hydration change:
  - Complete 16-step monotonic fits can hydrate for manual review when linear QC is within FLT3 review bounds (`max<=6`, `mean<=3`, `r2>=0.9985`), tail coverage remains present, and first anchor is `<=2000`.
  - Accepted guarded fits are marked `review_required`, not auto-pass.
  - Weak signal and compressed/bad-linear-span cases remain hard fail.
- Verification on all `282` original fail rows after patch: `273 FAIL`, `8 REVIEW`, `1 PASS`.
- Annotated non-fail outcome: `3/3 good -> REVIEW`; `5/7 wrong_35_50 -> REVIEW`, `1/7 -> PASS` due existing manual adjustment, `1/7 -> FAIL` due poor linear fit; `5/5 minor -> FAIL`; `weak_missing_ladder -> FAIL`.
- Tests: `python3 -m unittest tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py` ok; py_compile ok for `core/rust_bridge.py`, `core/analysis.py`, `scripts/render_flt3_review_html.py`.

## 2026-05-15 - FLT3 Review 35/50 Start-Family Detector

- Read review annotation export `Downloads/flt3_rox500_review_annotations.json`: `57` review rows; labels were `wrong_35_50=45`, `weak_missing_ladder=6`, `minor=4`, `good=2`.
- Added Rust ladder peak preview hydration to Python `FsaFile` objects so FLT3 pipeline can compare selected GS500ROX anchors against nearby Rust candidate peaks.
- Added a narrow `suspect_gs500rox_35_50_start_family` detector:
  - selected 35/50 gap is small (`<=85` scans),
  - selected 50/75 gap is large (`>=180` scans),
  - selected start is in the normal GS500ROX window and the tail remains present,
  - Rust candidate peaks exist immediately before or between selected 35/50 anchors.
- Rerun on the annotated review bundle: detector flags `39/45` `wrong_35_50`, `0/2` good, `0/4` minor, and `1/6` weak/missing ladder. All `57` remain `REVIEW`.
- This is a classification/QC reason improvement, not yet an automatic anchor remap. It makes the 35/50 failure mode explicit for the next repair pass.
- Tests: `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py` ok; py_compile ok for `core/analyses/flt3/pipeline.py`, `core/rust_bridge.py`, `core/analysis.py`.
- User annotated the 35/50 detector panel:
  - `move_both_right=42`, `move_35_right=3`, `weak_ladder=6`, `correct_35_50_flag=4`, blank/other `2`.
  - Existing `suspect_gs500rox_35_50_start_family` catches `39/42` `move_both_right`, with `1` weak-ladder false positive.
  - Added separate `suspect_gs500rox_35_start_family` detector for the three `move_35_right` rows; rerun catches `3/3` `move_35_right`, `0/4` correct flags, `0/6` weak ladder, plus one blank/unclassified review row.
  - Combined detector now catches `42/45` explicitly annotated move-right rows while keeping weak-ladder false positives at `1/6`.
- Shadow-tested naive local remaps:
  - `move_both_right`: replacing only 35/50 from nearby candidates usually leaves linear residuals very high; it does not produce review-safe fits.
  - `move_35_right`: replacing only 35 helps some rows numerically but still leaves high residuals in others.
  - Conclusion: the next real repair must rebuild the early GS500ROX start family against later anchors, not just swap the first one or two selected peaks.

## 2026-05-15 - FLT3 GS500ROX 35/50 Repair Attempt

- Added a conservative Rust `GS500ROX` start-family rebuild branch inside `repair_gs500rox_start_anchor_sequence`.
  - It only activates on the annotated start-family patterns: compressed 35/50 with expanded 50/75, or 35-only shift with an alternative between 35 and 50.
  - Candidate starts are projected from the stable tail and must materially improve residuals without hard regression.
- Built `fraggler-cli --release` and reran the 57 annotated review rows.
- Result: all 57 stayed `REVIEW`; no real row changed selected fit under the conservative acceptance criteria.
- Summary CSV: `local_triage/flt3_rox500_residual6_all_3730_2024_2026_2026-05-14_214626/FLT3_REVIEW_Rust_35_50_Start_Repair_Summary.csv`.
- Durable conclusion: current detector/QC marking is useful, but automatic anchor remapping needs a stronger candidate-selection strategy or manual-confirmed remap training examples. Do not loosen Rust acceptance blindly; many suspected rows are residual-technically acceptable but visually wrong.

## 2026-05-15 - FLT3 GS500ROX Start Proposal Annotation Panel

- Added `scripts/render_flt3_gs500rox_start_proposal_html.py`.
- Rendered a focused before/after annotation panel for the 45 user-labeled GS500ROX start-family rows:
  - included labels: `move_both_right`, `move_35_right`;
  - excluded weak/correct rows from this learning pass.
- Output: `local_triage/flt3_gs500rox_start_proposal_html/review_panel.html`.
- Supporting outputs:
  - `proposal_rows.csv`: chosen proposal per case;
  - `proposal_trials.csv`: top candidate strategies per case;
  - `images/`: 45 current-vs-proposal PNGs.
- Visual convention: red `x` is current Rust selection; blue open circle is proposed start-family remap.
- Browser file-open verification was blocked by Codex browser URL policy, but static checks confirmed 45 cards, 45 images, and export script marker are present.
- User reviewed the score-ranked proposal panel and reported it made the starts more wrong; the next test should follow the visual hypothesis that the selected 50 bp peak is often the true 35 bp anchor.
- Rendered a second visual-only panel using `--proposal-mode visual-label-shift`:
  - output: `local_triage/flt3_gs500rox_visual_label_shift_html/review_panel.html`;
  - blue labels are shifted one selected peak to the right (`current 50 -> proposed 35`, `current 75 -> proposed 50`, etc.);
  - this is for learning/annotation only, not a valid auto-fit proposal yet.
- User reviewed 6 examples and reported the visual-label-shift panel mainly misses true 50 bp; the true 50 is often an intermediate peak not the current 75.
- Added `--proposal-mode insert-mid-50`:
  - proposal is `35 = current 50`, `50 = strongest local peak around current50 + ~72 scans`, then keep current 75+;
  - output: `local_triage/flt3_gs500rox_insert_mid_50_html/review_panel.html`;
  - first 6 examples now place blue 50 on intermediate peaks, matching the next visual hypothesis better, but some linear residuals rise, so this remains annotation/learning only.
- User annotated 26 `insert-mid-50` examples and reported the direction is better, but some cases still just move labels rather than choosing the exact true 50.
- No new export file was found in Downloads; comments were not readable from disk.
- Added `scripts/render_flt3_gs500rox_50_candidate_html.py` and rendered `local_triage/flt3_gs500rox_50_candidate_html/review_panel.html`.
  - This panel shows multiple true local 50 candidates (`50 A`..`50 F`) between shifted 35 and current 75 rather than selecting one automatically.
  - Export file name: `flt3_gs500rox_50_candidate_annotations.json`.

## 2026-05-15 - FLT3 GS500ROX 50 Candidate Gap Prior

- User reported the 50-candidate panel had been annotated, but no `flt3_gs500rox_50_candidate_annotations*.json` export was present in Downloads and no matching Codex localStorage annotation key was found.
- Important limitation: the static `review_panel.html` does not write annotation state back to itself; without browser localStorage or an exported JSON, the comments/labels cannot be recovered from the HTML file alone.
- Direct CSV/image review showed the main remaining miss: candidate rank `A` could still be a large early blob only `25-55` scans after shifted 35, while the visually plausible true 50 is usually a weaker peak around `60-90` scans after shifted 35.
- Updated `scripts/render_flt3_gs500rox_50_candidate_html.py`:
  - candidate ordering now prioritizes peaks with `gap_from_35` in `60-90` scans before out-of-band large blobs;
  - candidate metadata now shows `gap=` in the HTML;
  - export now also writes the full JSON into a visible textarea, so failed downloads can still be copied out.
- Rendered new panel: `local_triage/flt3_gs500rox_50_gapprior_candidate_html/review_panel.html`.
- Gap-prior ranking changed `A` for 7/45 rows: ordinals `14`, `19`, `33`, `34`, `50`, `51`, `54`; these were the clearest big-blob false starts. Only ordinal `56` still has no 60-90 scan candidate and remains out-of-band/likely weak or different failure mode.

## 2026-05-15 - FLT3 GS500ROX 35-Earlier Submode From 50 Candidate Annotations

- User pasted the `flt3_gs500rox_50_gapprior_candidate` annotation export directly in chat.
- Imported the labels/notes into `local_triage/flt3_gs500rox_50_gapprior_candidate_html/annotations_imported.csv`.
- Annotation split:
  - `50_A`: 29/45 rows, mostly the simple mode (`35 = old 50`, `50 = gap-window A`).
  - `50_C`: 4 rows and `50_D`: 3 rows, all with notes that 35 bp should be earlier.
  - `none`: 9 rows, all saying `50 bp skal der 35 bp er og 35 bp skal tidligere`.
- Durable interpretation: the review bundle contains at least two repair modes:
  - simple both-right mode: shifted 35 plus gap-window 50 works for the majority;
  - 35-earlier mode: the annotated true 50 is fixed, but true 35 must be searched before it.
- Added `scripts/render_flt3_gs500rox_35_earlier_candidate_html.py`.
- Rendered focused 18-row panel: `local_triage/flt3_gs500rox_35_earlier_candidate_html/review_panel.html`.
  - The panel locks the annotated 50 from the prior pass and proposes `35 A`..`35 F` before it.
  - First-ranked 35 candidates are typically 66-85 scans before annotated 50; row 50 is borderline at 94 scans.
  - Export filename: `flt3_gs500rox_35_earlier_candidate_annotations.json`; export also appears in an on-page textarea as backup.

## 2026-05-15 - FLT3 GS500ROX Annotated Remap Evaluation

- User pasted the 18-row `35 earlier` annotation export.
- Imported it as `local_triage/flt3_gs500rox_35_earlier_candidate_html/annotations_imported.csv`.
- Annotation result: `35_A=17/18`, `35_B=1/18` (ordinal 50). This confirms the 35-earlier candidate ranking is mostly correct once the annotated 50 is locked.
- Added `scripts/evaluate_flt3_gs500rox_annotated_start_remaps.py` and evaluated the combined annotated 35/50 remap over all 45 start-family review rows.
  - Overall review-band fit after annotated 35/50 remap: `20/45`.
  - `annotated_35_earlier`: `15/18` in review band; median linear max `5.30 bp`, median mean `2.05 bp`.
  - `simple_shift_35_current50`: `5/27` in review band; median linear max `6.69 bp`, median mean `2.50 bp`.
- Added `scripts/evaluate_flt3_gs500rox_annotated_block_remaps.py` to try a constrained 75/100/139 block refit using visible candidates from the 50-candidate panel.
  - Block refit did not improve total review-band count (`20/45`), only selected an alternate block in `2` rows.
  - Conclusion: remaining simple-shift rows likely need a stronger Rust/Python candidate-generation prior, not merely choosing alternate visible peaks from the current HTML panel.
- Fixed FLT3 pipeline reason-code handling so `suspect_gs500rox_35_start_family` is preserved as its own reason code instead of always appending `suspect_gs500rox_35_50_start_family`.
- Verification: `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py` passed.

## 2026-05-15 - FLT3 GS500ROX Start-Family Prior In Pipeline

- Implemented a conservative explicit `GS500ROX` start-family prior in `core/analyses/flt3/pipeline.py`.
- The prior evaluates two modes:
  - `simple_shift`: current 50 becomes proposed 35, and proposed 50 is a peak 60-90 scans later.
  - `35_earlier`: proposed 50 is either current 50 in a wide 35/50 pattern or a strong early blob after current 50; proposed 35 is searched 55-95 scans before that 50.
- Review-band acceptance uses the same linear QC bounds used during annotation: max `<=6 bp`, mean `<=3 bp`, R2 `>=0.9985`.
- Review-band prior remaps are applied through `apply_manual_ladder_mapping`, assigned `ladder_fit_strategy=gs500rox_start_family_prior`, and still forced to manual review via `gs500rox_start_family_prior_review`.
- Non-review-band prior proposals are not applied, but they now keep the row in review with `gs500rox_start_family_prior_suggestion` and exported proposal metadata.
- Added QC output columns to the FLT3 all-injections runner:
  - `GS500ROXStartPriorMode`
  - `GS500ROXStartPriorReviewBand`
  - `GS500ROXStartPriorSelected`
  - `GS500ROXStartPriorSummary`
- Added unit tests for simple-shift and 35-earlier prior trial selection.
- Smoke-tested the 45 annotated start-family rows through the actual QC worker:
  - prior modes: `simple_shift=28`, `35_earlier=14`, blank `3`;

## 2026-05-26 - FLT3 Full-Review Annotation Cleanup

- Latest FLT3 review annotations were read from `Downloads/flt3_rox500_review_annotations (2).json`; `operator_data=115`, `minor=44`, `good=32`, `wrong_35_50=21`.
- Generated 080825 raw DATA4 plot at `local_triage/flt3_080825_followup_2026-05-26/080825_H9C0ZIZ2_A01_DATA4_1500_4500.png`; H9C0ZIZ2 trace ends at scan `3533` and has no peaks after `3500`, while C990WO69 same date has tail peaks.
- Added source-tracked FLT3 ROX500 exclusions in `core/analyses/flt3/rox500_exclusions.py` and tightened proposal-only review noise; focused annotation rerun after exclusions/noise cleanup: `PASS=30`, `REVIEW=37`, `FAIL=3` across 70 non-excluded annotated rows.
- Second 40-row annotation pass added two more operator exclusions and six user-confirmed good overrides; focused control now gives `SKIPPED=2`, `PASS=6`, `REVIEW=31`, `FAIL=1`.
  - review-band prior applied: `17/45`;
  - false applied versus annotation-derived review-band truth: `0`;
  - annotated review-band remaps applied: `17/20`;
  - output: `local_triage/flt3_gs500rox_start_prior_pipeline_smoke/qc_rows.csv`.
- Remaining misses: ordinals `26`, `38`, `50`; these should stay review/suggestion work, not be forced by loosening thresholds.
- Verification: py_compile ok; `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py` passed.

## 2026-05-15 - FLT3 Review Rerun After Start Prior

- Reran the original 57 FLT3 review rows through the QC worker with the GS500ROX start-family prior enabled.
- Output directory: `local_triage/flt3_rox500_review_rerun_start_prior_2026-05-15`.
- Result: `57/57 REVIEW`, `0 PASS`, `0 FAIL`.
- Prior mode counts: `simple_shift=38`, `35_earlier=10`, no prior `9`.
- Prior review-band counts: `True=13`, `False=35`, blank `9`.
- Interpretation: 13 rows now receive an applied review-band start-family remap, but remain `REVIEW` by design because applied prior remaps are not allowed to auto-pass yet.
- Rendered HTML panels:
  - all 57: `local_triage/flt3_rox500_review_rerun_start_prior_2026-05-15/html_all/review_panel.html`
  - applied review-band prior rows (13): `local_triage/flt3_rox500_review_rerun_start_prior_2026-05-15/html_prior_review_band/review_panel.html`
  - suggestions not applied (35): `local_triage/flt3_rox500_review_rerun_start_prior_2026-05-15/html_prior_suggested_not_applied/review_panel.html`
## 2026-05-15 - FLT3 Start-Prior HTML Render Fix

- User reported the rerun HTML still appeared not to fix the 35/50 bp start-family error.
- Root cause was the review HTML renderer, not the QC CSV: `scripts/render_flt3_review_html.py` reanalyzed raw files and plotted Rust `ladder_fit_preview`, ignoring `GS500ROXStartPriorSelected`.
- Fixed renderer to use `GS500ROXStartPriorSelected` only when `GS500ROXStartPriorReviewBand=True`; these points are labeled `Start-prior applied`. Non-applied suggestions still show the Rust-selected ladder.
- Rerendered corrected panels:
  - all 57 review rows: `local_triage/flt3_rox500_review_rerun_start_prior_2026-05-15/html_all/review_panel.html`
  - 13 applied review-band prior rows: `local_triage/flt3_rox500_review_rerun_start_prior_2026-05-15/html_prior_review_band/review_panel.html`
- Status counts are unchanged: `0 PASS`, `57 REVIEW`; applied start-prior rows intentionally remain review-required for visual confirmation.
## 2026-05-15 - FLT3 Start-Prior First Tightening After Visual Review

- User reported the corrected start-prior review HTML still did not look as good as expected, and export/download did not work.
- Could not recover new annotations from Codex browser localStorage: the current `html_all` path was absent from the readable LevelDB storage, so no durable labels were saved there.
- Tightened `simple_shift` so it only runs on compact 35/50 plus expanded 50/75 patterns (`gap35_50 <= 85`, `gap50_75 >= 175`). This prevents broad-start cases from choosing visually wrong right-shift fits just because residuals are slightly better.

## 2026-05-27 - FLT3 Area Validation Panel

- Reviewed upstream Fraggler area logic: peak widths at `rel_height=0.95`, raw padded peak windows, and lmfit model `amplitude` as area/ratio input.
- Built local validation panel from manually fixed HemaFrag reports: `outputs/flt3_area_validation_panel_2026-05-27/flt3_area_validation_panel.html`; support CSVs include per-case ratios and per-peak method areas.
- Current panel compares HemaFrag current area, straight-baseline trapezoid, raw padded sum, and Fraggler-like Gaussian/Voigt/Lorentzian amplitudes on report trace data; next step is manual review against GeneMapper-style area behavior.
- Added a guard that prevents 35/50 start-prior auto-application when proposed 50 bp is later than scan `1800`; this removed the clear bad applied row where 50 was being moved into the old 75-family.
- Updated `scripts/render_flt3_review_html.py` so Export also writes JSON into a visible backup textarea, making annotations recoverable even if browser download is blocked.
- Rerun result on the 57 review rows: still `57 REVIEW`, `0 PASS`, `0 FAIL`; start-prior modes now `simple_shift=35`, `35_earlier=12`, no prior `10`; applied review-band remaps now `12` instead of `13`.
- New panels:
  - all 57: `local_triage/flt3_rox500_review_rerun_start_prior_gate_simple_max50_2026-05-15/html_all/review_panel.html`
  - applied only: `local_triage/flt3_rox500_review_rerun_start_prior_gate_simple_max50_2026-05-15/html_prior_review_band/review_panel.html`
## 2026-05-15 - FLT3 35/50 Simple-Shift Review-Only Apply Band

- User annotated the tightened 57-row FLT3 start-prior panel. Labels: `good=10`, `wrong_35_50=34`, `minor=7`, `operator_data=6`.
- Evaluation of the prior before widening showed only `12` rows displayed remapped start-prior anchors; `31/34` wrong_35_50 rows were still only suggestions, so the panel mostly still showed the old wrong Rust fit.
- Added a review-only wider apply band for `GS500ROX simple_shift` remaps: linear max `<=8.6 bp`, mean `<=3.3 bp`, R2 `>=0.9993`.
- This wider band does not permit auto-pass; rows remain `REVIEW` and are drawn with the proposed 35/50 remap for visual confirmation.
- Kept `35_earlier` on the stricter review band because the current annotations contain more mixed minor/wrong behavior there.
- Rerun on the 57 rows: `57 REVIEW`, `0 PASS`, `0 FAIL`; applied start-prior rows `39`; by user labels, applied rows include `28/34 wrong_35_50`, `8/10 good`, `3/7 minor`, `0/6 operator_data`.
- Remaining wrong_35_50 rows not applied: ordinals `6`, `13`, `20`, `52`, `54`, `57`; these need a separate hard-case strategy rather than broader simple_shift thresholds.
- New panels:
  - all 57: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_all/review_panel.html`
  - applied 39: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_applied/review_panel.html`

## 2026-05-15 - FLT3 Start-Prior Next Learning Split

- User re-annotated the wider simple-shift panel and clarified the learning policy:
  - `good` rows should be treated as visually acceptable/pass disposition for this review set.
  - `operator_data` rows are human/operator ladder issues and should be excluded from model learning.
- Latest annotation split after the simple86 run: `good=30`, `minor=13`, `wrong_35_50=8`, `operator_data=6`.
- Durable learning conclusion:
  - The normal `simple_shift` and `35_earlier` priors now fix most reviewed 35/50 start-family cases.
  - The remaining `wrong_35_50` rows are hard cases, not evidence to broadly loosen the current apply band.
  - Two rows were applied but still visually wrong, so linear residual alone is not sufficient; next learning must add peak-shape/plausibility guards and candidate-pair annotation.
- Next learning split:
  - Hard 35/50 candidate-pair panel for the 8 remaining `wrong_35_50` rows.
  - Separate small-offset group for `minor` comments about 35 bp slightly earlier/later.
  - Separate downstream-anchor group for minor 100/150/300/340/350 bp comments.

## 2026-05-15 - FLT3 Comment-Driven Solution Search

- Parsed the final annotated simple86 review bundle and excluded `good`/`operator_data` from model learning.
- Built `wrong_35_50_panel_for_shadow.csv` and ran `scripts/gs500rox_start_strategy_shadow_eval.py` over the 8 remaining wrong 35/50 rows.
- Output: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/wrong_35_50_shadow_eval/`.
- Result: all 8 rows had a non-current shadow candidate with better linear metrics.
  - 7/8 best candidates use a constrained `start_block_35_50_75_100_139` remap.
  - 1/8 best candidate uses `pair_enum_keep_75_plus`; this is the DATA105 row and should not be mixed into normal GS500ROX/DATA4 learning.
- Interpretation:
  - The remaining hard cases need a third review-only proposal mode: a constrained start-block refit over the first five GS500ROX anchors.
  - This should first be exposed as a candidate/review proposal, not automatically pass/applied, because some top residual candidates may still choose visually debatable shoulders.
  - Minor note groups should become separate learning tasks: small 35 bp nudges and downstream apex recentering for 100/150/300/340/350.

## 2026-05-15 - FLT3 Start-Block Proposal Mode

- Implemented `start_block_35_50_75_100_139` as a GS500ROX start-family prior trial in `core/analyses/flt3/pipeline.py`.
  - It searches a constrained first-five-anchor block (`35,50,75,100,139`) and then keeps the existing `150+` anchors.
  - It supplements Rust peak preview with local early peak candidates from the size-standard trace, matching the shadow-eval candidate pool more closely.
  - It is proposal-only: `apply_band` is forced `False` for this mode, even when linear metrics are good.
- Updated `scripts/render_flt3_review_html.py` so proposal-only start-block rows can be drawn as `Start-prior proposal`.
- Added unit coverage for the start-block proposal mode.
- Verification:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/render_flt3_review_html.py`
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`
- Generated hardcase review panels:
  - pipeline-best proposal rows: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_start_block_proposals/review_panel.html`
  - explicit best start-block proposals: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_best_start_block_proposals/review_panel.html`

## 2026-05-15 - FLT3 Start-Block Baseline Guard

- User reviewed the start-block hardcase panel and correctly identified that many proposal labels were sitting on baseline/shoulders rather than true peaks.
- Added a peak-support gate to `start_block_35_50_75_100_139`:
  - use local baseline-corrected trace height at the proposed anchor scan;
  - require at least 4/5 early anchors to have real support (`>=50 RFU`);
  - require `75/100/139` anchors to be above baseline-level support (`>=35 RFU`).
- Updated simple candidate ranking to score/filter on baseline-corrected height where available, not only Rust preview height.
- Verification remained green:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/render_flt3_review_html.py`
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`
- New guarded hardcase panel: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_peak_supported_v2/review_panel.html`.

## 2026-05-15 - FLT3 Reverse-Anchor Shadow Strategies

- User suggested reversing from more stable known regions (`139/150/160`, `340/350`, `490/500`) to infer early anchors (`100/75/50/35`) instead of fitting from noisy start peaks.
- Extended `scripts/gs500rox_start_strategy_shadow_eval.py` with reverse-projection strategies:
  - `reverse_from_139_150_160_to_35_100`
  - `reverse_from_340_350_to_35_100`
  - `reverse_from_490_500_to_35_100`
  - corresponding `to_35_139` variants.
- Shadow result on the 8 hard 35/50 rows:
  - `reverse_from_340_350_to_35_139` won 3/8 rows.
  - `start_block_35_50_75_100_139` still won 5/8 rows in pure score, but `340/350` reverse candidates were competitive/high-ranked in several more.
  - `139/150/160` and `490/500` did not win in this set.
- Generated reverse-anchor panel: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_reverse_anchor_proposals/review_panel.html`.
- Visual impression: reverse-from-`340/350` is materially more aligned with the user's stated strategy, but still needs visual acceptance because some early projected labels can land on shoulders rather than apexes.

## 2026-05-15 - FLT3 Hardcase Reverse Projection Candidate Panel

- User annotated the reverse-anchor hardcase proposal panel: all `8/8` remaining rows were still `wrong_35_50`.
- Tail-fit and reverse-anchor shadow metrics still produce attractive residuals, but contact-sheet review shows the same failure mode: some proposed early anchors land on baseline-near bumps, shoulders, or huge start blobs rather than the intended local apex.
- Added `scripts/render_flt3_gs500rox_reverse_projection_candidate_html.py`.
  - It renders the 8 hardcases with three projection sources per row: `tail_300_500`, `tail_200_500`, and `anchor_340_350`.
  - For each source it displays ranked local candidates for `35/50/75/100/139` instead of choosing one residual winner.
- New panel: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_reverse_projection_candidates/review_panel.html`.
- Durable conclusion: use stable-region projection as a search-window prior, then learn/select per-anchor apex candidates. Do not promote the current reverse-anchor residual winner as an automatic fix.

## 2026-05-15 - FLT3 Reverse-Projection Pair Prior

- User annotated the reverse-projection candidate panel for the 8 remaining hard `wrong_35_50` rows.
- Evaluation of the exact user choices:
  - strict/review-band direct remaps: `3/8` rows (`3`, `5`, `6`);
  - rows `1`, `2`, `4`, and `7` are visually informative but still fail linear review when later anchors are kept fixed;
  - row `8` is a separate larger relabel case because the requested `139A` collides with the old `150` position.
- Implemented a narrow production prior mode family:
  - `reverse_pair_tail_300_500`
  - `reverse_pair_tail_200_500`
  - `reverse_pair_anchor_340_350`
- The mode projects from stable later anchors, chooses two real peaks in the projected `50 bp` window, and maps them to `35/50`; it applies only inside normal GS500ROX review band, otherwise remains a proposal.
- Direct smoke on the 8 hard rows after implementation applied `3/8` rows via `gs500rox_start_family_prior`; the other hard rows stayed review/proposal.
- Verification: py_compile ok; `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py` passed.

## 2026-05-15 - FLT3 Hardcase Family Hypothesis Test

- Tested a family-level shadow evaluator on the remaining 8 hardcases:
  - seed `35/50` from the user's reverse-projection annotations;
  - then rebuild `75/100/139/150/160` as one local apex family from the same tail/anchor projection.
- Result: `3/8` rows reached strict review band, the same rows that are already safe for the narrow `reverse_pair_*` prior.
- Several remaining rows have visually plausible starts but still fail because later anchors must move together, especially `150/160`.
- Row 8 behaves as a larger relabel/downstream-family issue, not a pure 35/50 start issue.
- Output: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/wrong_35_50_family_hypothesis_eval/summary.csv`.
- Generated a visual downstream-family proposal panel:
  - `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_downstream_family_proposals/review_panel.html`.
  - It locks the user-provided start seed and shows candidate/proposal placement through `160 bp`.
  - It still reaches only `3/8` strict review-band rows, confirming that the remaining rows need either a wider relabel model or separate downstream-anchor annotations.
- User annotated the downstream panel:
  - row 1 was visually perfect;
  - rows 2/3/5/6/7 needed earlier `75/100` choices;
  - row 7 also needed `150A/160A`;
  - row 8 needed `100` near scan `1950`, while the rest was visually good.
- Re-evaluated these exact user corrections:
  - direct linear review-band rows remain `3/8`;
  - however visually accepted rows show strong curved-fit QC. Example row 1: linear max/mean `10.70/5.02`, quadratic `2.92/1.18`, cubic `1.55/0.69`.
- Durable conclusion: for these low-end GS500ROX relabel cases, linear QC is too strict as the only review-display gate. Next implementation should add a review-only curved-fit/apex/gap gate, not loosen ordinary linear PASS criteria.
- User-corrected output: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/wrong_35_50_user_downstream_corrected_eval/summary.csv`.

## 2026-05-15 - FLT3 Curved Review Gate For Low-End Relabel Proposals

- Added quadratic/cubic residual metrics to GS500ROX start-prior trials in `core/analyses/flt3/pipeline.py`.
- Added a review-only curved gate: linear fit may be looser (`max <= 11 bp`, `mean <= 5.2 bp`) only when quadratic fit is strong (`max <= 4 bp`, `mean <= 2 bp`, `R2 >= 0.9995`).
- Exported new QC columns:
  - `GS500ROXStartPriorCurvedReviewBand`
  - `GS500ROXStartPriorQuadraticMaxBp`
  - `GS500ROXStartPriorQuadraticMeanBp`
  - `GS500ROXStartPriorQuadraticR2`
- Updated review HTML so curved-review proposals are displayed, while `apply_band` and ordinary PASS behavior remain unchanged.
- Smoke on the 8 hard `wrong_35_50` rows:
  - linear apply/review-band rows remain `3/8`;
  - curved review-band proposals are `5/8`;
  - rows `4` and `7` still fail the curved gate and need further downstream/apex learning.
- New hardcase panel: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_curved_review_gate/review_panel.html`.
- Verification:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/render_flt3_review_html.py scripts/run_flt3_liz500_qc_all_injections.py`
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`

## 2026-05-15 - FLT3 Adaptive CWT Pool Learning

- User reviewed the curved review-gate panel and found only row 6 good, but noted the adaptive CWT full-combo probe looked perfect for all except rows 5 and 8; rows 2/3/4 mainly missed a weak 35 bp peak.
- Tested baseline-corrected `DATA4` CWT pools over scan `1350-5000`.
  - Fixed `>200` CWT pool yielded candidate counts `[17, 21, 21, 18, 19, 20, 21, 10]`.
  - Adaptive threshold to at least 18 candidates yielded thresholds `[150, 400, 500, 300, 400, 500, 500, 100]` and counts `[18, 20, 20, 18, 18, 19, 18, 20]`.
- Full/beam combination scoring over the adaptive CWT pool gave strong family fits on most rows, confirming this is a better direction than pure residual repair from the Rust peak preview.
- Added a prototype first-anchor supplement: keep the adaptive CWT pool, then add weak early local/CWT candidates for 35 bp.
  - Output panel: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_wrong_35_50_adaptive_cwt_beam_supplement/review_panel.html`.
  - Rows 1/2/3/4/6/7 now have plausible low-end family fits by quadratic/linear metrics; row 5 remains poor and row 8 is dominated by baseline/early-blob issues.
- Durable next step: production candidate generation should use adaptive baseline-corrected CWT pools plus per-anchor supplements, then beam-search combinations with expected-gap, median-height/shape, and curved-fit constraints. Row 8 needs a separate baseline/blob handling path.

## 2026-05-15 - FLT3 Adaptive CWT Broad Eval

- Ran the adaptive CWT + first-anchor supplement + beam-combo prototype beyond the 8 hardcases:
  - all `57` night-review rows from `FLT3_REVIEW_Rerun_StartPrior_ApplySimple86_All57.csv`;
  - `24` deterministic PASS/DATA4 controls from the 2000-file ROX500 QC run.
- Results:
  - night review rows: `36/57` inside strict linear review band, `40/57` inside curved review band;
  - PASS controls: `23/24` inside both strict linear and curved review band;
  - user-labelled `wrong_35_50`: `3/8` strict linear, `5/8` curved;
  - user-labelled `good`: `22/30` strict linear, `24/30` curved;
  - `operator_data`: `0/6`, which is expected and useful because these are not model-learning targets.
- Rendered broad visual panel with CWT pools and beam-selected ladders:
  - `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_adaptive_cwt_broad_eval/review_panel.html`.
- Interpretation:
  - The adaptive CWT/beam approach generalizes better than the earlier start-prior heuristics and preserves most PASS controls.
  - It still needs stronger guards for already-good review rows and a separate baseline/blob path for row-8-like failures before promotion to production.

## 2026-05-15 - FLT3 35 bp Blob Guard Learning

- Investigated the remaining `35 bp` blob/shoulder failure in the adaptive CWT + beam prototype.
- A simple first-gap guard (`35->50` scan gap roughly `68-155`) prevents the most obvious tiny `35/50` blob pairs but is not sufficient by itself.
- The persistent bad cases often pass the first gap but fail the start-family geometry: compressed `50->75` / `75->100` gaps, or an over-large `75->100` jump.
- Prototype start-block gate over the first four gaps (`35->50`, `50->75`, `75->100`, `100->139`) flags the worst blob/cluster choices without materially changing the broad curved-review counts.
- Current learned guardrail for promotion: do not accept/review-display a low-end relabel solely because residuals are good; require plausible start-block scan gaps and no compressed early cluster.
- Implemented the conservative start-block blob guard in `core/analyses/flt3/pipeline.py` for `start_block_35_50_75_100_139` proposals: implausible first-five-anchor scan gaps are filtered before residual ranking.
- Verification after the guard: `python3 -m py_compile core/analyses/flt3/pipeline.py`; `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`.
- Remaining true failures after the gap guard are no longer just `35 bp`: row 50 needs better `75/100` family placement, and row 57 is a larger baseline/blob relabel case.

## 2026-05-15 - FLT3 Expanded Beam Struggler Proposals

- User asked to keep testing the remaining problematic 35/start-family cases.
- Tested reranking the existing gap-guard CWT pool with broader/no-cluster/learned gap variants; this did not materially improve most cases, so scoring alone is not enough.
- Tested an expanded low-end peak pool using baseline-corrected local peaks plus the existing CWT candidates, then beam-searched the first five GS500ROX anchors under start-block gap guards.
- Expanded-beam improved several struggler rows:
  - ordinals `2`, `4`, `39`, `47`, and `50` reached strict+curved review metrics in the prototype;
  - ordinal `20` improved slightly but still missed the curved gate;
  - ordinals `22`, `25`, `44`, and `46` remained poor;
  - ordinal `57` still had no safe proposal and remains a baseline/relabel hard case.
- New proposal panel: `local_triage/flt3_rox500_review_rerun_start_prior_apply_simple86_2026-05-15/html_adaptive_cwt_expanded_beam_struggler_proposals/review_panel.html`.
- Interpretation: the useful next production idea is not looser residual thresholds, but expanded low-end candidate rescue plus capped beam search and strong start-block geometry guards.

## 2026-05-15 - FLT3 GS500ROX Session Pause

- Paused the current GS500ROX 35/50/start-family tuning session after testing multiple approaches on the remaining hard files.
- What worked best:
  - normal `simple_shift`/`35_earlier` priors fixed most reviewed 35/50 cases;
  - curved review metrics are useful for visually good low-end relabel proposals where linear residual alone is too strict;
  - adaptive baseline-corrected CWT pools plus expanded low-end local peak rescue can find better proposals for several remaining strugglers;
  - start-block geometry guards are necessary to prevent `35 bp` from landing on blobs/shoulders.
- What did not fully solve the last cases:
  - residual-only reranking;
  - reverse-anchor residual winners without per-anchor visual/apex constraints;
  - simple first-gap-only `35->50` guard;
  - broader start-block scoring over the same candidate pool.
- Final state for now:
  - production code has conservative GS500ROX start-family proposal/apply logic plus curved-review metadata and a start-block blob guard;
  - generated exploratory panels remain under `local_triage/`;
  - the last few files are hard baseline/relabel/downstream-anchor cases and should remain review/manual-learning material rather than being forced into an automatic rule today.

## 2026-05-15 - Repo Hygiene And License Review Before Push

- Prepared the current FLT3/clonality work for git push.
- Added `local_triage/` to `.gitignore` so generated review panels, PNGs, JSON exports, and scratch analysis outputs stay out of source control.
- Reviewed local Python dependency license metadata from `requirements.txt`. Most dependencies are BSD/MIT/Apache/PSF-style scientific/runtime packages; MPL packages are present but weak-copyleft.
- Main licensing item requiring OUS governance is `PyQt6`: installed wheel includes GPL-3.0 license text while bundled Qt metadata is LGPLv3. Internal diagnostic use may be acceptable depending on OUS policy, but wider closed distribution should either use an appropriate commercial PyQt license or migrate/validate an LGPL GUI binding such as PySide6.
- Updated `THIRD_PARTY_NOTICES.md` with the dependency/license summary and PyQt6 caveat.
- Verification before push:
  - `python3 -m py_compile` on modified core/gui/scripts modules: ok;
  - `python3 -m unittest tests/test_water_filter.py tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`: ok;
  - `cargo test -p fraggler-core repair_gs500rox --quiet`: ok.

## 2026-05-15 - T7 Overnight FLT3 And Clonality Run

- User requested a new evening/night run from `/Volumes/T7 Shield/DATA` for both clonality and FLT3, with separate Excel trackers for validation.
- Added `--exclude-run-name-contains` to the FLT3 ROX500 all-injections runner so the run can require `3730` while excluding `LIZ`.
- FLT3 candidate check for `/Volumes/T7 Shield/DATA/flt3`: `7846` ROX500/3730 non-LIZ candidates (`2024=311`, `2025=5563`, `2026=1972`, `liz_included=0`).
- Started detached screen `hemafrag_flt3_20260515_2153`.
  - Script: `local_triage/overnight_t7_2026-05-15/run_flt3_rox500_3730.sh`
  - Output workbook target: `local_triage/overnight_t7_2026-05-15/flt3_rox500_3730_only/FLT3_ROX500_QC_All_Injections.xlsx`
  - Log: `local_triage/overnight_t7_2026-05-15/flt3_rox500_3730.log`
- Started detached screen `hemafrag_clonality_20260515_2158`.
  - Script: `local_triage/overnight_t7_2026-05-15/run_clonality_all.sh`
  - Input roots run sequentially: `2024_DATA`, `2025_data`, `2026`.
  - Output workbook target: `local_triage/overnight_t7_2026-05-15/clonality/Clonality_Tracking.xlsx`
  - Log: `local_triage/overnight_t7_2026-05-15/clonality.log`
- Initial validation: clonality processed the first folder and updated `Clonality_Tracking.xlsx`; FLT3 process was active in metadata filtering.

## 2026-05-16 - T7 Overnight Morning Status

- FLT3 ROX500/3730 non-LIZ run completed at `2026-05-15T22:49:56`.
  - Workbook: `local_triage/overnight_t7_2026-05-15/flt3_rox500_3730_only/FLT3_ROX500_QC_All_Injections.xlsx`.
  - Summary: `7846` analyzed, `PASS=67`, `REVIEW=7506`, `FAIL=273`, `skipped=0`.
  - Channel split: `DATA4=7686`, `DATA105=160`; `DATA105` rows came from five `FLT3_Leukostrat` 3730 run folders without `LIZ` in folder/run name, so the non-LIZ filter was not sufficient for a pure DATA4 validation workbook.
- Clonality run is still active in screen `hemafrag_clonality_20260515_2158`.
  - Current workbook: `local_triage/overnight_t7_2026-05-15/clonality/Clonality_Tracking.xlsx`.
  - Workbook currently has `Runs=951` data rows and `PK_Peaks=190` data rows.
  - State for `2024_DATA`: `done=15`, `failed=1`, `running=1`, `pending=212`.
  - The active blocker is `2024_01_25_igkkde_pr_C9U02GP2_2024-01-25_1123`, stuck on `00004_392f3aea_PK_KDE__250124_D07_C9U02GP2.fsa` for over 9 hours.

## 2026-05-16 - Stopped Hung Clonality Run

- User asked to stop the clonality job after the morning status showed it was hung.
- Stopped screen `hemafrag_clonality_20260515_2158` and manually terminated remaining child processes from that run.
- Confirmed no `clonality_backfill`, `run_clonality_all`, or `fraggler-cli serve-primitives` processes remained afterward.
- Preserved partial workbook and state:
  - `local_triage/overnight_t7_2026-05-15/clonality/Clonality_Tracking.xlsx`
  - `local_triage/overnight_t7_2026-05-15/clonality/state_2024_DATA.json`
- Last state still records `done=15`, `failed=1`, `running=1`, `pending=212`; the interrupted running folder is `2024_01_25_igkkde_pr_C9U02GP2_2024-01-25_1123` on `00004_392f3aea_PK_KDE__250124_D07_C9U02GP2.fsa`.

## 2026-05-16 - FLT3 Leukostrat Exclusion

- User confirmed all `FLT3_Leukostrat` files should be ignored for ROX500 validation because they are LIZ500 files.
- This explains the `160` `DATA105` rows in the overnight FLT3 3730/non-LIZ workbook.
- Wrote a filtered workbook excluding `SourceRunDir` containing `Leukostrat`:
  - `local_triage/overnight_t7_2026-05-15/flt3_rox500_3730_no_leukostrat/FLT3_ROX500_QC_All_Injections_no_Leukostrat.xlsx`
- Filtered summary: `7686` analyzed rows, all `DATA4`; `PASS=62`, `REVIEW=7351`, `FAIL=273`, `review_row_count=7624`.
- User annotated the first 4-example panel: three DATA4 review rows were `good`; the one DATA105/Leukostrat row was `wrong_35_50` with note that `50` is on baseline and `35 bp` is slightly wrong.

## 2026-05-16 - FLT3 DATA4 Review Sampling

- User annotated a 49-row DATA4/non-Leukostrat review sample.
- Label split: `good=21`, `wrong_35_50=17`, `minor=6`, `operator_data=3`, blank-note-only `2`.
- Key pattern:
  - `35_earlier` prior looked mostly good: `18 good`, `2 minor`, `1 wrong_35_50`.
  - Reverse-pair priors were much riskier: `reverse_pair_tail_200_500` had `9 wrong_35_50` in the sample; `reverse_pair_tail_300_500`/`anchor_340_350` also had multiple wrong/operator rows.
  - Residual metrics alone do not separate good from wrong; wrong 35/50 rows can have low linear residuals.
- Whole no-Leukostrat run impact:
  - `35_earlier` review rows: `4646`, of which `4581` are review-band true and inside normal linear QC.
  - If promoted, a conservative `35_earlier` auto-pass rule could reduce review rows from `7351` to about `2770`, but reverse-pair modes should stay review for now.

## 2026-05-16 - FLT3 35-Earlier Auto-Pass Cleanup

- Implemented the first review-noise cleanup from user annotations:
  - Applied `GS500ROX` start-prior mode `35_earlier` no longer forces `ladder_review_required=True` when it is inside strict apply/review band.
  - `simple_shift`, `reverse_pair_*`, and `start_block_35_50_75_100_139` remain review-only.
- Added unit coverage for the new prior review policy.
- Verification passed:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/run_flt3_liz500_qc_all_injections.py scripts/run_flt3_rox500_qc_all_injections.py`
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`
- Wrote an updated no-Leukostrat workbook using the same policy on the overnight CSV:
  - `local_triage/overnight_t7_2026-05-15/flt3_rox500_3730_no_leukostrat_post_35earlier_autopass/FLT3_ROX500_QC_All_Injections_no_Leukostrat_post_35earlier_autopass.xlsx`
  - Converted `4581` rows from `REVIEW` to `PASS`.
  - New status: `PASS=4643`, `REVIEW=2770`, `FAIL=273`.
- Rendered remaining review sample for next annotation:
  - `local_triage/overnight_t7_2026-05-15/flt3_remaining_review_after_35earlier_autopass_40_html/review_panel.html`

## 2026-05-16 - FLT3 Reverse-Pair Safety Tightening

- User asked to continue fixing `35/50` errors and cases where `35` should move slightly later/right.
- Compared annotated bad/minor rows against original Rust selected starts and prior proposals.
- Finding: reverse-pair modes often create visually wrong `35/50` placements even when linear residuals are excellent; some rows need per-anchor right-shift/nudge rather than a residual-winning pair projection.
- Tightened production behavior:
  - `reverse_pair_*` start-prior trials now have `apply_band=False`.
  - They remain review/proposal signals, but no longer modify the fitted ladder as if applied.
  - Tests updated and passed.
- Rendered a candidate panel for remaining review rows to learn per-anchor choices for `35/50/75/100/139`:
  - `local_triage/overnight_t7_2026-05-15/flt3_remaining_reverse_projection_candidates_after_reverse_unapply/review_panel.html`

## 2026-05-16 - FLT3 Reverse-Pair Peak-Support Guard

- User clarified not to repeat the same manual review and to use the previous learning: avoid `35/50` candidates on baseline or on top of the first large dye blob.
- Implemented production guardrails for GS500ROX `reverse_pair_*` proposals:
  - Candidate pool now requires stronger low-end signal (`min_height=35`) before pair search.
  - Proposed `35->50` gap is constrained to `60-95` scans.
  - Both anchors must have real peak height/prominence support.
  - Pairs with a massive first blob plus a tiny partner are rejected even if residuals are good.
- Added unit coverage for rejecting a baseline/first-blob reverse-pair case while preserving a learned good reverse-pair proposal.
- Verification passed:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py tests/test_flt3_gs500rox_start_family_review.py`
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`

## 2026-05-16 - FLT3 Guardrail 1000-File Smoke

- User asked to test with more files after reverse-pair guardrails.
- First 1000-file smoke excluded `Leukostrat` but not `LIZ`; result showed `DATA4=952`, `DATA105=48`, so the runner needed multiple exclude tokens.
- Updated `--exclude-run-name-contains` to accept comma/semicolon-separated tokens such as `LIZ,Leukostrat`.
- Clean 1000-file ROX500/3730 smoke command:
  - `python3 scripts/run_flt3_rox500_qc_all_injections.py --fsa-dir "/Volumes/T7 Shield/DATA/flt3" --outdir local_triage/overnight_t7_2026-05-15/flt3_guardrail_smoke_1000_data4 --year 2024 --year 2025 --year 2026 --require-run-name-contains 3730 --exclude-run-name-contains "LIZ,Leukostrat" --limit 1000 --workers 6`
- Clean smoke result:
  - Output workbook: `local_triage/overnight_t7_2026-05-15/flt3_guardrail_smoke_1000_data4/FLT3_ROX500_QC_All_Injections.xlsx`
  - Channel split: `DATA4=1000`.
  - Status: `PASS=459`, `REVIEW=414`, `FAIL=127`.
  - Ladder QC: `ok=456`, `review_required=414`, `analysis_failed=127`, `manual_adjustment=3`.
  - Prior modes: `35_earlier=454`, `start_block_35_50_75_100_139=401`, `simple_shift=5`, `reverse_pair_tail_200_500=5`.
  - `35_earlier` auto-passed `453/454`; all `reverse_pair_tail_200_500` remained `REVIEW`.
- Verification after runner/filter update passed:
  - `python3 -m py_compile scripts/run_flt3_liz500_qc_all_injections.py scripts/run_flt3_rox500_qc_all_injections.py`
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`

## 2026-05-16 - FLT3 GS500ROX Annotation Learning

- User annotated `/Users/christian/Downloads/flt3_gs500rox_start_proposal_annotations (1).json` from the 29-row check panel.
- Annotation split:
  - `proposal_correct=11`, `current_correct=17`, `proposal_close=1`.
  - `35_earlier`: `6` proposal-correct, `1` close.
  - `simple_shift`: `5` proposal-correct.
  - `reverse_pair_tail_200_500`: `5` current-correct.
  - `start_block_35_50_75_100_139`: `12` current-correct.
- Durable learning:
  - `35_earlier` remains good for auto-pass inside strict band.
  - `simple_shift` is promising, but stays review-only until tested on more data.
  - `reverse_pair_*` and `start_block` created false-positive reviews when the current early GS500ROX geometry was already coherent; better residuals alone should not move `35` left.
- Implemented stable-current suppression for hard GS500ROX start proposals:
  - Suppress `reverse_pair_*`/`start_block` proposal generation when current gaps match the visually stable pattern (`35->50` `68-76`, `50->75` `132-150`, `75->100` `128-145`, `100->139` `205-230`) and current linear fit is already strong (`max<=3.8`, `mean<=1.75`, `R2>=0.99983`).
  - Left `simple_shift` and remaining hard `start_block` rows as review-only.
- Verification:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py`: ok.
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`: ok.
- Reran clean 1000-file DATA4 smoke:
  - Output workbook: `local_triage/overnight_t7_2026-05-15/flt3_guardrail_smoke_1000_data4_after_annotation_learning/FLT3_ROX500_QC_All_Injections.xlsx`
  - Channel split: `DATA4=1000`.
  - Status improved from prior smoke `PASS=459`, `REVIEW=414`, `FAIL=127` to `PASS=616`, `REVIEW=257`, `FAIL=127`.
  - Review reduction: `157` fewer review rows without changing fail count.
  - Prior modes after learning: `35_earlier=463`, `start_block_35_50_75_100_139=240`, `simple_shift=5`, no remaining `reverse_pair_tail_200_500` mode in the 1000-file summary.

## 2026-05-16 - FLT3 Remaining Prior Overlay Panel

- Added `scripts/render_flt3_gs500rox_prior_overlay_html.py` to render current Rust selected anchors versus workbook start-prior proposals on the same trace.
  - Red X = current Rust anchors.
  - Blue circle = prior proposal anchors.
  - Export labels: proposal-correct, current-correct, close/minor, weak/bad ladder, unclear.
- Rendered a 40-row panel from the post-annotation-learning 1000-file smoke:
  - `local_triage/overnight_t7_2026-05-15/flt3_prior_overlay_remaining_after_annotation_learning_40/review_panel.html`
  - Composition: `35_earlier=10`, `simple_shift=5`, `start_block_35_50_75_100_139=25`.
- Quick metric sanity check:
  - `35_earlier` remnants: current median linear max `3.4115`, proposal median `7.708`; these are not auto-pass candidates and need visual review.
  - `simple_shift`: current median max `5.632`, proposal median `6.348`; user previously marked these 5 proposals correct, but keep review-only until more validation.
  - `start_block`: current median max `4.471`, proposal median `3.148`; residual improvement alone remains insufficient, so the overlay panel is the right next annotation unit.
- Verification:
  - `python3 -m py_compile scripts/render_flt3_gs500rox_prior_overlay_html.py`: ok.

## 2026-05-16 - FLT3 Current-Best Overlay Learning

- User annotated `/Users/christian/Downloads/flt3_gs500rox_prior_overlay_annotations.json` from the 40-row current-vs-proposal overlay.
- Annotation split:
  - Overall: `current_correct=34`, `proposal_correct=5`, `proposal_close=1`.
  - `35_earlier`: `current_correct=9`, `proposal_close=1`.
  - `simple_shift`: `proposal_correct=5`.
  - `start_block_35_50_75_100_139`: `current_correct=25`.
- Implemented a broader preferred-current GS500ROX guard:
  - Suppresses bad `35_earlier` proposals when the proposed residuals are materially worse than the already coherent current ladder.
  - Suppresses hard `reverse_pair_*`/`start_block` proposal generation when current early geometry is broadly coherent (`35->50` `67-76`, `50->75` `128-152`, `75->100` `128-152`, `100->139` `205-235`) and current fit is strong enough (`max<=4.9`, `mean<=1.9`, `R2>=0.99978`).
  - Keeps `simple_shift` review-only despite repeated proposal-correct samples because validation is still narrow.
- Reran clean 1000-file DATA4 smoke:
  - Output workbook: `local_triage/overnight_t7_2026-05-15/flt3_guardrail_smoke_1000_data4_after_current_best_learning/FLT3_ROX500_QC_All_Injections.xlsx`
  - Channel split: `DATA4=1000`.
  - Status improved from previous smoke `PASS=616`, `REVIEW=257`, `FAIL=127` to `PASS=723`, `REVIEW=150`, `FAIL=127`.
  - Remaining review prior modes: `start_block_35_50_75_100_139=141`, `simple_shift=5`, `35_earlier=1`, plus `3` non-prior late-anchor review rows.
- Verification:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/render_flt3_gs500rox_prior_overlay_html.py`: ok.
  - `python3 -m unittest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py`: ok (`8` tests).

## 2026-05-18 - FLT3 Follow-Up Review Panel

- User asked to look at more files after current-best learning.
- Rendered a 50-row current-vs-proposal overlay panel from the latest 1000-file DATA4 smoke review rows:
  - `local_triage/overnight_t7_2026-05-18/flt3_remaining_after_current_best_overlay_50/review_panel.html`
  - Composition from renderer output: `35_earlier=1`, `simple_shift=5`, `start_block_35_50_75_100_139=44`.
- Browser automation could not programmatically navigate to the local `file://` URL because the in-app browser policy blocked that URL form; panel file was still written successfully.
- User reported the panel was blank. Root cause: `/Volumes/T7 Shield/DATA/flt3` was not mounted, so raw `.fsa` files could not be re-read; the renderer had logged filenames but skipped all rows and wrote an empty HTML.
- Updated `scripts/render_flt3_gs500rox_prior_overlay_html.py` to print explicit skip reasons and include `skipped_missing`, `skipped_bad_proposal`, and `skipped_bad_analysis` counts in `summary.json`, preventing silent empty panels.
- User mounted T7 again and reported review buttons did not work in the in-app browser.
- Hardened the panel JavaScript for `file://` browser behavior:
  - `localStorage` access is wrapped in try/catch with in-memory fallback.
  - Each clicked label now shows a visible `Valgt: ...` status on the card.
  - Export now writes JSON into a visible textarea as fallback, while still attempting normal JSON download.
- Regenerated both panels successfully with T7 mounted:
  - Existing open panel: `local_triage/overnight_t7_2026-05-15/flt3_prior_overlay_remaining_after_annotation_learning_40/review_panel.html`, `rows=40`, no skipped rows.
  - New current-best panel: `local_triage/overnight_t7_2026-05-18/flt3_remaining_after_current_best_overlay_50/review_panel.html`, `rows=50`, no skipped rows.

## 2026-05-18 - FLT3 Simple-Shift Learning And Late-50 Review Mode

- User annotated the regenerated 40-row prior overlay panel. Split:
  - Overall: `current_correct=34`, `proposal_correct=5`, `proposal_close=1`.
  - `35_earlier`: `9` current-correct and `1` proposal-close where current `50 bp` appears to be true `35 bp`, with correct `50 bp` later.
  - `simple_shift`: `5/5` proposal-correct again.
  - `start_block_35_50_75_100_139`: `25/25` current-correct.
- Implemented production changes:
  - `simple_shift` no longer requires manual review when it is inside the strict apply band.
  - Added review-only `late_50_after_current_50` proposal mode for the hard case where current `50` should become `35`, and a later peak should become `50`.
  - Kept `reverse_pair_*`, `start_block_35_50_75_100_139`, and `late_50_after_current_50` review-only.
  - Relaxed compact GS500ROX guardrail hydration enough to allow known 3730 compact examples while still rejecting bad late-first-anchor tails.
- Verification:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py core/rust_bridge.py scripts/render_flt3_gs500rox_prior_overlay_html.py`: ok.
  - `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `31` passed.
- Reran clean 1000-file DATA4 smoke after simple-shift learning:
  - Output workbook: `local_triage/overnight_t7_2026-05-18/flt3_guardrail_smoke_1000_after_simple_shift_learning/FLT3_ROX500_QC_All_Injections.xlsx`
  - Channel split: `DATA4=1000`.
  - Status changed from prior current-best smoke `PASS=723`, `REVIEW=150`, `FAIL=127` to `PASS=725`, `REVIEW=148`, `FAIL=127`.
  - Remaining review prior modes: `start_block_35_50_75_100_139=141`, `simple_shift=3`, `35_earlier=1`, plus `3` non-prior review rows.
  - Multiprocessing was blocked by the sandbox, so the runner fell back to sequential processing and completed successfully.

## 2026-05-18 - FLT3 Review/Fail HTML Panels

- User asked for separate HTML panels to review remaining `REVIEW` and `FAIL` rows.
- Rendered all proposal-backed `REVIEW` rows from the latest 1000-file smoke:
  - `local_triage/overnight_t7_2026-05-18/flt3_review_rows_overlay_all_html/review_panel.html`
  - Rows rendered: `145`; skipped: `0`.
  - Modes included: `35_earlier`, `simple_shift`, `start_block_35_50_75_100_139`, `late_50_after_current_50`.
- Rendered all `FAIL` rows as trace-only review cards:
  - `local_triage/overnight_t7_2026-05-18/flt3_fail_rows_trace_all_html/review_panel.html`
  - Rows rendered: `127`; skipped: `0`.
  - All current fail rows are `analysis_failed`, so the panel shows full DATA4 corrected trace plus low-end ladder region rather than current/proposal anchors.

## 2026-05-18 - FLT3 Full Review Annotation Learning

- User annotated all `145` proposal-backed REVIEW rows and reported that most were `current_correct`.
- Annotation summary from the JSON:
  - `simple_shift`: `3/3` proposal-correct, confirming it should not remain in manual review when inside apply band.
  - `35_earlier`: `1` proposal-close where current `50 bp` is likely true `35 bp`, and correct `50 bp` should be later.
  - `start_block_35_50_75_100_139`: overwhelmingly current-correct; a few proposal-close notes say `50 bp` is right but `35 bp` should be slightly later.
- Implemented cleanup:
  - Applied simple-shift rows now clear old `blob_dominated_start` review codes and use the simple-shift linear apply band instead of the stricter generic GS500ROX linear review max.
  - Added a broad current-correct hard-start suppression band for rows already inside normal GS500ROX review band with mild early geometry (`35->50` `69-85`, `50->75` `136-165`, `75->100` `133-155`, `100->139` `214-250`).
  - Suppression now blocks both `reverse_pair_*` and `start_block_35_50_75_100_139` proposals for that band; the first attempt only blocked `start_block`, which simply allowed the same rows to reappear as reverse-pair proposals.
- Verification:
  - `python3 -m py_compile core/analyses/flt3/pipeline.py tests/test_flt3_gs500rox_start_family_review.py`: ok.
  - `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `33` passed.
- Intermediate 1000-file smoke after the simple-shift cleanup but before final reverse-pair suppression:
  - Output workbook: `local_triage/overnight_t7_2026-05-18/flt3_guardrail_smoke_1000_after_review_annotation_learning/FLT3_ROX500_QC_All_Injections.xlsx`
  - Channel split: `DATA4=1000`.
  - Status: `PASS=728`, `REVIEW=145`, `FAIL=127`.
  - `simple_shift` rows all moved to `PASS`; remaining proposal review rows shifted to `reverse_pair_*`, proving the hard-start suppression needed to cover both reverse-pair and start-block modes.

## 2026-05-18 - FLT3 MP1 Operator-Error Exclusion

- User reviewed the full FAIL trace panel and confirmed all current FAIL rows are real human/operator errors that can be discarded from future analysis.
- Pattern was clean in the 1000-file smoke: `127/127` FAIL rows were `MP1_*.fsa`, all from the 2024-11-27 HDD/C990RI16 `0278`/`0279` FLT3 runs.
- Implemented a pre-QC candidate filter in `scripts/run_flt3_liz500_qc_all_injections.py` so `MP1_*.fsa` files are excluded before year/run filters and before `--limit`; the compatibility `run_flt3_rox500_qc_all_injections.py` wrapper inherits this.
- Added focused runner-filter tests in `tests/test_flt3_rox500_runner_filters.py`.
- Verification:
  - `python3 -m pytest tests/test_flt3_rox500_runner_filters.py tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `35` passed.

## 2026-05-18 - FLT3 Review Cleanup After MP1 Filter

- Ran a 250-file 3730/DATA4 smoke after MP1 exclusion and review-family cleanup:
  - Initial state: `PASS=246`, `REVIEW=4`, `FAIL=0`.
  - Two good compact late-first-anchor rows were visually acceptable and had strong linear fits; one NTC late-first-anchor row had a suspicious tiny/late `35 bp` start and stayed review.
  - One `_r___G01_C990RI16.fsa` `35_earlier` proposal was proposal noise; current was better.
- Implemented:
  - Narrow `GS500ROX first anchor too late` auto-pass guardrail for good compact 16-anchor ladders only.
  - Extra suppression for bad `35_earlier` proposals when current is already in the reviewed current-correct hard-start band and proposal fit is worse.
- Verification:
  - `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_flt3_rox500_runner_filters.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `37` passed.
  - Final 250-file smoke: `PASS=249`, `REVIEW=1`, `FAIL=0`, all `DATA4`.
  - Final workbook: `local_triage/overnight_t7_2026-05-18/flt3_guardrail_smoke_250_after_review_cleanup_v3/FLT3_ROX500_QC_All_Injections.xlsx`.
  - Final review panel: `local_triage/overnight_t7_2026-05-18/flt3_review_current_trace_after_review_cleanup_v3_html/review_panel.html`.
- User annotated the remaining review row `NTC_ITD_1-10__100125_H01_C990RHLW.fsa` as `minor`: `35 bp` is along baseline and should move later/right/up to the true peak. Keep this row and this pattern in manual review rather than relaxing the late-first-anchor auto-pass guardrail.

## 2026-05-18 - FLT3 Right-Shift Start Proposal Learning

- User annotated the next 5 proposal-backed review rows:
  - All were `proposal_close`.
  - `25OUM03774_p1_ITD_ufort__070325_C01_C9U07BJX.fsa`: current `50 bp` should be true `35 bp`, but proposed `50 bp` was still too early; move `50` farther right.
  - Four start-block rows: proposed `35 bp` was still slightly too early; one H9C0VADZ row needed both `35` and `50` slightly farther right.
- User also confirmed the 8 FAIL rows in the H9C0VADZ ratio set are true missing-ladder/human-error failures.
- Implemented a review-only learning probe:
  - Expanded `late_50_after_current_50` search window to allow later true-50 peaks.
  - Added `right_shifted_start_review` proposals for the "proposal close but too far left" class.
  - Updated the overlay renderer to include `late_50_after_current_50` and `right_shifted_start_review`.
  - Kept both proposal modes review-only; they do not auto-apply.
- Verification:
  - `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_flt3_rox500_runner_filters.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `39` passed.
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/render_flt3_gs500rox_prior_overlay_html.py`: ok.
- Rendered focused probe panel:
  - `local_triage/overnight_t7_2026-05-18/flt3_right_shift_learning_probe_v1_overlay_html/review_panel.html`.
- User annotated the probe panel:
  - All 5 rows were marked `proposal_correct`.
  - The H9C0VADZ row still noted that `50 bp` was correct but `35 bp` should move slightly farther right than the v1 proposal.
- Refined `right_shifted_start_review` for the both-anchors-moving case:
  - Select the new `50 bp` first.
  - Then choose `35 bp` from the expected window relative to that new `50 bp`.
  - For `25OUM04778_p1_ITD_ufort__250324_A01_H9C0VADZ.fsa`, the focused probe now proposes `35/50 = 1602/1679`.
- Rendered v2 probe panel:
  - `local_triage/overnight_t7_2026-05-18/flt3_right_shift_learning_probe_v2_overlay_html/review_panel.html`.

## 2026-05-18 - FLT3 Learned Right-Shift Auto-Apply

- User annotated `flt3_right_shift_learning_probe_v2_overlay_html`:
  - All 5 rows were `proposal_correct`.
  - Confirmed `late_50_after_current_50` for the current-50-as-35 case (`1658/1734` start).
  - Confirmed `right_shifted_start_review` for the broad start-review family, including the H9C0VADZ both-anchor move (`1602/1679`).
- Implemented learned auto-apply for these two modes in `core/analyses/flt3/pipeline.py`:
  - Applies only under strict linear/quadratic/cubic residual thresholds plus confirmed current-gap family checks or an existing review signal.
  - Clears the start-family review reasons when the learned prior is applied successfully.
  - Keeps baseline/tiny-start cases out of the learned band, so `NTC_ITD_1-10__100125_H01_C990RHLW.fsa` remains `REVIEW`.
- Export updates:
  - Added `GS500ROXStartPriorLearnedApplyBand` to FLT3 ROX500 runner CSV/XLSX output.
- Verification:
  - Focused checks: all 5 user-confirmed rows now return `PASS` with the learned prior applied; the NTC baseline-35 row remains `REVIEW`.
  - `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_flt3_rox500_runner_filters.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `40` passed.
  - `python3 -m py_compile core/analyses/flt3/pipeline.py scripts/run_flt3_liz500_qc_all_injections.py scripts/run_flt3_rox500_qc_all_injections.py scripts/render_flt3_gs500rox_prior_overlay_html.py`: ok.
  - 1000-file 3730/DATA4 smoke after learning: `PASS=991`, `REVIEW=1`, `FAIL=8`.
  - The single review is `NTC_ITD_1-10__100125_H01_C990RHLW.fsa`; the 8 fails are the user-confirmed H9C0VADZ ratio/missing-ladder files.
  - Workbook: `local_triage/overnight_t7_2026-05-18/flt3_guardrail_smoke_1000_after_right_shift_learning_v4/FLT3_ROX500_QC_All_Injections.xlsx`.
- Broader 2500-file 3730/DATA4 smoke:
  - Result: `PASS=2485`, `REVIEW=5`, `FAIL=10`.
  - New reviews beyond the known NTC baseline case include `IVS-0000_D835_KUTT__300525_E05_H9C0ZJ3G.fsa`, `25OUM08837_p1_RATIO__300525_C04_H9C0ZJ3G.fsa`, `25OUM08172_p2_ITD_ufort__220525_E02_H9C0ZJ3R.fsa`, and `NTC_RATIO__110625_H02_H9U0BDEO.fsa`.
  - New fails beyond the known H9C0VADZ ratio/missing-ladder group are `IVS-0000_ITD__0300725_C01_H9C0ZJ88.fsa` and `25OUM11534_p2_TKD-kutting__240725_B05_H9C0VC6E.fsa`; inspect before classifying as durable exclusions.
  - Review trace panel: `local_triage/overnight_t7_2026-05-18/flt3_2500_review_trace_all_html/review_panel.html`.
  - Review overlay panel for rows with start-prior proposals: `local_triage/overnight_t7_2026-05-18/flt3_2500_review_overlay_html/review_panel.html`.
  - Fail trace panel: `local_triage/overnight_t7_2026-05-18/flt3_2500_fail_trace_html/review_panel.html`.

## 2026-05-18 - FLT3 2500 Review/Fail Cleanup

- User reviewed the 2500-file smoke panels:
  - The 5 review rows split into true minor/hard review (`NTC_ITD_1-10__100125_H01_C990RHLW.fsa`, `25OUM08172_p2_ITD_ufort__220525_E02_H9C0ZJ3R.fsa`, `25OUM08837_p1_RATIO__300525_C04_H9C0ZJ3G.fsa`) and current-correct/good rows (`IVS-0000_D835_KUTT__300525_E05_H9C0ZJ3G.fsa`, `NTC_RATIO__110625_H02_H9U0BDEO.fsa`).
  - The 10 fail rows were confirmed as human/operator/data-quality cases: missing ladder or too-short ladder. Added exact known filenames to the runner exclusion list.
- Implemented:
  - Suppression for bad `35_earlier` proposal noise when current is already good and the proposal fit is clearly worse.
  - Broadened the current-correct start-block suppression to include the `68`-scan 35/50 gap case.
  - Removed `start_block_35_50_75_100_139` as a review-creating suggestion; it remains visible proposal evidence but should not create review noise by itself.
- Verification:
  - `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_flt3_rox500_runner_filters.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py -q`: ok, `42` passed.
  - Focused 5-row reanalysis: `PASS=2`, `REVIEW=3`, `FAIL=0`, matching user annotation.
  - Focused 78-row review cleanup batch: `PASS=70`, `REVIEW=8`, `FAIL=0`.
  - Full 2500-file 3730/DATA4 smoke after cleanup: `PASS=2492`, `REVIEW=8`, `FAIL=0`.
- Latest outputs:
  - Workbook: `local_triage/overnight_t7_2026-05-18/flt3_guardrail_smoke_2500_after_startblock_cleanup_v3/FLT3_ROX500_QC_All_Injections.xlsx`.
  - Review trace panel: `local_triage/overnight_t7_2026-05-18/flt3_2500_review8_after_startblock_cleanup_trace_html/review_panel.html`.
  - Review overlay panel: `local_triage/overnight_t7_2026-05-18/flt3_2500_review8_after_startblock_cleanup_overlay_html/review_panel.html`.

## 2026-05-18 - Overnight T7 FLT3 and Clonality Full Run Started

- User requested a new T7 overnight run for both clonality and FLT3, with clonality prioritized and Excel tracking output for patient/DIT runs plus QC/PK peaks.
- Started output root: `local_triage/overnight_t7_2026-05-18_full_night/`.
- Clonality:
  - Started resumable backfill first, before FLT3.
  - Year roots are processed sequentially into one workbook to avoid concurrent Excel-write conflicts:
    - `/Volumes/T7 Shield/DATA/2026`
    - `/Volumes/T7 Shield/DATA/2025_data`
    - `/Volumes/T7 Shield/DATA/2024_DATA`
  - Tracking workbook: `local_triage/overnight_t7_2026-05-18_full_night/clonality/Clonality_Tracking_All_T7.xlsx`.
  - State files: `local_triage/overnight_t7_2026-05-18_full_night/states/clonality_<year>_state.json`.
  - Logs: `local_triage/overnight_t7_2026-05-18_full_night/logs/clonality_<year>.log`.
  - Run options: `max_workers=4`, `folder_workers=1`, `skip_html_reports`, deferred workbook refresh with spill files.
- FLT3:
  - Started ROX500 all-injections QC with lower priority (`workers=3`).
  - Input: `/Volumes/T7 Shield/DATA/flt3`.
  - Filters: years `2024/2025/2026`, require `3730`, exclude `LIZ,Leukostrat`.
  - Output dir: `local_triage/overnight_t7_2026-05-18_full_night/flt3_rox500/all_3730_rox500/`.
  - Log: `local_triage/overnight_t7_2026-05-18_full_night/logs/flt3_rox500.log`.
- Both commands are wrapped with `caffeinate -dimsu` to prevent sleep during the night. Clonality uses resumable state/spill files; FLT3 writes one final QC workbook/CSV set at completion.
- Runtime intervention:
  - Clonality hit a true long-running fallback on `26OUM01277_KDE_06022026_A08_H9C0VCG7.fsa` after >20 minutes.
  - Added this exact file to `KNOWN_CLONALITY_BACKFILL_SKIP_FILES` in `core/batch.py`.
  - Terminated and resumed the clonality backfill from the same state/workbook so completed folders are preserved and the night run can continue.
  - Clonality later hit the same unbounded fallback pattern on `25OUM02663_TRG_mixB__190225_E03_C9U078YZ.fsa`.
  - Added this exact file to the same skip list, terminated the stale 2025 worker, and resumed again from the shared state/workbook.
  - During 2024, the run stalled in `2024_02_20_tcrg_igkkde_pr_C9R0HJZA_2024-02-21_1171` with multiple parallel jobs stuck since 04:18.
  - Added the exact stuck files `24OUM02878_tcrgA__200224_H02_C9R0HJZA.fsa`, `24OUM02880_IGK__200224_B07_C9R0HJZA.fsa`, and `24OUM02881_tcrgB__200224_A06_C9R0HJZA.fsa` to the same guardrail list, then resumed from state/workbook.
  - A later 2024 folder (`2024_03_08_TCRg_IGKKDE_ef_C9R0HJPD_2024-03-08_1196`) also froze with stale job progress.
  - Added exact stale files from that folder to the guardrail list: `24OUM03702_TCRg_mixB_070324_E04_C9R0HJPD.fsa`, `24OUM03767_KDE_070324_E12_C9R0HJPD.fsa`, `24OUM03995_TCRg_mixA_070324_A05_C9R0HJPD.fsa`, and `24OUM03999_TCRg_mixA_070324_B05_C9R0HJPD.fsa`.

## 2026-05-19 - Clonality Review Panel Button Fix

- Built clonality ladder annotation panel for `47` `review_required` rows plus `1` `missing_ladder` row from `local_triage/overnight_t7_2026-05-18_full_night/clonality/Clonality_Tracking_All_T7.xlsx`.
- Output: `local_triage/overnight_t7_2026-05-18_full_night/clonality_review_required_plus_missing_html/review_panel.html`.
- Fixed `scripts/render_clonality_review_html.py` so JSON embedded in `<script type="application/json">` is not HTML-escaped as `&quot;`; the escaped JSON caused `JSON.parse` to fail and prevented annotation buttons from registering click handlers.
- Regenerated the existing panel HTML from `review_rows.tsv` without re-rendering all trace images.
- Saved user annotations for the `48`-row clonality review panel:
  - `local_triage/overnight_t7_2026-05-18_full_night/clonality_review_required_plus_missing_html_v2/clonality_ladder_review_required_or_missing_annotations_2026-05-19.json`
  - `local_triage/overnight_t7_2026-05-18_full_night/clonality_review_required_plus_missing_html_v2/clonality_review_annotations_2026-05-19.tsv`
  - `local_triage/overnight_t7_2026-05-18_full_night/clonality_review_required_plus_missing_html_v2/clonality_review_annotation_summary_2026-05-19.json`
- Annotation distribution: `20` good, `24` operator/data, `3` minor, `1` unclear; `22` LIZ500_250 and `26` ROX400HD. The 2025-03-18/19 rows were mixed (`12` operator/data, `9` good), consistent with low signal/user-input quality rather than a general ladder-selection regression.

## 2026-05-19 - Compact Logging Policy

- User requested reduced logging/token load. Updated `AGENTS.md` and `ObsidianVault/01_Project_Memory.md` to keep future logs to durable decisions, output paths, and unresolved next steps only.

## 2026-05-19 - Fedora Transfer Bundle

- Built HemaFrag Linux offline bundle in Docker with Rust built inside the Linux container; added Docker context hygiene and Linux Rust toolchain setup so macOS binaries are not reused.
- Transfer folder on T7: `/Volumes/T7 Shield/HemaFrag_Fedora_Transfer_2026-05-19/`.
- Outputs: `HemaFrag_Linux_offline.zip`, `HemaFrag_Source_2026-05-19.zip`, and `README_Fedora.txt`.

## 2026-05-19 - FLT3 Full Night Review Panels

- Built separate full-night FLT3 annotation panels: `local_triage/overnight_t7_2026-05-18_full_night/flt3_review_only_html/review_panel.html` and `local_triage/overnight_t7_2026-05-18_full_night/flt3_fail_only_html/review_panel.html`.
- Counts from full-night FLT3 QC: `PASS=7114`, `REVIEW=291`, `FAIL=137`; both panels rendered all images and passed embedded JSON/export button smoke checks.
- User annotated all `291` review rows. Durable takeaway: most remaining review is real `wrong_35_50` or minor baseline-35 placement, while some rows are visually `good`/operator and need narrower proposal-noise suppression rather than broad auto-apply.

## 2026-05-19 - FLT3 Supported Start-Pair Probe

- Built a 100-row `supported_start_pair_probe_v1` overlay panel to test a peak-support scorer for the remaining 35/50 issue.
- Probe compares current anchors against a proposed supported 35/50 pair chosen by real peak height/prominence plus local fit, not residual alone.
- Output: `local_triage/overnight_t7_2026-05-18_full_night/flt3_supported_start_pair_probe_v1_html/review_panel.html`.
- Next step: user annotation should decide whether this becomes a guarded pipeline proposal mode.
- Full 291-row feature pass found a stricter v2 rule (`d50 >= 15`, proposal linear max `<=4.8 bp`, mean `<=2.2 bp`) that matched `204/223` user-labeled `wrong_35_50` rows and `0` good/minor/operator rows in this annotation set.
- v2 output: `local_triage/overnight_t7_2026-05-18_full_night/flt3_supported_start_pair_probe_v2_html/review_panel.html`; keep it proposal-only until visual confirmation.
- User feedback on v2: `50 bp` improved substantially, but `35 bp` was still often wrong.
- Built v3 35-specific probe: lock the v2 fixed `50 bp`, then choose a real supported `35 bp` peak near the fixed 50 (`~70-80` scans before it), avoiding the earlier overly-wide 35/50 gap. Output: `local_triage/overnight_t7_2026-05-18_full_night/flt3_supported_start_pair_probe_v3_35_near50_html/review_panel.html`.

## 2026-05-20 - FLT3 Supported 35 Near Fixed 50 Promoted

- Promoted visually confirmed `supported_35_near_fixed50_probe_v3` into the GS500ROX start-prior pipeline as a guarded auto-apply mode that can clear start-family review when peak support, current-gap family, proposed `35->50` gap, and fit bands match.
- Verification: `python3 -m pytest tests/test_flt3_gs500rox_start_family_review.py tests/test_gs500rox_guardrail.py tests/test_flt3_size_standard_contract.py tests/test_ladder_review_gate.py tests/test_flt3_rox500_runner_filters.py -q` passed (`43` tests); py_compile passed for FLT3 pipeline and runner scripts.
- 2000-file 3730/DATA4 smoke output: `local_triage/flt3_rox500_supported35_near50_2000_2025_2026_2026-05-20_070059`; result `PASS=1997`, `REVIEW=3`, `FAIL=0`; review panel at `review_html/review_panel.html`.

## 2026-05-20 - FLT3 Final GS500ROX Start Cleanup

- Promoted two narrow fixes for the last annotated review rows: `late_first_35_right_shift` for baseline/shoulder `35 bp` rows, and `right_shifted_35_50_75_review` for the narrow curved case where `35/50/75` all shift right.
- Verification: focused FLT3 pytest set passed (`45` tests) and py_compile passed for FLT3 pipeline/runner scripts.
- 2000-file 3730/DATA4 smoke output: `local_triage/flt3_rox500_final_startfix_2000_2025_2026_2026-05-20_080133`; result `PASS=2000`, `REVIEW=0`, `FAIL=0`.

## 2026-05-25 - Overnight T7 FLT3 Then Clonality Started

- Started detached `caffeinate` supervisor: `local_triage/overnight_t7_2026-05-25_full_night/scripts/run_flt3_then_clonality.sh`; PID recorded in `local_triage/overnight_t7_2026-05-25_full_night/overnight.pid`.
- Order: full FLT3 ROX500 3730 first (`2024/2025/2026`, exclude `LIZ,Leukostrat`, workers `6`), then clonality backfill for `2026`, `2025_data`, `2024_DATA` into `Clonality_Tracking_All_T7.xlsx` with per-year state files and retry wrapper.
- Logs/output root: `local_triage/overnight_t7_2026-05-25_full_night/`; half-hour heartbeat monitor created for this thread.
- Runtime intervention: 2025_data stalled in `2025_10_08_TCRb_IgK_Kde_tmt_H9C0VCFS_2025-10-08_0219`; added exact skip files `25OUM15319_TCRgB_08102025_A07_H9C0VCFS.fsa` and `25OUM15320_TCRgA_08102025_B05_H9C0VCFS.fsa`, then supervisor resumed attempt 3 from state.
- User requested stop on 2026-05-26; terminated the screen/caffeinate supervisor and active 2024_DATA clonality worker, deleted the heartbeat monitor, and preserved state at `local_triage/overnight_t7_2026-05-25_full_night/states/clonality_2024_DATA_state.json` (`85` done, `1` failed, `1` running, `142` pending at stop).

## 2026-05-26 - FLT3 40-Row Review Cleanup

- Learned from the re-annotated 40-row FLT3 panel that `reverse_pair_*` proposals were still review noise when non-applied; they now stay metadata/proposal evidence and no longer force REVIEW.
- Focused 40-row control after exclusions/good overrides and reverse-pair suppression: `SKIPPED=2`, `PASS=18`, `REVIEW=19`, `FAIL=1`.
- New residual panel for the true remaining 20 rows: `local_triage/flt3_after_reversepair_suppression_2026-05-26/review_html/review_panel.html`.
- Follow-up 20-row annotation added one exact minor-review override for `26OUM06102_D835__200426_A05_H9H1DIAK.fsa` and one exact good override for `26OUM05975_NPM1_B04_H9H1DIB3.fsa`; focused control is now `PASS=19`, `REVIEW=19`, `FAIL=0`, with panel at `local_triage/flt3_after_user20_review_overrides_2026-05-26/review_html/review_panel.html`.
- The 19-row follow-up labels are current-ladder labels, not proposal validation. Built a 17-row current-vs-proposal overlay for rows with start-prior proposals at `local_triage/flt3_after_user20_review_overrides_2026-05-26/proposal_overlay_html/review_panel.html`; two rows have no usable start-prior proposal yet.
- Proposal-overlay annotation promoted only confirmed `proposal_correct` start fixes: focused 19-row control is now `PASS=3`, `REVIEW=16`, `FAIL=0`. New residual panel: `local_triage/flt3_after_overlay_learning_2026-05-26/review_html/review_panel.html`.

## 2026-05-26 - Clonality Output Cleanup

- Implemented normal clonality output contract: aggregated batch writes patient/control/PK tracking into local `reports_<date>/Clonality_Tracking.xlsx`, updates global `/Volumes/T7 Shield/HemaFrag_Clonality_All_Runs.xlsx`, and no longer creates `HemaFrag_QC_Trends.xlsx` or empty `ASSAY_REPORTS` in aggregate collect mode.
- Cleaned `/Volumes/T7 Shield/22_05`: merged local run/global-ready workbook has `Runs=154`, `Patient_Runs=97`, `Control_Runs=57`, `PK_Peaks=82`; obsolete root Excel files were moved/backed up under `/Volumes/T7 Shield/HemaFrag_Output_Backups/22_05_cleanup_20260526_154841/`.
- Verification: `python3 -m pytest tests -q` passed (`52` tests).

## 2026-05-26 - FLT3 Output Cleanup

- Implemented FLT3 max-two-workbook contract: normal pipeline writes local `FLT3_Tracking.xlsx` plus global `/Volumes/T7 Shield/HemaFrag_FLT3_All_Runs.xlsx`; ROX500 QC validation keeps one local `FLT3_ROX500_QC_All_Injections.xlsx` and appends all-injections QC sheets to the same global workbook.
- Cleaned old T7 FLT3 test output: converted `/Volumes/T7 Shield/flt3_test/HemaFrag_FLT3_LIZ500_2026-05-06/FLT3_NPM1_QC_TRACKER.xlsx` to `FLT3_Tracking.xlsx`, moved the old tracker to `/Volumes/T7 Shield/HemaFrag_Output_Backups/flt3_cleanup_20260526_162114/`, and removed one empty `plotly_figures/figures` directory.
- Verification: `python3 -m pytest tests -q` passed (`55` tests).

## 2026-05-26 - Smart Latest Run-Date Input Filter

- Added `Latest run date` input scope for clonality/FLT3 batch: broad parent-folder scans now select only direct run folders with the newest parsed `YYYY_MM_DD`/`YYYY-MM-DD` date before patient/QC grouping.
- GUI Run/Batch tab exposes `Input scope` (`Latest run date` or `All folders`), defaults clonality/FLT3 to latest, and reports the selected date/folder count or warning fallback.
- Verification: `python3 -m py_compile core/batch.py gui_qt/tabs/tab_batch.py config.py tests/test_batch_latest_run_filter.py` and `python3 -m pytest tests -q` passed (`58` tests).

## 2026-05-26 - Release Builds After Output Cleanup

- Built Linux offline bundle with Docker: `dist/HemaFrag_Linux` and `dist/releases/HemaFrag_Linux_offline.zip`.
- Built native macOS app with existing macOS 3.10 venv: `dist/HemaFrag.app` and `dist/releases/HemaFrag_macOS.zip`.
- Verification before build: `python3 -m pytest tests -q` passed (`58` tests).

## 2026-05-27 - FLT3 Legacy Excel Ratio Extract

- Extracted calculated ITD/D835 ratio rows from `/Volumes/T7 Shield/flt3_excel`: `127` workbooks read, `38` ratio rows, `13` unique DIT numbers, no read errors.
- Output files: `outputs/flt3_excel_ratio_extract_2026-05-27/flt3_dit_itd_d835_summary.csv`, `flt3_positive_ratio_parallel_details.csv`, and `flt3_dit_itd_d835_summary.md`.
- Interpretation used: a DIT is positive for an assay when a numeric calculated ITD-ratio or D835/TKD-ratio row exists in the corresponding calculation sheet; the counterpart assay is marked negative when no calculated ratio row exists for that DIT.
- Follow-up full-status extract includes all DITs found in `FLT3` sheets: `276` unique DITs, `263` both-negative, `11` ITD-positive, `7` D835-positive, `5` both-positive. Output: `outputs/flt3_excel_ratio_extract_2026-05-27/flt3_all_dit_itd_d835_status_summary.csv`.
- Compared four same-day manually edited HemaFrag HTML reports from Downloads against legacy Excel ratios; output: `outputs/flt3_report_manual_ratio_compare_2026-05-27/hemafrag_report_vs_legacy_ratio_comparison.csv`.

## 2026-05-27 - FLT3 Area Method Report Panel

- Generated normal FLT3 DIT HTML reports for `13/13` requested DITs across seven area methods; output root: `/Volumes/T7 Shield/HemaFrag_FLT3_Arealmetode_Rapporter_2026-05-27/`.
- Methods include current HemaFrag percentile-sum, linear-baseline trapezoid, arPLS-sum, and Fraggler-like raw/Gaussian/Voigt/Lorentzian variants; verified `91` real patient HTML reports (`7 x 13`, excluding macOS `._` sidefiles).
- Companion files: `selected_fsa_manifest.csv`, `area_method_run_summary.csv`, and local builder script `outputs/flt3_area_method_reports_2026-05-27/build_area_method_reports.py`.
- Compared user's manual review of methods 1-4 against legacy Excel ratios; output: `outputs/flt3_area_manual_review_compare_2026-05-27/`. Current HemaFrag percentile-sum is marginally best on the small common scored set, with baseline-trapezoid/arPLS effectively tied and Fraggler raw padded slightly worse.
- Re-ran comparison with Downloads copy including methods 5-7. Apparent Voigt/Lorentzian win is sample-selection bias (`8` scored rows only); on the common `8` rows across all seven methods, methods 1/2/3/5/6/7 tie and raw padded remains slightly worse. No evidence yet that model-amplitude methods improve ratio agreement.

## 2026-05-28 - Preparing for Windows Transfer

- Prepared a clean project and Desktop backup to transfer the codebase and related resources to a Windows PC via T7 Shield USB drive.
- Excluded bulky Mac-specific directories to optimize transfer size and speed (~1-2 GB total instead of 14+ GB):
  - `HemaFrag/fraggler-v2/target/` (Mac Rust build artifacts)
  - `HemaFrag/dist/` and `HemaFrag/build/` (Mac compiled Python/Qt executable files)
  - `HemaFrag/local_triage/` and `HemaFrag/artifacts/` (temporary test runs and AI logs)
- Packed files: `HemaFrag/` (with source, tests, configs, Rust engine source, `.git` repository), `Fraggler/` (legacy), `Excel_Fraggler/`, `Rapport_HemaFrag/`, and Desktop Excel sheets (`Klonaltitet_2024.xlsx`, `Klonaltitet_2024_2025.xlsx`).
- Target output archive: `/Volumes/T7 Shield/HemaFrag_Windows_Overforing.zip`.

## 2026-05-28 - Windows App Bundle To T7

- Built Windows x64 bundle with Docker/Wine/PyInstaller after updating `packaging/Dockerfile.windows` to cross-compile and include `fraggler-cli.exe`.
- Output copied to `/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows.zip`; Windows setup guide at `/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows_PC_Guide.md`.
- Verification: `python3 -m zipfile -t` passed on the copied T7 zip; SHA256 `0c0e3e35105520fc7a3dfdffe37afa3780addf03e9fdb7554e13cdd71804bb6d`.

## 2026-05-28 - Windows Stdout/Stderr Hotfix

- Fixed Windows `--windowed` startup/runtime crash: `sys.stdout`/`sys.stderr` can be `None`, causing legacy `sys.stdout.isatty()` to fail.
- Rebuilt and replaced `/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows.zip`; updated guide notes the `isatty` fix.
- Verification: py_compile and simulated `sys.stdout=None` imports passed; copied T7 zip passed `python3 -m zipfile -t`; SHA256 `db2a60ad51845d7fc226cb87afa7789da61e28bd0101ecbf79844ff3bd086305`.

## 2026-05-28 - Windows Rust CLI Resolver Hotfix

- Fixed Windows frozen runtime lookup for the bundled Rust engine: `core/rust_bridge.py` now searches for `fraggler-cli.exe` in `_MEIPASS`, beside `HemaFrag.exe`, and in `_internal`.
- Rebuilt and replaced `/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows.zip`; updated the Windows guide with the `fraggler-cli` fix note.
- Verification: py_compile and simulated frozen Windows CLI resolution passed; local and copied T7 zips passed `python3 -m zipfile -t`; SHA256 `63ea871417d74f8a7adae48ff239f230595a453534d9e260834df2120094a980`.

## 2026-05-28 - Windows Rust Workerpool Hotfix

- Disabled persistent Rust worker/prewarm on Windows packaged runtime to avoid `WinError 10038` from `select()` on subprocess pipes; one-shot Rust CLI calls still run and are hidden with Windows no-console subprocess flags.
- Built local replacement zip at `dist/releases/HemaFrag_Windows.zip`; T7 Shield was not mounted at copy time, so external copy is still pending.
- Verification: py_compile, simulated frozen Windows worker/prewarm behavior, and local zip integrity passed; SHA256 `a06947091753527eebeab9f678541071c3b57695c26446b8151b6c98acbf2d94`.

## 2026-05-28 - Windows Release Runbook

- User confirmed the Windows workerpool hotfix package worked.
- Added repeatable notes for future Windows builds at `packaging/WINDOWS_RELEASE_RUNBOOK.md`, including Rust CLI bundling, stdout/stderr, disabled Windows prewarm, and T7 copy steps.

## 2026-05-28 - Clonality 2024 Backfill Hang Guardrail

- Investigated repeated 2024 clonality overnight stalls: logs showed Rust prewarm failures followed by Python fallback hangs on individual historical `.fsa` files.
- Added source/runtime per-file clonality timeout (`analyses.clonality.pipeline.file_timeout_seconds`, default `240s`) that terminates and skips a hung file instead of blocking the folder/year; expanded known skip list with the prior 2024 blocker files.
- Verification: py_compile passed; focused tests passed (`tests/test_clonality_file_timeout.py`, `tests/test_batch_latest_run_filter.py`, `tests/test_water_filter.py`).

## 2026-05-28 - T7 Full Night Run Started

- Started detached screen `hemafrag_overnight_20260528` with output root `/Volumes/T7 Shield/HemaFrag/NightRuns/overnight_all_2026-05-28_214248`; run order is FLT3 ROX500 3730 first, then clonality `2026`, `2025_data`, `2024_DATA`.
- Clonality run exports `HEMAFRAG_CLONALITY_FILE_TIMEOUT_SECONDS=240` and `FRAGGLER_DISABLE_MULTIPROCESSING=1`; tracking workbook target is `/Volumes/T7 Shield/HemaFrag/NightRuns/overnight_all_2026-05-28_214248/clonality/Clonality_Tracking_All_T7.xlsx`.
- Created 30-minute heartbeat automation `hemafrag-nattkj-ring-monitor` to check process/log health in this thread.

## 2026-05-29 - Windows Source Transfer And Git Push

- Added a repeatable clean source-transfer packer at `scripts/package_for_windows.py` and Windows transfer note at `packaging/WINDOWS_TRANSFER_README.md`.
- Target archive for Windows transfer: `/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows_Transfer.zip`; latest source changes are pushed to GitHub from the Mac.
