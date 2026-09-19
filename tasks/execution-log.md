# Utføring av oppryddingsplan

Start: 2026-09-19, `feature/ladder-review-workflow`, grunnlag `1c7c51e`.
Brukeren har godkjent implementering og bedt om GPT-5.6 Sol som utførende modell med hovedagenten som orkestrator.

## Arbeidsdeling

- Sol / navigation: S01; eier MainWindow, Run og Archive-vern.
- Sol / settings: S02 først; eier config og Settings-lagring.
- Sol / ladder: S05; eier ladderlagring og ladderfanen.
- Orkestrator: koordinerer felles kontrakter, gjennomgår diff, verifiserer integrasjonen og lager fokuserte commits. Ingen to agenter skal redigere samme fil samtidig.

Alle arbeider i samme checkout. Utførende agenter skal ikke stage eller committe; dokumentasjon og integrasjonscommits eies av orkestratoren. Videre oppgaver deles ut etter review av avhengighetene.

## Resultater

Sol-agentene gjennomførte hoveddelene av implementeringen. Etter at agentene traff kredittgrensen, overtok orkestratoren integrasjon, layoutrettelser, CI og sluttverifikasjon.

| Oppgaver | Levert |
|---|---|
| S01 | Felles aktiv-operasjon-vern for analysebytte/settings, også finalize/rerun. Commit `acd4a8a`. |
| S02 | Atomisk settings-lagring og ærlig feilstatus; aktiv konfigurasjon oppdateres bare etter vellykket lagring. Commit `8a71ab6`. |
| S03/S04/S08 | Én App Settings-side for globale felt, separate analyseprofiler, dirty-status, feltvalidering, sammenleggbar avansert del og reell engine-status. Ctrl+, åpner App Settings. |
| S05 | Identitetsspesifikk deaktivering i SQLite med tombstone mot sidecar-gjenimport, cache-/review-opprydding og feiltester. Commit `acd4a8a`. Full revisjonshistorikk er ikke innført. |
| S06/S07 | Compare fjernet fra operatørnavigasjon, Run, UI-modul og worker. General viser ikke unsupported Archive. Selvstendig HTML-sammenlikningsmotor og tester beholdt. |
| S09 | Archive-handlinger i grid for laptopbredde; geometritester med stylesheet og faktisk Windows-font der tilgjengelig. |
| S10 | CI bruker Python 3.12/3.14 på Windows og 3.12 på macOS, full pytest, Node, JUnit og Windows-native-smoke. Tester isolerer settings/DB, også subprocesser. |
| S11a/c | Referansekartlegging gjennomført; foreldreløs `_run_yearly_job` fjernet. Se inventar nedenfor. |
| S12 | Kompakt Run-status, input først, kø tidligere på siden og eksplisitt kildeteller. |
| S13 | Valgfrie bundle-kontroller skjult til de trengs; tomtilstand, metadataavhengige handlinger og tydelig utkast/delvis godkjenning/konsumert rerun. |

### Inventar og avgrensning (S11)

- `tab_compare.py` / `tab_compare_worker.py`: avviklet. Ingen gjenværende produkt-/scriptkallere; navigasjonstester erstatter tester for den fjernede fanen.
- `tab_ml_training.py`: forsknings-/utviklerflate uten operatørinngang; egne tester finnes. Beholdt.
- `tab_clonality_interpretation.py`: forsknings-/utviklerflate uten operatørinngang; egne tester og integrasjonstester finnes. Beholdt.
- `tab_flt3_validation.py`: forsknings-/utviklerflate uten operatørinngang; startup-test sikrer at den ikke lastes automatisk. Beholdt.
- `_run_yearly_job`: foreldreløs wrapper uten kallere, fjernet; underliggende motor beholdt.

S11b er ikke gjennomført: faktisk manuell bruk av forskningsflatene er ukjent. Avklar eier/bruk før fjerning eller egen utviklerlauncher. Ingen analyse-/treningsmotorer, historiske formater eller legacy-fasader er massefjernet.

### Verifikasjon og begrensninger

- Integrasjon S01/S05: 36 tester bestått. Settings-feiltester injiserer skrivefeil med vilje.
- Layout/settings/navigasjon/ladder-utvalg: 28 tester bestått.
- Native wheel `0.1.2` installert uten dependencies i separat midlertidig mappe; `fraggler_native.is_available()` bekreftet. Brukerens Python-miljø ble ikke endret.
- Faktisk MainWindow rendret offscreen ved 1366 × 768 med lesbar Windows-font; Run, Settings og Archive visuelt vurdert. Geometritester dekker flere viewportbredder. Dette erstatter ikke fysisk høy-DPI- og tastaturtest.
- Ingen ny faglig godkjenning på private pasientdata. Numeriske standarder er ikke endret.
- CI-konfigurasjonen er oppdatert; ekstern CI-status må verifiseres på PR. Branch-push alene utløser ikke workflowen som er begrenset til main/PR.
- Endelig `python -m pytest -q`: **908 bestått, 3 skipped, 5 warnings** på 81,89 sekunder (Windows/Python 3.12). Tre warnings er forventet feilinjeksjon i settings, to gjelder sklearn/pandas.
- `python -m compileall -q qt_app.py core gui_qt` og `git diff --check`: bestått. Ingen påstand om at ekstern CI eller alle støttede Python-/OS-kombinasjoner er kjørt lokalt.
