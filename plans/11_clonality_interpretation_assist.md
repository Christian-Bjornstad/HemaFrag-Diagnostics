# Plan 11 — Clonality Interpretation Assist

> **Branch:** TBD (will be `codex-clonality-interp-v1-2026-06-XX` once we start).
> **Lead reviewer:** Christian + Hermes.
> **Why this exists:** clonality interpretation today is rule-based (`clonality_interpretation_rules_v1`) and uses ~12 hand-picked features. With ~22 000 historical `.fsa` files already labelled by clinical scientists, this is the dataset where an ML-assisted second opinion starts to pay off — but only if it stays research-only until validated per assay.

---

## Goal

Turn the existing **research-only** clonality interpretation into a **production-grade assistant** that:

1. **Reads the patient's full assay panel** (FR1/FR2/FR3, DHJH_D, DHJH_E, IGK, KDE, TCRB-A/B/C, TCRG-A/B, SL, IKZF1) in **one batch run** rather than per-file.
2. Predicts, per sample, the **most likely biological interpretation** (`polyklonal`, `monoklonal`, `bi_oligoklonal`, `irregulaer`, `pseudoklonal`, `intet_pcr_produkt_darlig_dna`, `qc_teknisk_fail`, `usikker_review`) with:
   - **Confidence score** calibrated per assay (because FR1 vs TCRG behave very differently).
   - **Evidence narrative** citing the rule(s), the dominant peak position relative to assay reference range, and any control flags (`kontroll_ok`, `kontroll_avvik`, `kontaminasjon_mistenkt`, `svakt_signal`).
3. **Always defers to the rule-based output** when both agree, surfaces disagreement when they don't, and only auto-applies the ML model when its calibration is at or above the **per-assay accept threshold**.
4. **Never silently overrules** a path-review flag, a `nonspecific_peak` exclusion evidence, a `uspesifikke_topper` warning, or any `ladder_qc_status != "ok"` row — when those are present, the row is **always** routed to `usikker_review`.
5. **`ObsidianVault`-persistent**: every tool run, model update, and major decision lands in `ObsidianVault/Clonality_ML_Log/` so the clinical narrative stays traceable.

## Why the goal is the right shape

- **Per-assay calibration** matters because FR1/FR2/FR3 have 2-3 reference bp regions + a wide noise floor; TCRG-A/B peak-height distribution is bimodal; IGK + KDE multiplex requires special handling. A single global model would mask rare-class mistakes in TCRG.
- **ml-assisted ≠ ml-decides**. The rule model (`interpretation.py` ANNOTATION_CLASSES) is the source of truth until the ML model is **empirically** proven strictly better on the rare-class F1 score, per assay.
- **Models stay opt-in, off by default**. Match the already-defined `interpretation.enabled` flag in `config.py:130`. The first shipped milestone enables ML for FR1 only, then a single TCRG tube, then expands.

---

## Recipes (ordered steps — execute one phase per PR)

### Phase 0 — Audit existing scaffolding (no code)

Already laid out in this repo:
- `core/analyses/clonality/interpretation.py` (835 lines, rules engine, schemas, `MODEL_VERSION = "clonality_interpretation_quick_model_v1"`).
- `core/analyses/clonality/feature_artifacts.py` (456 lines, per-entry feature builder).
- `core/analyses/clonality/candidate_artifacts.py` (365 lines, candidate peak handling).
- `core/analyses/clonality/ladder_review_gate.py` (165 lines, gate that QC-disables ML.
- `core/analyses/clonality/tracking_excel.py` (691 lines, Excel output).
- `scripts/train_clonality_interpretation_quick_model.py` (scikit-learn baseline).
- `scripts/render_clonality_interpretation_annotation_html.py` (panel-generation HTML for human review).
- `tests/test_clonality_interpretation_v1.py` (41 unit tests, the rule engine).

The first task is **documenting an asset map**: list every feature, every rule path, and where the ML model would slot in.

### Phase 1 — Surface the existing rule model in the GUI (off by default)

The GUI today doesn't expose "Clonality Interpretation" because the engine is off. Two requirements:

- `qt_app.py:tab_flt3_validation`-style badge logic lifted to a `tab_clonality_interpretation.py`:
  - Reads the batch's `Clonality_Tracking.xlsx` (already produced by `tracking_excel.py`).
  - For each entry, shows rule suggestion + (when enabled) ML suggestion side-by-side.
  - "Always defer" gate: when ML says `monoklonal` and rule says `polyklonal`, route to `usikker_review` with red flag.
- `ObsidianVault/Clonality_ML_Log/2026-06-XX_first_run.md` notes: which samples disagreed, which were rule-Wrong-but-ML-right.

### Phase 2 — Feature engineering: bring EVERY channel's data into the model

Current feature list (from `train_clonality_interpretation_quick_model.py:NUMERIC_FEATURES`) is single-sample-row only. **The 22k files** include multi-`DATAx` traces per FSA — that's the strong signal we currently throw out.

New feature groups to engineer:
1. **Per-channel raw-trace shape**: peak count, peak variance, normalized median absolute deviation. Decisive for `intet_pcr_produkt_darlig_dna` vs `qc_teknisk_fail`.
2. **Reference-window position distribution**: per assay, where dominant peak sits vs `ASSAY_REFERENCE_RANGES` (already in `config.py`). Kills any model that ignores target bp window.
3. **Per-patient replicate concordance**: when a patient has 3+ assays (IKZF1 + FR1 + IGK + KDE + TCRG), a model already trained on the (assay_name, slope, replicate) reflects immune system biology better than a single FSA.
4. **Ladder QC interactions**: combine `ladder_r2` with `ladder_late_first_anchor` (flaged here, not at the QC gate) so the model knows whether to trust a "monoklonal" call made under a sub-0.998 ladder R².

### Phase 3 — Train per-assay models (not one global model)

Why per-assay:
- **Class imbalance varies by assay**. TCRG has a heavy `polyklonal` skew (>70% of files); IKZF1 has a near 50/50 split.
- **Rare-class F1 is the metric that matters**, not accuracy. Per-assay we'd compute confusion matrices on each assay's holdout fold and flag per-assay acceptance.
- **Calibrated outputs can be inspected independently** by the chemist: "this ML model is good enough for FR1, NOT for KDE yet".

Pipeline:
1. Stratified split by `DIT` (so the same patient is never in both train and test).
2. For each assay with N≥200 files, train **RandomForest** (interpretable) + **XGBoost** (fit quality reference) + **calibrated QDA** (probabilistic baseline).
3. Pick the one whose rare-class F1 bests the rule engine by ≥3 points absolute on `OOF` (out-of-fold).
4. Serialize as `joblib`. Persist per-assay under `ObsidianVault/Clonality_ML_Log/models/<date>/<assay>/`.

### Phase 4 — Calibration + per-assay accept threshold

The model outputs a probability distribution over ANNOTATION_CLASSES. Calibration converts that to a clinically interpretable confidence via Platt scaling on a held-out fold.

Per-assay accept threshold rule:
```
accept if   ml_pred_argmax in {polyklonal, monoklonal, bi_oligoklonal}
       AND ml_pred_prob >= per_assay_accept_threshold[assay]
       AND no  usikker_review forcing-rule present:
            - ladder_qc_status != "ok"
            - control_flag in {kontroll_avvik, kontaminasjon_mistenkt}
            - any_assay says intet_pcr_produkt_darlig_dna or qc_teknisk_fail
otherwise: route to usikker_review (ML suggestion displayed, rule still authoritative).
```

Default accept thresholds (calibrated after Phase 3):
- `FR1/FR2/FR3`: τ = 0.85 (high; these are the most-impacted-by-noise assays).
- `TCRG-A/B`, `TCRB-A/B/C`: τ = 0.75 (high mono signal-to-noise typically).
- `DHJH_D/E`, `IGK`, `KDE`: τ = 0.92 (multiplex can confuse models).
- `SL`, `IKZF1`: τ = 0.95 (qualitative not clonality-driven).

These are defaults; chemists can override per assay via `config.py` `analyses.clonality.interpretation.thresholds`.

### Phase 5 — Model update cadence + traceability

The training script is current `scripts/train_clonality_interpretation_quick_model.py`. It needs to grow into:

- **`scripts/train_clonality_interpretation_models.py`** — full pipeline: load 22k-labelled FSA catalog → group-by-(patient, assay) → stratified split → per-assay fit → per-model metrics → save joblib + metadata JSON → emit a markdown report under `ObsidianVault/Clonality_ML_Log/<date>/report.md`.
- **`Makefile`-style targets** (or PowerShell-equivalent scripts) so retraining is one command.
- **`ObsidianVault/Clonality_ML_Log/_CHANGELOG.md`** — every model version, its accept threshold, per-assay recall/precision/F1, what the chemist should look at next.

### Phase 6 — Production wiring (off-by-default)

Wire `core/analyses/clonality/interpretation.py` so that the ML suggestion, if present + calibrated + accepted per Phase 4 thresholds, is written to the tracking export columns (`ClonalitySuggestion`, `ClonalityConfidence`, `ClonalityReviewNeeded`, `ClonalityEvidence`, `ClonalityModelVersion`). Gate is `interpretation.enabled`.

Critical: **trackers and DIT reports stay byte-identical in default mode**. Only when the chemist explicitly enables ML do they see an extra column.

### Phase 7 — Continuous improvement loop

Two feedback channels from product/UI back into training data:
1. **In-app disagreement logs** — when chemist marks a recorded `ml_suggestion != rule_suggestion` row as "rule correct, ML wrong", a JSON line is appended under `ObsidianVault/Clonality_ML_Log/feedback/<date>.jsonl`. Each line links back to the DIT/assay/sample.
2. **Re-annotation campaign** — every quarter, take a stratified sample of 200 disagreements and re-annotate. New training data.

This loop produces a model that improves unequally fast across assays. The Obsidian notes must record this per-assay trajectory.

---

## Concrete task list

> **Format:** each task has `scope` (one file or folder), `do`, `verify`, `done_when`. Tasks within a phase are ordered; phases ship independently.

### Phase 0 — audit
- **T-0.1** — `core/analyses/clonality/audit.md` (new): list every public function and feature touched by the interpretation pipeline so the next patch knows what to diff. Verify by reading the audit; `done_when` the file explains every rule path.

### Phase 1 — GUI hook (off by default)
- **T-1.1** — `gui_qt/tabs/tab_clonality_interpretation.py` (new): per-entry comparison widget with red/yellow/green coding. Verify by import-test (`from gui_qt.tabs.tab_clonality_interpretation import render_panel`). `done_when` a synthetic batch is rendered with at least one row.
- **T-1.2** — `gui_qt/main_window.py`: register the new tab in the QTabWidget. Verify by `MainWindow().tabWidget().count() > 0`. `done_when` tab counts goes up by one.
- **T-1.3** — `config.py`: add `analyses.clonality.interpretation.thresholds` block with the per-assay default τ table from Phase 4 (placeholder values for now). Verify by `from config import APP_SETTINGS; APP_SETTINGS["analyses"]["clonality"]["interpretation"]["thresholds"]["FR1"] == 0.85`. `done_when` key round-trips.
- **T-1.4** — `ObsidianVault/Clonality_ML_Log/2026-06-XX_first_run.md` (new) — handwritten notes from the first live test.

### Phase 2 — features
- **T-2.1** — `core/analyses/clonality/feature_artifacts.py`: add per-channel raw-trace stats. Verify with re-running the existing `tests/test_clonality_interpretation_v1.py::test_features_from_entry_*` cases; they must still pass. `done_when` all 41 tests green.
- **T-2.2** — `core/analyses/clonality/feature_artifacts.py`: add reference-window position features per assay. Done when the feature artifact writes include `dom_distance_to_ref_window_center_bp`, `ref_window_coverage_fraction`.
- **T-2.3** — `core/analyses/clonality/feature_artifacts.py`: per-patient replicate concordance. Done when the feature artifact writes include `patient_assays_run_count`, `assay_panel_completeness_pct`.

### Phase 3 — per-assay training
- **T-3.1** — `scripts/train_clonality_interpretation_models.py` (new): entry-point that runs Phase 3 for all qualifying assays. Verify with `--assay FR1 --dry-run` prints the dataset path counts. `done_when` dry-run succeeds.
- **T-3.2** — `core/analyses/clonality/ml_training.py` (new): internal module shared by train + inference; pure functions: `load_dataset_for_assay`, `GroupShuffleSplit_by_patient`, `per_assay_metrics`. Verify with `python -c "from core.analyses.clonality import ml_training; ml_training.per_assay_metrics_fake_run()"`: `done_when` returns a dict with the 4 metric keys.
- **T-3.3** — `tests/test_clonality_interpretation_ml.py` (new): per-assay fixture + assert load/split/metric logic on a 50-row synthetic frame. `done_when` ≥6 cases pass.

### Phase 4 — calibration + thresholds
- **T-4.1** — `core/analyses/clonality/calibration.py` (new): Platt scaling per assay + `predict_with_rejection` function. Verify with a fixture producing calibrated probs. `done_when` `predict_with_rejection` returns `(label, conf, accepted_bool)` and refuses to accept when `conf < τ`.
- **T-4.2** — `core/analyses/clonality/interpretation.py`: extend `interpret_entry` to consult the ML suggestion when `interpretation.enabled && ml_model_loaded_for_assay & per_assay_threshold_ok`. Done when a unit test in `tests/test_clonality_interpretation_v1.py` proves rule + ML agreement and rule + ML disagreement pathways both surface in the returned dict.

### Phase 5 — cadence + traceability
- **T-5.1** — `ObsidianVault/Clonality_ML_Log/_CHANGELOG.md` (new): template for per-model-version entries (date, model hash, per-assay F1, accept thresholds, known limitations). `done_when` the first entry references a model produced by T-3.1.
- **T-5.2** — `scripts/render_clonality_interpretation_drift_report.py` (new): reads the JSON feedback logs and emits a `ObsidianVault/Clonality_ML_Log/drift_<date>.md`. Done when the script runs against a synthetic 100-line JSONL fixture and produces the markdown.

### Phase 6 — production wiring
- **T-6.1** — `core/analyses/clonality/tracking_excel.py`: write `ClonalityMLSuggestion`, `ClonalityMLConfidence`, `ClonalityMLReviewNeeded`, `ClonalityMLModelVersion` columns alongside the existing rule ones. Done when a unit test asserts column presence to env-disabled and env-enabled.
- **T-6.2** — `core/analyses/clonality/tracking_excel.py`: keep the existing export columns unchanged when `interpretation.enabled == False`. Done when the unit test asserts byte-identical output before/after the patch.

### Phase 7 — feedback loop
- **T-7.1** — `gui_qt/tabs/tab_clonality_interpretation.py`: when chemist marks a row "rule correct, ML wrong" or vice versa, append a JSONL line. Done when clicking the button drops a line at `ObsidianVault/Clonality_ML_Log/feedback/<date>.jsonl`.
- **T-7.2** — `scripts/train_clonality_interpretation_models.py T-3.1`: read feedback logs, weight recent examples higher. Done when the script logs sample counts with and without the feedback flag.

---

## Stack / libraries (do NOT introduce any new dep without a phase-2 PR)

| Task                  | Tool                                      |
|-----------------------|-------------------------------------------|
| tabular data          | pandas, numpy (already in requirements) |
| training              | scikit-learn (RandomForest, QDA, CalibratedClassifierCV)  + xgboost ONLY IF simple RF < rule engine |
| model persistence     | joblib (already in pytest extras)          |
| calibration           | scikit-learn PlattScaling                 |
| clinician feedback UI | existing PyQt6 tab widget + JSONL flask  |
| model serving         | in-process (`model.predict_proba` in core) — no separate service |
| docs                  | ObsidianVault/Clonality_ML_Log/  (markdown) |
| reference docs        | `core/analyses/clonality/` docstrings — public functions must grow to read top-down |

If a phase needs MORE than what's listed, file a small note under `ObsidianVault/Clonality_ML_Log/decisions/` BEFORE writing code. The chemistry of the assay shouldn't be shoved into a tool that is hard to swap if the chemist rotates off the project.

If a phase needs internet-accessed data (public clonality paper reviews, NIH guidance pages, etc.) it goes via a one-shot `scripts/fetch_<source>.py` that writes into `ObsidianVault/Clonality_ML_Log/internet_cite_<date>.md` so we have a citation log.

---

## Agent use plan (3 layers)

Three layers of "AI" are available to the chemist:

### Layer 1 — in-Python interpretation copilot (always-on)
Already in `core/analyses/clonality/interpretation.py`. Rule-based. Output to DIT report. Doesn't disagree with the chemist; consent is by report sign-off.

### Layer 2 — ML second-opinion (opt-in)
After Phase 3/4 ships, this is the assistant the user is asking for. Per-assay calibrated probabilities. Surface area:
- `ObsidianVault/Clonality_ML_Log/<date>/report.md` — single-file markdown explaining what the ML flagged and why.
- In-app diff counter (Phase 1 widget): "rule said `polyklonal`, ML says `monoklonal` (conf=0.81) → recommend review".

### Layer 3 — research-only model + agent (gated tools)
When interpretation gets stuck (`usikker_review`, or reagent-batch-level disagreement), this layer is allowed to:
- Run web search for nearby public-domain literature on the assay + mutation class.
- Optionally spawn a sub-agent with a sandboxed calculator tool to recompute a likelihood ratio on a stylized model.
- Emit a `ObsidianVault/Clonality_ML_Log/<date>/disagreement_<dit>.md` with three buckets: rule, ML, and human-rationale, all attested date-stamped.

The agent must **NEVER** write to `core/` or `data/` from this layer; it only writes to `ObsidianVault/Clonality_ML_Log/`. The chemist owns what enters the codebase.

Hallucination guard: every agent output gets re-bound to a `DIT + assay + reagent lot` triple. Anything that doesn't end in `ObsidianVault/...` is rerun through the rule engine before being trusted.

---

## Internet use plan

Two reasons internet access is used:
1. **Anchor validation** — when the rule engine produces `usikker_review` and the model output is also unsure, fetch one or two authoritative pages (e.g., EuroClonality / BIOMED-2 / WHO references — concrete URLs to add to `Internet_Citation_List.md`) to triangulate. Pulls text into `ObsidianVault/Clonality_ML_Log/internet_cite_<date>.md` with date stamp.
2. **Model registry scouting** — when a new model class (gradient boosting, transformer-on-traces, etc.) is being considered, fetch a couple of abstracts from arXiv and a public IG/TR clonality paper. No code change without explicit chemist approval.

DO NOT directly hit patient-data servers. All training data is already on the local disk under `/Volumes/T7 Shield/DATA/clonality` (per `config.py`).

---

## Verification gate per phase

A phase is "done" only when:
1. All unit tests in `tests/test_clonality_interpretation_*.py` pass on a fresh checkout after `git pull`.
2. Logic-gating that turns the feature on/off via `analyses.clonality.interpretation.enabled=False|True` is unit-tested both ways.
3. A markdown note is added under `ObsidianVault/Clonality_ML_Log/<date>/` describing what changed and what the chemist must check next.
4. A1 / A2 / A3 from the `ObsidianVault/01_Project_Memory.md` "Hygiene" rules still hold (no autoship, no `artifacts/`, no raw data).
5. The chemist has signed off on the specific assay's first shipped model.

Phases don't shrink DIT report text or tracking exports. Only add new columns / new markdown files. Backwards-compat is mandatory.

---

## Open questions (chemistry side; not blocking code work)

1. **Per-assay τ thresholds** — the numbers above are educated guesses. The chemist owns the calibration and adjustment.
2. **"qc_teknisk_fail" classification boundary** — at what fraction of the input-DNA control flagged "weak signal" do we route to QC vs review?
3. **Pseudoklonal vs monoklonal boundary** — when rule and ML disagree is it practice-specific or assay-specific?
4. **Newly-onboarded assay** (e.g. TCE-allele) coming up — should the ML model be onboarded in parallel or wait until 200+ files exist?

These are tracked in `ObsidianVault/Clonality_ML_Log/open_questions.md` so they don't get lost in code reviews.

---

## Roles + cadence summary

| Role                                    | cadence                           |
|-----------------------------------------|-----------------------------------|
| Christian (lead)                        | weekly 30 min sync; ad-hoc per phase |
| Hermes (agent pair on phase tasks)      | per-task; commits tagged `clonality-interp` |
| Two clinical-chemistry reviewers (TBD)  | once at first shipped model per assay; then quarterly drift reviews |

No on-call for the ML lane. The rule engine remains operationally authoritative until the per-assay F1 is ≥3 points above the rule engine's own F1 on holdout test partitions.
