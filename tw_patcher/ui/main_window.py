from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QGroupBox

from ..config import settings
from .state import AppState
from .panels.game_panel import GamePanel
from .panels.settings_panel import SettingsPanel
from .panels.extract_panel import ExtractPanel
from .panels.repack_panel import RepackPanel
from .widgets import LogViewer


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TW Mod Patcher")
        self.setMinimumSize(1000, 700)

        settings.ensure_dirs()

        self._state = AppState()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._game_panel = GamePanel(self._state)
        self._settings_panel = SettingsPanel(self._state)
        self._extract_panel = ExtractPanel(self._state)
        self._repack_panel = RepackPanel(self._state)

        layout.addWidget(self._game_panel)
        layout.addWidget(self._settings_panel)
        layout.addWidget(self._extract_panel)
        layout.addWidget(self._repack_panel)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.addWidget(LogViewer(self._state))
        layout.addWidget(log_group)

        self._state.modding_root_changed.connect(self._update_panel_access)
        self._state.game_changed.connect(self._on_game_changed)
        self._update_panel_access()

    def _on_game_changed(self, game_key: str) -> None:
        self._update_panel_access()
        self._settings_panel.on_game_changed(game_key)

    def _update_panel_access(self) -> None:
        has_workspace = settings.modding_root is not None
        has_game = settings.selected_game is not None
        enabled = has_workspace and has_game

        self._extract_panel.setEnabled(enabled)
        self._repack_panel.setEnabled(enabled)

        if not has_game:
            tip = "Select a game above to enable"
        elif not has_workspace:
            tip = "Set a modding workspace in Settings to enable"
        else:
            tip = ""

        self._extract_panel.setToolTip(tip)
        self._repack_panel.setToolTip(tip)
