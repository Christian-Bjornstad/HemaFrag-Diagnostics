# Workflow guide

## First use

Choose the assay workflow and configure input and output folders in Settings.
Set the optional master tracking workbook for that assay only if a shared
workbook should be updated. A blank master path disables shared updates.
General profiles also specify ladder, size-standard channel, sample channels,
and base-pair range.

## Analyze and review

1. On **Run**, discover inputs and check the selected run/date, patients,
   controls, and job membership.
2. Start analysis and follow progress in the run view or **Log**.
3. Open **Ladder** when review is required. Inspect the trace and mapping, then
   save valid corrections or mark input unusable with a reason.
4. Rerun the affected files. A saved adjustment is used only when its source,
   ladder, channel, and assay provenance still match.
5. Resolve the review queue and use the completion/finalization action to publish
   the final reports and refresh the assay's tracking workbook.

A failed job or `unprocessed` input needs attention before a batch can be treated
as complete. A stop-on-error run does not publish a final aggregate from the
subset that happened to finish.

## Reports

HTML reports include the Plotly runtime and can be opened offline. In supported
reports, select manual peaks and add comments, then use **Save Peaks** to save
an updated report. Reopen the saved copy to verify the retained edits. Reports
contain sample information and belong in the laboratory's approved storage.

FLT3 reports use the relevant WT/mutant windows and grouping. NPM1 has a manual
peak review workflow. Clonality and FLT3 tracking are separate; verify the output
workbook belongs to the workflow you ran.

## Recovering work

Use **Archive Runner** to resume prior runs with their manifests. Keep the run's
input paths and review bundle together. Moving or changing source files can
invalidate a correction's provenance and require a new review.

If a file needs repeated review, inspect the logged failure reason and the
selected ladder/channel. An explicit General profile that disagrees with Rust's
automatic inference is rejected for review; it is not silently analyzed with a
different size standard.

## Common problems

| Symptom | Check |
|---|---|
| Native engine unavailable | Run the availability command from the README with the same Python interpreter used to launch HemaFrag |
| Workbook cannot be saved | Close it in Excel and confirm the configured local/shared path is writable |
| No files discovered | Confirm input folder, workflow, filename/run-date filters, and selected jobs |
| Ladder review persists after saving | Rerun the affected input and inspect its new QC/provenance reason |
| Packaged app fails after copying | Extract the full ZIP and keep `_internal` next to `HemaFrag.exe` |

The [Norwegian user manual](HemaFrag_Brukerveiledning.docx) provides the detailed
operator walkthrough.
