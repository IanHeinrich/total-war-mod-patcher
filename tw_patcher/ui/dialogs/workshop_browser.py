import webbrowser

from PyQt6.QtCore import Qt, QSize, QPoint
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QDialogButtonBox,
    QProgressBar, QMenu,
)

from ...clients.steam import SteamWorkshopClient
from ...config import settings
from ..styles import INFO_LABEL
from ..widgets import WorkshopModWidget, ThumbnailLoader
from ..workers import WorkshopMetadataWorker


class WorkshopBrowserDialog(QDialog):
    def __init__(self, parent=None, already_selected: set[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Browse Workshop Mods")
        self.setMinimumSize(650, 550)
        self._metadata_worker: WorkshopMetadataWorker | None = None
        self._thumb_loader: ThumbnailLoader | None = None
        self._workshop_widgets: dict[str, list[WorkshopModWidget]] = {}
        self._already_selected = already_selected or set()

        layout = QVBoxLayout(self)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet(INFO_LABEL)
        layout.addWidget(self.info_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(4)
        layout.addWidget(self.progress_bar)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search mods...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_list)
        search_row.addWidget(self.search_edit)

        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self._clear_selection)
        search_row.addWidget(clear_btn)
        layout.addLayout(search_row)

        self.workshop_list = QListWidget()
        self.workshop_list.setIconSize(QSize(64, 64))
        self.workshop_list.itemClicked.connect(self._on_item_clicked)
        self.workshop_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.workshop_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.workshop_list)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._populate()

    def _populate(self) -> None:
        self.workshop_list.clear()
        self._workshop_widgets.clear()

        if not settings.game_workshop_dir:
            self.info_label.setText("Set game install directory to browse workshop mods.")
            return

        mods = settings.list_workshop_mods()
        if not mods:
            self.info_label.setText("No workshop mods found.")
            return

        self.info_label.setText(f"{len(mods)} workshop mod(s) found. Fetching details...")

        steam_client = SteamWorkshopClient(settings.workshop_cache_file)
        all_ids = [m.workshop_id for m in mods]
        cached = steam_client.get_cached(all_ids)

        self._thumb_loader = ThumbnailLoader(settings.workshop_thumbs_dir)

        for mod in mods:
            cached_entry = cached.get(mod.workshop_id)
            mod_name = cached_entry["name"] if cached_entry and cached_entry["name"] else None

            for pack_path in mod.pack_paths:
                item = QListWidgetItem(self.workshop_list)
                path_str = str(pack_path)
                item.setData(Qt.ItemDataRole.UserRole, path_str)

                widget = WorkshopModWidget(mod.workshop_id, pack_path.name, mod_name)
                if path_str in self._already_selected:
                    widget.checkbox.setChecked(True)
                item.setSizeHint(widget.sizeHint())
                self.workshop_list.setItemWidget(item, widget)

                if mod.workshop_id not in self._workshop_widgets:
                    self._workshop_widgets[mod.workshop_id] = []
                self._workshop_widgets[mod.workshop_id].append(widget)

                if cached_entry and cached_entry["thumbnail_url"]:
                    self._thumb_loader.load(mod.workshop_id, cached_entry["thumbnail_url"], widget)

        self._metadata_worker = WorkshopMetadataWorker(all_ids, settings.workshop_cache_file)
        self._metadata_worker.finished.connect(self._on_metadata_loaded)
        self._metadata_worker.start()

    def _on_metadata_loaded(self, details: dict) -> None:
        self.progress_bar.hide()
        self.info_label.setText(
            f"{self.workshop_list.count()} workshop pack(s) available. Check items to select."
        )
        if not self._thumb_loader:
            self._thumb_loader = ThumbnailLoader(settings.workshop_thumbs_dir)

        for wid, entry in details.items():
            widgets = self._workshop_widgets.get(wid, [])
            for w in widgets:
                if entry.get("name"):
                    w.set_mod_name(entry["name"])
                if entry.get("thumbnail_url"):
                    self._thumb_loader.load(wid, entry["thumbnail_url"], w)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        widget = self.workshop_list.itemWidget(item)
        if isinstance(widget, WorkshopModWidget):
            widget.checkbox.setChecked(not widget.checkbox.isChecked())

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.workshop_list.itemAt(pos)
        if not item:
            return
        widget = self.workshop_list.itemWidget(item)
        if not isinstance(widget, WorkshopModWidget):
            return

        wid = widget.workshop_id
        menu = QMenu(self)
        open_web = menu.addAction("Open in Browser")
        open_steam = menu.addAction("Open in Steam")

        action = menu.exec(self.workshop_list.mapToGlobal(pos))
        if action == open_web:
            webbrowser.open(f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}")
        elif action == open_steam:
            webbrowser.open(f"steam://url/CommunityFilePage/{wid}")

    def _filter_list(self, text: str) -> None:
        query = text.lower()
        for i in range(self.workshop_list.count()):
            item = self.workshop_list.item(i)
            if not item:
                continue
            widget = self.workshop_list.itemWidget(item)
            if isinstance(widget, WorkshopModWidget):
                name = widget.name_label.text().lower()
                pack = widget.pack_name.lower()
                visible = query in name or query in pack or query in widget.workshop_id
                item.setHidden(not visible)
            else:
                item.setHidden(False)

    def _clear_selection(self) -> None:
        for i in range(self.workshop_list.count()):
            item = self.workshop_list.item(i)
            if not item:
                continue
            widget = self.workshop_list.itemWidget(item)
            if isinstance(widget, WorkshopModWidget):
                widget.checkbox.setChecked(False)

    def selected_pack_paths(self) -> list[str]:
        paths: list[str] = []
        for i in range(self.workshop_list.count()):
            item = self.workshop_list.item(i)
            if not item:
                continue
            widget = self.workshop_list.itemWidget(item)
            if isinstance(widget, WorkshopModWidget) and widget.checkbox.isChecked():
                pack_path = item.data(Qt.ItemDataRole.UserRole)
                if pack_path:
                    paths.append(pack_path)
        return paths
