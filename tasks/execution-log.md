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

## Andre reviewrunde — ML-avvikling og robusthet

Brukeren har godkjent full fjerning av ML/trening/labeling og gjennomgått avviklingsdesignet (commit `dae2ada`). Utføringsplanen er skrevet for Sol + orkestrator; produktendringene venter på gjennomgang av planen. Tidligere S11-forbehold om mulig ML-/labelingbruk er erstattet av eksplisitt avviklingsbeslutning.

Uavhengig Sol-review og hovedagentens gjennomgang ga B01–B08 i `review-robustness-2026-09-19.md`. To små, ikke-muterte diagnostiske reproduksjoner er kjørt:

- Faktisk `upsert_frame` i en workbook i minnet: gammel verdi 42 forblir 42 etter ny None. Forventet tom celle.
- Faktisk `TabBatch._on_run_finished` med mocked view og DIT aggregation-feil: gir `Batch complete.` / `success`.

Øvrige funn har statisk kontrollflytbevis og konkrete regresjonstestplaner, ikke påstått runtime-reproduksjon. Ingen pasientdata, brukerinnstillinger eller arbeidsbøker ble skrevet. Denne runden endrer bare review-/design-/plandokumentasjon; hele testsuiten kjøres ikke på nytt for uendret produktkode. `git diff --check` kontrolleres før dokumentasjonscommit.

Planen er selvreviewet og sjekket av Sol: HTML-badges/ML-decision-log er lagt til eksplisitt (M02b), blandede integrasjonstester oppdateres i samme commit som GUI-modulene fjernes, og `ml_training` slettes etter modulene som importerer den. Dermed unngår planen kjente røde mellomcommits og gjenværende aktiv ML-presentasjon.

## M07 — dokumentasjon, dependency-audit og importvern

Gjennomført 2026-09-22 etter at M01–M06 var integrert:

- README beskriver bare aktive operatørflater. Labeling-fanen, ML-kandidatstatus og treningsverktøy er fjernet fra aktiv veiledning.
- Den tidligere ML-guiden og de dedikerte ML-planene/designene er tydelig merket som historiske og superseded. De beholdes som beslutningshistorikk, ikke som aktiv backlog.
- `joblib` har ingen direkte import i aktiv kode og er fjernet som direkte krav. `scikit-learn` beholdes fordi `core/analysis/_legacy.py` og `fraggler/fraggler.py` fortsatt bruker pakken til ladder-fitting og R².
- Startup-importtesten avviser alle `core.analyses.clonality.ml_*`-moduler og hele `core.labeling`-navnerommet. Den importerer config, aktiv clonality-pakke, pipeline, batch, MainWindow og `qt_app` med både gammel ML/learning-YAML og ny YAML.
- 18 rene ML-/labeling-testmoduler er fjernet siden avviklingsplanens grunncommit. Dette er slettet dekning for slettede funksjoner, ikke ny dekning for gjenværende produkt.

Verifisering for denne deloppgaven:

- Fokuserte retirement/settings/startup/navigation/package-tester: **32 bestått**, 2 forventede warnings fra injiserte settings-skrivefeil.
- `python -m pytest --collect-only -q`: **691 tester samlet** uten importfeil.
- `python -m compileall -q qt_app.py core gui_qt scripts`: bestått.
- `git diff --check`: bestått; Git varslet kun om framtidig LF→CRLF-normalisering i `requirements.txt`.
- Referansesøk i aktiv Python-kode fant ingen referanser til de slettede navnene. Orkestratorens lokale sluttgate med full pytest, compileall, diffcheck og faktisk isolert native-wheel-smoke er senere gjennomført; se samlet lokal verifikasjon nedenfor.

## R02 — krasjsikker publisering av tracking

Gjennomført 2026-09-22 med atomisk erstatning og uten direkte overskrivingsfallback:

- Staging-filen lukkes og `fsync`-es før publisering. POSIX bruker deretter `os.replace` og `fsync` av målkatalogen; Windows bruker `MoveFileExW` med `REPLACE_EXISTING | WRITE_THROUGH` via standardbibliotekets `ctypes`.
- Lik staging- og målfil avvises før oppryddingsblokken. Feil ved filsynk, replace eller katalogsynk propageres, og en blokkert replace skriver aldri direkte over siste gode arbeidsbok.
- Kontrakten lover komplett gammel eller ny arbeidsbok ved prosesskrasj. Strømbruddsvarighet avhenger fortsatt av at operativsystem, filsystem og lagringsenhet respekterer sync-/write-through-forespørselen.
- `python -m pytest -q tests/test_tracking_workbook_io.py tests/test_clonality_tracking_output.py tests/test_flt3_tracking_output.py`: **26 bestått** på 9,17 sekunder.
- Isolert Windows-test med faktisk Excel COM-lås på en syntetisk midlertidig `.xlsx`: `PermissionError [WinError 5]`, original SHA-256 uendret og staging-filen fjernet. Ingen kliniske filer eller brukerfiler ble brukt.
- `python -m compileall -q qt_app.py core gui_qt scripts`: bestått.
- `git diff --check`: bestått.

## R03/R05/R06 — review-bundle og asynkron kontekst

Gjennomført 2026-09-23:

- R03 samler CSV og summary i en transaksjonell review-bundle-kontrakt med staging, journal og recovery. Både Run-carry og Ladder-lagring går gjennom samme kontrakt; lagringsfeil skal ikke presenteres som suksess.
- R05 binder metadata-resultater til request-ID, analyse-ID og løst filspor. Analyse-/kontekstbytte ugyldiggjør eldre callbacks, og single-/bundle-rerun låser kildekonteksten til gjeldende operasjon er ferdig.
- R06a bruker én gjensidig utelukkende Ladder source-load-livssyklus for scan og bundle-load; stale success/error-callbacks får ikke reaktivere kontroller som eies av en nyere operasjon.
- R06b inkluderer Run scan i MainWindow sitt aktiv-operasjon-vern. Analyse- og settingsbytte avvises mens scan eier konteksten, og success/error frigjør riktig scan-request uten å nullstille en aktiv analysejobb.

## R07 — close-/snapshot-undersøkelse

Undersøkelsen er dokumentert i `robustness-r07-investigation.md`; implementasjonen er fortsatt åpen.

- Kontrollert offscreen-reproduksjon brukte ordinær `MainWindow`/`Worker`, en kooperativ syntetisk jobb og en midlertidig syntetisk rapportfil. Close returnerte og Qt-eventløkken stanset etter ca. 15 ms mens cancellation fortsatt var usatt, begge workere kjørte og filen bare inneholdt første skrivefase. Etter kontrollert testopprydding var begge workere ferdige og fase 2 skrevet.
- Dette bekrefter arbeid etter skjult UI/event-loop-stopp. Virkelig HemaFrag HTML/XLSX-korrupsjon, krasj og heng er ikke reprodusert og omtales derfor bare som statisk risiko.
- Kartleggingen viser mutable `APP_SETTINGS`-reads gjennom batch/runner/pipeline/registry og downstream rapport/tracking, samt rerun-workere som muterer aktiv analyse. Planen deler close-coordinator og per-run `RunContext` i separate, testbare migreringssnitt.

## Samlet lokal verifikasjon 2026-09-23

Kjørt av orkestratoren etter integrasjon:

- Tre siste integrasjonsrettelser ble verifisert samlet: Ladder ugyldiggjør source-callbacks ved analysebytte; Run nullstiller scan-kontrollene; Locate File/annotation er serialisert, og CSV+relocation-audit publiseres atomisk med en koordinert toprosesstest.
- Full `python -m pytest -q` etter alle tre integrasjonsrettelsene: **734 bestått, 6 skipped, 4 warnings** på **95,22 sekunder**. Prosessen avsluttet uten teardown-traceback.
- Målrettet native/ladder/HTML-utvalg: **35 bestått**. Native-wheel-delen av dette in-process-testutvalget bruker mocking og er derfor ikke en faktisk installasjonstest av wheel-filen.
- Faktisk native-wheel-smoke ble kjørt isolert med `pip install --no-deps --target <temp> wheels/fraggler_kernels-0.1.2-cp310-abi3-win_amd64.whl`; deretter returnerte `fraggler_native.is_available()` `True`, og rapportert versjon var `0.1.2`. Brukerens Python-miljø ble ikke endret.
- `python -m compileall -q qt_app.py core gui_qt scripts` og `git diff --check`: bestått.
- Referansesøk i aktiv Python-kode etter de avviklede navnene: ingen treff.
- M07 er komplett for den lokale retirement-gaten. R08 er fortsatt åpen for ekstern CI, operatørvalidering og klinisk validering; de lokale resultatene er programvareregresjon og utgjør ikke ny klinisk godkjenning.
