#!/usr/bin/env python3
"""Compatibility entrypoint for FLT3 ROX500 all-injections QC."""

from __future__ import annotations

try:
    from scripts.run_flt3_liz500_qc_all_injections import main, run_qc
except ModuleNotFoundError:
    from run_flt3_liz500_qc_all_injections import main, run_qc


if __name__ == "__main__":
    main()
