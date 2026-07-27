# fraggler-kernels

PyO3 + maturin wrapper around `fraggler-core`. Compiles the existing Rust
engine into a Python extension module so HemaFrag can call into it directly
instead of spawning `fraggler-cli` via subprocess.

This crate is a sibling of `fraggler-cli` in the same Cargo workspace. The
two are intentionally kept independent:

- `fraggler-cli` is the standalone headless CLI (unchanged).
- `fraggler-kernels-py` exposes the same Rust engine primitives to Python
  in-process. No JSON marshalling, no temp files, no subprocess forks.

## Layout

```
crates/fraggler-kernels-py/
├── Cargo.toml         # lib crate, cdylib + rlib, depends on fraggler-core
├── pyproject.toml     # maturin build backend, exposes module fraggler_native
├── src/lib.rs         # PyO3 module definition (analyze_fsa, ...)
└── python/
    └── fraggler_native/
        └── __init__.py # Re-exports the compiled extension
```

## Build

From HemaFrag's repo root on Windows / macOS / Linux (needs Rust ≥ 1.75):

```bash
# 1. Install maturin in your project venv (one-time)
pip install maturin

# 2. Build + install in editable mode (fast for iteration)
pip install -e fraggler-v2/crates/fraggler-kernels-py

# OR: build a wheel and install it
maturin build --release -m fraggler-v2/crates/fraggler-kernels-py/Cargo.toml
pip install target/wheels/fraggler_kernels-*.whl
```

## Quick smoke test

```python
from fraggler_native import analyze_fsa, is_available, fraggler_cli_path

print("In-process Rust available?", is_available())
print("Standalone fraggler-cli at:", fraggler_cli_path())

result = analyze_fsa(
    r"C:\path\to\some_file.fsa",
    analysis_kind="clonality",
)
print(result["file_name"], result["scan_count"], result["data_channels"])
```

The function returns a plain Python `dict`, JSON-shaped against the
v1 contract shipped by `fraggler-core`. No type bindings to install on
the Python side.

## What you get

- `analyze_fsa(path, analysis_kind="clonality"|"flt3"|"general")` — full
  `PrimitiveAnalysisResult` (ABIF parse, peak detection, ladder preview,
  QC metrics, FLT3 / clonality previews).

## Companion: `fraggler-cli`

After `maturin build --release`, both the standalone CLI
(`fraggler-v2/target/release/fraggler-cli(.exe)`) and the wheel are
produced. HemaFrag's existing `core.rust_bridge._resolve_cli_bin()` can
find either one automatically.

## Status (June 2026)

Code is written but **not built yet** — Docker sandbox has no Rust
toolchain. The intent is for this to compile cleanly on Christian's
Windows machine on the first `maturin build`. If you hit an issue, the
likely fix is bumping `pyo3` to the latest patch release.
