from __future__ import annotations

import urllib.request
import urllib.error
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox

from ..constants import THUMBNAIL_TIMEOUT

THUMB_SIZE = 64
PLACEHOLDER_STYLE = "background-color: #3a3a3a; border: 1px solid #555;"


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
        self.thumb_label.setStyleSheet(PLACEHOLDER_STYLE)
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
        self.pack_label.setStyleSheet("color: #888;")
        text_layout.addWidget(self.pack_label)

        self.id_label = QLabel(f"ID: {workshop_id}")
        self.id_label.setFont(small_font)
        self.id_label.setStyleSheet("color: #666;")
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


class _DownloadWorker(QThread):
    downloaded = pyqtSignal(str, bytes)

    def __init__(self, workshop_id: str, url: str):
        super().__init__()
        self._wid = workshop_id
        self._url = url

    def run(self) -> None:
        try:
            req = urllib.request.Request(self._url)
            with urllib.request.urlopen(req, timeout=THUMBNAIL_TIMEOUT) as resp:
                data = resp.read()
            self.downloaded.emit(self._wid, data)
        except (urllib.error.URLError, OSError):
            pass


class ThumbnailLoader(QObject):
    def __init__(self, cache_dir: Path):
        super().__init__()
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(exist_ok=True)
        self._pending: dict[str, list[WorkshopModWidget]] = {}
        self._workers: list[_DownloadWorker] = []

    def load(self, workshop_id: str, url: str, widget: WorkshopModWidget) -> None:
        cached = self._cache_dir / f"{workshop_id}.jpg"
        if cached.exists():
            pixmap = QPixmap(str(cached))
            if not pixmap.isNull():
                widget.set_thumbnail(pixmap)
                return

        if workshop_id in self._pending:
            self._pending[workshop_id].append(widget)
            return

        self._pending[workshop_id] = [widget]
        worker = _DownloadWorker(workshop_id, url)
        worker.downloaded.connect(self._on_downloaded)
        self._workers.append(worker)
        worker.start()

    def _on_downloaded(self, workshop_id: str, data: bytes) -> None:
        widgets = self._pending.pop(workshop_id, [])
        if not data:
            return

        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return

        cache_path = self._cache_dir / f"{workshop_id}.jpg"
        try:
            cache_path.write_bytes(data)
        except OSError:
            pass

        for w in widgets:
            w.set_thumbnail(pixmap)
