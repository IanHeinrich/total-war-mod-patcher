import shutil

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QFileDialog, QMessageBox, QProgressBar, QDialog,
)

from ...config import settings
from ..state import AppState
from ..panels import BasePanel
from ..dialogs import WorkshopBrowserDialog
from ..workers import ExtractWorker


class ExtractPanel(BasePanel):
    def __init__(self, state: AppState):
        super().__init__("Extract Mods", state)
        self._worker: ExtractWorker | None = None

        layout = QVBoxLayout(self)

        source_header = QHBoxLayout()
        source_header.addWidget(QLabel(f"Source .pack files (max {settings.max_mods}):"))
        source_header.addStretch()

        workshop_btn = QPushButton("Browse Workshop...")
        workshop_btn.setToolTip("Browse installed Steam Workshop mods to select .pack files")
        workshop_btn.clicked.connect(self._browse_workshop)
        source_header.addWidget(workshop_btn)

        add_btn = QPushButton("Add .pack File")
        add_btn.setToolTip("Manually select .pack files from disk")
        add_btn.clicked.connect(self._add_source_file)
        source_header.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.setToolTip("Remove highlighted entries from the list")
        remove_btn.clicked.connect(self._remove_source_file)
        source_header.addWidget(remove_btn)

        layout.addLayout(source_header)

        self.source_list = QListWidget()
        self.source_list.setMaximumHeight(140)
        layout.addWidget(self.source_list)

        btn_row = QHBoxLayout()
        self.extract_btn = QPushButton("Extract All")
        self.extract_btn.setToolTip("Extract database tables from selected .pack files into sources/ as TSV")
        self.extract_btn.clicked.connect(self._run_extract)
        btn_row.addWidget(self.extract_btn)

        self.clear_btn = QPushButton("Clear Sources")
        self.clear_btn.setToolTip("Delete all extracted mod folders from sources/")
        self.clear_btn.clicked.connect(self._clear_sources)
        btn_row.addWidget(self.clear_btn)

        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)

    def set_busy(self, busy: bool) -> None:
        self.extract_btn.setEnabled(not busy)
        self.clear_btn.setEnabled(not busy)
        self.progress.setVisible(busy)

    def _clear_sources(self) -> None:
        sources_dir = settings.sources_dir
        entries = [d for d in sources_dir.iterdir() if d.is_dir()]
        if not entries:
            QMessageBox.information(self, "Nothing to Clear", "No extracted mods found in sources/.")
            return

        reply = QMessageBox.question(
            self, "Clear Sources",
            f"Delete {len(entries)} extracted mod folder(s) from sources/?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        removed = 0
        for entry in entries:
            try:
                shutil.rmtree(entry)
                removed += 1
            except OSError as e:
                self._state.log(f"Failed to remove {entry.name}: {e}", "error")

        self.source_list.clear()
        self._state.log(f"Cleared {removed} extracted mod(s) from sources/", "success")

    def _browse_workshop(self) -> None:
        if not settings.game_workshop_dir:
            QMessageBox.warning(
                self, "No Workshop Folder",
                "Set the game install directory first to browse workshop mods."
            )
            return

        existing: set[str] = set()
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            if item:
                existing.add(item.text())

        dialog = WorkshopBrowserDialog(self, already_selected=existing)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = set(dialog.selected_pack_paths())
            for i in range(self.source_list.count() - 1, -1, -1):
                item = self.source_list.item(i)
                if item and item.text() in existing and item.text() not in selected:
                    self.source_list.takeItem(i)
            current: set[str] = set()
            for i in range(self.source_list.count()):
                item = self.source_list.item(i)
                if item:
                    current.add(item.text())
            for path in selected:
                if self.source_list.count() >= settings.max_mods:
                    QMessageBox.warning(
                        self, "Limit Reached",
                        f"Maximum {settings.max_mods} source mods allowed."
                    )
                    break
                if path not in current:
                    self.source_list.addItem(path)
                    current.add(path)

    def _add_source_file(self) -> None:
        if self.source_list.count() >= settings.max_mods:
            QMessageBox.warning(self, "Limit Reached", f"Maximum {settings.max_mods} source mods allowed.")
            return

        start_dir = str(settings.game_workshop_dir or "")
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select .pack File(s)", start_dir,
            "Pack Files (*.pack);;All Files (*)"
        )
        existing: set[str] = set()
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            if item:
                existing.add(item.text())
        for f in files:
            if self.source_list.count() >= settings.max_mods:
                break
            if f not in existing:
                self.source_list.addItem(f)
                existing.add(f)

    def _remove_source_file(self) -> None:
        for item in self.source_list.selectedItems():
            self.source_list.takeItem(self.source_list.row(item))

    def _run_extract(self) -> None:
        if self.source_list.count() == 0:
            QMessageBox.warning(self, "No Sources", "Add at least one .pack file to extract.")
            return

        if self.source_list.count() > settings.max_mods:
            QMessageBox.warning(
                self, "Too Many",
                f"Maximum {settings.max_mods} source mods allowed."
            )
            return

        sources: list[str] = []
        for i in range(self.source_list.count()):
            item = self.source_list.item(i)
            if item:
                sources.append(item.text())

        self._state.set_busy(True)
        self._state.log(f"Extracting {len(sources)} mod(s)...", "progress")

        self._worker = ExtractWorker(sources)
        self._worker.progress.connect(lambda msg: self._state.log(msg, "progress"))
        self._worker.finished.connect(self._on_extract_done)
        self._worker.start()

    def _on_extract_done(self, success: bool, message: str) -> None:
        self._state.set_busy(False)
        self._state.log(message, "success" if success else "error")
        if success:
            QMessageBox.information(self, "Done", message)
        else:
            QMessageBox.critical(self, "Error", message)
