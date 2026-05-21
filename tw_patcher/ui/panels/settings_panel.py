from pathlib import Path
import subprocess
import shutil

from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QMessageBox, QMenu,
)

from ...config import settings
from ...models.game import GAMES
from ...services.scaffold import ScaffoldService
from ...services.system import SystemService
from ..state import AppState
from ..panels import BasePanel


class SettingsPanel(BasePanel):
    def __init__(self, state: AppState):
        super().__init__("Settings", state)
        layout = QVBoxLayout(self)

        # --- Modding workspace row ---
        ws_row = QHBoxLayout()
        ws_row.addWidget(QLabel("Modding Workspace:"))
        self.ws_edit = QLineEdit(str(settings.modding_root or ""))
        self.ws_edit.setPlaceholderText("Select a folder for sources, workspace, and output...")
        self.ws_edit.setReadOnly(True)
        ws_row.addWidget(self.ws_edit)

        ws_browse_btn = QPushButton("Browse...")
        ws_browse_btn.clicked.connect(self._browse_modding_root)
        ws_row.addWidget(ws_browse_btn)

        self._open_btn = QPushButton("Open In...")
        self._open_btn.setEnabled(settings.modding_root is not None)
        self._build_open_menu()
        ws_row.addWidget(self._open_btn)
        layout.addLayout(ws_row)

        # --- Game install row ---
        install_row = QHBoxLayout()
        self._install_label = QLabel(self._install_label_text())
        install_row.addWidget(self._install_label)
        self._install_edit = QLineEdit(str(settings.game_dir or ""))
        self._install_edit.setPlaceholderText(self._install_placeholder())
        self._install_edit.setReadOnly(True)
        install_row.addWidget(self._install_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_game_dir)
        install_row.addWidget(browse_btn)
        layout.addLayout(install_row)

        # --- RPFM path row ---
        rpfm_row = QHBoxLayout()
        rpfm_row.addWidget(QLabel("RPFM Path:"))
        self._rpfm_edit = QLineEdit()
        self._rpfm_edit.setReadOnly(True)
        self._update_rpfm_display()
        rpfm_row.addWidget(self._rpfm_edit)

        rpfm_browse_btn = QPushButton("Browse...")
        rpfm_browse_btn.clicked.connect(self._browse_rpfm)
        rpfm_row.addWidget(rpfm_browse_btn)

        rpfm_clear_btn = QPushButton("Clear")
        rpfm_clear_btn.setToolTip("Reset to auto-detect")
        rpfm_clear_btn.clicked.connect(self._clear_rpfm)
        rpfm_row.addWidget(rpfm_clear_btn)
        layout.addLayout(rpfm_row)

    def on_game_changed(self, game_key: str) -> None:
        self._install_label.setText(self._install_label_text())
        self._install_edit.setText(str(settings.game_dir or ""))
        self._install_edit.setPlaceholderText(self._install_placeholder())

    def _install_label_text(self) -> str:
        if settings.selected_game:
            game_def = GAMES[settings.selected_game]
            return f"{game_def.display_name} Install:"
        return "Game Install:"

    def _install_placeholder(self) -> str:
        if settings.selected_game:
            game_def = GAMES[settings.selected_game]
            return f"Select {game_def.display_name} install folder..."
        return "Select a game first..."

    def _build_open_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("File Explorer", lambda: self._open_workspace("explorer"))
        menu.addAction("VS Code", lambda: self._open_workspace("code"))
        menu.addAction("Cursor", lambda: self._open_workspace("cursor"))
        menu.addAction("Claude Code", lambda: self._open_workspace("claude"))
        self._open_btn.setMenu(menu)

    def _open_workspace(self, editor: str) -> None:
        path = settings.modding_root
        if not path:
            return
        try:
            if editor == "explorer":
                subprocess.Popen(["explorer", str(path)])
            else:
                cmd = shutil.which(editor)
                if cmd:
                    subprocess.Popen([cmd, str(path)])
                else:
                    QMessageBox.warning(
                        self, "Not Found",
                        f"'{editor}' not found on PATH."
                    )
        except OSError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _browse_modding_root(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Modding Workspace Folder",
            str(settings.modding_root or "")
        )
        if not dir_path:
            return

        path = Path(dir_path)
        settings.modding_root = path
        settings.save_user_config()
        self.ws_edit.setText(str(path))

        settings.ensure_dirs()

        scaffold = ScaffoldService(path)
        would_create = [
            rel for rel in [
                "modding_docs/README.md",
                ".github/copilot-instructions.md",
                "CLAUDE.md",
                ".cursorrules",
            ] if not (path / rel).exists()
        ]

        if would_create:
            generate_helpers = QMessageBox.question(
                self, "Generate Helper Files?",
                "Would you like to generate modding docs and AI coding assistant "
                "instructions in the workspace?\n\n"
                "This creates modding_docs/, .github/copilot-instructions.md, "
                "CLAUDE.md, and .cursorrules.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            ) == QMessageBox.StandardButton.Yes

            if generate_helpers:
                created = scaffold.scaffold()
                if created:
                    self._state.log(f"Generated {len(created)} helper file(s) in workspace", "success")

        self._open_btn.setEnabled(True)
        self._state.log(f"Modding workspace set: {path}", "success")
        self._state.modding_root_changed.emit()
        self._state.patch_mods_changed.emit()

    def _browse_game_dir(self) -> None:
        if not settings.selected_game:
            QMessageBox.warning(self, "No Game", "Select a game first.")
            return

        game_def = GAMES[settings.selected_game]
        dir_path = QFileDialog.getExistingDirectory(
            self, f"Select {game_def.display_name} Install Folder",
            str(settings.game_dir or "")
        )
        if not dir_path:
            return

        path = Path(dir_path)
        if not (path / "data").is_dir():
            QMessageBox.warning(
                self, "Invalid Folder",
                f"Selected folder doesn't appear to be a {game_def.display_name} install "
                "(no 'data' subfolder found)."
            )
            return

        settings.game_dir = path
        settings.save_user_config()
        self._install_edit.setText(str(path))
        self._state.log(f"{game_def.display_name} install set: {path}", "success")
        if settings.game_workshop_dir:
            self._state.log(f"Workshop folder detected: {settings.game_workshop_dir}")

    def _browse_rpfm(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select RPFM Installation Folder",
            str(settings.rpfm_path or "")
        )
        if not dir_path:
            return

        path = Path(dir_path)
        # Validate: look for rpfm_server.exe or rpfm executable
        has_server = (path / "rpfm_server.exe").exists() or (path / "rpfm_server").exists()
        has_ui = (path / "rpfm_ui.exe").exists() or (path / "rpfm_ui").exists()
        if not has_server and not has_ui:
            QMessageBox.warning(
                self, "Invalid Folder",
                "Selected folder doesn't appear to contain RPFM "
                "(no rpfm_server or rpfm_ui found)."
            )
            return

        settings.rpfm_path = path
        settings.save_user_config()
        self._update_rpfm_display()
        self._state.log(f"RPFM path set: {path}", "success")

    def _clear_rpfm(self) -> None:
        settings.rpfm_path = None
        settings.save_user_config()
        self._update_rpfm_display()
        self._state.log("RPFM path cleared (using auto-detect)", "success")

    def _update_rpfm_display(self) -> None:
        if settings.rpfm_path:
            self._rpfm_edit.setText(str(settings.rpfm_path))
            self._rpfm_edit.setPlaceholderText("")
            self._rpfm_edit.setStyleSheet("")
        else:
            svc = SystemService(settings)
            detected = svc.find_rpfm_executable()
            if detected:
                self._rpfm_edit.setText(str(detected.parent))
                self._rpfm_edit.setPlaceholderText("")
                self._rpfm_edit.setStyleSheet("color: gray;")
            else:
                self._rpfm_edit.setText("")
                self._rpfm_edit.setPlaceholderText("Not found — browse to set manually")
                self._rpfm_edit.setStyleSheet("")
