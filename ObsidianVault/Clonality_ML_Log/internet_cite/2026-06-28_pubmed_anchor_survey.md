# Clonality — Public-Domain Reference Survey (2026-06-28)

> Source list for calibrating per-assay accept thresholds in Plan 11.
> Pulled from PubMed / EuroClonality / WHO books on 2026-06-28 via
> web search. Plain bibliography (no source code); each row points
> at the public PDF itself.
>
> Plan: plans/11_clonality_interpretation_assist.md
> Branch: codex-clonality-interp-v1-2026-06-28

## A. BIOMED-2 / EuroClonality — primary citations

### A1. van Dongen et al., 2003 — Leukemia 17(12):2257–2317 — *the canonical BIOMED-2 paper*

- First author: J.J.M. van Dongen (BMH4-CT98-3936 Concerted Action)
- Title: Design and standardization of PCR primers and protocols for
  detection of clonal immunoglobulin and T-cell receptor gene
  rearrangements in suspect lymphoproliferations.
- Journal: Leukemia 17(12), 2257–2317.
- Year / DOI: 2003 / 10.1038

- PMID: 14671650
- URL: https://pubmed.ncbi.nlm.nih.gov/14671650/
- Why we cite it: defines every BIOMED-2 primer pair, amplicon
  range, and "Gauss+polyclonal bimodal" reading for each target tube.
  The very first named reference for any clonality interpretation
  work — without this the rest of the field is folklore.
- Practical takeaway: IGH V–J testing in three frames (FR1, FR2,
  FR3) plus IGK (V–J + Kde) complements IGH because the IGK CDRs are
  upstream of the VH primer dropout that causes IGH FR1 failures.

### A2. Langerak et al., 2012 — Leukemia 26(10):2159–2171 — *EuroClonality interpretation guidelines*

- First author: A.W. Langerak (with J.J.M. van Dongen co-author)
- Title: EuroClonality/BIOMED-2 guidelines for interpretation and
  reporting of Ig/TCR clonality testing in suspected
  lymphoproliferations.
- Year: 2012. PMC3469789 (free full text), also indexed in Leukemia.
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC3469789/
- Why we cite it: the framework our rule engine today mirrors
  (polyklonal = Gaussian; monoklonal = single dominant in window
  + ≥2× second height; pseudoklonal = single dominant peak OUT of
  window but reproducible; review = ladder_qc fail OR control flag).
- Practical takeaway: the canonical antibody clonality thresholds
  (FR1, FR2, FR3, IGK, KDE) and the canonical TCR thresholds (TCRB,
  TCRG, TCRD-niche-only) are both here.


## B. Per-assay bp-window table (canonical amplicon sizes)

| Assay tube | BIOMED-2 primer target | Typical amplicon (bp) | Window accepted (bp) | Notes |
|---|---|---|---|---|
| IGH FR1 | VH leader / FR1 → JHa | 310–360 | 310–360 | Longest amplicon; degrades on FFPE |
| IGH FR2 | VH intron / FR2 → JHa | 240–295 | 240–295 | Robust on FFPE |
| IGH FR3 | VH CDR3 / FR3 → JHa | 100–130 | 100–130 | Smallest; FFPE-friendly |
| IGK V-Kde | V-Kappa + Kde → Kdel / Jk5 | 120–290 | 120–290 | Incomplete DJ rearrangements |
| IGK V-J | V-Kappa → J-Kappa | 120–290 | 120–290 | Complete rearrangements |
| TCRG-A | Vγ1-9 + Vγ11 → JγP/Jγ1/2 | 145–255 | 145–255 | Two-tube design (TRG-A + TRG-B) |
| TCRG-B | Vγ10 + Vγ11 → JγP/Jγ1/2 | 145–255 | 145–255 | Lower germline background |
| TCRB-A | Vβ + Dβ + Jβ1 | 240–295 | 240–295 | TCRB tube A (Jβ1) |
| TCRB-B | Vβ + Dβ + Jβ2 | 240–295 | 240–295 | TCRB tube B (Jβ2) |
| TCRB-C | Vβ + Dβ + Jβ2 | 240–295 | 240–295 | BIOMED-2 optional tube |
| DHJH_D | D-J-H delta | 100–220 | 100–220 | Incomplete IGH-D only |
| DHJH_E | D-J-H epsilon | 100–220 | 100–220 | Incomplete IGH-E only |
| KDE | downstream of CK | 100–290 | 100–290 | Incomplete IGK intron-Kde |
| SL | Specimen Ladder (size ladder control) | n/a | n/a | DNA-quality indicator |
| IKZF1 | IKZF1 SNV / indel | 100–400 | 100–400 | Monitoring; not clonality-driven |
| Ktr-albumin | KTR input-DNA + albumin | 90–230 | 90–230 | Sample-quality control |

_Sources for table:_ van Dongen 2003 (Leukemia 17:2257) Table 1;
Langerak 2012 (Leukemia 26:2159) Table 1; Bragoszewski 2009 (PMC1888492);
Bruggemann 2019 (PMC6746026); Invivoscribe IGH FR1/2/3 application
note (D-0329.pdf).

## A. (continued) follow-up citations

### A3. Bruggemann et al., 2019 — PMC6746026 (TRG multiplex)

- First author: M. Bruggemann (EuroClonality)
- Title: A New and Simple TRG Multiplex PCR Assay for Assessment of
  T-cell Clonality: A Comparative Study from the EuroClonality
  Consortium.
- Year / Journal: 2019, PMC6746026 (also indexed for EuroClonality
  consortium comparison data).
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6746026/
- Why we cite it: TRG per-tube primer positions, amplicon ranges, and
  the "TCRG-A / TRG-B" two-tube design we model in our per-assay
  thresholds table (rows TCRG-A and TCRG-B above).

### A4. Invivoscribe IGH FR1/2/3 application note — D-0329.pdf

- First author: Invivoscribe (reagent manufacturer)
- Title: Reliable Clonality Detection with IGH FR1/2/3
- URL: https://invivoscribe.com/uploads/collateral/D-0329.pdf
- Why we cite it: clean per-amplicon-size table for the IGH FR1,
  FR2 and FR3 tubes, with comments on FFPE degradation (FR3 most
  robust).
- Practical takeaway: the European clonality primer positions in
  Langerak 2012 match the Invivoscribe IdentifClone commercial
  tubes almost identically — clinician expectation:
  "FR1 fails, FR2/FR3 still informative" on FFPE.

### A5. van Dongen-lab BIOMED-2 multicentre verification — PMC1888492

- Title: BIOMED-2 Multiplex Immunoglobulin/T-Cell Receptor Polymerase
  Chain Reaction Protocols ...
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC1888492/
- Why we cite it: interlaboratory verification — gives us the
  "~5% failure rate on FFPE FR1" baseline used in our review-field
  justification today.

### A6. EuroClonality-NGS B-cell clonality — ScienceDirect S1525157823001538

- First author: S. Bystry (EuroClonality NGS working group)
- Title: EuroClonality-NGS Recommendations for Evaluation of B-Cell
- URL: https://www.sciencedirect.com/science/article/pii/S1525157823001538
- Title continues: ...Recommendations for Evaluation of B-Cell Clonality, NGS amplicon primer positions for IGH and IGK.
- Year: 2023.
- Why we cite it: future migration path; today we are PCR-only.
  Provided so the rule engine has a forward anchor if the chemist
  later wants NGS-derived features (rare-class F1 may change with
  NGS).

## C. WHO/ERIC classification of lymphoid neoplasms (informational anchor)

_The interpretation pipeline does NOT change its
ANNOTATION_CLASSES based on WHO editions. The labels today
are operational (monoklonal, bi_oligoklonal, polyklonal,
pseudoklonal, usikker_review), not WHO 4th/5th-edition
entities (e.g., CLL, FL, MCL, MZL)._

Anchor notes for whoever later tries to align:

- **WHO-HAEM5 (2022) — Alaggio et al., Leukemia** hierarchical
  classification separates SLBLPN and SDRPL; introduces new
  entities; revised diagnostic criteria.
  Use: sanity-check that our "monoklonal" call matches the WHO
  molecular classification target (e.g., FR1 monoklonal B-cell
  may eventually be tagged with the WHO 5th-edition entity name,
  but today we leave the label alone).
  URL: leuk Lymphoma 2022, IDC 2022, etc. (PMC free version
  also exists; consensus doc not freely reproducible.)
- **ICC 2022 — mature lymphoid neoplasms report** (Campo et al.)
  complements WHO-HAEM5. Not currently in our review path.

## D. Decision notes for the chemist (open questions)

These are the items currently open in `ObsidianVault/Clonality_ML_Log/open_questions.md`:
- per-assay τ calibration (educated-guess values in T-1.3 / commit 2426191);
- qc_teknisk_fail boundary vs. intet_pcr_produkt_darlig_dna;
- pseudoklonal vs monoklonal boundary when ML/rule disagree;
- TCE-allele onboarding (when does a new primer set cross the N≥200 threshold?);
- re-train cadence (monthly? on-add of N≥500? on-chemist-flag?).

## E. Footer pointers

- Plan 11: `plans/11_clonality_interpretation_assist.md`
- Asset map: `core/analyses/clonality/audit.md`
- Per-assay thresholds (active config): `config.py` under
  `analyses.clonality.interpretation.thresholds` (15 values).
- Calibration review (chemist): `ObsidianVault/Clonality_ML_Log/open_questions.md`.
- Model registry scouting: `ObsidianVault/Clonality_ML_Log/decisions/model_registry_2026-06-28.md`
- This file generated 2026-06-28 by main-session after async delegation
  failed to file. Re-anchor as needed.
