#!/usr/bin/env python3
"""
Refresh the slim plotly-basic bundle used for self-contained per-patient
HTML reports.

This script is run as part of Plan 07 PR-A / PR-B. It downloads the
canonical basic partial from unpkg.com, saves it to
`assets/plotly-3.1.0-basic.min.js`, and re-runs the size + API
coverage tests in `tests/test_html_report_size.py`.

CLI:
    python scripts/refresh_slim_plotly.py

Exit codes:
    0  success
    1  download failed
    2  size budget exceeded
    3  API coverage check failed
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
SLIM_JS_PATH = ASSETS_DIR / "plotly-3.1.0-basic.min.js"
URL = "https://unpkg.com/plotly.js-basic-dist-min/plotly-basic.min.js"
SIZE_BUDGET_BYTES = 1_500_000  # generous; actual ~1.1 MB


def download_slim() -> None:
    print(f"Fetching {URL} -> {SLIM_JS_PATH}")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SLIM_JS_PATH.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(URL, timeout=60) as resp:
            with tmp.open("wb") as f:
                shutil.copyfileobj(resp, f)
    except Exception as exc:
        print(f"download failed: {exc}")
        if tmp.exists():
            tmp.unlink()
        sys.exit(1)
    tmp.replace(SLIM_JS_PATH)


def check_size() -> None:
    size = SLIM_JS_PATH.stat().st_size
    print(f"slim bundle size: {size} bytes")
    if size > SIZE_BUDGET_BYTES:
        print(f"FAIL: exceeds budget {SIZE_BUDGET_BYTES}")
        sys.exit(2)


def check_api_coverage() -> None:
    print("Running API coverage test in tests/test_html_report_size.py")
    r = subprocess.run(
        ["python3", "-m", "unittest", "tests.test_html_report_size"],
        cwd=REPO_ROOT,
    )
    if r.returncode != 0:
        print("FAIL: API coverage test failed")
        sys.exit(3)


def main() -> None:
    download_slim()
    check_size()
    check_api_coverage()
    print("OK")


if __name__ == "__main__":
    main()
