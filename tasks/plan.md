# Oppryddingsplan for HemaFrag — kjørbar med GPT-5.6 Sol

Grunnlag: review `review-2026-09-19.md`, commit `1c7c51e`, 2026-09-19.
Oppgavestatus og akseptansekriterier ligger i `todo.md`. Videre utviklingsbehov ligger i `roadmap.md`.

## Videreføring 2026-09-19 etter første leveranse

Brukeren har nå besluttet full avvikling av ML/trening/labeling, inkludert forskningsscripts og egne tester, med bevaring av brukerdata og regelbasert analyse. Dette erstatter tidligere S11-idé om å beholde ML/labeling som utviklerverktøy. Tidligere oppgaver/resultater nedenfor bevares som historikk.

- Ny robusthetsreview: `review-robustness-2026-09-19.md` (B01–B08).
- Prioritert robusthetsplan: `robustness-plan-2026-09-19.md` (R01–R08).
- Godkjent avviklingsdesign: `../docs/superpowers/specs/2026-09-19-remove-ml-labeling-design.md`.
- Godkjent utføringsplan: `../docs/superpowers/plans/2026-09-19-remove-ml-labeling.md` (M01–M07).

M01–M07, R01 og R04 er implementert. De gjenværende R-oppgavene står i `todo.md` og `roadmap.md`; historikken nedenfor beholdes som opprinnelig leveransegrunnlag.

## Mål og avgrensning

En operatør skal kunne velge analyse, kjøre filer, rette ladder, lagre innstillinger og gjenoppta arbeid uten skjult kontekstbytte eller misvisende status. Fjern den ubrukte Compare-flyten og gjør Settings enklere. Behold analysealgoritmer, rapportberegninger og Rust-first-standardene under denne oppryddingen.

Dette er planleveransen brukeren ba om. Implementeringen er delt i små oppgaver for senere utføring med 5.6 Sol; ingen av oppgavene er markert ferdig bare fordi dagens tester er grønne.

## Produktbeslutninger i planen

1. Compare fjernes fra vanlig navigasjon og Run-handoff, basert på brukerens opplysning om at funksjonen ikke brukes. Rapportbyggere vurderes separat etter referansesjekk.
2. Settings beholdes. Globale innstillinger får én eier, analyseprofiler beholder egne lagringsområder.
3. Rust-status blir informasjon i standard-UI. Denne planen gjeninnfører ikke Python som generell standardmotor.
4. General viser bare støttede verktøy. ML-/trenings-/labelingfunksjonalitet er avviklet; FLT3-valideringsverktøy vurderes separat.
5. Nåværende farger og komponentstil beholdes. Layout, tetthet, tilbakemeldinger og tilgjengelighet forbedres.
6. Ingen stor omskriving av `_legacy.py`. Trekk ut ett avgrenset ansvar om gangen når en konkret oppgave trenger det.

## Rekkefølge og avhengigheter

| Bølge | Oppgaver | Leveranse |
|---|---|---|
| A: Stabilitet | S01, S02, S03, S04, S05 | Aktiv kjøring beskyttet, ærlig lagring, riktige settings, fungerende fjerning |
| Kontrollpunkt A | Målrettede tester + én isolert operatørreise | Ingen tap av kjørings-/reviewtilstand |
| B: Forenkling | S06, S07, S08, S09 | Compare avviklet, støttet navigasjon, Settings og Archive ryddet |
| Kontrollpunkt B | Qt-visuell kontroll + navigasjonstester | Ingen døde knapper eller klippede hovedkontroller |
| C: Vedlikehold | S10, S11, S12, S13 | Reell CI, dokumentert kodeavvikling, ryddigere Run/Ladder |
| Kontrollpunkt C | Full pytest, compileall, startup- og packaging-smoke | Samlet opprydding er reviewbar |

S10 kan tas tidligere; den gir testvern for resten. S01 skal gjennomføres før nye endringer som påvirker navigasjon under kjøring. S03 bygger på S02; S08 bygger på S03/S04; S07 bygger på S06. S12 og S13 må ikke blandes i samme commit som numeriske endringer.

## Arbeidsinstruks til 5.6 Sol

Kopier denne prompten når implementeringen skal starte:

> Les tasks/review-2026-09-19.md, tasks/plan.md og tasks/todo.md. Gjennomfør neste uferdige oppgave i godkjent rekkefølge, med dens akseptansekriterier og verifikasjon. Begynn med git status og gjeldende branch; bevar andres endringer. Reproduser den relevante feilen med isolerte settings, midlertidig ladderdatabase og syntetiske testdata. Implementer én avgrenset endring og kjør relevante tester. Oppdater oppgavestatus med faktiske kommandoer/resultater og lag en fokusert commit. Fortsett til neste oppgave når avhengighetene er oppfylt. Ikke bruk ekte brukerinnstillinger eller kliniske filer som testdata. Ikke endre analyseterskler, beregningsmetoder eller Rust-standard for å få tester grønne. Dersom en oppgave trenger mer enn omtrent fem produksjons-/testfiler, del den i flere reviewbare underoppgaver før større endringer. Lever konkret avvik når et kriterium ikke kan verifiseres. Ingen push, merge eller deploy er nødvendig for denne planen.

## Felles ferdigkriterier

- Atferdsfeil har en test som feiler før rettelsen og beviser brukerutfallet etterpå. Rene tekst-/spacing-endringer trenger visuell kontroll, ikke implementasjonskopierende tester.
- UI-tester bruker midlertidig konfigurasjon og database; de skal ikke skrive til operatørens hjemmekatalog eller globale produksjonsinnstillinger.
- Endrede testfiler lintes; eksisterende lint-gjeld brukes ikke som grunn til å svekke kontroller. Ikke kjør mekanisk formattering av hele legacy-filer.
- Diff sjekkes for uvedkommende endringer, utilsiktet tap av tester, pasientdata og lokale stier.
- Qt-endringer vurderes ved 1280 × 720, 1366 × 768 og 1920 × 1080. Bruk ekte fonter; gjenta relevante kontroller ved 125/150 % skalering. Offscreen-verifikasjon erstatter ikke all fysisk høy-DPI-testing.
- Hver commit skal kunne forklares med ett brukerproblem og et verifisert resultat.

## Kommandoer og kontrollpunkter

PowerShell:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q <testfilene oppgaven angir>
python -m compileall -q core gui_qt
git diff --check
```

Ved samlet kontrollpunkt C: `python -m pytest -q`. Bruk eksisterende startup-/pakke-/native-tester; dokumenter eksplisitt om native wheel mangler. Kjøringer mot et godkjent ekte FSA-utvalg tilhører den senere valideringspakken i roadmap.

## Særskilte hensyn

- SQLite-record er kilde-/ladder-/kanalspesifikk og kan deles av identiske filkopier. Deaktivering må dokumentere denne semantikken og hindre sidecar-gjenimport. Ikke slett hele databasen.
- Global konfigurasjon har mange kallere. S02 beholder en kompatibel kontrakt for eksisterende kallere; en bred migrering må deles i egne commits.
- S01s UI-vern er første tiltak. Fullt immutable kjøringssnapshot gjennom alle lag er en separat videreutviklingspakke, ikke noe som kan hevdes løst med bare deaktiverte knapper.
- Ved avvikling av gamle faner: bevar motorer, dataformater og gyldige historiske artefakter. Oppdater tester når produktkontrakten faktisk endres; ikke slett feildekning for å få grønt.

## Avklaringer som kan vente til aktuell oppgave

- Norsk eller engelsk som gjennomgående operatørspråk? Funksjonsrettelser kan gjennomføres først; unngå omfattende oversettelse før valget er tatt.
- Skal trenings-/validerings-UI fortsatt kunne startes som utviklerverktøy? S11 kartlegger bruken før konkret avvikling.
- Hvordan skal langtidslagring, backup og historikk for manuelle korrigeringer håndteres operativt? Dette påvirker roadmap, ikke de første UI-rettelsene.
