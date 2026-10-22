# Third-party notices

HemaFrag Diagnostics includes original application code and third-party software.
This repository does not grant a single open-source license for the entire
application. The notices below apply to the identified third-party components.

## Fraggler

The embedded Python package in `fraggler/` and derived analysis code in
`core/analysis/` build on [Fraggler](https://github.com/willros/fraggler), by
William Rosenbaum and Pär Larsson, Clinical Genomic Umea.

The upstream MIT license is reproduced in
[LICENSES/fraggler_MIT.txt](LICENSES/fraggler_MIT.txt) and distributed with the
application, including Python wheels and desktop bundles.

## Plotly.js

The bundled Plotly.js files in `assets/` retain their upstream copyright and MIT
license headers. Plotly is used to render interactive, offline HTML reports.

## Runtime dependencies

Python and Rust dependencies retain their respective licenses. Python dependency
declarations are in `requirements.txt`; Rust dependency declarations and resolved
versions are in `fraggler-v2/Cargo.toml` and `fraggler-v2/Cargo.lock`. A packaged
desktop application also includes the notices supplied by its dependency wheels
and Qt distribution.
