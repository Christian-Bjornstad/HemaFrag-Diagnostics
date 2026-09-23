# R07 — undersøkelse av trygg avslutning og operasjonssnapshot

Dato: 2026-09-23. Status: undersøkelse og arkitekturplan; ingen livssyklus- eller settingsarkitektur er implementert her.

## Kort konklusjon

Lukking er konkret reprodusert som en umiddelbar, ukontrollert overgang: `MainWindow` har ingen `closeEvent`, og et kontrollert offscreen-forsøk godtok lukking mens to `Worker`-oppgaver fortsatt kjørte. Run sitt kanselleringssignal ble ikke satt, og en syntetisk rapportfil ble ferdigskrevet først etter at Qt-eventløkken var avsluttet.

Dette bekrefter at arbeid kan fortsette etter at UI-et er borte. Det bekrefter **ikke** at en virkelig HemaFrag-rapport blir korrupt, at prosessen krasjer, eller at avslutning henger. Disse er statiske risikoer som krever egne subprocess-/feilinjeksjonstester med syntetisk output før de kan kalles feil.

Kjøringskonteksten er heller ikke frosset. UI-et leser en sammenslått profil før oppstart, men `generate_jobs`, `run_batch_jobs`, `runner`, pipeline-dispatch, analyseimplementasjoner og enkelte rapport-/tracking-funksjoner leser fortsatt mutable `APP_SETTINGS`. Ladder- og Run-rerun-workere skriver dessuten `APP_SETTINGS["active_analysis"]` fra bakgrunnstråden. UI-blokkering reduserer sannsynligheten for et bytte, men gir ingen motor-kontrakt om at en startet kjøring beholder samme analyse og innstillinger.

## Reproduksjon og bevis

Kontrollert forsøk brukte `QT_QPA_PLATFORM=offscreen`, en ordinær `MainWindow`, to ordinære `gui_qt.worker.Worker`-objekter og bare en `TemporaryDirectory`:

1. En Run-lignende jobb ventet kooperativt på `threading.Event`.
2. En rapport-lignende jobb skrev `phase-1`, flush/fsync, ventet 0,6 s og skrev deretter `phase-2` til en syntetisk tekstfil.
3. Begge workerne ble startet i fanenes delte `QThreadPool.globalInstance()`.
4. Vinduet ble lukket så snart begge jobbene var startet.
5. Testharnessen ventet på threadpoolen først **etter** at Qt-eventløkken var avsluttet, bare for kontrollert opprydding.

Observerte verdier:

```text
active_operation_before_close = Run
close_returned = true
close_call_ms = 15.0
event_loop_ms = 15.0
cancel_set_after_close = false
job_done_after_close = false
report_done_after_close = false
content_after_close = "phase-1\n"
final_content_after_test_cleanup = "phase-1\nphase-2\n"
```

Reprodusert: lukking godtas uten kanselleringsforespørsel eller draining, og worker-/filaktivitet fortsetter etter at UI-eventløkken er avsluttet.

Ikke reprodusert: avbrutt virkelig HTML/XLSX, datatap, Qt-krasj eller ubegrenset heng. `qt_app.py::main` går direkte fra `app.exec()` til `sys.exit`, så ekte prosessavslutning med aktive runnables må testes i en separat subprocess. De viktigste DIT-HTML-skriverne bruker staging + fsync + `os.replace`, mens blant annet `core/qc/qc_html.py`, `core/qc/qc_excel.py` og enkelte summary-skrivere fortsatt har direkte skrivebaner. Det gjør skade ved ekstern terminering plausibel, ikke bekreftet.

## Nåværende livssyklus

| Område | Nåværende eierskap og stopp | Konkret hull ved lukking |
|---|---|---|
| `gui_qt/worker.py` | Generisk `QRunnable`; sender `result/error/finished`. | Ingen operasjons-ID, cancellation token eller appnivå-registrering. |
| Run scan | Request-ID og aktivt scan-flagg; MainWindow ser nå scan som aktiv operasjon. | Ingen kooperativ avbrytning og ingen beholdt worker-handle. |
| Run batch | `threading.Event` stopper ny scheduling; aktive jobber får fullføre ved jobbgrense. | Close kaller ikke `on_stop`; worker-handle eies ikke; token går ikke inn i aktiv pipeline-/filskrivefase. |
| Run review-finalisering | Boolsk aktiv-status og request-ID. | Ingen cancellation token; workeren muterer global aktiv analyse før ny batch. |
| Archive | Beholder `_active_worker`; yearly/combine kjører i global threadpool. | Ingen cancellation token eller close-protokoll. |
| Ladder scan/load/metadata/report-søk | Request-ID-er gjør gamle callbacks irrelevante. | Request invalidation avbryter ikke arbeidet; `MainWindow.active_operation()` ser bare rerun, ikke disse workerne. |
| Ladder single-/bundle-rerun | Boolske aktiv-flagg og request-ID-er. | Ingen cancellation token; helperne muterer global aktiv analyse fra workertråden. |
| Threadpool | Run, Archive og Ladder deler `QThreadPool.globalInstance()`. | `waitForDone()` i `closeEvent` ville være globalt, blokkere GUI-tråden og ha ukjent varighet. |

`MainWindow.active_operation()` er et navigasjonsvern, ikke et komplett operasjonsregister. Det kan derfor ikke brukes alene som bevis på at prosessen er trygg å avslutte.

## Mutable settings gjennom kjeden

Følgende reads/mutasjoner er relevante for `TabBatch → core.batch → core.runner → core.pipeline → registry` og resultatpublisering:

- `TabBatch._profile_for()` gir en sammenslått kopi for enkelte UI-argumenter, men konteksten sendes ikke videre som ett objekt.
- `core.batch.generate_jobs()` velger General-sporet fra `APP_SETTINGS["active_analysis"]` når scannet faktisk utføres.
- `core.batch.run_batch_jobs()` leser aktiv analyse, globale QC-verdier, analysis-batch/gate og sender hele den daværende globalen til manifest-fingerprint. Tracking-path løses senere uten eksplisitt settings-argument.
- `core.runner.run_pipeline_job()` velger General-spesialbanen fra global aktiv analyse.
- `core.pipeline.run_pipeline()` kaller `registry.get_analysis_module("pipeline")`; registry velger modul fra global aktiv analyse på dispatch-tidspunktet.
- Clonality og FLT3 leser globale engine-flagg under kjøringen; Clonality leser også `file_timeout_seconds`. `core.engine_flags` er globalt koblet.
- General-konfigurasjonen støtter allerede et `settings`-argument, men dagens pipelinekall sender ikke snapshotet.
- HTML/QC/tracking har ytterligere reads av globale QC-/batchinnstillinger, blant annet `core/html_reports/_legacy.py`, Clonality tracking og FLT3 QC tracker.
- `TabBatch._review_finalize_worker()` og Ladder sine rerun-workere setter `APP_SETTINGS["active_analysis"]` i bakgrunnstråden for å få riktig dispatch.

Konsekvensen er en statisk krysskjøringsrisiko: en global endring mellom kølegging, dispatch, rapportbygging og tracking kan påvirke hvilken modul eller hvilke verdier som faktisk brukes. Manifestet lagrer en fingerprint av globalen ved manifestopprettelse, men dette beviser ikke at alle senere reads brukte samme innhold.

## Avgrenset close-design

Innfør ett lite appnivå `OperationCoordinator`, ikke livssykluslogikk i hver knapp. Hver workerstart registrerer en handle med `operation_id`, `kind`, valgfri `run_id`, `cancel()` og status (`queued/running/cancelling/critical_write/settled`). `settled` må sendes fra `finally`, også ved feil. Nye operasjoner avvises når coordinator er i `draining`.

`MainWindow.closeEvent` blir en ikke-blokkerende tilstandsmaskin:

1. Hvis registeret er tomt, godtas eventet.
2. Ellers ignoreres eventet, nye starter sperres, alle handles får kooperativ `cancel()`, og UI viser hvilke operasjoner som dreneres.
3. En `QTimer` eller `settled`-signal oppdaterer fremdrift; aldri `waitForDone()` eller `terminate()` på GUI-tråden.
4. Ved null aktive handles settes et engangsflagg og `close()` postes på nytt, slik at neste event godtas.
5. En kort, testbar frist (foreslått 30 s) avgrenser hvert avslutningsforsøk. Hvis arbeid fortsatt pågår, forblir appen åpen og viser «fortsetter trygg ferdigstilling» med valgene vent videre eller avbryt avslutning. Det finnes ingen intern «force kill» mens en writer er i kritisk fase.

Kansellering betyr «ikke start neste enhet» og «stopp ved neste deklarerte sikre grense». En aktiv staging-/fsync-/replace-sekvens må fullføres eller rydde staging før handlen blir `settled`. Direkte ikke-atomiske writere må vurderes i sine lagringsoppgaver; close-koordinatoren alene er ikke en durability-garanti.

## Migreringssnitt

### C1 — Operasjonsregister og close-test

- Opprett coordinator/handle-kontrakten og en isolert `tests/test_safe_app_shutdown.py` med kontrollerte workere.
- Test at close ignoreres, cancellation settes, nye starter avvises, GUI-tråden ikke blokkeres, og andre close-forsøk er idempotente.
- Test fristen med en worker som ikke blir ferdig: vinduet skal forbli åpent; ingen terminate/waitForDone.

### C2 — Skrivende operasjoner først

- Registrer Run batch og review-finalisering, Archive yearly/combine og Ladder-reruns.
- Propager token til `run_batch_jobs`; eksisterende Run-semantikk med aktive jobber som fullfører trygt beholdes.
- Legg cancellation checks mellom arkivmåneder/foldere og mellom Ladder-rerun-filer, aldri midt i publisering.

### C3 — Alle øvrige workere

- Registrer Run scan og Ladder scan/load/metadata/report-søk samt eventuelle aktive valideringsflater.
- Request-ID beholdes for stale-callback-sikkerhet; coordinator dekker prosesslivssyklus. De to mekanismene har forskjellige ansvar.

### S1 — `RunContext` ved kølegging

- Opprett en liten frozen kontrakt med `run_id`, `parent_run_id`, `analysis_id`, `created_at_utc` og en deep-copied, validert settings-snapshot.
- Test at endring i `APP_SETTINGS` etter opprettelse ikke endrer context eller fingerprint. Ikke bruk `settings or APP_SETTINGS`; et eksplisitt tomt mapping må respekteres.

### S2 — TabBatch og batch

- Capture context én gang før scan/run-worker kølegges; callback-token inkluderer `run_id`.
- Gi `generate_jobs(..., run_context=...)` og `run_batch_jobs(..., run_context=...)` en midlertidig kompatibilitetsfallback for CLI.
- Les analysis/QC/gate/tracking-path fra snapshotet. Manifestet bruker contextens `run_id` og fingerprint og registrerer parent ved rerun.
- Bevar contexten i Run-review-sessionen; en child-rerun får ny `run_id`, men arver den eksplisitte analysen/profilen.

### S3 — Runner, pipeline og registry

- Før context gjennom alle `run_pipeline_job*`-/QC-/DIT-kall og `core.pipeline.run_pipeline`.
- Endre registry til eksplisitt `get_analysis_module(submodule, analysis_id=...)`; global fallback beholdes bare mens CLI-kallsteder migreres.
- Test to samtidige syntetiske context-er med ulike analyser mens global `active_analysis` endres; hver må dispatches til riktig stubmodul.

### S4 — Analyse- og outputreads

- Migrer General først fordi config allerede kan lese et settings-argument.
- Migrer deretter Clonality engine/timeout/interpretation/report/tracking og FLT3 engine/QC-tracking i små vertikale commits.
- For hver analyse: muter global settings etter kølegging og verifiser med spies at pipeline, rapport og tracking bruker snapshotet.

### S5 — Ladder og Archive

- Fjern workertrådenes writes til `APP_SETTINGS["active_analysis"]`; bygg context på GUI-tråden og send den eksplisitt.
- Archive får eget context/run-ID ved start. Ladder-rerun får child-context og parent-manifest-/run-ID.
- Når alle innganger er migrert, fjern kompatibilitetsfallbackene og gjør manglende context til en tydelig programmeringsfeil i workerbaner.

## Ferdigkriterier for senere implementering

- Lukking under syntetisk batch, Archive, Ladder-rerun og rapportpublisering skjuler ikke UI før alle operasjoner er ved sikker grense.
- Close-handler blokkerer aldri GUI-tråden og kaller aldri `terminate()` eller ubegrenset `waitForDone()`.
- Ingen worker starter etter at draining er innledet; alle startede workere ender i `settled` ved success, error eller cancellation.
- To samtidige syntetiske kjøringer med forskjellige profiler kan ikke endre hverandres dispatch, QC, output-path eller manifest-fingerprint.
- Manifestets run-ID/settings-fingerprint matcher contexten som faktisk nådde pipeline og outputskriverne.
- Subprocess-smoke av den virkelige `qt_app.py`-avslutningen bruker bare midlertidige syntetiske filer og rapporterer eksplisitt om prosessen drenerer, forblir åpen eller feiler. Før dette er kjørt, forblir produksjonskrasj/heng/dataskade «ikke reprodusert».
