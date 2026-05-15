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
