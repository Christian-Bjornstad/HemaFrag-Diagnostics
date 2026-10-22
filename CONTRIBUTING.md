# Contributing

Use Windows 10/11 x64, Python 3.12–3.14, and the checked-in Windows native wheel.
Install developer dependencies with `python -m pip install -r requirements-dev.txt`.
Use the Rust toolchain declared in `fraggler-v2/rust-toolchain.toml` for native work.

## Changes

- Use short-lived branches and focused commits. Explain the behavior and reason.
- Reproduce a bug with a failing regression test, then implement the correction.
- Preserve explicit assay, source, ladder, and channel provenance.
- Keep failed, rejected, cancelled, and unprocessed work distinguishable.
- Test report edits after saving and reopening when changing HTML/JavaScript.
- Keep clinical data, generated reports, local paths, and credentials out of Git.
  Checked-in fixtures must be synthetic.
- Update current documentation and the changelog when behavior changes.

## Checks before merging

```powershell
python -m pytest -q
python -m ruff check --select F821 core gui_qt hemafrag_diagnostics qt_app.py config.py app_meta.py app_resources.py build_qt.py
python -m pip check
python -m pip_audit -r requirements.txt
cargo fmt --manifest-path fraggler-v2/Cargo.toml --all -- --check
cargo test --locked --manifest-path fraggler-v2/Cargo.toml --workspace --exclude fraggler-kernels-py
cargo check --locked --manifest-path fraggler-v2/Cargo.toml -p fraggler-kernels-py
```

Install Node.js to run report interaction tests. Python tests build and inspect
an application wheel, then verify imports/resources away from the source tree.
Some corpus-dependent tests require private data; record those limitations
instead of treating skipped cases as successful validation.

After a native change, rebuild and version the Windows ABI3 wheel, verify it on
supported Python versions, and update its references in CI/build instructions.
See the [native binding guide](fraggler-v2/crates/fraggler-kernels-py/README.md).
Run the Windows packaging check before distributing a desktop ZIP.

Engineering tests and synthetic benchmarks do not authorize changes to clinical
interpretation thresholds. Assay/algorithm changes need local laboratory review
and validation on the controlled private corpus.
