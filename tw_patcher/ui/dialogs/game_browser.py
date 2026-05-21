from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QGridLayout, QFileDialog, QMessageBox,
    QDialogButtonBox,
)

from ...config import settings
from ...models.game import GAMES, GAME_KEYS, GameDef
from ..widgets import GameCard
from ..workers import ArtworkLoader


GRID_COLUMNS = 3


class GameBrowserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Game")
        self.setMinimumSize(800, 500)
        self.selected_game_key: str | None = None

        self._cards: dict[str, GameCard] = {}

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Games detected on this PC:")
        header.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(header)

        # Scroll area with game cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        self._grid = QGridLayout(container)
        self._grid.setSpacing(10)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # Bottom row: manual select + dialog buttons
        bottom = QHBoxLayout()

        manual_btn = QPushButton("Select Game Folder Manually...")
        manual_btn.setToolTip("Choose any game install folder (must have a 'data' subfolder)")
        manual_btn.clicked.connect(self._manual_select)
        bottom.addWidget(manual_btn)

        bottom.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btn_box.rejected.connect(self.reject)
        bottom.addWidget(btn_box)

        layout.addLayout(bottom)

        # Detect installed games and populate
        self._artwork_loader = ArtworkLoader(settings.game_art_dir)
        self._populate()

    def _populate(self) -> None:
        installed = settings.detect_installed_games()

        if not installed:
            label = QLabel("No Total War games detected.\nUse 'Select Game Folder Manually...' below.")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #888; font-size: 11pt; padding: 40px;")
            self._grid.addWidget(label, 0, 0, 1, GRID_COLUMNS)
            return

        i = 0
        for key in GAME_KEYS:
            if key not in installed:
                continue
            game_def = GAMES[key]
            card = GameCard(key, game_def.display_name)
            card.clicked.connect(self._on_card_clicked)
            self._cards[key] = card

            row = i // GRID_COLUMNS
            col = i % GRID_COLUMNS
            self._grid.addWidget(card, row, col)
            i += 1

            # Load artwork
            if game_def.header_image_url:
                self._artwork_loader.load(game_def, self._on_artwork_ready)

        # Highlight currently selected game
        if settings.selected_game and settings.selected_game in self._cards:
            self._cards[settings.selected_game].selected = True

    def _on_card_clicked(self, game_key: str) -> None:
        for card in self._cards.values():
            card.selected = False
        self._cards[game_key].selected = True
        self.selected_game_key = game_key
        self.accept()

    def _on_artwork_ready(self, game_key: str, pixmap: QPixmap) -> None:
        if game_key in self._cards:
            self._cards[game_key].set_image(pixmap)

    def _manual_select(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Total War Game Install Folder", ""
        )
        if not dir_path:
            return

        path = Path(dir_path)
        if not (path / "data").is_dir():
            QMessageBox.warning(
                self, "Invalid Folder",
                "Selected folder doesn't appear to be a Total War install "
                "(no 'data' subfolder found)."
            )
            return

        # Try to identify which game this is by folder name
        matched_key: str | None = None
        for key, game_def in GAMES.items():
            if game_def.folder_name and game_def.folder_name.lower() in path.name.lower():
                matched_key = key
                break

        if not matched_key:
            # Ask user to pick from full list
            from PyQt6.QtWidgets import QInputDialog
            names = [f"{GAMES[k].display_name} ({k})" for k in GAME_KEYS]
            chosen, ok = QInputDialog.getItem(
                self, "Which Game?",
                "Could not auto-detect the game. Please select:",
                names, 0, False
            )
            if not ok:
                return
            idx = names.index(chosen)
            matched_key = GAME_KEYS[idx]

        settings.game_dirs[matched_key] = path
        self.selected_game_key = matched_key
        self.accept()
