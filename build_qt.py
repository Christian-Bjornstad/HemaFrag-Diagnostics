from __future__ import annotations

import dis
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


# Monkey-patch dis._get_const_info to swallow known Python 3.10 bytecode IndexErrors
_orig_get_const_info = getattr(dis, '_get_const_info', None)
if _orig_get_const_info:
    def _patched_get_const_info(*args, **kwargs):
        try:
            return _orig_get_const_info(*args, **kwargs)
        except IndexError:
            # Python 3.10/3.11 use ``(arg, constants)`` while newer
            # interpreters include the opcode first.  In both forms the
            # argument is immediately before the constants tuple.
            arg = args[-2] if len(args) >= 2 else kwargs.get("arg")
            return arg, repr(arg)
    dis._get_const_info = _patched_get_const_info

APP_NAME = "HemaFrag"
PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
RELEASE_DIR = DIST_DIR / "releases"
HOOK_DIR = PROJECT_ROOT / "packaging" / "hooks"
SPEC_DIR = PROJECT_ROOT / "build" / "specs" / sys.platform

COMMON_HIDDEN_IMPORTS = [
    "PyQt6",
    "pandas",
    "plotly",
    "core.analyses.general.config",
    "core.analyses.general.classification",
    "core.analyses.general.pipeline",
    "core.analyses.clonality.config",
    "core.analyses.clonality.classification",
    "core.analyses.clonality.pipeline",
    "core.analyses.flt3.config",
    "core.analyses.flt3.classification",
    "core.analyses.flt3.pipeline",
]

COMMON_DATAS = [
    ("assets", "assets"),
    ("app.py", "."),
    ("LICENSES", "LICENSES"),
    ("THIRD_PARTY_NOTICES.md", "."),
]

def _format_data_arg(src: str, dest: str) -> str:
    source = Path(src)
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    return f"--add-data={source};{dest}"


def _format_binary_arg(src: str, dest: str) -> str:
    return f"--add-binary={src};{dest}"


def _build_pyinstaller_args(*, include_rust_engine: bool = True) -> list[str]:
    args = [
        "qt_app.py",
        f"--name={APP_NAME}",
        "--noconfirm",
        "--clean",
        "--windowed",
        f"--distpath={DIST_DIR}",
        f"--workpath={PROJECT_ROOT / 'build'}",
        f"--specpath={SPEC_DIR}",
        f"--additional-hooks-dir={HOOK_DIR}",
        f"--runtime-hook={HOOK_DIR / 'runtime_desktop.py'}",
    ]

    for src, dest in COMMON_DATAS:
        args.append(_format_data_arg(src, dest))
    for mod in COMMON_HIDDEN_IMPORTS:
        args.append(f"--hidden-import={mod}")

    if include_rust_engine:
        # Cargo verifies that the recovery CLI matches the source being shipped.
        subprocess.run(
            ["cargo", "build", "--locked", "--release", "-p", "fraggler-cli"],
            cwd=PROJECT_ROOT / "fraggler-v2",
            check=True,
        )
        rust_binary = PROJECT_ROOT / "fraggler-v2/target/release/fraggler-cli.exe"
        if not rust_binary.is_file():
            raise FileNotFoundError(f"Rust build did not produce {rust_binary}")
        args.append(_format_binary_arg(str(rust_binary), "."))

    args.append(f"--icon={PROJECT_ROOT / 'assets' / 'app_icon.ico'}")

    return args


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _prepare_build_dirs() -> None:
    # Only clear the temporary outputs owned by this Windows build.
    for path in [
        DIST_DIR / APP_NAME,
        PROJECT_ROOT / "build" / APP_NAME,
    ]:
        _remove_path(path)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)


def _zip_path(src: Path, zip_path: Path, root_name: str | None = None) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if src.is_dir():
            for file_path in sorted(src.rglob("*")):
                if file_path.is_dir():
                    continue
                if file_path.name.startswith("._") or file_path.name == ".DS_Store":
                    continue
                rel = file_path.relative_to(src)
                arcname = Path(root_name or src.name) / rel
                zf.write(file_path, arcname.as_posix())
        else:
            zf.write(src, (root_name or src.name))
    return zip_path


def _stage_release_dir(name: str) -> Path:
    target = DIST_DIR / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target


def _post_build_windows() -> None:
    source_dir = DIST_DIR / APP_NAME
    release_dir = _stage_release_dir("HemaFrag_Windows")
    shutil.copytree(source_dir, release_dir, dirs_exist_ok=True)
    zip_path = RELEASE_DIR / "HemaFrag_Windows.zip"
    _zip_path(release_dir, zip_path, root_name=release_dir.name)
    print(f"Created Windows bundle: {zip_path}")


def _prioritize_windows_system_libraries() -> None:
    # Qt uses Windows' ICU API. A tool such as Poppler/Conda on PATH can
    # otherwise cause PyInstaller to bundle an incompatible same-named DLL.
    system_dir = Path(os.environ["SystemRoot"]) / "System32"
    if not system_dir.is_dir():
        raise FileNotFoundError(f"Windows system library directory is missing: {system_dir}")
    other_paths = [
        entry for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and os.path.normcase(os.path.normpath(entry)) != os.path.normcase(str(system_dir))
    ]
    os.environ["PATH"] = os.pathsep.join([str(system_dir), *other_paths])


def build_app() -> None:
    if sys.platform != "win32":
        raise RuntimeError("HemaFrag desktop packaging requires Windows 10 or 11 (x64).")
    if not (3, 12) <= sys.version_info[:2] < (3, 15) or sys.maxsize <= 2**32:
        raise RuntimeError("Use 64-bit Python 3.12, 3.13, or 3.14 to build HemaFrag.")
    _prioritize_windows_system_libraries()
    import PyInstaller.__main__

    print(f"Building HemaFrag Diagnostics desktop app for {sys.platform}...")
    _prepare_build_dirs()
    PyInstaller.__main__.run(_build_pyinstaller_args())

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    _post_build_windows()

    print("\nBuild complete! Check the 'dist' directory.")

if __name__ == "__main__":
    build_app()
