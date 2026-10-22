"""HemaFrag clonality analysis package.

Patient-sample clonality analysis, QC, rule interpretation, and tracking.

Public submodules:
- `pipeline`              : main patient-sample QC pipeline
- `interpretation`        : assay-specific interpretation helpers + v1
                           interpretation-dispatch scaffold
- `classification`        : control / QC classification
- `config`                : assay-specific config tables
- `ladder_review_gate`    : GS500ROX ladder review filtering gates
- `tracking_excel`        : per-run + global Excel workbook helpers
- `tracking_dashboard`    : global dashboard workbook update helper
- `scoring`               : shared scoring utilities
"""
