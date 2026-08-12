# Ladder Development Review Bundle Design

## Goal

Prepare the three development-partition ladder cases for an unbiased chemist review in the existing HemaFrag Ladder Studio, then compare the newly reviewed anchors with the historical manual corrections and current Rust selections.

## Review method

Use a blind-first bundle. Each development FSA is copied into a research-only bundle without its historical `.ladder_adj.json` sidecar. Ladder Studio therefore displays the current engine result without automatically applying the historical answer.

The chemist reviews each case and records one of the existing app outcomes:

- `reviewed_no_change` when the displayed anchors are correct.
- `manual_adjusted` after selecting and saving the correct anchors.

Historical sidecars remain available to the research pipeline for comparison only; they are not placed beside the review copies and are not shown before the new decision.

## Bundle layout

The bundle is created below `D:\HemaFrag_Research\ladder\current\development_review_bundle` and contains:

- `files/`: three copied FSA files with collision-safe research names.
- `ladder_review_cases.csv`: app-compatible case rows pointing to the copied files.
- `ladder_review_summary.json`: bundle metadata and instructions.
- `research_case_map.json`: copied-path to original-path, content hash, partition, ladder, historical truth source, and baseline outcome mapping.
- `README.md`: the short operator workflow.

The bundle must not contain historical adjustment sidecars. The original raw files, original sidecars, archive, and annual workbooks remain read-only.

## App workflow

1. Launch HemaFrag from the isolated worktree.
2. Open Ladder Studio.
3. Load the development review bundle.
4. Review all three cases one at a time.
5. Save either `reviewed_no_change` or a manual adjustment for every case.
6. Do not run the historical rerun from this bundle yet.

The app writes bundle annotations and adjustment records for the copied FSA paths. These research-only results are later imported and compared with the historical manual anchors and current Rust baseline.

## Completion criteria

- The app loads exactly three reachable cases.
- No copied file has a neighboring historical sidecar before review.
- Every copied FSA hash matches its original source hash.
- All paths remain outside the raw and archive roots.
- The chemist resolves all three cases.
- The research pipeline can relate each new decision back to its original development record without relying on file names alone.

## Failure handling

- Abort bundle creation if any development manifest path is missing, outside the allowed raw roots, or has a content-hash mismatch.
- Refuse to overwrite an existing non-empty review bundle.
- If the app cannot load a copied file, leave the bundle unchanged and report the exact case.
- Rust changes remain blocked until the three new decisions are imported and the gold rule is approved.
