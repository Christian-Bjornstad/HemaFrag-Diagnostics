# fraggler-kernels

PyO3 + maturin wrapper around `fraggler-core`. Compiles the existing Rust
engine into a Python extension module so HemaFrag can call into it directly
instead of spawning `fraggler-cli` via subprocess.

This crate is a sibling of `fraggler-cli` in the same Cargo workspace. The
two are intentionally kept independent:

- `fraggler-cli` is the standalone headless CLI (unchanged).
- `fraggler-kernels-py` exposes the same Rust engine primitives to Python
  in-process. No JSON text round trip, temporary files, or subprocess forks.

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

From HemaFrag's repository root on Windows 10 or 11 (64-bit), using the
MSVC build tools and a Rust toolchain supporting edition 2024 (Rust 1.85
or newer):

```bash
# Install maturin in your project environment
python -m pip install maturin

# 2. Build + install in editable mode (fast for iteration)
python -m pip install -e fraggler-v2/crates/fraggler-kernels-py

# OR: build a wheel and install it
python -m maturin build --release --locked -m fraggler-v2/crates/fraggler-kernels-py/Cargo.toml --out wheels
python -m pip install wheels/fraggler_kernels-0.1.3-cp310-abi3-win_amd64.whl
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

Maturin builds the Python extension. Build the standalone CLI separately:

```bash
cargo build --release --locked --manifest-path fraggler-v2/Cargo.toml -p fraggler-cli
```

HemaFrag searches `fraggler-v2/target/release/`, `fraggler-v2/target/debug/`,
and `bin/` for the standalone executable when the native wheel is unavailable.

## Validation

The Windows ABI3 wheel is distributed in the root `wheels/` directory.
Its version matches the Rust workspace and this crate's Python metadata.
The analysis releases Python's GIL while running the Rust numerical engine.

```bash
cargo test --locked --manifest-path fraggler-v2/Cargo.toml -p fraggler-core -p fraggler-cli
cargo check --locked --manifest-path fraggler-v2/Cargo.toml -p fraggler-kernels-py
python -m fraggler_native._smoke path/to/synthetic.fsa
```

The Python bridge verifies that the native ladder and size-standard channel
match the requested analysis. A mismatch requires review; native channel
guesses do not replace a configured profile silently.
