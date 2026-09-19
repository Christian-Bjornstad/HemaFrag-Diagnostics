# Videre utvikling etter UI- og stabilitetsopprydding

Dato: 2026-09-19. Dette er utviklingsbehov, ikke en påstand om at eksisterende manifest-, QC-, ML- eller rapportfunksjoner mangler helt. Skill bekreftede hull fra områder som trenger mer verifikasjon.

Oppdatert etter implementering: S01–S10 og S12–S13 er levert, og den foreldreløse Archive-wrapperen er fjernet. Se `execution-log.md` for testbevis. De tre «Nå»-radene nedenfor beskriver opprinnelig leveransegrunnlag; gjenværende arbeid der er fysisk/faglig validering og ekstern CI. S11b (avklaring/flytting av forskningsfaner) er fortsatt åpen. Compare-worker er fjernet, og den observerte Archive-klippingen ved laptopbredde er rettet; generell worker-livssyklus og høy-DPI-validering gjenstår.

## Neste nødvendige leveranser

| Prioritet | Behov | Nåværende grunnlag / hull | Ferdig når |
|---|---|---|---|
| Nå | Stabil kjørings- og settingsflyt | Bekreftede R01–R04/R07 | S01–S05 oppfylt |
| Nå | Enklere navigasjon og Settings | Compare ubrukt, feil kontekst, General→Archive unsupported | S06–S09 oppfylt |
| Nå | Reell automatisert regresjonskontroll | Lokal testsuite finnes; CI kjører feil runtime og bare et lite utvalg | S10 og isolerte UI-tester oppfylt |
| Neste | Fast kjøringskontekst gjennom hele motoren | Registry/pipeline leser global `APP_SETTINGS`; UI-vern alene er begrenset | Analyse-ID, settings-snapshot og run-ID følger hvert arbeid eksplisitt; endring i UI påvirker ikke startet arbeid |
| Neste | Livssyklus for bakgrunnsjobber | Run har stopp; ingen appnivå-closeEvent funnet i gui_qt, Compare har QThread | Definert stans/avslutning for alle workertyper; ingen ødelagte referanser, falsk slutt eller halvpresenterte resultater |
| Neste | Historikk for manuelle korrigeringer | SQLite lagrer siste record med UPSERT; loader importerer sidecar | Tidligere revisjon, aktivering/deaktivering, kildeidentitet, operatør og konsumert revisjon kan spores |
| Neste | Backup og flytting av arbeidsoppsett | Settings og ladder-DB er lokale; full backup-/restoreflyt ikke verifisert | Dokumentert eksport/import og testet gjenoppretting på ny maskin uten å miste korrigeringsidentitet |
| Neste | Reelle arbeidsflyttester | Mye unit-testdekning, men påviste UI-feil passerte | Midlertidig appmiljø tester kjør→review→lagre→gjenåpne→rerun→rapporter med feilinjeksjon |
| Neste | Windows- og høy-DPI-validering | Offscreen ved 1366 × 768 viser klipping; fysisk DPI ikke prøvd | 100/125/150/200 %, laptop/ekstern skjerm, lange stier og keyboard-only kontrollert |
| Senere | Avgrensning av forskningsverktøy | Flere testede UI-moduler uten produktinngang | Tydelig operatørprodukt og eksplisitt utvikler-/forskningsverktøy med egne innganger |
| Senere | Målrettet legacy-reduksjon | Store klasser/filer; fasader finnes, men mye ansvar ligger samlet | Ett ansvar flyttes og total kompleksitet reduseres per commit; offentlig importkontrakt og numerisk resultat bevares |
| Senere | Reproduserbar installasjon | Pythonavhengigheter har intervaller, ingen komplett Python-lock funnet | Plattform-/Pythonspesifikk validert installasjonsliste med versjoner og reproduserbar wheel/install-smoke |

## Egne utviklingspakker etter denne planen

### D01 — Eksplisitt kjøringskontekst

Start med kallkjeden `TabBatch → core.batch → core.runner → core.pipeline → registry`. Kartlegg alle reads av APP_SETTINGS i denne kjeden. Innfør en liten, eksplisitt kontekst med analyse-ID, profilkopi og run-ID ved arbeidsstart. Migrer én kjøringsvei om gangen; behold kompatibilitet for CLI under overgangen.

Akseptanse: to syntetiske kjøringer med ulike profiler påvirker ikke hverandre; callbacks knyttes til riktig run-ID; manifestet beskriver de innstillingene som faktisk ble brukt. En endring i GUI etter arbeidsstart endrer ikke dispatch eller rapportkontekst.

### D02 — Korrigeringshistorikk og gjenoppretting

S05 retter deaktivering. Neste steg er revisjoner og gjenoppretting: avklar om historikken skal være append-only, hvilken identitet identiske FSA-kopier deler, og hva «angre» betyr etter at rapport allerede er laget. Ikke bruk sletting av en hel DB-fil som normal brukerhandling.

Akseptanse: en rapport/rerun kan knyttes til eksakt korrigeringsrevisjon; tidligere revisjoner kan inspiseres; eksport og gjenoppretting er testet i isolert miljø. Retensjon og operativ backup må avklares med de som drifter løsningen.

### D03 — Samlet rapport-/redigeringsflyt

Den nye peak-slettingen er testet uten popup. Neste audit må dekke legg til, flytt, slett, eventuelt angre, lagring/eksport og gjenåpning i genererte HTML-rapporter. Dokumenter hvilke endringer som bare finnes i nettleseren, og hvilke som faktisk påvirker senere analyse eller eksport.

Akseptanse: operatøren ser hva som er lagret; eksakte markøridentiteter bevares; tabell/plot/eksport er konsistente. Ingen ny Compare-fane bygges uten konkret brukerbehov; eventuell sammenlikning bør bruke allerede analyserte, manifestbundne resultater.

### D04 — Validert datasett og ytelsesgrunnlag

Eksisterende Plan 13/15 har referanser og benchmarkarbeid. Oppdater dem på et godkjent privat utvalg med vanskelige ladders, manglende kanaler, lavt signal, delvis mapping, flere samtidige jobber og store rapporter. Hold rådata utenfor Git.

Akseptanse: forventet resultat/eksplisitt reviewutfall per case, ingen forsvunne input, målt tid/minne på arbeids-PC og sammenlikning mot godkjent referanse. Nye fitting-/ML-standarder krever sin egen vurdering og skal ikke smugles inn i UI-opprydding.

### D05 — Produkt- og vedlikeholdsdokumentasjon

Skriv en kort operatørguide for innlesing, kjøring, ladderutkast, godkjenning, rerun og feilretting. Oppdater arkitekturbeskrivelsen fra sidecar som primærlager til SQLite, med kompatibilitetsimport tydelig beskrevet. Rett runtime-støttematrisen og dokumenter hvor konfigurasjon, korrigeringer og rapporter ligger.

Akseptanse: dokumentasjonen følger faktisk UI; en ny operatør kan fullføre en syntetisk prøve uten kodekunnskap; en utvikler kan se hvilke moduler som er aktive, avviklet eller forskningsverktøy.

## Ting som må undersøkes videre, uten å kalles bekreftede feil

- Robusthet ved lukking av vinduet under Archive-/workerarbeid, prosesskrasj og gjenopptak etter omstart.
- Tunge ML-statuskontroller ved hvert tastetrykk i modellstien og potensielt blokkerende nettverksmapper; profiler før optimalisering.
- HTML-escaping av filnavn/kommentarer, dependency-sårbarheter og data i logger: trenger separat målrettet sikkerhetsreview. Denne reviewen fant ikke grunnlag for å erklære disse områdene sikre eller sårbare.
- Tilgjengelighet med skjermleser, kontrast i alle tilstander og fysisk tastaturnavigasjon ved høy DPI.
- Hvilke Pythonavhengigheter som virkelig trengs i distribusjonen kontra utvikling/forskning. Kjør import-/packaging-audit før reduksjon.

## Anbefalt leveranserekkefølge

Først gjennomfør stabilitets- og oppryddingsoppgavene i `todo.md`. Deretter D01/D02 for mer pålitelig tilstand og sporbarhet, D03 for komplett redigeringsflyt og D04 for fersk validering/ytelse. D05 oppdateres samtidig med de aktuelle endringene. Utvidelser som nye modeller, nye analysetyper og ny sammenlikningsfunksjon kommer etter at dette grunnlaget er verifisert.
