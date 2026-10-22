"""Exercise the distributed Rust wheel with synthetic ABIF inputs."""
from __future__ import annotations

import array
from pathlib import Path
import struct
import sys

import pytest


def _write_abif(path: Path, channels: list[int], *, truncated_count: bool = False) -> None:
    scan_count = 5000
    trace = array.array("h", [0]) * scan_count
    for scan in [1500, 1600, 1750, 1900, 2100, 2200, 2300, 2500, 2800,
                 3100, 3400, 3500, 3800, 4100, 4350, 4400]:
        trace[scan - 1:scan + 2] = array.array("h", [300, 1000, 300])
    if sys.byteorder == "little":
        trace.byteswap()
    payload = trace.tobytes()
    header = b"ABIF" + struct.pack(
        ">H4sIHHIIII", 101, b"tdir", 1, 1023, 28,
        len(channels), len(channels) * 28, 34, 0,
    )
    offset = len(header) + len(channels) * 28
    directory = b"".join(
        struct.pack(
            ">4sIHHIIII", b"DATA", channel, 4, 2,
            scan_count + int(truncated_count), len(payload),
            offset + index * len(payload), 0,
        )
        for index, channel in enumerate(channels)
    )
    path.write_bytes(header + directory + payload * len(channels))


@pytest.mark.parametrize(
    ("name", "kind", "channels", "expected_channel", "expected_ladder"),
    [
        ("synthetic_ITD.fsa", "flt3", [1, 4, 105], "DATA4", "GS500ROX"),
        ("synthetic_IGK.fsa", "clonality", [1, 4, 5], "DATA5", "LIZ500_250"),
    ],
)
def test_native_engine_uses_assay_channel_contract(
    tmp_path, name, kind, channels, expected_channel, expected_ladder
):
    native = pytest.importorskip("fraggler_native")
    path = tmp_path / name
    _write_abif(path, channels)

    result = native.analyze_fsa(str(path), kind)

    assert result["size_standard_channel_guess"] == expected_channel
    assert result["ladder"] == expected_ladder
    assert result["scan_count"] == 5000


def test_native_engine_rejects_truncated_channel_payload(tmp_path):
    native = pytest.importorskip("fraggler_native")
    path = tmp_path / "truncated_ITD.fsa"
    _write_abif(path, [1, 4], truncated_count=True)

    with pytest.raises(RuntimeError, match="too few bytes"):
        native.analyze_fsa(str(path), "flt3")
