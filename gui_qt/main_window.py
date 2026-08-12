from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QStackedWidget, QPushButton, QLabel, QFrame, QComboBox, QScrollArea, QApplication
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QShortcut, QKeySequence

from app_meta import APP_VERSION
from gui_qt.styles import VIBRANT_PRO_QSS
from gui_qt.tabs.tab_batch import TabBatch
from gui_qt.tabs.tab_archive_runner import TabArchiveRunner
from gui_qt.tabs.tab_labeling import TabLabeling
from gui_qt.tabs.tab_flt3_validation import TabFlt3Validation
from gui_qt.tabs.tab_ladder import TabLadder
from gui_qt.tabs.tab_log import TabLog
from gui_qt.tabs.tab_about import TabAbout
from gui_qt.tabs.tab_settings import TabAnalysisSettings
from gui_qt.widgets.brand_lockup import BrandLockup
from config import APP_SETTINGS, get_analysis_settings, save_settings

class SidebarButton(QPushButton):
    def __init__(self, text, icon_name=None, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

class AnalysisGroupHeader(QPushButton):
    """The main button for an analysis type (e.g. Klonalitet)."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("AnalysisGroupHeader")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

class AnalysisSubButton(QPushButton):
    """The sub-buttons that appear when a group is expanded."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("AnalysisSubButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

class AnalysisGroup(QWidget):
    """Container for an analysis header and its sub-buttons."""
    def __init__(self, name, internal_id, on_sub_clicked, sub_buttons: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.internal_id = internal_id
        self.on_sub_clicked = on_sub_clicked
        self.sub_button_labels = sub_buttons or ["Run", "Ladder", "Log", "Settings"]
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self.header = AnalysisGroupHeader(name)
        self.layout.addWidget(self.header)
        
        self.sub_container = QWidget()
        self.sub_layout = QVBoxLayout(self.sub_container)
        self.sub_layout.setContentsMargins(0, 0, 0, 0)
        self.sub_layout.setSpacing(0)
        
        self.sub_buttons = []
        for label in self.sub_button_labels:
            button = AnalysisSubButton(f"•  {label}")
            self.sub_buttons.append(button)
        self.btn_run = self.button_for_label("Run")
        self.btn_ladder = self.button_for_label("Ladder")
        self.btn_archive = self.button_for_label("Archive Runner")
        self.btn_log = self.button_for_label("Log")
        self.btn_settings = self.button_for_label("Settings")
        for i, btn in enumerate(self.sub_buttons):
            self.sub_layout.addWidget(btn)
            btn.clicked.connect(lambda _, b=btn, idx=i: self._handle_sub_click(b, idx))
            
        self.layout.addWidget(self.sub_container)
        self.sub_container.setVisible(False)
        
        self.header.clicked.connect(self.toggle_expansion)

    def button_for_label(self, label: str) -> AnalysisSubButton | None:
        try:
            return self.sub_buttons[self.sub_button_labels.index(label)]
        except ValueError:
            return None
        
    def _handle_sub_click(self, clicked_btn, tab_idx):
        for btn in self.sub_buttons:
            btn.setChecked(btn == clicked_btn)
        self.on_sub_clicked(self.internal_id, tab_idx)

    def toggle_expansion(self):
        # We handle expansion control from MainWindow to ensure only one is open
        pass
        
    def set_expanded(self, expanded):
        self.header.setChecked(expanded)
        self.sub_container.setVisible(expanded)
        if not expanded:
            for btn in self.sub_buttons:
                btn.setChecked(False)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"HemaFrag Diagnostics v{APP_VERSION}")
        self.setStyleSheet(VIBRANT_PRO_QSS)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # --- Sidebar ---
        self.sidebar_container = QWidget()
        self.sidebar_container.setObjectName("Sidebar")
        self.sidebar_container.setFixedWidth(220)
        
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(4)
        
        app = QApplication.instance()
        brand = BrandLockup(app.windowIcon() if app is not None else None)
        sidebar_layout.addWidget(brand)
        
        sidebar_layout.addSpacing(10)
        
        # --- Analysis Groups ---
        self.groups = []
        
        self.group_clonality = AnalysisGroup(
            "Klonalitet",
            "clonality",
            self.on_sub_tab_clicked,
            sub_buttons=[
                "Run",
                "Ladder",
                "Archive Runner",
                "Log",
                "Labeling",
                "Settings",
            ],
        )
        self.group_flt3 = AnalysisGroup(
            "FLT3 Analysis",
            "flt3",
            self.on_sub_tab_clicked,
            sub_buttons=[
                "Run",
                "Ladder",
                "Archive Runner",
                "Log",
                "Settings",
            ],
        )
        self.group_general = AnalysisGroup("General", "general", self.on_sub_tab_clicked)
        
        self.groups = [self.group_clonality, self.group_flt3, self.group_general]
        for g in self.groups:
            sidebar_layout.addWidget(g)
            g.header.clicked.connect(lambda _, grp=g: self.on_group_clicked(grp))

        sidebar_layout.addStretch()

        self.btn_about = SidebarButton("About")
        self.btn_about.clicked.connect(self.on_about_clicked)
        sidebar_layout.addWidget(self.btn_about)
        
        # --- Stacked Widget (Content) ---
        self.stacked_widget = QStackedWidget()
        
        # Tabs
        self.tab_run = TabBatch()
        self.tab_ladder = TabLadder()
        self.tab_archive_runner = TabArchiveRunner()
        self.tab_flt3_validation = TabFlt3Validation()
        self.tab_labeling = TabLabeling()
        self.tab_log = TabLog()
        self.tab_about = TabAbout()
        self.tab_settings_clonality = TabAnalysisSettings("clonality")
        self.tab_settings_flt3 = TabAnalysisSettings("flt3")
        self.tab_settings_general = TabAnalysisSettings("general")

        # Connect settings saved to reload run defaults
        self.tab_settings_clonality.settings_saved.connect(self._on_settings_saved)
        self.tab_settings_flt3.settings_saved.connect(self._on_settings_saved)
        self.tab_settings_general.settings_saved.connect(self._on_settings_saved)
        
        # Connect global core logging to this tab
        from gui_qt.log_handler import qt_log_handler
        qt_log_handler.emitter.log_signal.connect(self.tab_log.append_log)
        
        # Add to stack. NOTE: indices must match the per-analysis
        # ``sub_to_stack_index_map`` dicts further below. If you add or
        # remove a tab here, update those maps too.
        self.tab_run_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_run))
        self.tab_ladder_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_ladder))
        self.tab_archive_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_archive_runner))
        self.tab_flt3_validation_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_flt3_validation))
        self.tab_labeling_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_labeling))
        self.tab_log_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_log))
        self.tab_about_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_about))
        self.tab_settings_clonality_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_settings_clonality))
        self.tab_settings_flt3_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_settings_flt3))
        self.tab_settings_general_idx = self.stacked_widget.addWidget(self._wrap_scroll_page(self.tab_settings_general))

        # Per-analysis sub-button → stack index. Scoped by analysis_id so a
        # single ``tab_run_idx`` index can be shared cleanly. Built from a
        # structured schema instead of a hardcoded page_map dict to avoid
        # the off-by-one drift we just fixed.
        sub_button_map: dict[str, dict[str, int]] = {
            "clonality": {
                "Run": self.tab_run_idx,
                "Ladder": self.tab_ladder_idx,
                "Archive Runner": self.tab_archive_idx,
                "Log": self.tab_log_idx,
                "Labeling": self.tab_labeling_idx,
                "Settings": self.tab_settings_clonality_idx,
            },
            "flt3": {
                "Run": self.tab_run_idx,
                "Ladder": self.tab_ladder_idx,
                "Archive Runner": self.tab_archive_idx,
                "Log": self.tab_log_idx,
                "Settings": self.tab_settings_flt3_idx,
            },
            "general": {
                "Run": self.tab_run_idx,
                "Ladder": self.tab_ladder_idx,
                "Archive Runner": self.tab_archive_idx,
                "Log": self.tab_log_idx,
                "Settings": self.tab_settings_general_idx,
            },
        }
        self._sub_button_map = sub_button_map
        
        # Content Container (for padding)
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.addWidget(self.stacked_widget)
        
        # Add to main
        main_layout.addWidget(self.sidebar_container)
        main_layout.addWidget(content_container, stretch=1)
        
        # Initialize
        active_ana = APP_SETTINGS.get("active_analysis", "clonality")
        group_map = {
            "clonality": self.group_clonality,
            "flt3": self.group_flt3,
            "general": self.group_general,
        }
        start_group = group_map.get(active_ana, self.group_clonality)
        self.tab_run.set_analysis(active_ana)
        self.tab_ladder.set_analysis(active_ana)
        self.on_group_clicked(start_group)
        start_group.btn_run.setChecked(True)
        self.stacked_widget.setCurrentIndex(self.tab_run_idx)

        # --- Keyboard shortcuts ---
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Alt+1..N activates each analysis group's Run tab.
        Ctrl+, opens Settings for the current analysis.
        Alt+letter jumps to a semantic sub-tab in the current group."""
        for i in range(min(len(self.groups), 9)):
            sc = QShortcut(QKeySequence(f"Alt+{i + 1}"), self)
            sc.activated.connect(lambda idx=i: self._activate_group(idx))
        sc_settings = QShortcut(QKeySequence("Ctrl+,"), self)
        sc_settings.activated.connect(self._activate_settings)
        shortcut_labels = {
            "R": "Run",
            "L": "Ladder",
            "A": "Archive Runner",
            "G": "Log",
            "B": "Labeling",
            "S": "Settings",
        }
        for letter, label in shortcut_labels.items():
            sc = QShortcut(QKeySequence(f"Alt+{letter}"), self)
            sc.activated.connect(lambda selected_label=label: self._activate_sub_label(selected_label))

    def _activate_group(self, idx: int) -> None:
        """Keyboard-driven group activation — same path as clicking a sidebar header."""
        if 0 <= idx < len(self.groups):
            self.on_group_clicked(self.groups[idx])

    def _activate_sub_label(self, label: str) -> None:
        """Jump to a named sub-tab without relying on per-analysis positions."""
        active = APP_SETTINGS.get("active_analysis", "clonality")
        group_map = {
            "clonality": self.group_clonality,
            "flt3": self.group_flt3,
            "general": self.group_general,
        }
        group = group_map.get(active, self.group_clonality)
        button = group.button_for_label(label)
        if button is None:
            return
        sub_idx = group.sub_button_labels.index(label)
        self.btn_about.setChecked(False)
        for other_group in self.groups:
            for other_button in other_group.sub_buttons:
                other_button.setChecked(other_button is button)
        self.on_sub_tab_clicked(group.internal_id, sub_idx)

    def _activate_settings(self) -> None:
        """Jump to the Settings page for the current analysis."""
        active = APP_SETTINGS.get("active_analysis", "clonality")
        group_map = {
            "clonality": self.group_clonality,
            "flt3": self.group_flt3,
            "general": self.group_general,
        }
        group = group_map.get(active, self.group_clonality)
        # Expand the group so the sidebar reflects the navigation
        self.on_group_clicked(group)
        sub_idx = len(group.sub_buttons) - 1
        if 0 <= sub_idx < len(group.sub_buttons):
            self.btn_about.setChecked(False)
            for other_group in self.groups:
                for button in other_group.sub_buttons:
                    button.setChecked(button is group.sub_buttons[sub_idx])
            self.on_sub_tab_clicked(group.internal_id, sub_idx)

    def _clear_sidebar_selection(self) -> None:
        self.btn_about.setChecked(False)
        for group in self.groups:
            for button in group.sub_buttons:
                button.setChecked(False)

    def on_about_clicked(self) -> None:
        self._clear_sidebar_selection()
        self.btn_about.setChecked(True)
        self.stacked_widget.setCurrentIndex(self.tab_about_idx)

    def _wrap_scroll_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("TabScrollArea")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _activate_analysis(self, analysis_id: str) -> bool:
        """Switch the active analysis and persist the related settings."""
        if APP_SETTINGS.get("active_analysis") == analysis_id:
            return False

        APP_SETTINGS["active_analysis"] = analysis_id
        profile = get_analysis_settings(analysis_id)
        APP_SETTINGS.setdefault("batch", {}).update(profile.get("batch", {}))
        APP_SETTINGS.setdefault("pipeline", {}).update(profile.get("pipeline", {}))
        save_settings(APP_SETTINGS)
        print(f"[UI] Analysis switched to: {analysis_id}")
        return True
        
    def on_group_clicked(self, group):
        self.btn_about.setChecked(False)
        # Update active analysis in core
        new_ana = group.internal_id
        changed = self._activate_analysis(new_ana)
        if changed:
            # Refresh tabs if needed
            self.tab_run.set_analysis(new_ana)
            self.tab_ladder.set_analysis(new_ana)
            self.tab_archive_runner.set_analysis(new_ana)
            self.tab_flt3_validation.set_analysis(new_ana)

        # Update Sidebar expansion
        for g in self.groups:
            expanded = (g == group)
            g.set_expanded(expanded)
            if expanded:
                # Automatically select the first sub-tab (Run) when expanding a new group
                g.btn_run.setChecked(True)
                self.on_sub_tab_clicked(g.internal_id, 0)
            
    def on_sub_tab_clicked(self, analysis_id, tab_idx):
        # Ensure we are on the right analysis
        changed = self._activate_analysis(analysis_id)
        if changed or getattr(self.tab_run, "_current_analysis_id", None) != analysis_id:
            self.tab_run.set_analysis(analysis_id)
        if changed or getattr(self.tab_ladder, "_current_analysis_id", None) != analysis_id:
            self.tab_ladder.set_analysis(analysis_id)
        if changed or getattr(self.tab_archive_runner, "_current_analysis_id", None) != analysis_id:
            self.tab_archive_runner.set_analysis(analysis_id)
        if changed or getattr(self.tab_flt3_validation, "_current_analysis_id", None) != analysis_id:
            self.tab_flt3_validation.set_analysis(analysis_id)

        analysis_sub_map = self._sub_button_map.get(analysis_id, {})
        group_lookup = {
            "clonality": self.group_clonality,
            "flt3": self.group_flt3,
            "general": self.group_general,
        }
        group = group_lookup.get(analysis_id)
        if group is None:
            return
        label = group.sub_button_labels[tab_idx] if 0 <= tab_idx < len(group.sub_button_labels) else None
        if label is None or label not in analysis_sub_map:
            return
        page_idx = analysis_sub_map[label]
        self.btn_about.setChecked(False)
        self.stacked_widget.setCurrentIndex(page_idx)

    def _on_settings_saved(self, analysis_id):
        if APP_SETTINGS.get("active_analysis") == analysis_id:
            self.tab_run.set_analysis(analysis_id)
            self.tab_ladder.set_analysis(analysis_id)
            self.tab_archive_runner.set_analysis(analysis_id)
            self.tab_flt3_validation.set_analysis(analysis_id)
