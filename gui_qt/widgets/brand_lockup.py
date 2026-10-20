from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class BrandLockup(QWidget):
    def __init__(
        self,
        icon: QIcon | None = None,
        icon_size: QSize | None = None,
        descriptor: str = "Diagnostics",
        parent=None,
    ):
        super().__init__(parent)
        if icon_size is None:
            icon_size = QSize(30, 30)
        self.setObjectName("SidebarBrandLockup")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(11)

        self.mark = QLabel()
        self.mark.setObjectName("SidebarBrandMark")
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mark.setFixedSize(icon_size)
        if icon is not None and not icon.isNull():
            self.mark.setPixmap(icon.pixmap(icon_size))
        else:
            self.mark.setText("HF")
        layout.addWidget(self.mark)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self.wordmark = QLabel("HEMAFRAG")
        self.wordmark.setObjectName("SidebarBrandText")
        text_layout.addWidget(self.wordmark)

        self.descriptor_label = QLabel(descriptor)
        self.descriptor_label.setObjectName("SidebarBrandDescriptor")
        text_layout.addWidget(self.descriptor_label)
        layout.addLayout(text_layout, stretch=1)
