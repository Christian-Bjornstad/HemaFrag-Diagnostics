import os

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget, QTextBrowser, QWidget

from app_meta import APP_NAME, APP_VERSION
from gui_qt.tabs.tab_about import TabAbout


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_about_uses_compact_hero_and_three_legal_tabs(qapp):
    tab = TabAbout()

    assert tab.findChild(QWidget, "AboutHero") is not None
    legal = tab.findChild(QTabWidget, "AboutLegalTabs")
    assert legal is not None
    assert [legal.tabText(index) for index in range(legal.count())] == [
        "Third-party",
        "Repository notice",
        "MIT license",
    ]
    browsers = tab.findChildren(QTextBrowser, "AboutTextBrowser")
    assert len(browsers) == 3


def test_about_keeps_identity_and_full_legal_sources(qapp):
    tab = TabAbout()

    visible_text = " ".join(label.text() for label in tab.findChildren(QLabel))
    assert APP_NAME in visible_text
    assert APP_VERSION in visible_text
    documents = "\n".join(
        browser.toPlainText()
        for browser in tab.findChildren(QTextBrowser, "AboutTextBrowser")
    )
    assert "fraggler" in documents.lower()
    assert "MIT License" in documents
