# Avvikling av ML og labeling

Brukerbeslutning 2026-09-19: fjern hele ML-/trenings-/labeling-funksjonaliteten, også tilhørende scripts og egne tester. Bevar brukerdata, manuell ladder-review og regelbasert analyse.

## Produktkontrakt

- Ingen ML-/labeling-fane, modellvelger, modellinnlasting, treningsjobb eller learning-eksport skal kunne aktiveres i appen, heller ikke av gammel YAML.
- Run, Archive, ladderutkast/godkjenning/rerun, regelbasert klonalitetsanalyse, FLT3 og General skal beholde sin funksjon og sine numeriske standarder.
- Ingen eksisterende FSA, modeller, labeling-filer, korrigeringsdatabase eller arbeidsbøker slettes. Historiske kolonner i eksisterende Excel-filer skal ikke gå tapt ved oppdatering; nye kjøringer skal ikke generere nye ML-/labelingfelt.
- Kode og rene funksjonstester for avviklede funksjoner fjernes fra Git-checkout; Git-historikk bevares. Tester for delte analyse-/rapportkontrakter beholdes og tilpasses.

## Avviklingsgrenser

1. Fjern `TabLabeling`, `TabMlTraining` og deres operatørinnganger. Den separate forskningsfanen for clonality interpretation fjernes hvis dens eneste formål er annotering/trening; regelmotoren i `interpretation.py` beholdes.
2. Fjern ML-innlasting fra clonality pipeline og labeling-/learning-eksport fra batch. Fjern modell-, terskel- og learning-valg fra Settings, men behold eksplisitt regelbasert interpretation-bryter dersom den fortsatt styrer aktiv regelanalyse.
3. Frikoble tracking/rapporter fra ML-moduler før disse slettes. Historiske data leses som historiske data, aldri som aktive modellresultater fra en ny kjøring.
4. Fjern trenings-, prediksjons-, kalibrerings- og labeling-moduler/scripts etter referansesjekk. Delte feature-/trace-/identitetsfunksjoner vurderes per kallested, ikke etter filnavn.
5. Fjern bare avhengigheter som ikke lenger brukes. `scikit-learn` må foreløpig beholdes: ladder-fitting og R²-beregning bruker pakken uavhengig av ML-funksjonen som avvikles.

## Verifikasjon

- Regresjonstest med gammel YAML som aktiverer ML/learning: ingen modellinnlasting/labelingeksport, normal analyse virker.
- Navigasjon/startup/settings uten avviklede kontroller eller imports.
- Eksisterende arbeidsbok med manuelle/historiske kolonner oppdateres uten tap; nye rapporter/arbeidsbøker har ikke ML-output.
- Regelbasert analyse, ladder-review, korrigeringer og rerun testes videre; ML-spesifikke tester fjernes sammen med avviklet kode, ikke for å skjule feil i aktiv funksjonalitet.
- Full pytest, compileall, import-/pakke-smoke og referansesøk. Testantallsreduksjon forklares eksplisitt.

## Robusthet utenfor denne avviklingen

Konkrete reviewfunn om bakgrunnsjobber, lagring og tilstand dokumenteres med egne, små rettingsoppgaver. Avviklingen skal ikke blandes med en stor motoromskriving. Ingen garanti om problemfri klinisk drift gis uten validering på godkjent datasett og faktisk driftsmiljø.
