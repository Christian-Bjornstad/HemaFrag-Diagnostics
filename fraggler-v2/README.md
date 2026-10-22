# Rust analysis engine

This workspace supplies the native engine for HemaFrag on Windows 10/11 x64.
The supported application interface is the Python/PyQt6 desktop app in the
repository root.

| Crate | Purpose |
|---|---|
| `fraggler-core` | ABIF parsing, traces, peak detection, ladder selection/sizing, and analysis previews |
| `fraggler-cli` | Headless analysis and recovery path used by the Python bridge |
| `fraggler-kernels-py` | PyO3 extension distributed as the `fraggler-kernels` ABI3 wheel |

Python handles full assay workflows, manual review, manifests, HTML reports, QC,
and tracking. The Rust `qc`, `validate-flt3`, and `build-report` commands are
contract scaffolds and do not replace those Python workflows.

## Build and test

Use Windows with the MSVC C++ build tools, Windows SDK, and the Rust toolchain
declared in `rust-toolchain.toml`. From this directory:

```powershell
cargo build --locked --release -p fraggler-cli
cargo test --locked --workspace --exclude fraggler-kernels-py
cargo check --locked -p fraggler-kernels-py
cargo fmt --all -- --check
```

The CLI is produced at `target/release/fraggler-cli.exe`. The Python extension is
built separately with maturin; see its [build guide](crates/fraggler-kernels-py/README.md).

## Contracts and examples

`schemas/fraggler-contract-v1.schema.json` describes the JSON contract. Request
examples are in `examples/`. For CLI usage:

```powershell
cargo run --locked -p fraggler-cli -- analyze --help
cargo run --locked -p fraggler-cli -- analyze --json-request examples/analyze_request.json
```

Replace example input/output paths with local synthetic or approved data paths.
Automatic inference in the engine is checked against the requested Python
ladder/channel contract before its result is consumed. A mismatch routes to
review rather than silently changing the size standard.

## Validation tools

`../scripts/freeze_v2_baseline.py` records reference timings, hashes, and output
fingerprints using the scenario format in `baselines/scenarios.example.json`.
Use local environment variables for private dataset roots; never commit source
data or generated validation output. Synthetic engine tests are engineering
checks, not a clinical validation claim.
