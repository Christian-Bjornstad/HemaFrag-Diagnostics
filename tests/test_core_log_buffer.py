"""Regression tests for core.log.LogBuffer.

The buffer used to build its text with ``self.text += msg + "\\n"`` —
quadratic in line count (~470 us/line measured at 20k lines). It now
appends to a list and joins lazily, keeping the param-compatible API.
"""

from __future__ import annotations

import time

from core.log import LogBuffer


def test_write_and_text_roundtrip():
    buf = LogBuffer()
    buf.write("alpha")
    buf.write("beta")
    assert buf.text == "alpha\nbeta"


def test_text_setter_replaces_content():
    buf = LogBuffer()
    buf.write("old")
    buf.text = "reset"
    assert buf.text == "reset"


def test_watchers_fire_on_write_and_clear():
    buf = LogBuffer()
    seen: list[str] = []
    buf.watch(lambda: seen.append(buf.text))
    buf.write("gamma")
    assert seen == ["gamma"]
    buf.clear()
    assert seen[-1] == ""
    assert buf.text == ""


def test_write_is_linear_not_quadratic():
    """20k writes must stay in the sub-second range (was ~9.4 s quadratic)."""
    buf = LogBuffer()
    buf.watch(lambda: None)  # one watcher, like real usage
    line = "x" * 140
    start = time.perf_counter()
    for _ in range(20_000):
        buf.write(line)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"log writing regressed to quadratic: {elapsed:.2f}s for 20k lines"
