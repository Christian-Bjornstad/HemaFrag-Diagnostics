# Avvikling av ML og labeling — Implementation Plan

**Status 2026-09-22:** M01–M06 er implementert. M07s dokumentasjon,
dependency-audit og importvern er gjennomført; orkestratorens fulle sluttgate
gjenstår før planen markeres komplett.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fjern hele ML-/trenings-/labeling-funksjonaliteten uten å svekke aktiv analyse eller slette brukerdata.

**Architecture:** Fjern først produktkallere, deretter frikoble tracking fra forskningskontrakter, så slett de avviklede modulene og scriptinngangene. Regelmotor og ladder-review er eksplisitt utenfor slettingen. Historiske Excel-data behandles som bevarte data, ikke nye ML-resultater.

**Tech Stack:** Python >=3.12,<3.15, PyQt6, pandas/openpyxl, pytest, Rust-first analyse.

**Spec:** `docs/superpowers/specs/2026-09-19-remove-ml-labeling-design.md` (godkjent av bruker).

## Global Constraints

- Ingen eksisterende FSA, modeller, labeling-filer, korrigeringsdatabase eller arbeidsbøker slettes.
- Run, Archive, ladderutkast/godkjenning/rerun, regelbasert klonalitetsanalyse, FLT3 og General skal beholde sin funksjon og sine numeriske standarder.
- Ingen ML-/labeling-fane, modellvelger, modellinnlasting, treningsjobb eller learning-eksport skal kunne aktiveres i appen, heller ikke av gammel YAML.
- Historiske kolonner i eksisterende Excel-filer skal ikke gå tapt ved oppdatering; nye kjøringer skal ikke generere nye ML-/labelingfelt.
- Behold scikit-learn for aktiv ladder-fitting/R². Ingen dependency-oppgraderinger i denne planen.
- Gjeldende branch: `feature/ladder-review-workflow`. Bevar andre endringer. Ingen merge/release som del av avviklingen.

## Review Focus

1. Gammel YAML med enabled=true og modellsti må ikke laste modeller eller eksportere annotasjoner — M02/M04.
2. Historisk arbeidsbok med labeling/ML-kolonner og brukerformler må overleve oppdatering — M03.
3. Manglende modeller og ødelagte gamle modellfiler må ikke påvirke vanlig oppstart/Run — M02/M07.
4. `label` i ladder-review er fortsatt nødvendig; må ikke slettes med labeling — M01/M07.
5. Regelbasert interpretation deler fil med forskningshjelpere; regelresultatene må forbli like — M04/M06.

## Felles test-/commit-syklus

Hver M-oppgave følger denne syklusen; utførende agent skal føre kommando og faktisk resultat i `tasks/execution-log.md`:

- [ ] Skriv regresjonstest for akseptansen, kjør den og kontroller at riktig atferd feiler før endring.
- [ ] Gjør bare den oppgitte endringen. Ved ren filsletting er referanse-/importtest relevant, ikke en kunstig atferdsfeil.
- [ ] Kjør oppgavens testkommando. Ingen skip/xfail av tester for gjenværende funksjonalitet.
- [ ] `git diff --check`, review diff, stage eksplisitte filer og commit med oppgavens formål. Slettecommits kan være store i linjetall, men skal ikke skjule endret aktiv logikk.

### M01 — Fjern produktinngangene (M)

**Filer:** `gui_qt/main_window.py`, `gui_qt/tabs/tab_settings.py`, `tests/test_main_window_navigation.py`, `tests/test_tab_settings_save.py`. Ingen avhengigheter.

**Kontrakt:** `MainWindow` har ikke `tab_labeling` eller navigasjonsmål Labeling; profilinnstillinger tilbyr bare aktive valg. `interpretation.enabled` beholder sin betydning for regelmotoren, men merkes eksplisitt «Rule-based interpretation».

- [ ] Legg inn denne navigasjonskontrakten i eksisterende qapp-test:

```python
window = MainWindow()
assert not hasattr(window, "tab_labeling")
assert all("Labeling" not in group.sub_button_labels for group in window.groups)
assert "Ladder" in window.group_clonality.sub_button_labels
window.close()
```

- [ ] Fjern TabLabeling-import/konstruksjon/stack-indeks/menyoppføring. Behold semantiske navigasjonsmål.
- [ ] Fjern modellsti, ML-status, learning-checkbox/mappe og tilhørende browse/statusmetoder fra Settings. Fjern kun ML/learning-save/load; behold regelbryter og alle andre profilfelt.
- [ ] Verifiser `python -m pytest -q tests/test_main_window_navigation.py tests/test_tab_settings_save.py tests/test_active_operation_navigation.py`.

### M02 — Frikoble runtime fra modeller og learning-eksport (M)

**Filer:** `core/analyses/clonality/pipeline.py`, `core/batch.py`, ny `tests/test_retired_ml_runtime.py`; behold blandede integrasjonstester ved å flytte regelasserts til denne testen. Avhenger av M01.

**Kontrakt:** `run_pipeline` og batch beholder sine øvrige signaturer/resultater. Fjern `learning_annotation_seed` fra nye resultater etter referansesøk. `_attach_batch_context_and_ml` og kallene til den avvikles; den finnes kun for ML/cohort-berikelse.

- [ ] Legg til subprocess-importtest som avviser avviklede imports før import av pipeline og batch:

```python
import importlib.abc
import sys

class RejectRetiredImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            "core.analyses.clonality.ml_runtime",
            "core.analyses.clonality.ml_model",
            "core.analyses.clonality.ml_training",
        }:
            raise AssertionError(fullname)

sys.meta_path.insert(0, RejectRetiredImports())
import core.analyses.clonality.pipeline
import core.batch
```

- [ ] Bruk eksisterende syntetiske batch-/pipeline-fixtures med `interpretation.model_path` til ugyldig modellmappe og `learning.enabled=True`. Kontroller normale analyse-resultater, fravær av `ClonalityML*` og ingen `clonality_learning_annotations`-mappe.
- [ ] Fjern ml_runtime/cohort-importene og ML/cohort-attachment, men behold `attach_interpretation_if_enabled(attach_analysis_provenance(entry))`. Fjern batchens learning-export-blokk og resultatfelt.
- [ ] Verifiser `python -m pytest -q tests/test_retired_ml_runtime.py tests/test_clonality_interpretation_v1.py tests/test_manual_ladder_rerun.py` samt eksisterende batchtester identifisert med `rg --files tests -g '*batch*'`.

### M02b — Fjern ML-presentasjon fra nye HTML-rapporter (M)

**Filer:** `core/html_reports/_legacy.py`, `core/html_reports/_constants.py`, `tests/test_html_report_clonality_badge.py`, `tests/test_html_report_dit.py`. Avhenger av M02.

- [ ] Legg til rapporttest med eksternt/historisk entry som inneholder `ClonalityMLSuggestion`, `ClonalityMLConfidence` og `ClonalityMLChannelResults`. Generert HTML skal ikke ha ML-badge, kanalprediksjon, dismiss/restore-knapp eller ML-decision-log.
- [ ] Fjern `_clonality_ml_*`-hjelpere, `_render_clonality_ml_badge`, `_render_clonality_channel_ml_results`, deres kall og tilhørende JS/CSS/eksportserialisering. Behold vanlig peak-editor, lagring og regelbasert rapportinnhold.
- [ ] Erstatt badge-only-testene med fraværstesten, men behold aktiv peak-/rapportdekning. Eksisterende HTML-filer på brukerens disk endres ikke; kontrakten gjelder nye rapporter.
- [ ] Verifiser `python -m pytest -q tests/test_html_report_clonality_badge.py tests/test_html_report_dit.py tests/test_html_peak_editor_interactions.py` og nettleser-smoke med syntetisk rapport.

### M03 — Bevar historisk Excel uten aktive ML-/labelingkolonner (M)

**Filer:** `core/analyses/clonality/tracking_excel.py`, `tests/test_clonality_tracking_output.py`, `tests/test_tracking_workbook_io.py`. Avhenger av M02; robusthetsoppgave R01 bør gjøres først.

**Kontrakt:** `update_clonality_tracking_workbook` lager bare aktive genererte kolonner; historiske ukjente kolonner beholdes av eksisterende upsert. Ingen import av ml_data_contract/interpretation_units.

- [ ] Bygg testarbeidsbok med `Chemist_Label`, kanal-label, `ClonalityMLSuggestion` og en egendefinert formel. Oppdater samme IdentityKey og legg til ny rad. Gamle celler skal være uendret, ny rad skal ikke få historisk label/modellresultat.
- [ ] Test ny arbeidsbok: ingen kolonner som starter `ClonalityML`, ingen genererte chemist-labelkolonner, aktive analyse-/QC-kolonner finnes.
- [ ] Fjern ML-/chemistkolonner fra genererte schemas/entry-row og `_run_columns`-valg. Fjern `_carry_forward_chemist_labels` bare etter at testen beviser bevaring gjennom ikke-genererte kolonner. Ikke dropp eksisterende kolonner via en DataFrame-reindex uten etterfølgende bevaring i workbook-writer.
- [ ] Verifiser `python -m pytest -q tests/test_clonality_tracking_output.py tests/test_tracking_workbook_io.py tests/test_flt3_tracking_output.py`.

### M04 — Rydd konfigurasjon og blandet regel-/annotasjonsfil (M)

**Filer:** `config.py`, `core/analyses/clonality/interpretation.py`, `tests/test_settings_persistence.py`, `tests/test_clonality_interpretation_v1.py`, `tests/test_retired_ml_runtime.py`. Avhenger av M02/M03.

- [ ] Test last/save av gammel YAML: aktive felt og regel-`enabled` beholdes. Retired `model_path`, ML-`thresholds` og `learning` kan ikke aktivere funksjonene; fjernes fra normalisert konfigurasjon uten å slette refererte filer.
- [ ] Fjern disse feltene fra defaults og normaliser lastet clonality-profil eksplisitt. Eksempel på avgrenset transformasjon (bruk eksisterende migreringsfunksjon, ikke enda et globalt settings-lager):

```python
profile.pop("learning", None)
interpretation = profile.get("interpretation")
if isinstance(interpretation, dict):
    interpretation.pop("model_path", None)
    interpretation.pop("thresholds", None)
```

- [ ] Fjern learning-export/annotation-funksjoner fra interpretation etter M05 har fjernet deres siste kallere; behold `interpret_entry`, `attach_interpretation_if_enabled`, SL-kvalitet, peaks/ranges og delte featurehjelpere. Utfør denne delen etter M05 selv om config-delen kan tas før.
- [ ] Verifiser `python -m pytest -q tests/test_settings_persistence.py tests/test_clonality_interpretation_v1.py tests/test_clonality_interpretation_features_v2.py tests/test_retired_ml_runtime.py`.

### M05 — Fjern avviklede GUI-/scriptkallere (S per commit)

Avhenger av M01–M03. Bruk `apply_patch` for slettinger. Før hver rad: søk modul-/scriptnavn i hele repoet; fjern kun tester som utelukkende tester avviklet funksjon, flytt aktive regel-/trackingasserts ut av blandede tester. Ingen brukergenererte filer slettes.

| Commit | Eksakte targets | Kontroll |
|---|---|---|
| M05a | `gui_qt/tabs/tab_labeling.py`, `tests/test_tab_labeling.py`, `core/labeling/labeling_plot.py`, `tests/test_labeling_plot.py`, aktive deler av `tests/test_clonality_interp_integration.py` | Navigasjon/startup og ingen produktimport av core.labeling |
| M05b | `core/labeling/labeling_session.py`, eventuell tom `core/labeling/__init__.py`, `tests/test_labeling_session.py` | Tracking-tests beviser at gamle labels beholdes |
| M05c | `gui_qt/tabs/tab_ml_training.py`, `tests/test_tab_ml_training.py` | Startup uten trening-import |
| M05d | `gui_qt/tabs/tab_clonality_interpretation.py`, `tests/test_clonality_interpretation_tab.py`, `tests/test_clonality_interp_integration.py` | Fjern annotasjonsflate; behold regelmotor/integrasjonsasserts i samme commit |
| M05e | `scripts/train_clonality_interpretation_models.py`, `scripts/train_clonality_interpretation_quick_model.py`, `tests/test_clonality_ml_trainer_outputs.py`, `tests/test_clonality_interpretation_ml.py` | Ingen gjenværende trenings-entrypoints |
| M05f | `scripts/prepare_clonality_labeling_batch.py`, `scripts/merge_clonality_labeling_batch.py`, `scripts/export_clonality_labels_csv.py`, `scripts/render_clonality_interpretation_annotation_html.py` | Ingen dokumentert aktiv labeling-CLI |
| M05g | `scripts/build_clonality_ml_features.py`, `scripts/audit_clonality_ml_data.py`, `scripts/assess_clonality_ml_readiness.py` | Import-/referansesøk |

- [ ] Etter hver GUI-commit: `python -m pytest -q tests/test_main_window_navigation.py tests/test_startup_lazy_imports.py tests/test_qt_app_startup_review.py tests/test_clonality_interp_integration.py`.
- [ ] Etter scriptfjerning: `python -m compileall -q scripts core gui_qt`; testcollection skal ikke ha imports av slettede scripts.

### M06 — Fjern forskningsmotorer fra ytterkant og innover (S per commit)

Avhenger av M05 og M03. Modulene ligger i `core/analyses/clonality/`. Ikke slett en modul før dens gjenværende kallere enten er avviklet eller avklart som aktiv delt kode. Slett tilhørende rene tester i samme commit; blandede tester justeres, ikke droppes.

| Rekkefølge | Moduler | Egne testfiler |
|---|---|---|
| 1 | `ml_runtime.py`, `calibration.py` | `test_clonality_ml_runtime.py`, `test_clonality_calibration.py`; behold aktive deler av `test_clonality_ml_e2e_app.py` i retired-runtime testen |
| 2 | `ml_model.py` | `test_clonality_ml_model.py` |
| 3 | `ml_validation.py`, `ml_readiness.py` | `test_clonality_ml_validation.py`, `test_clonality_ml_readiness.py` |
| 4 | `ml_data_audit.py`, `ml_feature_dataset.py` | `test_clonality_ml_data_audit.py`, `test_clonality_ml_feature_dataset.py` |
| 5 | `labeling_batch.py` | `test_clonality_labeling_batch.py` |
| 6 | `ml_training.py`, `ml_data_contract.py` | Treningstester allerede fjernet i M05; alle importerende forskningsmoduler er nå borte |
| 7 | `interpretation_units.py`, `cohort_features.py` | `test_clonality_interpretation_units.py`, `test_clonality_cohort_features.py` |
| 8 | `candidate_artifacts.py`, `feature_artifacts.py` | Flytt/behold eventuell delt I/O-dekning fra eksisterende tester etter referansesjekk |

- [ ] Behold `ladder_review_labels.py`, `ladder_review_gate.py`, `interpretation.py`, `trace_features.py` og aktiv analyse-/trackingkode. Fjern kun forskningshjelpere i blandede filer når alle kallere er kartlagt.
- [ ] Oppdater `tests/test_clonality_interp_integration.py` og `core/analyses/clonality/__init__.py` så aktive regelkontrakter dokumenteres/testes uten imports av avviklede moduler.
- [ ] Kjør `python -m pytest --collect-only -q` etter hver slettingsgruppe; kjør aktive clonality-/ladder-/trackingtester før commit.

### M07 — Dokumentasjon, dependency-audit og samlet gate (M)

**Filer:** `README.md`, `requirements.txt`, `docs/ml-clonality-interpretation.md`, `tests/test_retired_ml_runtime.py`, `tasks/execution-log.md`. Avhenger av M02b og M04–M06.

- [ ] Fjern aktive ML/Labeling-bruksinstruksjoner/menytabeller. Merk gamle design-/planfiler som historiske der de fortsatt brukes som beslutningshistorikk; de er ikke nye aktive utviklingsmål. Oppdater roadmap så ML/labeling ikke lenger står som kommende arbeid.
- [ ] Søk `rg -n 'sklearn|joblib' core fraggler gui_qt scripts`. Behold scikit-learn. Fjern direkte joblib-pin bare hvis ingen aktive direkte imports gjenstår; transitive avhengigheter bestemmes av pakken som trenger dem.
- [ ] Referansesøk etter alle slettede modulnavn: bare eksplisitt historisk dokumentasjon og avviklingstest skal gjenstå. Utvid M02s import-vakt til alle `core.analyses.clonality.ml_`-moduler og `core.labeling` nå som tracking er frikoblet. Subprocess-test skal importere app/analyses uten avviklede moduler, både med gammel og ny YAML.
- [ ] Kjør `python -m pytest -q`, `python -m compileall -q qt_app.py core gui_qt scripts`, `git diff --check`. Oppgi nytt testantall og antall fjernede ML-only tester uten å late som redusert antall er ny dekning.
- [ ] Kjør eksisterende startup-/package-resource-tester og Windows-native-smoke. Verifiser Run→Ladder→lagre→rerun med syntetiske data, og alle tre analysegruppers navigasjon/settings.
- [ ] Review ferdig diff separat fra robusthetsrettingene. Commit dokumentasjon og be om/bruk eksplisitt push-instruks; ingen automatisk merge.

## Kontrollpunkter og utføring

- Etter M01–M03: produktet kan kjøre uten ML, historiske data bevares; gjennomgå diff før massen av rene slettinger.
- Etter M04–M06: ingen aktive kallere av avviklet funksjonalitet, hele testcollection virker.
- Etter M07: verifisert avvikling. Dette er ikke faglig godkjenning på privat referansedatasett.

Anbefalt utføring er fortsatt GPT-5.6 Sol med hovedagent som orkestrator, slik brukeren allerede har valgt. Del ut én oppgave om gangen der filene overlapper; uavhengig review kan gå parallelt. Robusthetsplanen i `tasks/robustness-plan-2026-09-19.md` utføres som separate rettingscommits, med R01 før M03. Planen skal gjennomgås av bruker før implementering starter.
