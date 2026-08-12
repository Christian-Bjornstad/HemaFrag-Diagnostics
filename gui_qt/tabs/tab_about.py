from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION
from gui_qt.about_content import (
    APP_OVERVIEW,
    THIRD_PARTY_NOTICE_PATH,
    THIRD_PARTY_SOFTWARE,
    UPSTREAM_LICENSE_PATH,
    load_text,
)


class TabAbout(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_summary_card())
        layout.addWidget(self._build_legal_card())
        layout.addStretch()

    def _build_hero(self) -> QWidget:
        hero = QWidget()
        hero.setObjectName("AboutHero")
        body = QHBoxLayout(hero)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(16)

        icon_label = QLabel()
        icon_label.setObjectName("AboutAppIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(56, 56)
        app = QApplication.instance()
        icon = app.windowIcon() if app is not None else None
        if icon is not None and not icon.isNull():
            icon_label.setPixmap(icon.pixmap(QSize(56, 56)))
        else:
            icon_label.setText("HF")
        body.addWidget(icon_label)

        text_stack = QVBoxLayout()
        text_stack.setSpacing(3)
        title = QLabel(f"About {APP_NAME}")
        title.setObjectName("AboutTitle")
        text_stack.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("AboutVersion")
        text_stack.addWidget(version)

        subtitle = QLabel(APP_OVERVIEW["subtitle"])
        subtitle.setObjectName("AboutSubtitle")
        subtitle.setWordWrap(True)
        text_stack.addWidget(subtitle)
        body.addLayout(text_stack, stretch=1)
        return hero

    def _build_summary_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("AboutSummaryCard")
        body = QGridLayout(card)
        body.setContentsMargins(18, 16, 18, 16)
        body.setHorizontalSpacing(18)
        body.setVerticalSpacing(9)

        rows = (
            ("Application", APP_OVERVIEW["version_label"]),
            ("Maintenance", APP_OVERVIEW["owner_context"]),
            ("Repository license", APP_OVERVIEW["repo_license_status"]),
        )
        for row, (label_text, value_text) in enumerate(rows):
            label = QLabel(label_text.upper())
            label.setObjectName("AboutSummaryLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            value = QLabel(value_text)
            value.setObjectName("AboutSummaryValue")
            value.setWordWrap(True)
            body.addWidget(label, row, 0)
            body.addWidget(value, row, 1)
        body.setColumnStretch(1, 1)
        return card

    def _build_legal_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("AboutLegalCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 16, 18, 18)
        body.setSpacing(10)

        title = QLabel("LEGAL & THIRD-PARTY INFORMATION")
        title.setObjectName("AboutSectionLabel")
        body.addWidget(title)

        tabs = QTabWidget()
        tabs.setObjectName("AboutLegalTabs")

        third_party = self._new_browser()
        third_party.setMarkdown(self._third_party_markdown())
        tabs.addTab(third_party, "Third-party")

        notice = self._new_browser()
        notice.setMarkdown(
            f"Full notice file: `{THIRD_PARTY_NOTICE_PATH.name}`\n\n"
            f"{load_text(THIRD_PARTY_NOTICE_PATH)}"
        )
        tabs.addTab(notice, "Repository notice")

        license_text = self._new_browser(open_external_links=False)
        license_text.setPlainText(load_text(UPSTREAM_LICENSE_PATH))
        tabs.addTab(license_text, "MIT license")

        body.addWidget(tabs)
        return card

    @staticmethod
    def _new_browser(*, open_external_links: bool = True) -> QTextBrowser:
        browser = QTextBrowser()
        browser.setObjectName("AboutTextBrowser")
        browser.setOpenExternalLinks(open_external_links)
        browser.setReadOnly(True)
        browser.setMinimumHeight(260)
        browser.document().setDefaultStyleSheet("a { color: #2563EB; }")
        return browser

    @staticmethod
    def _third_party_markdown() -> str:
        chunks: list[str] = []
        for item in THIRD_PARTY_SOFTWARE:
            chunks.append(
                "\n".join(
                    [
                        f"**{item['name']}**",
                        f"- Homepage: {item['homepage']}",
                        f"- Authors: {item['authors']}",
                        f"- Copyright: {item['copyright']}",
                        f"- License: {item['license_name']}",
                        f"- Summary: {item['summary']}",
                        f"- Local derived paths: {', '.join(item['derived_paths'])}",
                    ]
                )
            )
        return "\n\n".join(chunks)
