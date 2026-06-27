# HemaFrag Diagnostics - Testing Status

## Current Status (Docker Sandbox)

✅ **Working:**
- FLT3 pipeline imports and basic peak detection
- Clonality pipeline imports and assay classification  
- Rust engine bridge (stats tracking, cache management)
- PyQt6 GUI imports (MainWindow, tabs, dialogs)
- 20 test files in `/workspace/hemafrag/tests/`
- Repository on `code-cleanup` branch, commit 5b48b84

❌ **Not Available:**
- Real FSA files (need to be copied from your Windows machine)
- GUI display (Docker has no X server)
- Legacy Panel UI (gui.main module doesn't exist)

## How to Test on Your Windows Machine

### Option 1: Copy FSA Files to Docker

Copy a few test files to the container:
```powershell
# From PowerShell on your Windows machine
docker cp "C:\Users\molpa\Desktop\DATA\flt3\some_file.fsa" <container-id>:/workspace/hemafrag/data/
docker cp "C:\Users\molpa\Desktop\DATA\clonality\some_file.fsa" <container-id>:/workspace/hemafrag/data/
```

### Option 2: Run Tests Directly on Windows

From your Windows checkout at `C:\Users\molpa\Desktop\Hermes\HemaFrag-Diagnostics-code-cleanup`:

```powershell
# Run existing unit tests
python -m pytest tests/test_flt3_area_baseline.py -v
python -m pytest tests/test_clonality_control_smoke.py -v

# Run diagnostic script with your real data
python scripts/run_real_data_diagnostic.py ^
  --flt3-dir "C:\Users\molpa\Desktop\DATA\flt3" ^
  --clonality-dir "C:\Users\molpa\Desktop\DATA\clonality" ^
  --output-dir "C:\Users\molpa\Desktop\Hermes\bench-results"
```

### Option 3: Launch the PyQt6 GUI

```powershell
# Set environment if needed
$env:HEMAFRAG_ENABLE_LEGACY_PANEL = "0"

# Run the app
python qt_app.py
```

## Key Files

- **Entry point:** `qt_app.py` (PyQt6 desktop app)
- **FLT3 pipeline:** `core/analyses/flt3/pipeline/`
- **Clonality pipeline:** `core/analyses/clonality/pipeline.py`
- **Test scripts:** `tests/test_*.py`
- **Diagnostic runner:** `scripts/run_real_data_diagnostic.py`

## Recent Fixes

- Fixed `core/rust_bridge/_legacy.py` to properly import constants (was using `import *` which doesn't work for underscore-prefixed names)
- All 33 baseline tests should pass (last known state from memory)
