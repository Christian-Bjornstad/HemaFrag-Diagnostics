# Robusthet — prioritert utføringsplan

Grunnlag: `review-robustness-2026-09-19.md`, funn B01–B08. Dette er konkrete rettingsoppgaver, ikke gjennomførte rettelser. ML-avviklingen har separat godkjent design og utføringsplan; ingen av oppgavene under endrer numeriske analyseterskler.

## Utføringskontrakt for GPT-5.6 Sol

Les reviewen og den aktuelle oppgaven. Én fokusert retting per commit. Skriv først en isolert test som viser brukerfeilen, kjør den og kontroller at den feiler av riktig grunn. Implementer minimalt, kjør målrettede tester og oppdater execution-log med faktisk resultat. Ikke bruk brukerens config/DB eller kliniske filer. Hovedagenten reviewer diff før neste overlappende oppgave. Ingen stor legacy-omskriving, ingen skip av aktive tester og ingen påstand om klinisk validering på grunnlag av unit-tester.

## R01 — Tøm utgåtte genererte Excel-verdier (P1, S)

Funn B01. Filer: `core/tracking_workbook_io.py`, `tests/test_tracking_workbook_io.py`. Avhengigheter: ingen; gjør før ML-plan M03.

- [ ] Legg til parametrisk test for None/NaN/pd.NA på samme radidentitet. Utgangspunkt:

```python
workbook = Workbook()
upsert_frame(workbook, "Runs", pd.DataFrame([{"ID": "A", "Value": 42}]), key_columns=["ID"])
upsert_frame(workbook, "Runs", pd.DataFrame([{"ID": "A", "Value": None}]), key_columns=["ID"])
assert workbook["Runs"]["B2"].value is None
```

- [ ] Endre setter til `ws.cell(row, headers[column]).value = _excel_value(record.get(column))`. Kontroller at 0 og False ikke regnes som manglende, og at brukerformler utenfor genererte kolonner er uendret.
- [ ] Verifiser `python -m pytest -q tests/test_tracking_workbook_io.py tests/test_clonality_tracking_output.py tests/test_flt3_tracking_output.py`; commit `fix: clear missing generated tracking values`.

## R02 — Krasjsikker publisering av tracking (P1, M)

Funn B02. Filer: `core/tracking_workbook_io.py`, `tests/test_tracking_workbook_io.py`, ved behov de to kallstedene `core/analyses/clonality/tracking_excel.py` og `core/analyses/flt3/qc_tracker.py`. Avhengigheter: R01; beslutning om filidentitet før implementering.

- [ ] Dokumenter at nåværende test krever bevart filidentitet. Anbefalt ny kontrakt prioriterer gyldig gammel/ny fil ved crash fremfor samme filesystem entry; Excel-referansebruk må verifiseres på driftsmaskin.
- [ ] Først test feil i publisering: `os.replace` som kaster PermissionError skal bevare original bytes. Test også vellykket publisering, fsync-feil før replace og staging-opprydding uten å fjerne siste gode kopi.
- [ ] Bruk staging på samme volum/katalog, lukk og fsync før replace. Ikke bruk fallback som skriver direkte over original når replace er blokkert. Vis at Excel må lukkes ved låst fil, ikke suksess.
- [ ] Verifiser trackingtestene fra R01 og manuell låst-Excel-test i isolert kopi. Ikke marker denne som fullført etter bare mocked PermissionError.

## R03 — Transaksjonell ladder-review-bundle (P1, M)

Funn B03. Filer: ny `core/ladder_review_bundle_store.py`, `gui_qt/tabs/tab_batch/_legacy.py`, `gui_qt/tabs/tab_ladder/_io.py`, ny `tests/test_review_bundle_transactions.py`. Avhengigheter: ingen; ikke parallelt med Ladder-kodeendringer.

- [ ] Test skrivefeil etter CSV-header: gammel CSV/summary må fortsatt kunne lastes konsistent. Test avbrudd etter første replace og recovery ved neste lesing.
- [ ] Definer én offentlig funksjon `save_review_bundle(cases_path: Path, rows: list[dict], fieldnames: list[str], summary_path: Path | None, summary: dict) -> None`; feil kastes til UI. Staging + journal/recovery må identifisere hvilken revisjon CSV og summary tilhører. Alternativt gjør summary eksplisitt avledet og gjenoppbyggbar fra canonical CSV ved lesing; velg og dokumenter én kontrakt før implementering.
- [ ] Flytt både Run-carry og Ladder-save til denne kontrakten. Fjern silent exception-pass for summary-lagring; suksess vises først når valgt kontrakt er oppfylt.
- [ ] Verifiser `python -m pytest -q tests/test_review_bundle_transactions.py tests/test_manual_ladder_rerun.py tests/test_ladder_draft_workflow.py tests/test_ladder_adjustment_removal.py`.

## R04 — Sluttstatus må inkludere rapportfeil (P1, S)

Funn B04. Filer: `gui_qt/tabs/tab_batch/_legacy.py`, ny `tests/test_batch_completion_status.py`; eventuelt `core/batch.py` dersom resultatkontrakten må presiseres. Avhengigheter: ingen.

- [ ] Kall `_on_run_finished` med denne syntetiske payloaden og assert error-status, bevart vellykket filrad og nevnt rapportfeil:

```python
result = {
    "total_jobs": 1,
    "completed_job_indexes": [0],
    "failed_job_indexes": [],
    "failed_jobs": ["DIT aggregation"],
}
```

- [ ] Skill file/job-feil og output/finalization-feil. Ikke legg rapportfeilen inn som falsk filindeks. Suksess forutsetter at begge feilklassene er tomme; cancellation/review-needed beholder egen status.
- [ ] Verifiser `python -m pytest -q tests/test_batch_completion_status.py tests/test_manual_ladder_rerun.py tests/test_run_layout.py`.

## Kontrollpunkt 1

- [ ] R01/R03/R04 grønne og reviewet; R02s kontraktbeslutning dokumentert.
- [ ] Feilinjeksjon viser bevart lagret data og ingen falsk ferdigstatus.

## R05 — Bind Ladder-resultater til riktig kontekst (P1/P2, M)

Funn B05/B08. Filer: `gui_qt/tabs/tab_ladder/_legacy.py`, ny `tests/test_ladder_async_context.py`, `tests/test_active_operation_navigation.py`. Avhengigheter: ingen; sekvensielt med R06.

- [ ] Bruk kontrollert Worker/threadpool-fake som lagrer arbeid og lar testen sende result/error manuelt. Test metadata A → analysebytte B → callback A; `_apply_metadata_result` skal ikke kalles for A i B.
- [ ] Ugyldiggjør analysis-sensitive request-ID-er og pending editor-open ved bytte. Bruk token `(request_id, analysis_id, resolved_file_path)` ved resultatanvendelse; rydd controls etter gjeldende operasjon, ikke etter tilfeldig gammel callback.
- [ ] Under single-/bundle-rerun: sperr source/file/bundle-skifte eller avvis det på funksjonsinngang med forståelig status. Test programmatisk `load_review_bundle_from_path`, ikke bare disabled knapp. Resultat A skal aldri fremstå som resultat for vist B.
- [ ] Verifiser `python -m pytest -q tests/test_ladder_async_context.py tests/test_active_operation_navigation.py tests/test_manual_ladder_rerun.py tests/test_ladder_draft_workflow.py`.

## R06 — Scan/load har én tydelig livssyklus (P2, M per del)

Funn B06/B07. Avhengigheter: R05.

### R06a — Ladder scan/load

Filer: `gui_qt/tabs/tab_ladder/_legacy.py`, `tests/test_ladder_async_context.py`.

- [ ] Test Scan→Load og Load→Scan med callbackene i begge rekkefølger, både success og error. Etter siste gyldige operasjon skal alle relevante controls kunne brukes.
- [ ] Bruk én kildeinnlastingsoperasjon og avvis konkurrerende start, eller separate request-domener med samlet control-state. Ikke reparer ved å reaktivere knapper ubetinget fra stale callbacks.
- [ ] Verifiser async-context og ladder-editor-layouttestene; commit separat.

### R06b — Run scan og analysebytte

Filer: `gui_qt/main_window.py`, `gui_qt/tabs/tab_batch/_legacy.py`, `tests/test_active_operation_navigation.py`.

- [ ] Test pågående scan → forsøk analysebytte → callback success/error. Velg eksplisitt kontrakt: anbefalt blokkering mens scan eier køen; Log/progress skal fortsatt være tilgjengelig.
- [ ] Inkluder scan i aktiv-operasjon-oversikten og kontroller settings-save/programmatisk navigasjon. Sørg for at reset/error/cancel frigjør riktig eier, uten å nullstille en reell aktiv analysejobb.
- [ ] Verifiser navigation-, active-operation-, Run-layout- og eksisterende scan-tester.

## R07 — Trygg avslutning og operasjonssnapshot (undersøkelse før retting, M)

Filer som undersøkes: `gui_qt/main_window.py`, `gui_qt/workers.py` dersom finnes (ellers faktisk Worker-definisjon fra `rg -n 'class Worker' gui_qt`), Run/Archive/Ladder. Avhengigheter: R05/R06.

- [ ] Lag reproduksjon for lukk app under kontrollert pågående jobb og under rapportskriving, med midlertidig output. Registrer konkret heng/krasj/dataproblem før det kalles bekreftet feil.
- [ ] Skriv avgrenset design for closeEvent: stopp nye jobber, be om kooperativ kansellering, vent asynkront/vis fremdrift, ikke terminate midt i filskriving. Ingen blokkert GUI-tråd med ubegrenset `waitForDone`.
- [ ] Kartlegg mutable APP_SETTINGS-lesinger gjennom `TabBatch → core.batch → runner → pipeline`; lag separat vertikal migrering til snapshot per run-ID. Denne arkitekturendringen skal ikke skjules i en knappretting.

## R08 — Driftstest og ferdigkriterier (M per testreise)

Avhengigheter: R01–R06 og ML-avviklingsplanens M07. Eier: hovedagent + operatør for faktiske driftsforhold.

- [ ] Full pytest/compileall/diffcheck, fersk ekstern CI på Windows 3.12/3.14 og macOS 3.12; dokumenter skips og warnings.
- [ ] Syntetisk reise for clonality/FLT3/General: velg→scan→run→review→utkast→gjenåpne→godkjenn→rerun→rapport. Ved feil skal bruker se hvilken del som ikke er ferdig.
- [ ] Isolerte feilscenarioer: låst Excel, skrivebeskyttet output, disk-full-simulering, utilgjengelig input/nettverkssti, korrumperte config/bundle-filer, to prosesser mot samme mål. Ikke bruk produksjonsdata som feilinjeksjonsmål.
- [ ] Operatørtest ved 100/125/150/200 % DPI, lange stier og tastatur-only. Ingen avhuking bare fordi offscreen geometritest passerte.
- [ ] Privat godkjent referansedatasett verifiserer uendret regel-/ladder-/rapportresultat. Brukeren må stille dette til rådighet uten å legge rådata i Git.

## Anbefalt rekkefølge

R01 → R04 → M01/M02 → M03 → resten av ML-avviklingen. Deretter R03 og R05/R06; R02 etter eksplisitt beslutning om filidentitet. R07 gir neste arkitekturplan. R08 er avsluttende gate, ikke løfte om at programmet aldri kan feile.
