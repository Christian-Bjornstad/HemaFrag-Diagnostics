# Robusthetsreview — andre gjennomgang

Grunnlag: `b6bf2c2`, 2026-09-19. Hovedagentens gjennomgang av tracking/batch/ML-avhengigheter + uavhengig GPT-5.6 Sol-review av asynkron GUI-livssyklus. Ingen produktrettinger er gjort i denne reviewen.

Forrige 908 beståtte tester gjelder forrige leveranse, ikke en garanti mot funnene nedenfor. P1 betyr bør rettes før løsningen omtales som robust i drift. P2 betyr viktig, men normalt gjenopprettbart med omstart/ny innlasting.

## B01 — P1: Tomt nytt resultat beholder gammel Excel-verdi

`core/tracking_workbook_io.py:155`: `ws.cell(row, column, None)` leser/oppretter cellen uten å tømme en eksisterende verdi. `_excel_value` konverterer manglende/NaN til None, men upsert skriver derfor ikke manglende verdier tilbake.

**Reprodusert i minnet:** upsert `{ID: A, Value: 42}`, deretter `{ID: A, Value: None}`. Faktisk B2 = 42, forventet tom celle. Dermed kan en ny analyse beholde en gammel metrikk og se mer komplett ut enn den er.

**Rettelse/test:** sett `ws.cell(row, column).value = _excel_value(...)` bare for genererte kolonner. Test None, NaN, pd.NA, null, False og tom streng; egendefinerte formel-/kommentarkolonner skal bevares. Oppgave R01.

## B02 — P1: Publisering kan ødelegge eksisterende tracking-arbeidsbok

`core/tracking_workbook_io.py:210–223`: for eksisterende mål åpnes filen med `r+b`, og innholdet overskrives direkte før truncate/fsync. Et avbrudd eller en I/O-feil midt i kopieringen kan etterlate en blanding av gammelt og nytt ZIP-innhold. Både clonality (`tracking_excel.py:265`) og FLT3 (`qc_tracker.py:478`) bruker funksjonen.

**Bevisnivå:** statisk bekreftet skrivevindu; ingen produksjonsfil er berørt eller krasjtestet. Eksisterende test `test_publishing_existing_workbook_keeps_destination_entry` krever samme filidentitet og forbyr replace: dette er en reell kontraktkonflikt, ikke bare en manglende try/except.

**Rettelse/test:** avklar filidentitet mot atomisk publisering. Anbefaling: samme-katalog staging + fsync + atomisk replace, ærlig feil hvis mål er låst i Excel, bevart original ved feil. Hvis filidentitet absolutt kreves, må backup/journal og restart-recovery spesifiseres; kopi på stedet er ikke krasjsikker. Injiser delvis kopifeil/replace-feil. Oppgave R02.

## B03 — P1: Review-CSV trunkeres før ny versjon er skrevet

`gui_qt/tabs/tab_batch/_legacy.py:795–811`, `_carry_resolved_labels_to_gate`: canonical CSV åpnes med `w`. Skrivefeil etter åpning kan fjerne lagrede review-rader. Summary skrives separat, og feil svelges, så CSV og summary kan beskrive ulike tilstander.

**Bevisnivå:** statisk bekreftet. `label` her gjelder nødvendig ladder-review, ikke ML-labeling som skal avvikles.

**Rettelse/test:** én felles bundle-store-funksjon med staging og definert commit/recovery for CSV+summary. To separate replace-kall alene er ikke en transaksjon. Injiser feil før/etter første publisering og verifiser gjenoppretting/eksplisitt ufullstendig status, aldri falsk suksess. Oppgave R03.

## B04 — P1: «Batch complete» selv om DIT-rapportbygging feiler

`core/batch.py:1189–1190` legger `DIT aggregation` i `failed_jobs`, men ikke i `failed_job_indexes`. `gui_qt/tabs/tab_batch/_legacy.py:1849–1873` bestemmer feilstatus utelukkende fra lengden på `failed_job_indexes` og velger success ellers.

**Reprodusert:** kalt den faktiske `_on_run_finished` med kontrollert view og payload med én fullført fil, tom failed_job_indexes og `failed_jobs=['DIT aggregation']`. Faktisk statuskall: `('Batch complete.', 'success')`. En kjøring hvor filanalysene er vellykket, men sluttrapporten feiler, kan dermed presenteres som fullført.

**Rettelse/test:** separate analysefeil og sluttproduktfeil i visningen; vis error når `failed_jobs` inneholder aggregasjonsfeil, behold vellykkede filrader. Test payload med tom failed_job_indexes og `failed_jobs=['DIT aggregation']`. Oppgave R04.

## B05 — P1: Metadata fra gammel analyse godtas etter analysebytte

`gui_qt/tabs/tab_ladder/_legacy.py:354–373` nuller metadata ved `set_analysis`, men ugyldiggjør ikke `_metadata_request_id`. Callbacken ved 1932–1938 sjekker bare denne ID-en. `MainWindow.active_operation` ved 423–431 omfatter ikke metadatajobben, så byttet er tillatt.

**Reproduksjonssekvens:** start metadata for clonality → bytt til FLT3 → la gammelt resultat ankomme. Resultatet kan fylle den nye analyseflaten. Statisk bekreftet; kontrollert Qt-regresjonstest skal bygges før retting.

**Rettelse/test:** analyse-/filkontekst og request-ID må følge resultater. Ugyldiggjør gamle requests og pending auto-open ved bytte; hent eventuelt valgt fil på nytt. Test begge callback-rekkefølger. Oppgave R05.

## B06 — P2: Ladder scan og bundle-load kan låse hverandres knapper

`tab_ladder/_legacy.py:433–458` deler `_scan_request_id`, men deaktiverer bare hver sin knapp. Callbackene ved 1862–1929 returnerer for stale ID før de frigjør den gamle knappens tilstand.

**Sekvens:** start treg Scan → start Load Bundle → fullfør begge. Scan kan forbli deaktivert. Omvendt rekkefølge kan ramme Load. Statisk bekreftet.

**Rettelse/test:** én eksplisitt kildeinnlastingsoperasjon med eier-token, eller separate request-domener og en samlet control-state-avleder. Stale resultat skal aldri eie gjeldende controls. Test success/error og begge fullføringsrekkefølger. Oppgave R06.

## B07 — P2: Run-scan blir deaktivert etter analysebytte

`tab_batch/_legacy.py:543–555` nuller aktiv scan-ID uten å reaktivere Scan. Scan teller ikke i `MainWindow.active_operation`; analysebytte kan derfor kjøre reset. Gammelt resultat forkastes korrekt ved 1322–1361, men ingen callback frigjør knappen.

**Rettelse/test:** inkluder scan i operasjonsmodellen eller gjenopprett controls eksplisitt når den ugyldiggjøres. Test forsinket scan → analysebytte → success/error. Oppgave R06.

## B08 — P2: Rerun kan fullføre inn i en annen Ladder-visning

`tab_ladder/_legacy.py:1071–1093` deaktiverer rerun/editor/refresh, men lar kildevalg/scan/bundle-load fortsette. Callback ved 1337–1355 oppdaterer nåværende metadata/rapportvisning og status, selv om den viste filen/bundlen er byttet.

**Avgrensning:** consumption registreres med payloadens filsti; reviewen hevder ikke at denne nøkkelen skrives på feil fil. Feilen er ueid visnings-/sessiontilstand og misvisende resultat i ny kontekst.

**Rettelse/test:** sperr alle kontekstendrende handlinger under rerun, også programmatisk inngang, eller valider et komplett immutable operation-token før visningen endres. Test rerun A → forsøk bundle B → fullfør A. Oppgave R05.

## Risikoer som fortsatt trenger egen undersøkelse

- Close under Run/Archive/QRunnable: definer trygg stans og venting uten å fryse GUI; ingen påstand om reprodusert krasj ennå.
- To app-prosesser som skriver samme settings/SQLite/workbook, låste Excel-filer, disk-full og frakoblet nettverksdisk.
- Private referansedata, høy DPI, tastaturflyt og faktisk Windows-pakking. Offscreen tester er nødvendige, ikke tilstrekkelige.

## ML-avvikling: viktige avhengighetsfunn

- Pipeline laster `ml_runtime` og kaller `_attach_batch_context_and_ml`; batch eksporterer learning-annotasjoner ved aktivering i YAML.
- Tracking importerer `ml_data_contract` og `interpretation_units`; disse må frikobles før modulene slettes.
- `interpretation.py` inneholder både regelmotor og annotasjons-/treningshjelpere. Hele filen må ikke slettes.
- `ladder_review_labels.py` er aktiv kvalitetskontroll for ladder, ikke avviklet labeling.
- `scikit-learn` brukes i `fraggler/fraggler.py` og `core/analysis/_legacy.py` til fitting/R². Blind sletting av dependency ville bryte aktiv analyse.
- Fjerning av forskningsfunksjoner reduserer vedlikeholdsflate, men retter ikke B01–B08 alene.
