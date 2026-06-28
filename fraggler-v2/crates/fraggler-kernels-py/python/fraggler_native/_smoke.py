"""Smoke-test the in-process Rust engine.

Run after `pip install -e fraggler-v2/crates/fraggler-kernels-py`:
    python -m fraggler_native._smoke path/to/file.fsa
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fraggler_native import analyze_fsa, is_available, fraggler_cli_path


def main(argv: list[str]) -> int:
    if not is_available():
        print(
            "[FAIL] fraggler_native is not available. Did you pip install "
            "fraggler-v2/crates/fraggler-kernels-py?",
            file=sys.stderr,
        )
        return 1

    if len(argv) != 2:
        print("usage: python -m fraggler_native._smoke <path.fsa>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"[FAIL] {path} does not exist", file=sys.stderr)
        return 2

    print(f"[OK ]  in-process Rust path is enabled")
    cli = fraggler_cli_path()
    print(f"[INFO] sibling fraggler-cli binary: {cli or '<not built>'}")

    print(f"[RUN]  analyze_fsa({path}, 'clonality')")
    result = analyze_fsa(str(path), "clonality")
    print("[OK ]  result keys:", sorted(result.keys()))

    print("\n== pretty-printed first 600 chars ==")
    as_json = json.dumps(result, indent=2, default=str)
    sys.stdout.write(as_json[:600])
    print("\n...")
    print("\n(key entries)")
    for k in (
        "file_name", "scan_count", "data_channels", "ladder",
        "sample_channel_guess", "size_standard_channel_guess",
        "ladder_peak_count",
    ):
        print(f"  {k}: {result.get(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
