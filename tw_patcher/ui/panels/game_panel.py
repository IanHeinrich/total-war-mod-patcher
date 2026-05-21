from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QDialog

from ...config import settings
from ...models.game import GAMES
from ..state import AppState
from ..panels import BasePanel
from ..dialogs import GameBrowserDialog
from ..workers import ArtworkLoader


HEADER_WIDTH = 460
HEADER_HEIGHT = 215
DISPLAY_WIDTH = 300
DISPLAY_HEIGHT = 140


class GamePanel(BasePanel):
    def __init__(self, state: AppState):
        super().__init__("Game", state)

        layout = QHBoxLayout(self)

        # Left: game artwork
        self._image_label = QLabel()
        self._image_label.setFixedSize(DISPLAY_WIDTH, DISPLAY_HEIGHT)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #444; border-radius: 6px;"
        )
        self._image_label.setText("No game selected")
        layout.addWidget(self._image_label)

        # Right: game name + change button
        right = QVBoxLayout()
        right.setSpacing(8)

        self._name_label = QLabel("No game selected")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self._name_label.setFont(font)
        right.addWidget(self._name_label)

        self._path_label = QLabel("")
        self._path_label.setStyleSheet("color: #888;")
        self._path_label.setWordWrap(True)
        right.addWidget(self._path_label)

        right.addStretch()

        change_btn = QPushButton("Change Game...")
        change_btn.setFixedWidth(140)
        change_btn.clicked.connect(self._open_browser)
        right.addWidget(change_btn)

        layout.addLayout(right, stretch=1)

        # Load artwork for current selection
        self._artwork_loader = ArtworkLoader(settings.game_art_dir)
        if settings.selected_game:
            self._show_game(settings.selected_game)

    def _open_browser(self) -> None:
        dialog = GameBrowserDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_game_key:
            game_key = dialog.selected_game_key
            settings.select_game(game_key)
            settings.save_user_config()
            self._show_game(game_key)
            self._state.game_changed.emit(game_key)
            self._state.log(f"Game selected: {GAMES[game_key].display_name}", "success")

    def _show_game(self, game_key: str) -> None:
        game_def = GAMES[game_key]
        self._name_label.setText(game_def.display_name)

        game_dir = settings.game_dirs.get(game_key)
        if game_dir:
            self._path_label.setText(str(game_dir))
        else:
            self._path_label.setText("(install not detected)")

        # Load artwork
        if game_def.header_image_url:
            self._artwork_loader.load(game_def, self._on_artwork_ready)
        else:
            self._image_label.setText(game_def.display_name)

    def _on_artwork_ready(self, game_key: str, pixmap: QPixmap) -> None:
        if game_key == settings.selected_game:
            from PyQt6.QtCore import QSize
            scaled = pixmap.scaled(
                QSize(DISPLAY_WIDTH, DISPLAY_HEIGHT),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image_label.setPixmap(scaled)
            self._image_label.setStyleSheet(
                "border: 1px solid #444; border-radius: 6px;"
            )
