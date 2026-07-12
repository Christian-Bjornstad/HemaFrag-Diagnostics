# Plan 13 — ML Learning Tab + Annotation Panel (Plotly) for Clonality

> Branch start: `ml-clonality-interpretation-2026-06-27` (carries Plan 11 + Phase 12).
> Offshoot branch: `feat/ml-learning-tab-2026-07-12` (this plan).
> Goal: connect the rule-based clonality interpreter to ML training via an
> in-app workflow the chemist can drive end-to-end without touching the CLI.
> Stretch: hand the ML a feedback loop it can ingest on next retrain.

## User quote (verbatim)

> make it so that the ML part is working with the app. i want a tab in like
> Clonality where i can load files, and it gets sorted by assays, then i get a
> new window or soemthing where i can annotate the files so that the ML can
> learn. i want the files to be runned with the rust engine and the python as
> fallback. and i want the plots to be made with plotly or something, which
> makes it easy for me to annotate with buttons etc. i want it to already be
> zoomed in based on the y-axis for the height and the x-axis for the
> reference area. lets gooo, you have all night to do this task

## Architecture

The chemist flow inside the existing PyQt6 desktop app:

```
Klonalitet group (sidebar)
  Run        [tab_run]
  Ladder     [tab_ladder]
  Archive Runner
  Interpretation         (rule vs ML comparison — already shipped)
  ML Learning  ← NEW
  Log
  Settings
```

ML Learning tab contains:

```
+--------------------------------------------------------------+
|  [Browse...] input FSA folder                                 |
|  [Run] — populates assay-sorted selection below               |
|                                                              |
|  Assay: [FR1  v]   Files N=750     Sort by: [DIT] [name]     |
|  +----------------------------------------------------+      |
|  | [x] 24OUM20364_FR1_A_040125_A01.fsa  PK   354.2 bp |      |
|  | [x] 24OUM20365_FR1_A_040125_B01.fsa  pat  --     |      |
|  | ...                                                 |      |
|  +----------------------------------------------------+      |
|                                                              |
|  [Render Annotation Panel]  -> opens Browser Window          |
|  [Export Annotations JSONL]                                  |
+--------------------------------------------------------------+
```

Behind this:

* Every FSA file is run through `_analyze_single_file()` with PE fallback
  (already shipped in `a053e8c` / branch `improvement/clonality-annotation-panel-2026-07-11-v2`).
  The Rust engine runs when `fraggler-cli.exe` is present; otherwise the
  Python scikit.peak fallback. Decision is logged once at start of run.
* Results aggregate by assay (FR1/FR2/FR3/TCRbA/B/C/TCRgA/B/IGK/KDE/...).
* The annotation panel is a SINGLE Plotly-driven HTML page written to
  `ML_Learning/<timestamp>/review_panel.html` and opened in the system
  browser. The chemist keyboard-labels (M monoklonal, P polyklonal, … per
  existing pattern) and clicks **Export Annotations** at the bottom.
* Export writes `ML_Learning/<timestamp>/annotations.jsonl` (one line per
  file) `{file, assay, dit, label, control_flag, note, annotated_at_utc, ...}`.
* Plan 11 trainer reads the JSONL alongside the rule-engine suggestions
  and updates per-assay metrics on next retrain.

## Phases (ship per phase, one atomic commit each)

### Phase A — Learn-tab skeleton (pure PyQt6 widget + tests)

* `gui_qt/tabs/tab_ml_learning/__init__.py` star-reexport facade.
* `gui_qt/tabs/tab_ml_learning/_io.py`: `load_fsa_folder(folder) -> list[Path]`.
  Pure helper that calls `_scan_folder_fsa_files` from `core.batch`.
* `gui_qt/tabs/tab_ml_learning/_summary.py`:
  - `group_by_assay(files) -> dict[str, list[Path]]` — sorted by assay display
    order (`ASSAY_DISPLAY_ORDER` from `core.analyses.clonality.config`) with
    an "UNKNOWN" bucket.
  - `extract_dit(file_name) -> str` — uses existing `_assay_name` and
    `extract_dit_from_name`.
  - `summarize_run_summary(run_summary) -> dict` — returns simple counts so
    the UI badge can show "750 files, 12 assays".
* `gui_qt/tabs/tab_ml_learning/_workers.py`:
  - `AnalyzeWorker` (QThread subclass) takes a list of `Path`s, runs
    `_analyze_single_file` on each, emits `progress(i, n, entry)` signals
    and finishes with `finished(all_entries)`. Catches exceptions per file
    so one bad file does not kill the run.
  - `_entry_dict_for_row(entry) -> dict` — minimal serialization for
    persisting to disk between runs.
* `gui_qt/tabs/tab_ml_learning/_legacy.py`:
  - `TabMlLearning(QWidget)` — Browse input dir, assay selector QComboBox,
    QTableWidget for file list (selectable checkboxes), Run / Open Panel /
    Export JSONL buttons. Toolbar layout matches the rest of the app.
  - Tests pin: helper logic (group by assay, extract DIT, summarize counts),
    widget construction is offscreen (no spawn).

Commit: `feat(gui): ML Learning tab skeleton — group-by-assay file picker`.

### Phase B — Analysis worker + Plotly panel path

* `core/plotting_plotly/_legacy.py`: extend `_create_plotly_figure` so the
  rendering side can accept pre-computed zoom axes (xmin/xmax + ymax). Returns
  `(fig, xmin, xmax, ymax, ymin)` so the caller can persist them.
* `gui_qt/tabs/tab_ml_learning/_render.py`: NEW pure helper module:
  - `render_annotation_panel_html(entries, *, out_dir) -> Path` — pure-pure.
    Builds a single self-contained HTML file with embedded Plotly.js
    (`assets/plotly-3.1.0-basic.min.js` per CDN pitfall), one Plotly
    `Figure` per file as a `dashboard` with no scroll-y, axis state
    serialized in a hidden `<pre>` so the helper can update annotations.
    Extra:
      - zoom is pre-set: xmin/xmax = `assay_interpretation_range(assay)`
        expanded by 18 bp on each side; ymin=0, ymax=ymax computed from
        trace's max RFU inside the window × 1.18.
      - per-file annotation widget: 8 `Class` buttons (`monoklonal`,
        `polyklonal`, `bi_oligoklonal`, `irregulaer`, `pseudoklonal`,
        `intet_pcr_produkt_darlig_dna`, `qc_teknisk_fail`, `usikker_review`)
        matching `ANNOTATION_CLASSES`; 4 `Flag` buttons for controls; Note
        textarea. Buttons are HTML `<button>`s, JS handlers `onclick` set
        the active class on a hidden `<input>` for export.
      - keyboard shortcuts: M/P/B/I/Q/N/T/U/Z (mirror the label_tool).
      - sticky bar at top so annotation buttons stay in view while
        scrolling through plots.
      - raw path collapsed into `<details>` (don't repeat Path 12 lessons).
  - `compute_panel_axes(entry) -> dict` — pre-computes xmin/xmax/ymax/ymin
    for each entry so all plots render with the correct zoom on first paint.
  - `layout_annotations(entries) -> list[dict]` — same shape as
    existing interpretation annotations so Phase E can feed training
    idempotently.
* `gui_qt/tabs/tab_ml_learning/_legacy.py`:
  - Wire `AnalyzeWorker` to a `Run` button click; results populate the
    file table + persist `local_triage/ml_runs/<timestamp>/raw_entries.json`
    so reopens don't re-run.
  - Wire `Open Panel` button to call `render_annotation_panel_html` and
    use `webbrowser.open(...)` to launch the panel. On Windows use
    `os.startfile`.
  - Tests pin the layout helper (button presence, Plotly.js included via
    `<script src="...">`, no live CDN).

Commit: `feat(ml): Plotly annotation panel + zoom pre-set helper`.

### Phase C — JSONL feedback loop + integration with training

* `core/analyses/clonality/calibration.py`: add
  `append_learning_annotations_jsonl(annotation, output_path)` — append-only
  writer that respects a stable schema `{file, assay, dit, label,
  control_flag, note, annotated_at_utc, schema_version: 1}`. Reflects ALL
  eight annotation classes plus NULL note.
* `scripts/train_clonality_interpretation_models.py`:
  - `--annotations-jsonl PATH` — load annotations, merge with the existing
    `ClonalitySuggestion` rule-engine labels. Annotation rows win when both
    exist (chemists are authoritative). Persist `metadata.json::learning_annotations_total`.
* `gui_qt/tabs/tab_ml_learning/_legacy.py`:
  - Wire `Export Annotations` button: walks `local_triage/ml_runs/<ts>/entries.csv`
    (which the JS panel wrote via the panel's own export button) and calls
    `append_learning_annotations_jsonl` per row to produce
    `ML_Learning/<ts>/annotations.jsonl`. Status text shows N lines written.

Commit: `feat(ml): JSONL feedback loop -- export + trainer merge`.

### Phase D — MainWindow wiring (Klonalitet / ML Learning sub-button)

* `gui_qt/main_window.py`:
  - Add `TabMlLearning` instance.
  - Add `self.tab_ml_learning = TabMlLearning()`.
  - Add to `stacked_widget` before `tab_log` (idx 5 → push others).
  - Add `ML Learning` to `AnalysisGroup` sub_buttons, between
    `Interpretation` and `Log`.
  - Update `page_map` for clonality `{0: 0, 1: 1, 2: 2, 3: 4, 4: 5
    (=tab_ml_learning), 5: 6 (=tab_log), 6: 8 (=settings_clonality)}`.
* No regression on existing routing tests.

Commit: `feat(gui): wire ML Learning into Klonalitet group sidebar`.

### Phase E — Documentation + Obsidian pickups

* `ObsidianVault/Clonality_ML_Log/_todo.md` — Plan 13 section.
* `ObsidianVault/Clonality_ML_Log/_CHANGELOG.md` — per-phase row.
* `docs/ml-clonality-interpretation.md` — add a "GUI workflow" section.
* Update skill `lab-workflow/hemafrag-diagnostics-lab` to point at the new
  tab + plotly panel.

Commit: `docs(ml): Plan 13 -- ML Learning tab + Plotly annotation workflow`.

## Out of scope (explicit non-goals)

* xgboost trigger (separate decision doc).
* New model architectures (RF + QDA + calibrated classifiers as Plan 11).
* Live retraining triggered by annotation export (push a button to retrain
  is a separate spec; debounced retrain belongs in Plan 14).
* Keyboard shortcut routing through the GUI itself (annotation buttons
  live inside the BrowserWindow, not the Qt window).
* Update of the run.bat / start.bat — separate ticket.

## Acceptance criteria

1. From the HemaFrag GUI sidebar, **Klonalitet → ML Learning** opens a new
   tab. (Manual QA on Windows desktop.)
2. Browse button picks a folder; Run produces a file-table grouped by
   assay; passing `--input-root` arg of the existing label_tool should
   validate it ends up under `ML_Learning/...annotation`. (CI test.)
3. Rust engine runs when `fraggler-cli.exe` is present; Python
   `scipy.signal.find_peaks` fallback otherwise. Existing
   `tests/test_clonality_pipeline.py` (if present) plus a new
   `tests/test_ml_learning_tab.py` cover the routing logic.
4. Annotation panel plots render pre-zoomed x/y on first paint.
   `compute_panel_axes` is unit-tested.
5. Annotations JSONL writer idempotent; replays of duplicates are tolerated
   (test pinned via write_twice → assert identical hash).
6. Plan 11 trainer `--annotations-jsonl` path merges annotation rows and
   reports the merge in `metadata.json::learning_annotations_total`.
7. Test suite green at every phase commit (≥345 passed, 1 skipped baseline).
8. Each phase commit is pushed immediately after write+tests pass.

## Risks

* R1 (HIGH) — MSYS/Windows path shell handling when launching the panel via
  `os.startfile`. Test on actual Windows before claiming it works.
* R2 (MED) — Plotly.js version pin to `assets/plotly-3.1.0-basic.min.js`.
  See lab-workflow skill pitfall (corporate CDN blocked).
* R3 (MED) — `local_triage` directory grows unbounded; defer purge logic
  to a separate housekeeping task.
* R4 (LOW) — JSONL race conditions if chemist double-clicks Export — outer
  try/except already in plan per Recipe 12.9.

## Push cadence

Push after every atomic phase commit. Multi-hour Docker container pitfall
(see hemafrag-diagnostics-lab skill §Pitfalls) — never let container-only
commits sit unpushed.
