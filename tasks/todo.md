# Utføringsliste for GPT-5.6 Sol

Les `plan.md` først. Status per 2026-09-19: alle implementeringsoppgaver er åpne.
S = liten oppgave, M = middels. Filoversiktene er startpunkter, ikke anledning til å endre hele filene.

## S01 — Beskytt aktiv kjøring mot analyse- og settingsbytte (M)

Funn: R01. Avhengigheter: ingen. Filer: `gui_qt/main_window.py`, `gui_qt/tabs/tab_batch/_legacy.py`, `gui_qt/tabs/tab_archive_runner.py`, ny `tests/test_active_operation_navigation.py`, eventuelt `gui_qt/tabs/tab_ladder/_legacy.py` for rerun-status.

- [ ] En aktiv Run, Archive eller ladder-rerun hindrer skifte av analysetype og endring av kjøringsinnstillinger; Log og fremdrift er fortsatt tilgjengelige.
- [ ] Kø, review-kontekst og stoppfunksjon beholdes. Vellykket slutt, feil og avbrudd frigjør sperren.
- [ ] Programmatisk navigasjon og settings-signaler følger samme regel; en statusmelding forklarer hvorfor et valg er utilgjengelig.

Implementering: bruk én appnivåfunksjon for å sjekke aktive operasjoner. Ikke spre separate busy-regler i hver knapp. Kontroller også klikk på samme analysegruppe. Ikke hev at global settings-arkitektur er fullstendig isolert av denne rettelsen.

Verifikasjon: `python -m pytest -q tests/test_active_operation_navigation.py tests/test_main_window_navigation.py tests/test_manual_ladder_rerun.py`. Simuler worker-progress og slutt uten ekte analyse; forsøk analysebytte og settings-save midtveis. Kontroller normal navigasjon etter slutt.

## S02 — Gi settings-lagring en ærlig og atomisk kontrakt (M)

Funn: R02, R11. Avhengigheter: ingen. Filer: `config.py`, `gui_qt/tabs/tab_settings.py`, `tests/test_tab_settings_save.py`, ny `tests/test_settings_persistence.py`.

- [ ] Lagre til midlertidig fil i samme katalog og erstatt målet atomisk. Feil bevarer eksisterende YAML.
- [ ] UI får eksplisitt suksess/feil; bare suksess sender `settings_saved` og endrer den aktive konfigurasjonen.
- [ ] Reell save/load, skrivefeil og opprydding etter feil testes med midlertidige filer; APP_SETTINGS gjenopprettes etter hver test.

Implementering: kartlegg nåværende save-kallere før kontraktendring. Et boolsk resultat kan innføres kompatibelt for eksisterende kallere; UI må håndtere det. Bygg et kopiert forslag fra feltene, lagre dette og publiser først deretter. Behold redigerte felt ved feil. Oppdater andre kallere i egne oppgaver ved behov.

Verifikasjon: `python -m pytest -q tests/test_settings_persistence.py tests/test_tab_settings_save.py tests/test_master_tracking_settings.py`. Injiser feil ved skriving/replace og kontroller at den gamle filen er uendret og at ingen suksesssignal sendes.

## S03 — Skill globale settings fra analyseprofiler (M)

Funn: R03. Avhengigheter: S02. Filer: `gui_qt/main_window.py`, `gui_qt/tabs/tab_settings.py`, ny `gui_qt/tabs/tab_app_settings.py`, `tests/test_tab_settings_save.py`, `tests/test_main_window_navigation.py`.

- [ ] Appinnstillinger har én redigeringsflate/eier for annotator/Author og globale QC-valg. Analyseprofiler lagrer bare sine egne felter.
- [ ] Lagre profil A, så profil B: globale verdier og A sine profilvalg beholdes. Ulagrede endringer blir tydelig markert og overskrives ikke av bakgrunnsoppfrisking.
- [ ] Eksisterende YAML fortsetter å laste uten å miste globale verdier eller analyseprofiler; Ctrl+, har et klart, dokumentert navigasjonsmål.

Implementering: bevar lagringsnøkler i første omgang. Navngi Author etter faktisk bruk også i annotasjoner/review. Unngå tre skjulte kopier av globale felt. Ikke innfør en ekstra konfigurasjonsdatabase.

Verifikasjon: `python -m pytest -q tests/test_tab_settings_save.py tests/test_main_window_navigation.py tests/test_master_tracking_settings.py`. Gjenta den konkrete A→B-overskrivingssekvensen fra reviewen og åpne/lagre/gjenåpne hver profil.

## S04 — Gjør engine-status korrekt i Settings (S)

Funn: R07. Avhengigheter: S03. Filer: settings-siden som eier engine-visningen, `gui_qt/tabs/tab_archive_runner.py`, `tests/test_tab_settings_save.py`, eventuelt `README.md`.

- [ ] Vanlig UI har ikke lenger en avkrysning som lover vedvarende Python-fallback. Vis faktisk engine-tilgjengelighet/versjon med eksisterende lettvekts-API.
- [ ] Rust-first-kontrakten og numeriske standarder er uendret; manglende engine har en forståelig status.
- [ ] Archive-hjelpeteksten peker til korrekt engine-informasjon og beskriver ikke en fjernet bryter.

Verifikasjon: Settings-test med tilgjengelig/manglende engine og startup-test: `python -m pytest -q tests/test_tab_settings_save.py tests/test_startup_lazy_imports.py tests/test_strict_rust_ladder_mode.py`. Ikke legg tunge imports i GUI-startup for å vise status.

## S05 — Fjern/deaktiver lagret ladderkorrigering via riktig lager (M)

Funn: R04. Avhengigheter: ingen. Filer: `core/ladder_adjustment_store.py`, `core/ladder_adjustment_io.py`, `gui_qt/tabs/tab_ladder/_legacy.py`, ny `tests/test_ladder_adjustment_removal.py`, `tests/test_ladder_draft_workflow.py`.

- [ ] Operasjonen gjelder bare valgt kildehash + ladder + kanal; andre korrigeringer beholdes. Identiske kildekopiers delte identitet er beskrevet.
- [ ] Etter fjerning og gjenåpning lastes ikke gammel record eller gammel sidecar tilbake. Bruk deaktivering/tombstone hvis det er nødvendig for å hindre gjenimport og bevare historikk.
- [ ] Bare vellykket operasjon rydder cache, korrigeringsstatus og berørt review-/rerun-state; feil viser ærlig status.

Verifikasjon: `python -m pytest -q tests/test_ladder_adjustment_removal.py tests/test_ladder_draft_workflow.py tests/test_manual_ladder_rerun.py`. Midlertidig DB via `HEMAFRAG_LADDER_ADJUSTMENT_DB`; test SQLite-only, sidecar-only, begge, feil og to uavhengige identiteter. Ingen sletting av operatørens database eller FSA.

## Kontrollpunkt A

- [ ] S01–S05 er verifisert. Simuler flyten kjør → review → utkast → gjenåpne → godkjenn → rerun.
- [ ] Lagre settings med skrivefeil og bytt mellom profiler; ingen falsk suksess eller tap av innstillinger.
- [ ] Diff-review og oppdatert status viser konkrete resultater per oppgave.

## S06 — Fjern Compare fra operatørflyten (M)

Funn: R05/R08/R10. Avhengigheter: S01. Filer: `gui_qt/main_window.py`, `gui_qt/tabs/tab_batch/_legacy.py`, `tests/test_main_window_navigation.py`, relevant eksisterende Run-review-test.

- [ ] Compare fjernes fra alle sidebarmenyer, oppstartskonstruksjon og Run-knappen/handoff. Ingen tomme eller døde handlinger står igjen.
- [ ] Navigasjon bruker semantiske mål fremfor nye hardkodede posisjoner. Run→Ladder og shortcuts fungerer fortsatt.
- [ ] General viser ikke Archive Runner som et brukbart navigasjonsmål når funksjonen ikke støttes.

Verifikasjon: `python -m pytest -q tests/test_main_window_navigation.py tests/test_manual_ladder_rerun.py tests/test_qt_app_startup_review.py`. Søk `rg -n 'tab_compare|Compare|on_compare_review_queue' gui_qt`; vurder hvert gjenværende treff. Test hver analysegruppes synlige mål.

## S07 — Fjern avviklet Compare-kode etter referansesjekk (S)

Funn: R05/R08. Avhengigheter: S06. Filer: `gui_qt/tabs/tab_compare.py`, `gui_qt/tabs/tab_compare_worker.py`, `tests/test_tab_compare_redesign.py`, referanseoversikten i `tasks/review-2026-09-19.md`.

- [ ] UI/worker har ingen produkt-, script-, packaging- eller dynamiske kallere før fjerning.
- [ ] Tester som bare verifiserer den avviklede fanen fjernes eller erstattes med testen som beviser at inngangene er borte. Aktiv rapport- og review-dekning beholdes.
- [ ] `core/html_reports/comparison.py` og tilhørende tester beholdes hvis de har selvstendig bruk; eventuell avvikling av dem blir en egen commit med referansebevis.

Verifikasjon: `rg -n 'tab_compare|CompareWorker|TabCompare|build_group_comparison_html_report' . --glob '*.py'`; `python -m pytest -q tests/test_main_window_navigation.py tests/test_html_comparison_report.py tests/test_startup_lazy_imports.py` for filer som fortsatt finnes.

## S08 — Gjør Settings kompakt og validerbar (M)

Funn: R10/R11. Avhengigheter: S03/S04. Filer: `gui_qt/tabs/tab_settings.py`, `gui_qt/tabs/tab_app_settings.py`, `gui_qt/styles.py`, `tests/test_tab_settings_save.py`.

- [ ] Vanlige mapper og profilvalg kommer først; ML/learning og andre avanserte felt ligger i tydelig merket, sammenleggbar del. Lagrehandling og dirty-status er tilgjengelig uten å scrolle gjennom hele siden.
- [ ] Ugyldig regex, feil filtype og `WARN > OK` gir feltspesifikk feil før lagring. Nettverksstier skal ikke testes med langsom skanning på GUI-tråden.
- [ ] Profilspesifikke kontroller vises bare der de brukes. Off/on/disabled forklares, og innholdet har fornuftig tastaturrekkefølge.

Verifikasjon: Settings-testene + visuell kontroll av alle profiler ved 1280/1366/1920 px. Test tastatur-only lagring og feilretting. Unngå global oversettelse før språkvalg er avklart.

## S09 — Rett Archive-layout ved laptopbredde (S)

Funn: R09. Avhengigheter: ingen. Filer: `gui_qt/tabs/tab_archive_runner.py`, eventuelt `gui_qt/main_window.py`, ny `tests/test_archive_layout.py`.

- [ ] Input-/output-knapper og øvrige handlinger er fullt tilgjengelige ved 1280 × 720 og 1366 × 768, også med lange stier.
- [ ] Innhold tilpasser viewport; horisontal scrollbar kan være en sikker fallback, men skal ikke skjule manglende tilpasning av vanlig skjema.
- [ ] Lang tekst har wrap/elidering med full verdi tilgjengelig; fokus og scrolling tar brukeren til hele kontrollen.

Verifikasjon: Qt-geometritest med reell font og skjermbilder før/etter. Test 125/150 % skalering i separat Qt-prosess. `python -m pytest -q tests/test_archive_layout.py tests/test_clonality_archive_runner.py tests/test_flt3_archive_runner.py`.

## Kontrollpunkt B

- [ ] S06–S09 verifisert. Ingen Compare-innganger, General viser bare støttet navigasjon, Settings lagrer riktig scope.
- [ ] Før/etter-bilder ved laptopstørrelse er vurdert med faktisk tekst, ikke fontbokser.

## S10 — Koble CI til faktisk produkt og tester (M)

Funn: R06. Avhengigheter: ingen; kan tas tidlig. Filer: `.github/workflows/ci.yml`, `README.md`, `requirements.txt` (runtime-kommentar), eventuell egen test-/CI-konfigurasjon.

- [ ] Python-jobbene bruker støttede versjoner i tråd med pyproject; Windows er inkludert. Kjør pytest med offscreen Qt og nødvendige testverktøy som Node der en JS-test bruker det.
- [ ] Tester får isolert settings-/DB-katalog. Native-wheel-smoke kjøres eksplisitt på kompatibel Windows-jobb; bevar separat Rust-validering.
- [ ] CI må rapportere faktisk testantall og feil. Runtime-dokumentasjon og packaging har ingen motstridende støttepåstander om Python 3.10/3.11.

Verifikasjon: samme pytest-/compileall-kommandoer lokalt, deretter faktisk CI ved PR. Ingen grønn CI-påstand basert bare på YAML-inspeksjon. Ikke oppgrader alle dependencies i denne oppgaven.

## S11 — Avvikle eller plasser gamle utviklerfaner (S per deloppgave)

Funn: ubrukt-kodeoversikten. Avhengigheter: S06/S07. Først dokumenter referanser i en kort inventarliste.

- [ ] S11a: Kartlegg `tab_ml_training`, `tab_clonality_interpretation`, `tab_flt3_validation` og `_run_yearly_job` i produkt, tests, scripts, docs og packaging. Merk «aktiv», «utviklerverktøy» eller «avviklet» med bevis.
- [ ] S11b: Behandle én avviklet fane per commit: UI-modul, dens egne tester og dokumentasjon, maksimalt omtrent fem filer. Hvis faktisk manuell bruk finnes, gi den en eksplisitt utviklerinngang fremfor å koble den tilbake i operatørmenyen.
- [ ] S11c: Fjern bekreftet foreldreløs `_run_yearly_job`-wrapper separat. Behold analyse-/trenings-/rapportmotorer og historiske filformater.

Verifikasjon per commit: relevant import-/startup-test og motorens eksisterende funksjonstester. Ingen massefjerning av `*_legacy.py` eller kompatibilitetsfasader. Ved ukjent reell brukerbruk dokumenteres den konkrete usikkerheten før irreversibel produktavvikling.

## S12 — Prioriter innholdet i Run (M)

Funn: R10. Avhengigheter: S01/S06. Filer: `gui_qt/tabs/tab_batch/_legacy.py`, `gui_qt/styles.py`, ny `tests/test_run_layout.py` og eksisterende Run-review-test.

- [ ] Filvalg, primærhandling og kø får plass tidligere; store oversiktstall erstattes av kompakt, lesbar status. Tomtilstanden sier hva neste handling er.
- [ ] Ready/running/review-needed/cancelled/failed har tydelig tekst, riktig handling og konsekvent tilgjengelighet. Inputtelleren beskriver hva den teller (kilder eller filer).
- [ ] Eksisterende scan-, review- og rerun-logikk er uendret; tastaturbruk og lange filstier fungerer.

Verifikasjon: skjermbilder av tom side, syntetisk kø, aktiv kjøring og review-status ved laptopstørrelse. `python -m pytest -q tests/test_run_layout.py tests/test_manual_ladder_rerun.py tests/test_main_window_navigation.py`.

## S13 — Gjør Ladder-status og redigering tydelig (M)

Funn: R10 og gjenstående UX etter ladderrettelsen. Avhengigheter: S05. Filer: `gui_qt/tabs/tab_ladder/_legacy.py`, `gui_qt/dialogs/ladder_dialog/_legacy.py`, `tests/test_ladder_editor_layout.py`, `tests/test_ladder_draft_workflow.py`, eventuelt `gui_qt/styles.py`.

- [ ] Før filvalg vises en enkel tomtilstand. Review-bundle-felter kan åpnes når de trengs; manglende fil/kø har ingen tilsynelatende kjørbare handlinger.
- [ ] 1–2 ankre kommuniseres som «Lagre utkast»; godkjent delvis fit og konsumert rerun har egne tekster. Lagret skal ikke leses som ferdig analysert.
- [ ] Eksisterende hit-testing, eksakte markører, utkast-gjenåpning og godkjenning bevares. Kontroller med to nærliggende topper og både inn-/utzooming.

Verifikasjon: `python -m pytest -q tests/test_ladder_editor_layout.py tests/test_ladder_draft_workflow.py tests/test_ladder_partial_save.py tests/test_manual_ladder_rerun.py`. Visuell prøve med syntetisk trace og tastatur; faktisk peak-sletting i HTML skal fortsatt være uten popup.

## Kontrollpunkt C og overlevering

- [ ] Alle ferdige oppgaver har faktisk testresultat og commitreferanse; åpne kriterier er eksplisitt oppført.
- [ ] Kjør `python -m pytest -q`, `python -m compileall -q core gui_qt`, relevante startup-/packaging-smoketester og `git diff --check`.
- [ ] Gjør en samlet operatørreise for Klonalitet, FLT3 og General. Angi tydelig hvilke deler som er syntetiske og hvilke som er verifisert på ekte godkjent datasett.
- [ ] Oppdater `roadmap.md` med det som fortsatt mangler. Ikke marker faglig validering eller høy-DPI-bruk som fullført uten egne bevis.
