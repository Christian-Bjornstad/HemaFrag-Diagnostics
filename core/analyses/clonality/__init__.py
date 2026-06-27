"""HemaFrag clonality analysis package.

Per project memory, the clonality subsystem is **parked** and should NOT
drive new context unless explicitly requested. This package contains the
patient-sample clonality QC pipeline and supporting helpers but is not
the focus of current FLT3 work.

Public submodules:
- `pipeline`              : main patient-sample QC pipeline
- `interpretation`        : assay-specific interpretation helpers + v1
                           interpretation-dispatch scaffold
- `classification`        : control / QC classification
- `config`                : assay-specific config tables
- `ladder_review_gate`    : GS500ROX ladder review filtering gates
- `candidate_artifacts`   : clonality candidate artifact I/O
- `feature_artifacts`     : trace feature artifact I/O
- `tracking_excel`        : per-run + global Excel workbook helpers
- `tracking_dashboard`    : global dashboard workbook update helper
- `scoring`               : shared scoring utilities
"""
