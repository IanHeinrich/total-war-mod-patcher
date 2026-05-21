from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QFont, QMouseEvent
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel


CARD_WIDTH = 230
CARD_IMAGE_HEIGHT = 107
BORDER_RADIUS = 6

STYLE_DEFAULT = f"""
    QFrame#GameCard {{
        border: 2px solid #444;
        border-radius: {BORDER_RADIUS}px;
        background-color: #2a2a2a;
    }}
    QFrame#GameCard:hover {{
        border-color: #666;
    }}
"""

STYLE_SELECTED = f"""
    QFrame#GameCard {{
        border: 2px solid #4fc3f7;
        border-radius: {BORDER_RADIUS}px;
        background-color: #1e3a4a;
    }}
"""


class GameCard(QFrame):
    clicked = pyqtSignal(str)  # emits game_key

    def __init__(self, game_key: str, display_name: str):
        super().__init__()
        self.setObjectName("GameCard")
        self.game_key = game_key
        self._selected = False

        self.setFixedWidth(CARD_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(STYLE_DEFAULT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(4)

        self._image_label = QLabel()
        self._image_label.setFixedSize(CARD_WIDTH - 4, CARD_IMAGE_HEIGHT)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background-color: #1a1a1a; border-radius: 4px;")
        self._image_label.setText("...")
        layout.addWidget(self._image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._name_label = QLabel(display_name)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setWordWrap(True)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        self._name_label.setFont(font)
        layout.addWidget(self._name_label)

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value
        self.setStyleSheet(STYLE_SELECTED if value else STYLE_DEFAULT)

    def set_image(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            QSize(CARD_WIDTH - 4, CARD_IMAGE_HEIGHT),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.setStyleSheet("")

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.game_key)
        super().mousePressEvent(event)
