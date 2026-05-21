from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox

from ..styles import THUMB_PLACEHOLDER, MUTED_TEXT, DIM_TEXT

THUMB_SIZE = 64


class WorkshopModWidget(QWidget):
    def __init__(self, workshop_id: str, pack_name: str, mod_name: str | None = None):
        super().__init__()
        self.workshop_id = workshop_id
        self.pack_name = pack_name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.checkbox = QCheckBox()
        layout.addWidget(self.checkbox)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(THUMB_PLACEHOLDER)
        self.thumb_label.setText("?")
        layout.addWidget(self.thumb_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.name_label = QLabel(mod_name or "Loading...")
        bold_font = QFont()
        bold_font.setBold(True)
        self.name_label.setFont(bold_font)
        self.name_label.setWordWrap(True)
        text_layout.addWidget(self.name_label)

        self.pack_label = QLabel(pack_name)
        small_font = QFont()
        small_font.setPointSize(small_font.pointSize() - 1)
        self.pack_label.setFont(small_font)
        self.pack_label.setStyleSheet(MUTED_TEXT)
        text_layout.addWidget(self.pack_label)

        self.id_label = QLabel(f"ID: {workshop_id}")
        self.id_label.setFont(small_font)
        self.id_label.setStyleSheet(DIM_TEXT)
        text_layout.addWidget(self.id_label)

        text_layout.addStretch()
        layout.addLayout(text_layout, stretch=1)

    def set_mod_name(self, name: str) -> None:
        self.name_label.setText(name)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            QSize(THUMB_SIZE, THUMB_SIZE),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)
        self.thumb_label.setStyleSheet("")
