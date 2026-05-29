#!/usr/bin/env python3
"""Create a clean HemaFrag source transfer zip for a Windows PC."""

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path


DEFAULT_ZIP = Path("/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows_Transfer.zip")
DEFAULT_WINDOWS_APP_DIR = Path("/Volumes/T7 Shield/HemaFrag/Windows")

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".obsidian",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
    "build",
    "data",
    "dist",
    "local_triage",
    "review_bundle_final_two_igk_a05",
    "review_bundle_linear_max_over5",
    "review_bundle_overnight_soft_fail_2026-05-05",
    "review_bundle_remaining_global",
    "review_bundle_worst_now",
    "target",
    "tmp_rust_review_results_timed",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
}

EXCLUDED_NAMES = {
    ".DS_Store",
    "output_linear_max_over20.txt",
    "output_linear_max_over5.json",
    "output_linear_max_over5.tsv",
}


def should_skip(path: Path, root: Path, include_git: bool) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts

    if not include_git and ".git" in parts:
        return True
    if any(part in EXCLUDED_DIRS and (part != ".git" or not include_git) for part in parts):
        return True
    if path.name in EXCLUDED_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    if path.name.startswith("._"):
        return True
    return False


def iter_files(root: Path, include_git: bool):
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        dirs[:] = [
            d for d in dirs
            if not should_skip(current / d, root, include_git)
        ]
        for name in files:
            path = current / name
            if not should_skip(path, root, include_git):
                yield path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--include-git", action="store_true")
    parser.add_argument(
        "--windows-app-dir",
        type=Path,
        default=DEFAULT_WINDOWS_APP_DIR,
        help="Directory containing optional ready-made Windows app zip and guide.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(iter_files(root, args.include_git))
    if not files:
        raise SystemExit(f"No files selected from {root}")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            zf.write(path, Path("HemaFrag") / path.relative_to(root))
        for extra_name in ("HemaFrag_Windows.zip", "HemaFrag_Windows_PC_Guide.md"):
            extra = args.windows_app_dir / extra_name
            if extra.exists() and extra.resolve() != output:
                zf.write(extra, Path("WindowsApp") / extra.name)

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Wrote {output}")
    print(f"Files: {len(files)}")
    print(f"Size: {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
