# HemaFrag Open Items

- Verifisere om mer av `data/Euroclonality` skal inn i den rene prosjektmappen eller holdes utenfor
- Kjor en full lokal GUI-smoke av `qt_app.py` ved neste manuelle app-test. Import-smoke av `qt_app`, Ladder Dialog og learning-skriptene passerte 2026-05-06.
- Kjor eventuelt en ny PyInstaller-build fra den rene mappen
- Vurdere om legacy Panel-GUI fortsatt skal beholdes langsiktig
- Klonalitet ladder-plan:
  - `25OUM08246_TRb_mixA...` er ikke lenger review/manual-case etter smal ROX nonlinear start-pair repair og quadratic complete-fit waiver. Behold regelen smal og valider visuelt pa ROX-delta-bildene for de 33 endrede startparene for eventuell videre stramming.
  - Neste motorforskning bor ikke være global baseline/peak detection. Complete-QC-aware 3000-gate hadde `0` errors, `5` review, `6` soft og `2987` complete-QC-ok; aktivlisten er kjent bad/operator.
  - Operator-/bad-ladder-saker er na sentralisert i `scripts/known_ladder_cases.py` og brukes av manifest/failure-refresh.
  - LIZ soft-tail/490-500 cases er gjennomgått som complete-QC/non-regression-støy i gate-skriptene; ikke bruk dem som motortrigger uten ny visuell feil.
  - Gjenværende curated P1-motorliste etter manifest-triage er primært LIZ blob/sequence: `25OUM03913`, `25OUM16586_tcrgB_F03`, `25OUM16288_tcrgB_B03`, `26OUM05318_IGK`, `26OUM06407_TCRg_B`, pluss ROX control-instability `25OUM16586_FR3`.
