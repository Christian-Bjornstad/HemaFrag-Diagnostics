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


@pytest.mark.skipif(os.name != "posix" or getattr(sys, "frozen", False), reason="isolated timeout uses posix fork in source runs")
def test_clonality_file_timeout_returns_large_success_payload(monkeypatch):
    payload = {"blob": "x" * (8 * 1024 * 1024)}

    def large_result(_path):
        return payload

    monkeypatch.setattr(pipeline, "_analyze_single_file", large_result)

    result, reason = pipeline._analyze_single_file_with_timeout(Path("dummy.fsa"), 10)

    assert reason == ""
    assert result == payload


def test_clonality_child_temporarily_disables_persistent_rust_worker(monkeypatch):
    seen = {}

    def fake_analyze(_path):
        seen["disabled"] = os.environ.get("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER")
        return {"ok": True}

    monkeypatch.setattr(pipeline, "_analyze_single_file", fake_analyze)
    monkeypatch.delenv("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER", raising=False)

    class Queue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

    queue = Queue()
    pipeline._run_analyze_single_file_child(Path("dummy.fsa"), queue)

    assert seen["disabled"] == "1"
    assert os.environ.get("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER") is None
    assert queue.items[0][0] == "ok"
    assert queue.items[0][1]["ok"] is True
    assert "_rust_engine_stats_delta" in queue.items[0][1]
