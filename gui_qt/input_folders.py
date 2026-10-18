"""Directory-only browser with explicit multiple-folder selection."""
from pathlib import Path

from PyQt6.QtCore import QDir, QEvent, Qt
from PyQt6.QtGui import QColor, QFileSystemModel, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
)

from gui_qt.styles import INPUT_FOLDERS_QSS, PALETTE


class InputFoldersDialog(QDialog):
    def __init__(self, parent=None, start_directory: str = ""):
        super().__init__(parent)
        self.setObjectName("InputFoldersDialog")
        self.setWindowTitle("Add Input Folders")
        # This custom picker must remain light even with a dark Windows palette.
        palette = self.palette()
        for role, color in (
            (QPalette.ColorRole.Window, PALETTE["background"]),
            (QPalette.ColorRole.Base, PALETTE["card_bg"]),
            (QPalette.ColorRole.AlternateBase, PALETTE["empty_state"]),
            (QPalette.ColorRole.WindowText, PALETTE["neutral_text"]),
            (QPalette.ColorRole.Text, PALETTE["neutral_text"]),
            (QPalette.ColorRole.Button, PALETTE["card_bg"]),
            (QPalette.ColorRole.ButtonText, PALETTE["neutral_text"]),
            (QPalette.ColorRole.Highlight, PALETTE["primary"]),
            (QPalette.ColorRole.HighlightedText, PALETTE["card_bg"]),
        ):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.setStyleSheet(INPUT_FOLDERS_QSS)
        self.resize(780, 500)
        self.setMinimumSize(540, 320)
        layout = QVBoxLayout(self)
        instructions = QLabel("Select folders with Ctrl or Shift. Double-click a folder to open it.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        navigation = QHBoxLayout()
        self.up_button = QPushButton("Up")
        self.up_button.setAutoDefault(False)
        self.up_button.clicked.connect(lambda: self.navigate(self.current_directory.parent))
        navigation.addWidget(self.up_button)
        self.location = QLineEdit()
        self.location.setAccessibleName("Folder browser location")
        self.location.installEventFilter(self)
        navigation.addWidget(self.location, stretch=1)
        browse = QPushButton("Browse...")
        browse.setAutoDefault(False)
        browse.setToolTip("Open the system picker to navigate to a parent folder or pinned location.")
        browse.clicked.connect(self.browse_parent)
        navigation.addWidget(browse)
        layout.addLayout(navigation)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot)
        self.model.setReadOnly(True)
        self.tree = QTreeView()
        self.tree.setObjectName("InputFoldersTree")
        self.tree.setAccessibleName("Input folders")
        self.tree.setModel(self.model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setAlternatingRowColors(True)
        self.tree.setHeaderHidden(False)
        for column in (1, 2):
            self.tree.hideColumn(column)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.tree.doubleClicked.connect(lambda index: self.navigate(Path(self.model.filePath(index))))
        self.tree.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.tree, stretch=1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = buttons.addButton("Add Selected Folders", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._accepted_directories: list[str] = []
        start = Path(start_directory or Path.home()).expanduser()
        self.navigate(start if start.is_dir() else Path.home())

    def navigate(self, directory: Path) -> None:
        directory = Path(directory).expanduser()
        if not directory.is_dir():
            self.tree.clearSelection()
            self.add_button.setEnabled(False)
            self.status.setText("Folder is unavailable. Choose another location with Browse.")
            return
        self.current_directory = directory.absolute()
        self.location.setText(str(self.current_directory))
        self.tree.setRootIndex(self.model.setRootPath(str(self.current_directory)))
        self.tree.clearSelection()
        self.up_button.setEnabled(self.current_directory != self.current_directory.parent)
        self._selection_changed()

    def eventFilter(self, watched, event):
        if watched is self.location and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Qt otherwise forwards Enter to the default Add button after
            # editing the location, which can accept an old selection.
            self.navigate(Path(self.location.text()))
            return True
        return super().eventFilter(watched, event)

    def browse_parent(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Parent Folder", str(self.current_directory), QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self.navigate(Path(folder))

    def selected_directories(self) -> list[str]:
        return list(dict.fromkeys(
            self.model.filePath(index)
            for index in self.tree.selectionModel().selectedRows(0)
            if self.model.isDir(index) and Path(self.model.filePath(index)).is_dir()
        ))

    def _selection_changed(self, *_args) -> None:
        count = len(self.selected_directories())
        self.status.setText(f"{count} folder(s) selected. Only selected folders will be added.")
        self.add_button.setEnabled(count > 0)

    def accept(self) -> None:
        self._accepted_directories = self.selected_directories()
        if self._accepted_directories:
            super().accept()


def choose_input_directories(parent, start_directory: str) -> list[str]:
    dialog = InputFoldersDialog(parent, start_directory)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog._accepted_directories
    return []
