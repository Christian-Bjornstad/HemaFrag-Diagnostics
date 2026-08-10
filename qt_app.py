"""
HemaFrag Diagnostics — Main Entry Point for PyQt6 UI
"""
import multiprocessing
import sys
import os
import locale
from dataclasses import dataclass
from pathlib import Path

from app_meta import APP_NAME, APP_VERSION
from app_resources import load_application_icon, set_windows_app_user_model_id


class _NullTextStream:
    encoding = "utf-8"

    def write(self, _text):
        return 0

    def flush(self):
        return None

    def isatty(self):
        return False

    def reconfigure(self, **_kwargs):
        return None


if sys.stdout is None:
    sys.stdout = _NullTextStream()
if sys.stderr is None:
    sys.stderr = _NullTextStream()

# Force X11 (xcb) on Linux to avoid Wayland symbol mismatches (e.g., wl_proxy_marshal_flags)
if sys.platform == "linux":
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    os.environ.setdefault("LANG", "C.UTF-8")
    os.environ.setdefault("LC_ALL", "C.UTF-8")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from core.log import log

LEGACY_PANEL_HOST = "localhost"
LEGACY_PANEL_PORT = 5078
LEGACY_PANEL_ENABLED = (
    os.environ.get("HEMAFRAG_ENABLE_LEGACY_PANEL", os.environ.get("FRAGGLER_ENABLE_LEGACY_PANEL", "")).lower()
    in {"1", "true", "yes"}
)


@dataclass(frozen=True)
class StartupOptions:
    qt_argv: tuple[str, ...]
    review_bundle: Path | None = None


def parse_startup_options(argv: list[str]) -> StartupOptions:
    """Remove HemaFrag startup options while preserving Qt's arguments."""

    qt_argv: list[str] = []
    review_bundle: Path | None = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument != "--ladder-review-bundle":
            qt_argv.append(argument)
            index += 1
            continue
        if review_bundle is not None:
            raise ValueError("--ladder-review-bundle may only be supplied once.")
        if index + 1 >= len(argv):
            raise ValueError("--ladder-review-bundle requires a directory.")
        review_bundle = Path(argv[index + 1]).expanduser().resolve()
        cases_path = review_bundle / "ladder_review_cases.csv"
        if not cases_path.is_file():
            raise FileNotFoundError(f"Missing review bundle file: {cases_path}")
        index += 2
    return StartupOptions(qt_argv=tuple(qt_argv), review_bundle=review_bundle)


def _remove_macos_metadata_files(bundle_dir: Path) -> None:
    """Delete AppleDouble/Finder metadata files that can break Linux runtime imports."""
    patterns = ("._*", ".DS_Store")
    removed = 0
    for pattern in patterns:
        for path in bundle_dir.rglob(pattern):
            if not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    if removed:
        log(f"[INFO] Removed {removed} macOS metadata file(s) from bundle: {bundle_dir}")


def _prepare_runtime_bundle() -> Path:
    bundle_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
    _remove_macos_metadata_files(bundle_dir)
    return bundle_dir


_BUNDLE_DIR = _prepare_runtime_bundle()

from gui_qt.main_window import MainWindow

def start_panel_server():
    """Start the legacy Panel server when explicitly requested."""
    try:
        import panel as pn
        # Resolve path to app.py relative to this file
        app_path = os.path.join(_BUNDLE_DIR, "app.py")
        
        if not os.path.exists(app_path):
            log(f"[WARN] Could not find legacy app.py at {app_path}. Server not started.")
            return

        log(
            f"[INFO] Starting legacy Panel server at "
            f"http://{LEGACY_PANEL_HOST}:{LEGACY_PANEL_PORT}/app"
        )

        pn.serve(
            {"app": app_path},
            port=LEGACY_PANEL_PORT,
            address=LEGACY_PANEL_HOST,
            show=False,
            title="HemaFrag Diagnostics",
            verbose=False,
        )
    except Exception as e:
        log(f"[ERROR] Failed to start legacy web server: {e}")

def exception_hook(exctype, value, tb):
    """Global exception handler to prevent silent crashes in slots."""
    import traceback
    from PyQt6.QtWidgets import QMessageBox
    
    err_msg = "".join(traceback.format_exception(exctype, value, tb))
    print(err_msg, file=sys.stderr)
    
    # Try to show a message box
    try:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("An unexpected error occurred.")
        msg.setInformativeText(str(value))
        msg.setDetailedText(err_msg)
        msg.setWindowTitle("Error")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    except:
        pass
    
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = exception_hook

def main():
    startup = parse_startup_options(list(sys.argv))
    if sys.platform == "linux":
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            try:
                locale.setlocale(locale.LC_ALL, "C.UTF-8")
            except locale.Error:
                pass

    # Windows otherwise groups a source-launched Qt window under the generic
    # Python interpreter icon.  This identity must be set before QApplication.
    set_windows_app_user_model_id(log_message=log)

    app = QApplication(list(startup.qt_argv))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("OUS")
    app.setApplicationVersion(APP_VERSION)
    
    app_icon = load_application_icon(bundle_dir=_BUNDLE_DIR, log_message=log)
    if app_icon is not None:
        app.setWindowIcon(app_icon)
    
    if LEGACY_PANEL_ENABLED:
        import threading
        server_thread = threading.Thread(target=start_panel_server, daemon=True)
        server_thread.start()

    window = MainWindow()
    window.resize(1200, 800)
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()
    if startup.review_bundle is not None:
        QTimer.singleShot(
            0,
            lambda bundle=startup.review_bundle: window._open_archive_ladder_review(
                "clonality", bundle
            ),
        )
    
    sys.exit(app.exec())

if __name__ == "__main__":
    # Ensure stdout/stderr use UTF-8 regardless of environment locales
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    multiprocessing.freeze_support()
    
    try:
        main()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"CRITICAL STARTUP ERROR:\n{err_msg}", file=sys.stderr)
        
        # If QApplication was already created (unlikely here but for safety)
        # we try to show a message box.
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
            
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Startup Error")
        msg.setText("HemaFrag Diagnostics failed to start.")
        msg.setInformativeText(str(e))
        msg.setDetailedText(err_msg)
        msg.exec()
        sys.exit(1)
