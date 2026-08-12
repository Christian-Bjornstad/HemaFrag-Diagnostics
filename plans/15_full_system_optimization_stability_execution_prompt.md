# HemaFrag Full-System Optimization, Stability, and App-Icon Execution Prompt

Copy everything from **BEGIN PROMPT** through **END PROMPT** into a new Codex task. This is an execution request, not only a request for another plan.

---

## BEGIN PROMPT

You are working in the HemaFrag repository. Execute an evidence-driven, end-to-end review and improvement of the application. Do not stop after writing an audit or plan: profile the current system, make the highest-confidence improvements, test them, build any required distributable wheel, document the results, commit the finished work, and push the current `codex/` branch when all release gates pass.

### Goal

Make HemaFrag faster, more stable, easier to maintain, and safer to use without reducing diagnostic quality. Evaluate whether moving measured hotspots to Rust or another implementation technology would materially help, but do not rewrite working code merely to use a different language. Preserve or improve correct ladder-peak selection, explicit review behavior, report completeness, traceability, and Python 3.14 deployment.

Also fix the HemaFrag application icon comprehensively. The repository already contains:

- `assets/app_icon.png`
- `assets/app_icon_transparent.png`
- `assets/app_icon.ico`
- `assets/app_icon.icns`

The HemaFrag icon must appear consistently when the Qt app is run from source and, where relevant, in the window title bar, Windows taskbar and Alt-Tab view, macOS app bundle, Linux desktop integration, and packaged builds. The work computer runs the app with Python 3.14 and installs the Rust extension as a wheel; it cannot rely on a newly distributed standalone `.exe`.

### Important current context

- The primary desktop UI is Python/PyQt6: `qt_app.py` and `gui_qt/`.
- Analysis/report orchestration is primarily under `core/`.
- Native analysis code is in the Rust workspace `fraggler-v2/`.
- The in-process Rust integration is a PyO3/maturin `abi3-py310` wheel and must work on CPython 3.14 Windows.
- The Rust wheel is the required native deployment route on the work computer. Do not treat a standalone Rust `.exe` or Python-only fallback as the normal solution there.
- Existing real-FSA benchmark and release-gate work is documented in `plans/13_app_quality_speed_precision_roadmap.md`; reuse and extend it rather than starting from zero.
- Existing ladder work and tests must be reviewed before changing ladder or preprocessing behavior.
- Known historical performance examples include LIZ500 ladder fitting taking much longer than ROX400HD and an FLT3 batch previously taking roughly 200 seconds per patient. Measure the current code; do not assume those old timings still apply.
- Whole ladder traces can be negative or have a baseline below zero. The display/working signal should have a sensible zero baseline while preserving real ladder apex height, shape, area, ordering, and peak selection.
- Failed or ambiguous ladder fits must never silently discard a file. They must produce an explicit status and a usable review/Ladder Studio path.
- FLT3 quantitative area traces must remain protected from peak-detection preprocessing changes.
- Patient and QC outputs must remain complete, deterministic, and auditable.
- Preserve user settings, manual ladder sidecars, run manifests, and existing output compatibility unless a versioned migration is implemented and tested.

### Working rules

1. Read repository guidance and inspect the current Git state first. Preserve unrelated user changes and do not use destructive Git commands.
2. Inspect the existing architecture, tests, plans, benchmarks, build scripts, Rust crates, packaging, settings, error handling, and launch paths before editing.
3. Establish or refresh reproducible before-change measurements. Profile first; optimize second.
4. Use representative, de-identified real-FSA manifests when locally available. Never commit raw clinical/FSA data or patient identifiers.
5. Keep algorithmic changes behind assay-specific validation or shadow-mode gates until reviewed evidence supports promotion.
6. Make changes in small, understandable units. Add regression tests for each bug or reliability issue fixed.
7. Do not hide errors with broad exception handling. Give operators a useful reason code, preserve the file in the run manifest, and route recoverable cases to review.
8. Do not silently fall back from the Rust wheel to a slower or behaviorally different engine. Record the engine, version, strategy, and fallback/review reason in run provenance.
9. Continue autonomously through safe, in-scope work. Ask only if a decision would change clinical interpretation, requires unavailable labeled data, or needs new authority.
10. Do not claim performance or quality improvements without before/after evidence.

### Phase 1 — Baseline, architecture map, and risk review

Create or update a concise execution document under `plans/` or `docs/` containing:

- the current data flow from file discovery through ABIF decode, ladder fitting, baseline/preprocessing, assay analysis, plots, HTML, QC, and workbook publication;
- boundaries between Qt, Python orchestration, NumPy/SciPy work, Rust/PyO3, Rust CLI recovery, file I/O, and subprocess/process-pool work;
- the normal and failure paths for clonality, FLT3, and General mode;
- how a rejected, failed, or manually corrected file reaches Ladder Studio and then re-enters a report;
- launch and packaging routes for source, Python 3.14 + wheel, PyInstaller Windows, macOS, and Linux;
- the ten highest technical risks, ranked by diagnostic impact, data-loss/report-loss risk, runtime cost, likelihood, and difficulty.

Review specifically for:

- duplicate ABIF reads and repeated transformations;
- Python/Rust JSON or array copying overhead;
- nested Python worker and Rust thread oversubscription;
- locks, blocking GUI work, subprocess startup, repeated imports, and excessive filesystem scans;
- repeated plot or HTML generation;
- Excel/workbook serialization bottlenecks and non-atomic publication;
- unbounded caches or large-array copies;
- exception paths that lose a file, plot, QC row, report entry, or manual review link;
- nondeterministic ordering, mutable shared state, race conditions, and retry/idempotency problems;
- absolute paths, platform assumptions, stale specifications, missing resources, and silent configuration fallback;
- weak typing or overly coupled modules that make assay behavior hard to reason about;
- dependency compatibility and reproducible installation on Python 3.14.

### Phase 2 — Reproducible profiling and benchmarks

Use or extend the existing Plan 13 benchmark tooling. Measure at least:

- application startup to responsive main window;
- first analysis versus warm analysis;
- ABIF decode;
- LIZ and ROX ladder candidate detection and fitting;
- baseline correction and peak detection;
- in-process Rust wheel calls and any CLI/subprocess path separately;
- clonality analysis;
- FLT3 ITD and D835/TKD analysis;
- plot generation;
- HTML generation;
- QC and workbook generation/update;
- total single-file and batch wall time;
- p50, p95, peak memory, failure count, review count, and output fingerprints;
- worker counts appropriate to the machine, including protection from nested oversubscription.

Use repeated runs, record machine/runtime versions, and distinguish CPU time, I/O time, wait time, and one-time startup cost where practical. If representative real data is unavailable, build deterministic synthetic/unit microbenchmarks and clearly label the remaining real-data validation gates.

Keep a checked-in benchmark summary without raw data. Record exact commands so the measurements can be repeated on the work computer.

### Phase 3 — Language and architecture decision

For every material hotspot, produce a decision table with:

- measured share of total runtime;
- root cause;
- simplest optimization in the current implementation;
- Python/NumPy vectorization option;
- Rust/PyO3 option;
- Cython or Numba option;
- C/C++ library option where a mature dependency already exists;
- any credible Go, Zig, GPU, or process-service option only if it fits this desktop/offline deployment;
- expected speedup and memory effect;
- correctness and diagnostic risk;
- Python 3.14/Windows wheel and offline deployment impact;
- build complexity, maintenance burden, debugging cost, and recommendation.

Use these defaults unless measurements disprove them:

- keep PyQt UI, workflow orchestration, settings, and report composition in Python;
- keep or move tight deterministic numerical/sequence-search kernels to Rust when they dominate runtime and have clear typed inputs/outputs;
- reduce copies and serialization at the PyO3 boundary before adding another language;
- prefer vectorized NumPy/SciPy for well-supported array operations that are already fast and readable;
- avoid a new language/runtime when it would add packaging risk without a substantial measured gain;
- avoid GPU dependencies unless batch size and benchmark evidence clearly overcome transfer, packaging, driver, and support costs.

Implement the best high-confidence optimizations. Keep larger or clinically sensitive alternatives as benchmarked prototypes or shadow-mode experiments rather than changing validated defaults prematurely.

### Phase 4 — Ladder quality and preprocessing safety

Treat ladder correctness as a hard release gate, not just a performance metric.

Verify and improve, where evidence supports it:

- whole-trace negative offset handling and robust baseline-to-zero behavior;
- preservation of ladder peaks, apex positions, relative heights, morphology, and monotonic order;
- rejection of baseline noise, shoulders, pull-up, dye blobs, saturation artifacts, and implausible gap sequences;
- LIZ and ROX assay-specific behavior;
- stability under small threshold and preprocessing perturbations;
- confidence margin between the best and competing monotonic fits;
- explicit status/reason codes for pass, review, and fail;
- review-bundle creation and Ladder Studio routing for every ambiguous or rejected file;
- manual sidecar validation, save, reload, rerun, and report inclusion;
- no silent Python fallback and no silent dropped file or missing plot.

Build regression fixtures covering at least:

- a clean LIZ ladder;
- a clean ROX ladder;
- a fully negative-offset trace;
- sloped and curved baseline;
- weak real peaks near noise;
- large baseline fluctuations;
- saturated/clipped peaks;
- broad artifact peaks or shoulders;
- missing high-end ladder tail;
- an ambiguous competing peak sequence;
- a case requiring manual correction.

For synthetic cases, assert peak recall and false-positive/noise-selection limits. For real reviewed cases, compare selected ladder indices, sizes, residuals, confidence/review outcome, and report behavior. Never promote a smoother or faster baseline method solely because its plot looks better.

### Phase 5 — Reliability, recovery, and reporting

Audit and improve the end-to-end failure contract:

- Every input file must end in a visible state: passed, needs review, failed with reason, or intentionally skipped with reason.
- A failure must not erase already completed jobs or prevent eligible plots/reports from being finalized.
- Finalization must be atomic, resumable, idempotent, and count-checked against the run manifest.
- Interrupted or partially failed batches must be recoverable after restart.
- Patient and QC rows must appear exactly once.
- Clonality QC ordering must remain PK, RK, then NK.
- FLT3 plot grouping and mutation/base-pair information must remain correct.
- General mode must be able to generate a report even when the operator uses a non-patient identifier, with provenance that explains the identifier source.
- Missing network/master-sheet access must give an actionable message and use the configured master-sheet location rather than a hard-coded drive.
- Worker failures, corrupt files, missing resources, unavailable Rust wheel, and publication errors must be tested.
- Logs and run manifests must include enough context to diagnose a work-computer failure without exposing patient data.

Add fault-injection tests where practical: permission denial, missing file, corrupt FSA, invalid manual sidecar, missing wheel, process-worker exception, plot failure, workbook lock, and interrupted finalization.

### Phase 6 — Complete application-icon fix

Investigate the actual launch method on Windows and fix all relevant icon paths, not only one code line.

Current clues to verify:

- `qt_app.py` currently attempts to load `assets/app_icon.png` through a bundle/source directory and silently does nothing if the path is missing or the `QIcon` is null.
- `build_qt.py` bundles `assets`, requests `app_icon.ico` on Windows and `app_icon.icns` on macOS.
- the checked-in `HemaFrag.spec` may be stale, platform-specific, and contain absolute paths from another machine. It must not be a hidden alternate build path that overrides the correct Windows icon.

Implement a single tested icon/resource resolver and use it consistently. Requirements:

- resolve assets correctly from source, installed project, PyInstaller one-folder/one-file context if supported, and platform bundle resources;
- validate that the file exists and that the resulting `QIcon` is not null;
- log or surface a clear diagnostic when the icon cannot load instead of failing silently;
- set application metadata and the application icon before creating/showing top-level windows;
- set the main-window icon as well;
- on Windows, set a stable explicit AppUserModelID before `QApplication` when appropriate so the taskbar does not group HemaFrag as a generic Python process;
- use a valid multi-resolution `.ico` for Windows executable/shortcut integration and verify its embedded sizes;
- use `.icns` for macOS bundles;
- use PNG plus a correct `.desktop` entry/icon installation for Linux packaging where applicable;
- make the PyInstaller spec portable or generate it per platform; eliminate hard-coded user-machine paths and ensure Windows never inherits the macOS icon configuration;
- prevent generated platform-specific specs from becoming a stale source of truth, or test that they match the build script;
- for the Python 3.14/no-new-EXE work-computer route, document and, if suitable, provide a safe launcher/shortcut setup that points to the Python environment while displaying the HemaFrag `.ico`. Do not distribute a forbidden replacement executable;
- add automated resource/spec tests plus a short manual visual checklist.

Manually verify or provide exact verification steps for:

1. source launch on Windows;
2. title-bar icon;
3. taskbar icon while running;
4. Alt-Tab icon;
5. shortcut/pinned icon if that is the work-computer launch route;
6. packaged Windows build if locally permitted;
7. macOS/Linux packaging statically or in CI when those platforms are unavailable.

If Windows caches an old icon, document how to distinguish a code problem from shortcut/taskbar icon caching without asking the operator to delete unrelated system data.

### Phase 7 — Implementation priorities

Prioritize in this order:

1. correctness, no dropped inputs, and reproducible output;
2. ladder peak/noise discrimination and explicit review behavior;
3. app-icon/resource portability fix;
4. crashes, hangs, GUI blocking, and recovery failures;
5. the largest measured end-to-end performance bottlenecks;
6. memory/copy/serialization and concurrency improvements;
7. maintainability improvements that reduce future error risk;
8. experimental algorithms or new-language prototypes.

Do not perform a broad rewrite. Refactor only where tests and measured value support it. Preserve public/internal contracts where practical; version changes that cannot remain compatible.

### Required validation gates

Before calling the task complete:

- run the full Python test suite;
- run all relevant Rust workspace tests and checks;
- run icon/resource/packaging tests;
- run ladder-specific regression and review-flow tests;
- run representative clonality, FLT3, General, plotting, report, QC, manifest, and recovery tests;
- compare before/after output fingerprints;
- compare before/after performance with repeated runs;
- confirm no input disappears from the manifest/report workflow;
- confirm all changes remain compatible with Python 3.14 on Windows;
- if Rust/PyO3 code changed, bump the native package version appropriately, build a release `abi3` Windows wheel, verify its wheel tags, install it into an isolated Python 3.14 environment, import it, exercise a real native function, run the native-wheel contract tests, copy the verified wheel to the repository's documented wheel distribution location, and report its SHA-256;
- do not claim macOS or Linux visual runtime verification if only static checks were possible.

Performance acceptance should be based on the refreshed baseline. As a target, improve the dominant safe hotspot by at least 20–30% or explain with evidence why the remaining time is inherent I/O/library work. Do not accept more than a 5% p95 regression in other important workflows without a justified tradeoff. Performance gains never override diagnostic or completeness gates.

Quality acceptance requires:

- zero unexplained changes to approved ladder selections;
- no increase in baseline-noise peaks selected as ladder anchors;
- full negative-trace coverage without flattening or removing real peaks;
- 100% manual correction save/reload/rerun success in available fixtures;
- every failed or ambiguous file retained with a reason and review route;
- every expected patient and QC entry present exactly once;
- deterministic outputs across repeated runs;
- no silent engine fallback;
- app icon loading verified for the available Windows source/shortcut route and statically validated for packaging routes.

### Required deliverables

At the end, provide:

1. an architecture and risk review document;
2. a before/after benchmark table with exact commands and environment;
3. the language/hotspot decision table, including options rejected and why;
4. implemented optimization and stability changes with concise reasoning;
5. the complete app-icon fix and platform verification matrix;
6. added/updated tests and their results;
7. remaining clinical or real-data validation gates, clearly separated from completed engineering work;
8. the Python 3.14 wheel filename and SHA-256 if Rust changed;
9. changed-file summary;
10. commit hash and pushed branch name.

Lead the final handoff with the outcome: what is faster, what is safer, whether the icon now displays, what was actually verified, and what—if anything—still needs testing on the work computer.

Start now by inspecting the repository and current Git state, then execute the work through validation, commit, and push.

## END PROMPT
