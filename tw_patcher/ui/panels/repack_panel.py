import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QFileDialog, QMessageBox, QProgressBar, QInputDialog,
)

from ...config import settings
from ..state import AppState
from ..panels import BasePanel
from ..workers import RepackWorker


class RepackPanel(BasePanel):
    def __init__(self, state: AppState):
        super().__init__("Repack Patch Mod", state)
        self._worker: RepackWorker | None = None

        layout = QVBoxLayout(self)

        patch_row = QHBoxLayout()
        patch_row.addWidget(QLabel("Patch Mod:"))
        self.patch_combo = QComboBox()
        self.patch_combo.setMinimumWidth(200)
        patch_row.addWidget(self.patch_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Rescan workspace/ for patch mod folders")
        refresh_btn.clicked.connect(self.refresh_patch_mods)
        patch_row.addWidget(refresh_btn)

        new_btn = QPushButton("New Patch Mod...")
        new_btn.setToolTip("Create a new empty patch mod folder in workspace/")
        new_btn.clicked.connect(self._new_patch_mod)
        patch_row.addWidget(new_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Permanently delete the selected patch mod folder")
        delete_btn.clicked.connect(self._delete_patch_mod)
        patch_row.addWidget(delete_btn)

        patch_row.addStretch()
        layout.addLayout(patch_row)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output Directory:"))
        default_output = str(settings.game_data_dir or settings.output_dir)
        self.output_dir_edit = QLineEdit(default_output)
        output_row.addWidget(self.output_dir_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output_dir)
        output_row.addWidget(browse_btn)
        layout.addLayout(output_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Pack Filename:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("(defaults to patch mod name)")
        name_row.addWidget(self.name_edit)
        name_row.addWidget(QLabel(".pack"))
        layout.addLayout(name_row)

        self.repack_btn = QPushButton("Repack")
        self.repack_btn.setToolTip("Build the selected patch mod's TSV tables into a .pack file for the game")
        self.repack_btn.clicked.connect(self._run_repack)
        layout.addWidget(self.repack_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)

        state.patch_mods_changed.connect(self.refresh_patch_mods)
        self.refresh_patch_mods()

    def set_busy(self, busy: bool) -> None:
        self.repack_btn.setEnabled(not busy)
        self.progress.setVisible(busy)

    def refresh_patch_mods(self) -> None:
        self.patch_combo.clear()
        for mod in settings.list_patch_mods():
            path = settings.get_patch_mod_path(mod)
            tsv_count = len(list(path.glob("**/*.tsv")))
            self.patch_combo.addItem(f"{mod} ({tsv_count} tables)", mod)

    def update_output_dir(self, path: str) -> None:
        self.output_dir_edit.setText(path)

    def _new_patch_mod(self) -> None:
        name, ok = QInputDialog.getText(self, "New Patch Mod", "Patch mod name:")
        if ok and name.strip():
            name = name.strip().replace(' ', '_')
            patch_path = settings.get_patch_mod_path(name)
            if patch_path.exists():
                QMessageBox.warning(self, "Exists", f"Patch mod '{name}' already exists.")
                return
            (patch_path / "db").mkdir(parents=True)
            self._state.log(f"Created patch mod: workspace/{name}/", "success")
            self.refresh_patch_mods()
            idx = self.patch_combo.findData(name)
            if idx >= 0:
                self.patch_combo.setCurrentIndex(idx)

    def _delete_patch_mod(self) -> None:
        if self.patch_combo.count() == 0:
            return

        patch_name = self.patch_combo.currentData()
        if not patch_name:
            return

        reply = QMessageBox.question(
            self, "Delete Patch Mod",
            f"Permanently delete '{patch_name}' and all its contents?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        patch_path = settings.get_patch_mod_path(patch_name)
        try:
            shutil.rmtree(patch_path)
            self._state.log(f"Deleted patch mod: workspace/{patch_name}/", "warning")
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Failed to delete: {e}")
            return

        self.refresh_patch_mods()

    def _browse_output_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", str(settings.output_dir)
        )
        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def _run_repack(self) -> None:
        if self.patch_combo.count() == 0:
            QMessageBox.warning(self, "No Patch Mod", "No patch mods available. Create one first.")
            return

        patch_name = self.patch_combo.currentData()
        custom_name = self.name_edit.text().strip() or None
        output_dir = Path(self.output_dir_edit.text().strip())

        pack_filename = f"{custom_name or patch_name}.pack"
        output_path = str(output_dir / pack_filename)

        self._state.set_busy(True)
        self._state.log(f"Repacking '{patch_name}' -> {output_path}", "progress")

        self._worker = RepackWorker(patch_name, output=output_path, name=custom_name)
        self._worker.progress.connect(lambda msg: self._state.log(msg, "progress"))
        self._worker.finished.connect(self._on_repack_done)
        self._worker.start()

    def _on_repack_done(self, success: bool, message: str) -> None:
        self._state.set_busy(False)
        self._state.log(message, "success" if success else "error")
        if success:
            QMessageBox.information(self, "Done", message)
            self.refresh_patch_mods()
        else:
            QMessageBox.critical(self, "Error", message)
