"""Operator attribution shared by report formats."""
from html import escape

def operator_name(entries=None, settings=None):
    for entry in entries or ():
        if "operator" in entry:
            return str(entry["operator"] or "")
    if settings is None:
        from config import APP_SETTINGS
        settings = APP_SETTINGS
    return str(settings.get("general", {}).get("author") or "").strip()

def operator_html(entries=None):
    name = operator_name(entries)
    return f"Operatør: {escape(name)}" if name else ""
