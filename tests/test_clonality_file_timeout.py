import os
import sys
import time
from pathlib import Path

import pytest

from core.analyses.clonality import pipeline


@pytest.mark.skipif(os.name != "posix" or getattr(sys, "frozen", False), reason="isolated timeout uses posix fork in source runs")
def test_clonality_file_timeout_terminates_hung_analysis(monkeypatch):
    def sleepy(_path):
        time.sleep(5)
        return {"unexpected": True}

    monkeypatch.setattr(pipeline, "_analyze_single_file", sleepy)

    started = time.monotonic()
    result, reason = pipeline._analyze_single_file_with_timeout(Path("dummy.fsa"), 1)
    elapsed = time.monotonic() - started

    assert result is None
    assert reason == "timeout_after_1s"
    assert elapsed < 3
