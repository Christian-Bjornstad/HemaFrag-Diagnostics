from __future__ import annotations

import copy

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from config import APP_SETTINGS, save_settings


def native_engine_status() -> str:
    """Return a lightweight, truthful status without importing analysis code."""
    try:
        import fraggler_native as native
    except (ImportError, OSError):
        return "In-process Rust engine unavailable. Check the installed engine or configured workflow."
    try:
        available = bool(native.is_available())
    except Exception:
        available = False
    version = getattr(native, "version", getattr(native, "__version__", None))
    if not available:
        return "In-process Rust engine unavailable. Check the installed engine or configured workflow."
    return f"In-process Rust engine available{f' (version {version})' if version else ''}."


class TabAppSettings(QWidget):
    settings_saved = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._refreshing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("App Settings")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Shared author and quality settings used by every analysis profile.")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)
        self.dirty_lbl = QLabel("")
        self.dirty_lbl.setAccessibleName("Unsaved changes status")
        layout.addWidget(self.dirty_lbl)

        card = QWidget()
        card.setObjectName("Card")
        form = QFormLayout(card)
        self.author = QLineEdit()
        self.author.setAccessibleName("Author for annotations and reports")
        form.addRow("Author (annotations and reports):", self.author)
        self.d_min_r2_ok = self._r2_spin()
        form.addRow("Min R² (OK):", self.d_min_r2_ok)
        self.d_min_r2_warn = self._r2_spin()
        form.addRow("Min R² (WARN):", self.d_min_r2_warn)
        self.engine_status = QLabel(native_engine_status())
        self.engine_status.setWordWrap(True)
        self.engine_status.setAccessibleName("Analysis engine status")
        form.addRow("Engine:", self.engine_status)
        layout.addWidget(card)

        self.status_lbl = QLabel("")
        self.status_lbl.setAccessibleName("Save status")
        layout.addWidget(self._save_button())
        layout.addWidget(self.status_lbl)
        layout.addStretch()
        self.refresh_from_settings()
        self.author.textChanged.connect(lambda _value: self._set_dirty())
        self.d_min_r2_ok.valueChanged.connect(lambda _value: self._set_dirty())
        self.d_min_r2_warn.valueChanged.connect(lambda _value: self._set_dirty())

    @staticmethod
    def _r2_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1)
        spin.setSingleStep(0.001)
        spin.setDecimals(3)
        return spin

    def _save_button(self) -> QPushButton:
        button = QPushButton("Save App Settings")
        button.setObjectName("PrimaryButton")
        button.clicked.connect(self.save)
        return button

    def is_dirty(self) -> bool:
        return bool(self.dirty_lbl.text())

    def _set_dirty(self, dirty: bool = True) -> None:
        if not self._refreshing:
            self.dirty_lbl.setText("Unsaved app changes" if dirty else "")
            self.dirty_lbl.setStyleSheet("color: #b45309; font-weight: 500;")

    def refresh_from_settings(self) -> None:
        if self.is_dirty():
            return
        self._refreshing = True
        general = APP_SETTINGS.get("general", {})
        qc = APP_SETTINGS.get("qc", {})
        self.author.setText(str(general.get("author", "OUS")))
        self.d_min_r2_ok.setValue(float(qc.get("min_r2_ok", 0.995)))
        self.d_min_r2_warn.setValue(float(qc.get("min_r2_warn", 0.990)))
        self._refreshing = False
        self._set_dirty(False)

    def save(self) -> bool:
        window = self.window()
        changes_allowed = getattr(window, "settings_changes_allowed", None)
        if callable(changes_allowed) and not changes_allowed():
            self._show_error("Settings cannot be saved while an operation is running.")
            return False
        if self.d_min_r2_warn.value() > self.d_min_r2_ok.value():
            self.d_min_r2_warn.setFocus()
            self._show_error("Min R² (WARN) must be less than or equal to Min R² (OK).")
            return False
        proposed = copy.deepcopy(APP_SETTINGS)
        proposed.setdefault("general", {})["author"] = self.author.text().strip()
        proposed.setdefault("qc", {})["min_r2_ok"] = self.d_min_r2_ok.value()
        proposed.setdefault("qc", {})["min_r2_warn"] = self.d_min_r2_warn.value()
        if not save_settings(proposed):
            self._show_error(config.LAST_SETTINGS_SAVE_ERROR or "Failed to save settings.")
            return False
        APP_SETTINGS.clear()
        APP_SETTINGS.update(proposed)
        self.settings_saved.emit("app")
        self.status_lbl.setText("App settings saved.")
        self.status_lbl.setStyleSheet("color: #15803d; font-weight: 500;")
        self._set_dirty(False)
        return True

    def _show_error(self, message: str) -> None:
        self.status_lbl.setText(message)
        self.status_lbl.setStyleSheet("color: #b91c1c; font-weight: 500;")
