# HemaFrag code-cleanup playbook

This file describes the **safe** way to verify every phase of the
`code-cleanup` branch on this machine.

## One-time environment setup (Linux/WSL)

```bash
apt-get update -q
apt-get install -y -q \
    libgl1 libglib2.0-0 libegl1 libgles2 \
    libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 \
    libxcb-util1 libxcb-xinerama0 libxcb-xkb1 \
    libfontconfig1 fonts-noto-core

pip3 install -q -r requirements.txt pytest
```

## Per-phase verification

From the repo root (`/workspace/hemafrag`):

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
```

Current baseline (recorded 2026-06-27, before any cleanup):

```
Ran 33 tests in 1.646s
OK
```

Any phase that drops below 33 passing / introduces an `ERROR` /
`FAILED` is a regression and must be fixed before commit.

## Optional: smoke import of the GUI module

The cleanup must not break the GUI import surface. A lightweight smoke:

```bash
QT_QPA_PLATFORM=offscreen python3 -c "import gui_qt.tabs.tab_batch; print('ok')"
```

## Working agreements

1. **No destructive git ops without a sandbox.** Test the cleanup
   in `/workspace/hemafrag` and only push the branch after the
   33-test baseline still passes.
2. **One phase = one commit.** Each of phases 1–7 lands separately
   in the `code-cleanup` branch.
3. **Archive, don't delete.** Anything removed from the active tree
   goes to `archive/<phase>_<date>/` first. The archive directory
   is committed but ignored as a working surface.
4. **Update the Session Log after each phase.** Compact note per
   the project's logging policy.

## Phase status (all complete as of 2026-06-27)

- [x] **Phase 0**: tests-baseline env + verification recipe documented
- [x] **Phase 1**: delete legacy modules (gui/, 59 scripts, etc.)
- [x] **Phase 2a**: split `core/analysis.py` into a package
- [x] **Phase 3**: split `core/analyses/flt3/pipeline.py` into a package
- [x] **Phase 4**: clonality subsystem structural tidy (`__init__.py` only)
- [x] **Phase 5a/b/c**: split the three GUI giants into packages
- [x] **Phase 6a/b/c**: split `core/rust_bridge.py`, `core/plotting_plotly.py`,
       `core/html_reports.py` into packages
- [x] **Phase 7**: final hygiene (this update)

Result: 12 commits on `code-cleanup` branch, `Ran 33 tests, OK` baseline
preserved across the entire campaign.

Files converted from monolith to package:
- `core/analysis.py`               -> `core/analysis/{__init__,_constants,_legacy}.py`
- `core/analyses/flt3/pipeline.py` -> `core/analyses/flt3/pipeline/{__init__,_constants,_legacy}.py`
- `core/rust_bridge.py`            -> `core/rust_bridge/{__init__,_constants,_legacy}.py`
- `core/plotting_plotly.py`        -> `core/plotting_plotly/{__init__,_legacy}.py`
- `core/html_reports.py`           -> `core/html_reports/{__init__,_constants,_legacy}.py`
- `gui_qt/tabs/tab_batch.py`       -> `gui_qt/tabs/tab_batch/{__init__,_constants,_legacy}.py`
- `gui_qt/tabs/tab_ladder.py`      -> `gui_qt/tabs/tab_ladder/{__init__,_legacy}.py`
- `gui_qt/dialogs/ladder_dialog.py`-> `gui_qt/dialogs/ladder_dialog/{__init__,_constants,_legacy}.py`

Subsequent sub-splits of `_legacy.py` (e.g. splitting the giant
TabLadder / TabBatch / LadderAdjustmentDialog / TabBatch classes into
focused submodules) are out of scope for this campaign — each `_legacy`
file is now its own coherent unit that can be split incrementally
later without breaking callers.

