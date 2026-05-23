from __future__ import annotations

import urllib.request
import urllib.error
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap

from ...constants import THUMBNAIL_TIMEOUT
from .workshop_mod import WorkshopModWidget


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
