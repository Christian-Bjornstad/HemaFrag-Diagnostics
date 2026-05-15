# HemaFrag Third-Party Notices

HemaFrag contains and builds on MIT-licensed code and concepts from the upstream
[`willros/fraggler`](https://github.com/willros/fraggler) project.

## Upstream project

- Project: `fraggler`
- Upstream repository: <https://github.com/willros/fraggler>
- Authors listed upstream: William Rosenbaum and Pär Larsson
- Upstream license: MIT
- Upstream copyright notice: `Copyright (c) 2023 Clinical Genomic Umea`

The MIT license text used by the upstream project is included verbatim in
[`LICENSES/fraggler_MIT.txt`](LICENSES/fraggler_MIT.txt).

## Local areas derived from or closely based on upstream

The following areas in this repository should be treated as likely upstream-derived or vendored
foundations that preserve the upstream MIT notice:

- [`fraggler/`](fraggler)
  - Local embedded runtime module used by the application
  - Includes ladder definitions and FSA/baseline-related logic derived from the upstream package
- [`core/analysis.py`](core/analysis.py)
  - Contains explicit references to upstream Fraggler logic and builds on the local `fraggler`
    runtime module

These areas have been substantially modified and extended for the HemaFrag application,
including clinical workflow, GUI, QC tracking, reporting, archive validation, and assay-specific
logic that are not part of the upstream package.

## Python dependency license review

Local package metadata from the current Python environment was reviewed on 2026-05-15 against
`requirements.txt`. Most scientific/runtime dependencies are permissive or weak-copyleft packages
commonly used in internal clinical/research tooling:

- BSD/MIT/Apache/PSF-style packages include NumPy, SciPy, pandas, scikit-learn, matplotlib,
  openpyxl, requests, Plotly, Panel/Bokeh, pyqtgraph, PyYAML, Jinja2, tqdm, and related support
  packages.
- MPL-licensed packages are present (`certifi`; `tqdm` metadata also lists MPL/MIT). MPL is
  file-level weak copyleft and is usually compatible with internal use, but keep bundled license
  notices if distributing an application bundle.
- `PyQt6` is the main item requiring explicit governance. The installed `PyQt6` wheel includes a
  GPL-3.0 license file; `PyQt6-Qt6` metadata lists LGPLv3. For internal OUS diagnostic use this may
  be acceptable if the legal/IT policy permits GPL components, but if HemaFrag is distributed as a
  closed application outside the organization or to third parties, OUS should either obtain the
  appropriate Riverbank commercial PyQt license or migrate the GUI binding to an LGPL alternative
  such as PySide6, subject to technical validation.

This is an engineering license inventory, not legal advice. Before clinical deployment or wider
distribution, OUS should confirm the PyQt6 position and retain third-party license notices in any
packaged build.

## Repository licensing status

This repository does **not** currently declare a single root open-source license for the whole
project. The application contains third-party MIT-licensed components and derived code, while the
repository as a whole remains otherwise unpublished under a separate open-source license.

This notice is intended to preserve attribution and license visibility for upstream-derived code.
