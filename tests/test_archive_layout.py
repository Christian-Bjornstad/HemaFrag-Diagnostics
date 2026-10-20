"""Archive actions must fit inside a laptop-sized scroll viewport."""
import os
from pathlib import Path

import pytest
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication, QScrollArea

from gui_qt.tabs.tab_archive_runner import TabArchiveRunner
from gui_qt.styles import VIBRANT_PRO_QSS


@pytest.mark.parametrize("width", [980, 1072, 1636])
def test_archive_actions_fit_laptop_viewport(width):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    page = TabArchiveRunner()
    page.setStyleSheet(VIBRANT_PRO_QSS)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    scroll.resize(width, 650)
    scroll.show()
    app.processEvents()
    try:
        assert page.width() <= scroll.viewport().width()
        for button in (page.btn_run, page.btn_combine, page.btn_review_ladders,
                       page.btn_refresh_workbook, page.btn_open_run, page.btn_open_workbook):
            assert button.isVisible()
            right = button.mapTo(page, button.rect().topRight()).x()
            assert right < scroll.viewport().width()
    finally:
        scroll.close()
