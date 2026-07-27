# Clonality ML — Model Registry Scouting Note (2026-06-28)

> Goal: pick the model class for per-assay clonality interpretation.
>
> Constraints (carried forward from Plan 11):
> 1. **Zero new third-party deps.** scikit-learn + joblib already
>    in pytest extras (promote `joblib` to runtime at Phase 3 ship).
> 2. Interpretability is required (chemist must understand the
>    features that drove any per-row prediction).
> 3. Per-assay model (FR1 ≠ TCRG ≠ DHJH_D).
> 4. Calibration via Platt scaling on a held-out fold.
> 5. ~22k labelled files loaded from
>    `/Volumes/T7 Shield/DATA/clonality`.

## A. Scikit-learn candidates (already in stack)

### RandomForestClassifier — *baseline we ship*
- Bagging of decision trees; handles mixed numeric/categorical,
  tolerant of NaNs in features; reports feature_importances_ for
  per-row explainability.
- **Best for:** tabular binary/categorical classification with
  class imbalance; rare-class F1 on per-assay models.
- **Platt:** CalibratedClassifierCV around RandomForest gives
  per-assay probabilities matching the calibration curve.
- **Plan 11 verdict:** primary model for Phase 3.

### GradientBoostingClassifier — *alternative*
- Boosted trees (smaller ensemble, deeper trees) — usually slightly
  better than RF on tabular, but slower to train, no native
  feature_importances_ plotting.
- **Best for:** when RF plateau is reached and we want a sanity
  reference. We do not ship as primary.
- **Plan 11 verdict:** keep on bench; use only in head-to-head
  against RF for a particular assay where RF is under-calibrated.

### CalibratedQuadraticDiscriminantAnalysis — *probabilistic baseline*
- Each class has its own Gaussian; Platt-scaled output is naturally
  well-calibrated (no need for CalibratedClassifierCV).
- **Best for:** well-balanced data with multivariate normal features;
  fails when feature distribution is bimodal (which TCRG cases are
  on the dominant-vs-polyclonal axis).
- **Plan 11 verdict:** ship as a per-assay head-to-head. If its
  rare-class F1 is comparable to RF, ship it instead — output is
  more interpretable (each class a 2-D Gaussian usually).

### NB (GaussianNB / BernoulliNB)
- Very fast, very high bias for tabular classification.
- **Plan 11 verdict:** NOT used. Baselines only; expected F1 below
  RF or QDA on every assay.

## B. Optional / not-in-stack — decision: deferred

### xgboost — *trigger criterion*
- 2.x; needs install. Per `decisions/xgboost_pending.md`, only
  add if monoklonal-class F1 on FR1 OOF drops below 0.85 for the
  RandomForest baseline. Decision lives in
  `decisions/xgboost_pending.md`.

### lightgbm — same position as xgboost.
- Same trigger criterion; lighter install footprint.

## C. Tabular deep learning (survey, NOT adopted)

### TabPFN — *"Tabular Prior-Fitted Network"*
- arXiv 2207.01848, original 2022 paper; tabpfn-v2 in 2025
  (Hollmann et al.) scales to ~10k samples per inference.
- Pretrained on synthetic tabular tasks. Performs well on small
  (≤ 1k) tabular; for our per-assay models we routinely exceed
  10k.
- **Class imbalance:** out-of-box, no calibration; would need a
  Platt layer.
- **Verdict:** keep on bench, **DO NOT adopt** in production
  Phase 3. Useful as a research comparison once we have a real
  per-assay holdout to score.

### TabNet / TabTransformer / FT-Transformer
- Attention-based deep models for tabular. TabNet specifically
  interprets at the row level (selected features).
- **Verdict:** heavy dep on PyTorch + transformers. Out of the
  scope for Plan 11. Future idea: when (and only if) chemist
  specifically asks for SHAP-style explanations, revisit.

## D. Pre-trained B/T-cell clonality / rearrangement models

These are domain-specific models in the V(D)J recombination field.
We list them so the chemist knows they exist; we do NOT install any
in production Phase 3.

### ImmuneML — `immuneml/immuneml` (Milagen/UNIPD)
- An ML framework for immunology. Provides built-in B-cell receptor
  classification, including clonality classifiers (IG/TR) trained
  on repertoire datasets.
- Per-assay retraining is possible; the framework wraps sklearn
  or PyTorch backends.
- **Verdict:** possible Phase-7+ research dive; not in scope.

### NetTCR-2.0 — *CDR3 binding prediction*
- Sequence-to-binding classifier for TCR CDR3 peptide binding
  predictions. NOT a clonality classifier per se; useful in MRD
  monitoring.
- **Verdict:** out of scope for clonality interpretation.

### TITAN — *Tumor-Infiltrating clonality Atlas Toolkit*
- Repository-level TCR/BCR repertoire analytics. Works on
  repertoire-scale datasets (TCR/BCR sequencing), not per-tube
  per-bp what we assay today.
- **Verdict:** out of scope.

### ARResT/Interrogate
- BIOMED-2 NGS export interpretation. Open source; bundled with
  EuroClonality-NGS companion tools.
- **Verdict:** useful in a future NGS migration (Plan 16/17).

## E. Recommendation

**Given:**
- Zero new third-party deps (cap).
- Interpretability required (chemist signoff per row).
- Per-assay model (FR1/FR2/FR3, TCRG-A/B, TCRB-A/B/C, DHJH_D/E,
  IGK, KDE, plus SL/IKZF1 as DNA-quality/monitoring).
- ~22k labelled files.
- Calibration-via-Platt, head-to-head rare-class F1.

**Recommendation:** **RandomForest + Platt scaling per assay** as
the primary Phase-3 model. Calibrated QDA as the head-to-head
baseline. Both via scikit-learn + joblib.

We do **not** preclude calling out to a research agent with
TITAN/ImmuneML in a Future Phase-7 sandbox experiment — the
footprint is a real concern but the chemist owns the decision.

**Trigger criterion for xgboost promotion** (see `xgboost_pending.md`):
if the FR1 monoklonal-class F1 drops below 0.85 on OOF holdout
across multiple chemist-validations.

## F. Footer pointers
- Plan 11: `plans/11_clonality_interpretation_assist.md`
- Asset map: `core/analyses/clonality/audit.md`
- Deps decision: `decisions/dependencies.md`
- xgboost pending: `decisions/xgboost_pending.md`
- Citation survey: `internet_cite/2026-06-28_pubmed_anchor_survey.md`
- This file generated 2026-06-28 by main-session after async
  delegation failed to file. Re-anchor as needed.
