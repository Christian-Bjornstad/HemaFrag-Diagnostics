# Open Questions for Clinical Reviewer (Clonality ML)

> Capture every chemist-side question that came up while not blocking code work.

## Calibration of accept thresholds (τ)

- **FR1/FR2/FR3 @ 0.85** — is that the right amount of headroom on these assays? Quiet samples with strong polyclonal humps sometimes read ~0.78 under our QDA baseline. If the threshold is too aggressive, reviewable polyclonal cases go to `usikker_review`. If too lenient, false-mono calls accumulate.
- **TCRG-A/B @ 0.75** — TCRG is bimodal; the rare-class F1 is dominated by germline-pattern clones. Bias from the rule model is hard to predict. Run a ROC over the 22k file set, eyeball the precision-at-95%-recall operating point, then land a recommendation.
- **TCRB-A/B/C @ 0.75** — same family of question.
- **DHJH_D/E @ 0.92** — multiplexed — the threshold might need to be PAR assay (per tube) rather than DHJH_D broad.
- **IGK vs KDE @ 0.92** — depends on how much cross-tube signal we trust in `_compute_patient_panel_features`.
- **SL, IKZF1 @ 0.95** — these are *not* clonality-driven (SL is DNA-quality, IKZF1 is monitoring). Lower priority for ML. Confirm whether ML is even useful here at all, or whether the rule engine is already adequate.

## Boundary cases

- **Pseudoklonal vs monoklonal**. The rule model rarely fires "pseudoklonal"; the model might. Practice-specific or data-set-specific?
- **qc_teknisk_fail** vs **intet_pcr_produkt_darlig_dna**. Two failure classes that should never be merged silently. Where's the rule for "routing to qc_teknisk_fail wins regardless of ML probability"?
- **Control flag override**: when the assay-level `kontroll_ok=false` flag fires, MUST the row route to `usikker_review` regardless of model output? Currently proposed; needs chemist sign-off.

## Operational

- **Feedback ledger append**: should it be opt-in per row (a chemist clicks "log this disagreement") or always-on? If always-on, storage grows fast over 92-batch runs.
- **Re-training cadence**: monthly? On-add of N≥500 new labelled files? Quarterly review?
- **When does the GUI tab become the default in `qt_app.py`?** Today it's hidden behind `interpretation.enabled=False`. Chemist's call on when to flip the default.
- **DIT coverage**: do we require at least one FR1+FR2+FR3 trio per patient before ML runs? Or any-OK?

## New-assay onboarding

- **TCE-allele**: coming. Decisions: (a) wait until ≥200 labelled TCE-allele files exist before adding it to per-assay pipeline, or (b) start calibrating from seed values.
- Same for any new IgH primer set — what calibration strategy?

## Drift detection

- **What triggers a re-run?** Drift report at every batch run? Weekly offline job? Manual trigger only?
- **Acceptable F1 drift before forcing re-train**: K-of-N rolling window of -3 F1 to trigger alert?
- **Once re-trained, do we deprecate old models or keep version-locked pin?** I propose keep-version-locked for 90 days post-deprecate.
