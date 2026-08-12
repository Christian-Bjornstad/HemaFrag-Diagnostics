# Plan 15 — Architecture, Risk, Performance, and Stability Review

Date: 2026-08-09
Branch: `codex/ladder-fitting-performance-safety`
Scope: engineering review and high-confidence improvements; no clinical algorithm promotion

## Outcome Summary

Plan 15 keeps the existing Python/PyQt orchestration and Rust numerical-engine architecture. No new language was justified by the measured hotspots or by the Python 3.14/offline deployment contract.

Implemented engineering changes:

- source startup median improved from `4.986 s` to `3.231 s` (`35.2%` faster), and p95 improved from `5.145 s` to `3.255 s` (`36.7%` faster);
- large scientific/report dependencies in `fraggler.fraggler` now load on first use instead of blocking the first Qt window;
- an unreachable FLT3 validation page no longer loads during startup; its standalone module remains available for direct use and tests;
- the legacy Python arPLS solver now uses a cached CSC penalty matrix, emits no sparse-format warning, preserves the legacy numerical result, and safely handles flat, short, and non-finite traces;
- one portable icon resolver now covers source, Python/wheel, PyInstaller, and platform resource roots;
- Windows receives the stable AppUserModelID `no.ous.hemafrag` before `QApplication` is created;
- the app validates `QIcon` instead of silently ignoring missing or invalid resources;
- the stale machine-specific root `HemaFrag.spec` was removed; generated specs now live under ignored, platform-specific `build/specs/<platform>/` directories;
- Windows source deployments can create a HemaFrag-icon `.lnk` pointing to the already approved Python environment, without distributing another executable;
- Linux packaging now contains a `.desktop` entry and installed icon layout.

No Rust source or diagnostic ladder-selection default changed, so the already verified `0.1.2` wheel remains the correct native artifact. Its Python 3.14 smoke result is recorded below.

## Current Architecture

### End-to-end data flow

1. `qt_app.py` prepares the desktop runtime, application identity, icon, exception hook, and `MainWindow`.
2. `gui_qt/main_window.py` owns navigation. `TabBatch` discovers input paths and invokes `core.batch` on a worker rather than on the Qt event loop.
3. `core.batch.generate_jobs` scans explicit files/folders, applies run-date and patient/control grouping, and creates deterministic job membership. General mode supports identifier-free grouping.
4. `core.batch.run_batch_jobs` creates `BatchRunManifest`, runs jobs within the unified concurrency budget, records progress/heartbeats, and retains completed and failed job state.
5. `core.runner` stages explicit cohorts once, dispatches through `core.pipeline`, collects entries, stamps source provenance, and separates patient, QC, and final report work.
6. The dispatcher selects `core.analyses.clonality.pipeline`, `core.analyses.flt3.pipeline`, or `core.analyses.general.pipeline`.
7. `core.fsa_artifact` decodes each FSA into an immutable, versioned per-process artifact so ladder, sample channels, plots, and provenance can reuse it.
8. Ladder execution prefers the in-process PyO3 `fraggler-kernels` wheel, then the Rust worker/CLI recovery route when supported. Engine statistics and provenance record the route. FLT3 GS500ROX remains Rust-owned; legacy Python rescue is opt-in only.
9. `core.analysis` prepares the peak-preserving nonnegative size-standard trace, applies saved manual mappings when valid, validates anchor geometry/QC, and emits pass/review/fail metadata.
10. Assay pipelines perform sample-peak analysis and classification. FLT3 quantitative area continues to use the raw DATA-channel trace with its separate mild local-sideband baseline.
11. Entries flow to Plotly/matplotlib, HTML, QC, and tracking writers. Atomic publication and idempotent workbook replacement protect final output.
12. Review-required entries create review-bundle rows rather than disappearing. Ladder Studio validates and saves a versioned sidecar; a manifest-based rerun verifies that the exact sidecar hash was consumed before rebuilding reports.

### Normal and failure paths

| Workflow | Normal path | Ambiguous/failure path |
|---|---|---|
| Clonality | FSA artifact → Rust-first ladder → sample peaks → rules/optional gated ML → DIT/QC/tracking | explicit `review_required` entry and bundle; valid manual sidecar can rerun; run manifest retains failed job/input |
| FLT3 | DATA4 GS500ROX or explicit DATA105 LIZ override → Rust-owned ladder → raw-trace area/ratio and selected WT/MUT base-pair difference → grouped reports | missing/unsafe ladder remains review/fail; no default Python ladder rescue; partial batch can still finalize eligible output |
| General | versioned profile declares ladder, channels, ranges, and fields → report | arbitrary/non-patient identifier is retained as source identity; missing profile/input produces visible reason rather than an empty successful report |

### Runtime and packaging routes

| Route | Native engine | Icon/resource route | Status |
|---|---|---|---|
| Windows source, Python 3.14 | installed `cp310-abi3-win_amd64` wheel | platform resolver prefers `assets/app_icon.ico`; AppUserModelID set before Qt | primary work-computer route |
| Windows source shortcut | same wheel | generated `.lnk` points to approved Python and `app_icon.ico` | implemented; operator creates shortcut explicitly |
| Windows PyInstaller | bundled CLI recovery plus packaged Python | `build_qt.py --icon=assets/app_icon.ico`; generated spec under `build/` | built and launched on Windows; not the work-computer deployment |
| macOS app | platform build | `.icns`, bundle id `no.ous.hemafrag` | static contract only in this Windows run |
| Linux portable folder | platform build | PNG plus `HemaFrag.desktop` and hicolor icon tree | static contract only in this Windows run |

## Before/After Measurements

### Plan 15 reproducible local measurements

Environment: Windows, Python `3.11.15`, 16 logical CPUs. Startup means a fresh process through first Qt event processing with `QT_QPA_PLATFORM=offscreen`. arPLS uses the deterministic 6,000-point synthetic negative/drifting trace in `scripts/benchmark_plan15_runtime.py`.

| Metric | Before | After | Change | Output parity |
|---|---:|---:|---:|---|
| source startup median, 5 repeats | `4.986 s` | `3.231 s` | `35.2%` faster | same constructed `MainWindow` and first event processing |
| source startup p95, 5 repeats | `5.145 s` | `3.255 s` | `36.7%` faster | same |
| warm Python arPLS median, 10 repeats | `3.824 ms` | `3.489 ms` | `8.8%` faster | numerical reference test `rtol=1e-10`, `atol=1e-8`; benchmark output SHA-256 `149729e963a4b3d25ef194b939de92c332f614bbe653a22dd649c909aee0c86e` |

Repeat the after benchmark:

```powershell
python scripts/benchmark_plan15_runtime.py `
  --startup-repeats 5 `
  --arpls-repeats 10 `
  --output validation_outputs/plan15_runtime_after.json
```

The scientific imports intentionally move from app startup to first use. This makes the UI responsive sooner but does not claim that the first clinical analysis itself is faster. The arPLS change is a small measured improvement; its main value is numerical and warning stability.

### Existing real-FSA reference retained from Plan 13

The private raw-data roots were not mounted for Plan 15. The last immutable three-repeat manifest at `validation_outputs/plan13_phase0_repeat3_final/` therefore remains the before-change clinical reference:

| Scenario | p50 | p95 | Completeness/fingerprint |
|---|---:|---:|---|
| heavy LIZ clonality file | `2.754 s` | `3.098 s` | deterministic, approved selected ladder |
| ROX clonality file | `0.176 s` | `0.181 s` | deterministic, approved selected ladder |
| combined patient/QC cohort | `43.004 s` | `47.494 s` | 22/22 entries, 14/14 QC, zero failed jobs |
| 25-file FLT3 subset | `15.078 s` | `15.329 s` | 25/25 PASS, one consumed manual correction |

Those runs used the Rust CLI because the wheel was not installed in that benchmark environment. Later Plan 13 evidence already measured exact output parity and `13.88%` p95 improvement from immutable FSA reuse. Plan 15 does not fabricate new real-FSA timings in the absence of the private input roots.

## Language and Hotspot Decision Table

| Area | Evidence/root cause | Options considered | Deployment/quality impact | Decision |
|---|---|---|---|---|
| Qt startup | eager imports accounted for most startup time | Python lazy imports; Rust/C++ rewrite; new UI toolkit | Python-only change is low risk and wheel-independent | keep PyQt/Python; lazy-load scientific/report dependencies (`35%` startup gain) |
| ladder search and signal kernels | combinatorial, deterministic CPU work; already Rust-owned | Rust/PyO3, C++, Cython, Numba, GPU | existing ABI3 wheel works on Python 3.14 and preserves one engine contract | continue Rust; do not add another native language |
| Python arPLS compatibility path | sparse matrix format warning and repeated penalty construction; only milliseconds warm | CSC/cache in Python; Rust call; Cython/Numba | Python fix preserves numerical output and avoids a new boundary | implement CSC/cache and finite-input guards; no Rust change |
| ABIF decode/data reuse | Plan 13 found repeated decode/copy cost | immutable Python artifact; Rust parser; memory-mapped service | current artifact already gave parity and p95 gain | retain versioned per-process artifact; measure cross-process reuse later |
| PyO3 boundary | JSON text round-trip already removed | typed Python dict/list; NumPy buffer; C ABI | direct typed conversion is already active; arrays are not yet the dominant measured cost | retain; test buffers only with a real measured array-copy hotspot |
| plots/HTML | imports and rendering can be heavy but are I/O/library dominated | Python lazy imports; browser service; Rust templating | Python ecosystem is more maintainable and output-compatible | keep Python; load plotting/report packages on demand |
| Excel tracking | real reference spent `6.4–8.4 s` in tracking publication | openpyxl optimization; SQLite ledger + Excel export; Rust writer | workbook compatibility/formulas/styles are higher risk than raw speed | keep atomic Excel production; retain SQLite as validated prototype only |
| concurrency | Python workers can multiply Rust/numeric threads | unified budget; process service; Go/Rust daemon | current `core.concurrency` already controls the budget | retain one budget; remeasure 1/2/4/6/8 on each target machine |
| Cython/Numba | no remaining hotspot uniquely suited to them | compile selected Python kernels | Python 3.14 wheels/cache and support add another failure mode | reject until a profiler shows a substantial Python loop not suited to Rust/NumPy |
| Go/Zig/GPU | no measured fit; offline desktop and small per-file arrays | service process, Zig library, CUDA/OpenCL | additional runtime/toolchain/driver and clinical validation surface | reject for current product |

## Top Engineering Risks

Scores: impact/likelihood/difficulty from 1 (low) to 5 (high).

| Rank | Risk | Impact | Likelihood | Difficulty | Current control / action |
|---:|---|---:|---:|---:|---|
| 1 | algorithm promotion without reviewed real-FSA labels and area-bias tolerances | 5 | 3 | 5 | no Plan 15 diagnostic default changed; shadows remain non-promotable |
| 2 | a failed/ambiguous input disappears before final report | 5 | 2 | 4 | manifests, explicit review entries, count gates, atomic finalization, fault tests |
| 3 | Rust wheel missing or wrong environment silently changes behavior | 5 | 3 | 3 | engine provenance/stats; Python 3.14 wheel smoke; work-computer install check remains operational |
| 4 | very large legacy modules make local changes hard to audit | 4 | 4 | 5 | facades exist; future splits must be test-preserving and hotspot-driven, not a rewrite |
| 5 | workbook lock/network loss interrupts publication | 4 | 3 | 3 | atomic outputs and resumable manifest; explicit path/settings diagnostics; retain fault tests |
| 6 | stale platform build metadata or missing resources | 3 | 4 | 2 | root spec removed, platform-generated ignored specs, central resolver and packaging tests |
| 7 | nested Python/Rust/numeric concurrency oversubscribes a work PC | 3 | 3 | 3 | one concurrency resolver; target-machine worker matrix remains required |
| 8 | optional-feature imports hide a missing dependency | 3 | 3 | 2 | visible archive availability message; avoid broad silent import fallbacks in new code |
| 9 | hard-coded/local default paths reappear | 3 | 3 | 2 | settings-owned master path and platform migration; static path audit retained |
| 10 | benchmark conclusions drift because private data is not mounted | 4 | 4 | 2 | checked-in commands and ignored immutable manifests; state validation limitation explicitly |

## Icon Verification Matrix

| Check | Result |
|---|---|
| PNG/ICO/ICNS readable | pass |
| Windows ICO frames | pass: 16, 32, 48, 64, 128, and 256 px |
| Qt `QIcon` non-null | pass |
| source resolver selects ICO on Windows | pass |
| application and main-window icon assignment | pass |
| Windows AppUserModelID setter/readback | pass: `no.ous.hemafrag` |
| live Windows source window | pass: visible `HemaFrag Diagnostics v1.2.0`, nonzero WM small/big and class icon handles |
| portable PyInstaller spec path | pass: generated under ignored `build/specs/win32/` |
| Windows build selects ICO, not ICNS | pass: built executable contains one icon group and exposes nonzero large/small icon handles |
| live Windows packaged window | pass: visible `HemaFrag Diagnostics v1.2.0` with nonzero WM small/big icon handles |
| macOS `.icns` selection | pass, static only |
| Linux `.desktop`/PNG layout | pass, static only |
| work-computer pinned/taskbar cache | operator visual check required after recreating/pinning the new shortcut |

## Python 3.14 Native Wheel Verification

Verified in a fresh Python `3.14.0` virtual environment with `--no-index --no-deps`:

- wheel: `wheels/fraggler_kernels-0.1.2-cp310-abi3-win_amd64.whl`
- install: pass
- import: pass
- `fraggler_native.is_available()`: `True`
- native version: `0.1.2`
- SHA-256: `638070b876eb11c91bedf9df6235b4a94db0371ea10c0b1223367dc0d50e9f0b`

Rust source did not change in Plan 15, so rebuilding or version-bumping this wheel would create needless deployment churn.

## Windows Packaged Build Verification

The Windows package was built locally after the resource/spec changes, its ZIP was integrity-tested, and the packaged application was launched through its real executable:

- application window: `HemaFrag Diagnostics v1.2.0`;
- bundled Rust recovery CLI: present at `_internal/fraggler-cli.exe`;
- embedded executable icons: one icon group, with nonzero extracted large/small handles;
- live window icons: nonzero WM small/big handles;
- release ZIP SHA-256: `b4d737ef61b71522a846752ccf7159525e0d6a13b57a630359136e655bcac3ff`;
- executable SHA-256: `3dd086bbaa325ded7478a5a184bbb8a64b3f4020031b51a36a5534b7e097c9ae`.

The build exercise also exposed and fixed three portability defects before release: asset paths had become relative to the relocated spec, the Python `dis` compatibility hook assumed only the newer call signature, and the build environment used an obsolete `setuptools` incompatible with modern Python. These are now covered by absolute resource paths, a cross-version hook signature, a maintained build dependency, and packaging-contract tests.

## Validation Boundaries

Completed engineering evidence:

- full pre-change Python baseline and Rust workspace baseline;
- icon/resource and packaging contracts;
- live Windows source window icon handles and application identity;
- successful Windows packaged build, ZIP integrity check, bundled Rust CLI check, live launch, and embedded/window icon checks;
- deterministic synthetic baseline/noise stability;
- legacy arPLS numerical-parity test;
- Python 3.14 ABI3 wheel installation/import smoke;
- full Python suite (`561 passed, 3 skipped`) and Rust workspace/native-package gates (`93 passed, 1 ignored`);
- existing Plan 13 run-manifest, report-completeness, review, and provenance evidence.

Still requires the private corpus or operator environment:

- repeat the real LIZ/ROX/FLT3/combined scenarios after installing the final branch on the work computer;
- visually confirm the title-bar, taskbar, Alt-Tab, and newly pinned shortcut icon there;
- macOS and Linux runtime visual launch checks;
- any clinical sizing/baseline/peak-selection promotion, FLT3 area-bias decision, or interpretation change.

Plan 15 intentionally does not convert missing clinical evidence into an engineering PASS.
