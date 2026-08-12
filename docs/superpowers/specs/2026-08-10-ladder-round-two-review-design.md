# Ladder Round-Two Blind Review Design

## Goal

Create a second patient-clonality ladder review round that distinguishes genuine fitting failures, correct current fits, and files that cannot be fitted because no ladder was added. The round must provide enough trustworthy evidence to guide a later Rust ladder change without treating historical corrections as unquestioned truth.

## Scope and boundaries

- Use only patient-clonality FSA files from `D:\DATA\2024_DATA`, `D:\DATA\2025_data`, and `D:\DATA\2026_data`.
- Never enumerate, read, copy, or derive records from `D:\DATA\backup`.
- Keep the raw data and archive read-only.
- Write generated research artifacts only below `D:\HemaFrag_Research\ladder\current`.
- Do not modify the Rust ladder algorithm during this round.
- Do not use round-two decisions for ML training until every included case has a valid final disposition.

## Review label contract

Replace scattered hard-coded resolved-label sets with one centralized registry. Each label declares whether it resolves a case, whether its file may be rerun, and whether the result is eligible for fitting evaluation or later ML work.

| Label | Meaning | Resolved | Rerunnable | Fitting evaluation | ML eligible |
|---|---|---:|---:|---:|---:|
| `manual_adjusted` | Chemist saved corrected anchors | Yes | Yes | Yes | Yes, after dataset approval |
| `reviewed_no_change` | Chemist accepted the displayed anchors | Yes | Yes | Yes | Yes, after dataset approval |
| `excluded_missing_ladder_signal` | No ladder signal was added or is usable | Yes | No | No | No |

The registry is intentionally extensible: a new class is added once with explicit policy instead of being repeated across Ladder Studio, the batch gate, and chip-state code.

## Ladder Studio workflow

Add a visible `No ladder / human error` action for a loaded review-bundle case. Activating it requires a confirmation dialog because it changes the research disposition. Confirmation writes an annotation with:

- `label=excluded_missing_ladder_signal`
- an operator note stating that no usable ladder signal exists
- the review timestamp
- no adjustment path
- no ladder adjustment database record

The case becomes resolved and receives a reviewed chip state, but it is excluded from rerun-file lists. Existing manual-adjustment and reviewed-no-change behavior remains unchanged.

## Cohort construction

Round two contains exactly 18 unique files:

- 12 suspicious fits: 6 LIZ and 6 ROX.
- 6 blind controls: 3 LIZ and 3 ROX.

All cases must have distinct content hashes and distinct physical runs. The first-round three content hashes are excluded. Selection is deterministic and seeded so the same research state produces the same cohort.

### Suspicious cases

Select from diagnostics classified as `fit_rejected_with_usable_signal`. Balance the cohort across available years and reason families, including poor linear fit, baseline-like selected peaks, and suspicious compressed ROX families. Prefer broader coverage over repeatedly sampling the same failure signature.

### Controls

Select from diagnostics currently accepted by Rust without a review requirement. Controls must have no discovered historical manual correction and must cover both ladder families and multiple years. They are "apparently correct" rather than assumed gold; the blind review determines their final status.

### Blindness

The app-facing CSV contains no group, risk score, failure family, or control marker. Cohort allocation and selection rationale are written to a withheld manifest beside, not inside, the review bundle. The bundle's case map contains only the identity needed to join the copied file back to the research corpus.

## Bundle construction

Publish the bundle at:

`D:\HemaFrag_Research\ladder\current\round_2_review_bundle`

The bundle contains:

- `files/<ordinal>/<original-name>.fsa`
- `ladder_review_cases.csv`
- `ladder_review_summary.json`
- `research_case_map.json`
- `README.md`

The withheld selection manifest is stored at:

`D:\HemaFrag_Research\ladder\current\round_2_selection_withheld.json`

Creation uses staging plus atomic publication, refuses a non-empty destination, verifies source and copied SHA-256 values, and copies no historical sidecars. The app is launched with a new bundle-local `ladder_adjustments.sqlite3` path so hash-matched historical adjustments cannot leak into the review.

## Post-review processing

After all 18 rows have a recognized resolved label, produce a structured outcomes file and Markdown comparison containing:

- confirmed correct current fits
- confirmed manually corrected fits
- human-error/no-ladder exclusions
- Rust-versus-fresh-review scan deltas per anchor
- counts by ladder, year, assay, failure signature, and blind cohort group
- a shortlist of repeated error patterns that may justify a Rust change

Excluded cases remain in the audit denominator but not in fitting-accuracy or ML-training denominators. The withheld cohort allocation is revealed only during this post-review comparison.

## Error handling

- Abort selection if 6 unique suspicious cases for either ladder family or 3 unique controls for either family cannot be produced.
- Reject paths outside the allowed year roots.
- Reject any content hash mismatch before bundle publication.
- Refuse to overwrite an existing non-empty round-two bundle or withheld manifest.
- Fail loudly if an exclusion annotation creates an adjustment record or enters a rerun list.
- Leave existing bundle contents unchanged if publication fails.

## Verification

Automated tests must prove:

- label-policy consumers agree on resolution and rerun eligibility
- missing-ladder exclusion writes no adjustment and is counted as resolved
- excluded cases never enter rerun or training-eligible outputs
- cohort selection is deterministic, balanced 6/6 suspicious and 3/3 controls, and isolated by hash and physical run
- no first-round case is reused
- app-facing artifacts do not reveal cohort allocation
- all copied hashes match and no sidecars are present
- the existing Ladder Studio and batch review flows remain green

Before launch, a real-data audit must confirm exactly 18 reachable rows, 18 copied FSA files, zero sidecars, zero hash mismatches, blank labels, and an absent adjustment database.

## Completion criteria

- The app opens directly into Ladder Studio with the round-two bundle.
- All 18 cases can be resolved using the three registered outcomes.
- No-ladder cases require no fabricated fit and cannot enter reruns or later training.
- Cohort identity remains blind until post-review analysis.
- No Rust fitting change begins until the round-two comparison report is complete.
