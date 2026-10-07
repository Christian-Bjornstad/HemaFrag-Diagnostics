from pathlib import Path
from unittest.mock import Mock

import pytest

from config import APP_SETTINGS
from gui_qt.tabs.tab_batch import TabBatch


@pytest.mark.parametrize("analysis", ["clonality", "flt3", "general"])
def test_configured_browser_parent_is_never_selected_as_input(qapp, tmp_path, analysis):
    APP_SETTINGS["active_analysis"] = analysis
    APP_SETTINGS["analyses"][analysis]["batch"]["base_input_dir"] = str(tmp_path)
    widget = TabBatch()
    try:
        assert widget.folder_list.count() == 0
        source = tmp_path / "selected"
        source.mkdir()
        widget._add_source_item(str(source))
        widget.load_from_settings()
        assert [widget.folder_list.item(i).text() for i in range(widget.folder_list.count())] == [str(source)]
    finally:
        widget.close()


def test_add_folders_adds_all_selected_siblings_once(qapp, tmp_path, monkeypatch):
    sources = [tmp_path / name for name in ("first", "second", "third")]
    for path in sources:
        path.mkdir()
    profile = APP_SETTINGS["analyses"]["clonality"]["batch"]
    profile["base_input_dir"] = str(tmp_path)
    profile["last_input_directory"] = str(tmp_path / "old_selection")
    profile["run_date_filter"] = "latest"
    widget = TabBatch()
    picker = Mock(return_value=[str(path) for path in sources])
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.choose_input_directories", picker, raising=False)
    saved = Mock(return_value=True)
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.save_settings", saved)
    try:
        widget._add_folders()
        widget._add_folders()
        assert [widget.folder_list.item(i).text() for i in range(widget.folder_list.count())] == [str(p) for p in sources]
        assert picker.call_args.args[1] == str(tmp_path)
        assert profile["base_input_dir"] == str(tmp_path)
        assert profile["last_input_directory"] == str(tmp_path)
        assert profile["run_date_filter"] == "all"
        assert widget.input_scope_combo.currentData() == "all"
    finally:
        widget.close()


def test_cancel_folder_selection_changes_nothing(qapp, monkeypatch):
    widget = TabBatch()
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.choose_input_directories", lambda *args: [], raising=False)
    saved = Mock()
    monkeypatch.setattr("gui_qt.tabs.tab_batch._legacy.save_settings", saved)
    try:
        widget._add_folders()
        assert widget.folder_list.count() == 0
        saved.assert_not_called()
    finally:
        widget.close()


def test_folder_dialog_selects_multiple_folders_with_shift(qapp, tmp_path):
    from PyQt6.QtCore import QElapsedTimer, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QDialog

    from gui_qt.input_folders import InputFoldersDialog

    sources = [tmp_path / name for name in ("first", "second", "third")]
    for path in sources:
        path.mkdir()
    (tmp_path / "ignore.fsa").write_bytes(b"fsa")
    dialog = InputFoldersDialog(start_directory=str(tmp_path))
    dialog.show()
    try:
        timer = QElapsedTimer()
        timer.start()
        while dialog.model.rowCount(dialog.tree.rootIndex()) != 3 and timer.elapsed() < 3000:
            QTest.qWait(10)
        assert dialog.model.rowCount(dialog.tree.rootIndex()) == 3
        assert not dialog.add_button.isEnabled()
        indexes = [dialog.model.index(str(path)) for path in sources]
        qapp.processEvents()
        QTest.mouseClick(dialog.tree.viewport(), Qt.MouseButton.LeftButton,
                        pos=dialog.tree.visualRect(indexes[0]).center())
        QTest.mouseClick(dialog.tree.viewport(), Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.ShiftModifier,
                        pos=dialog.tree.visualRect(indexes[2]).center())
        assert set(map(Path, dialog.selected_directories())) == set(sources)
        assert dialog.add_button.isEnabled()
        QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert set(map(Path, dialog._accepted_directories)) == set(sources)
    finally:
        dialog.close()


def test_navigating_folder_dialog_does_not_add_parent_or_old_selection(qapp, tmp_path):
    from PyQt6.QtCore import QItemSelectionModel

    from gui_qt.input_folders import InputFoldersDialog

    child = tmp_path / "child"
    child.mkdir()
    dialog = InputFoldersDialog(start_directory=str(tmp_path))
    try:
        index = dialog.model.index(str(child))
        dialog.tree.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        assert dialog.selected_directories()
        dialog.navigate(child)
        assert dialog.selected_directories() == []
        assert not dialog.add_button.isEnabled()
        assert dialog.current_directory == child
    finally:
        dialog.close()


@pytest.mark.parametrize("valid", [False, True])
def test_enter_in_folder_location_only_navigates(qapp, tmp_path, valid):
    from PyQt6.QtCore import QItemSelectionModel, Qt
    from PyQt6.QtTest import QTest

    from gui_qt.input_folders import InputFoldersDialog

    child = tmp_path / "child"
    child.mkdir()
    dialog = InputFoldersDialog(start_directory=str(tmp_path))
    dialog.show()
    try:
        index = dialog.model.index(str(child))
        dialog.tree.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        target = child if valid else tmp_path / "unavailable"
        dialog.location.setText(str(target))
        dialog.location.setFocus()
        QTest.keyClick(dialog.location, Qt.Key.Key_Return)
        assert dialog.isVisible()
        assert dialog.current_directory == (child if valid else tmp_path)
        assert not dialog.selected_directories()
        assert not dialog.add_button.isEnabled()
    finally:
        dialog.close()
