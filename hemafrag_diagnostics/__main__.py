"""Official installed entry point for the existing HemaFrag Qt application."""

from __future__ import annotations


def main() -> None:
    """Delegate to the existing validated Qt startup function."""
    from qt_app import main as run_app

    run_app()


if __name__ == "__main__":
    main()
