import urllib.request
import urllib.error
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

from ...models.game import GameDef


class ArtworkDownloadWorker(QThread):
    downloaded = pyqtSignal(str, bytes)  # (game_key, image_data)

    def __init__(self, game_key: str, url: str):
        super().__init__()
        self._game_key = game_key
        self._url = url

    def run(self) -> None:
        try:
            req = urllib.request.Request(self._url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            self.downloaded.emit(self._game_key, data)
        except (urllib.error.URLError, OSError):
            pass


class ArtworkLoader:
    def __init__(self, cache_dir: Path):
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(exist_ok=True)
        self._workers: list[ArtworkDownloadWorker] = []
        self._pending: dict[str, list[callable]] = {}

    def load(self, game_def: GameDef, callback: callable) -> None:
        if not game_def.header_image_url or not game_def.steam_app_id:
            return

        cached = self._cache_dir / f"{game_def.steam_app_id}.jpg"
        if cached.exists():
            pixmap = QPixmap(str(cached))
            if not pixmap.isNull():
                callback(game_def.key, pixmap)
                return

        if game_def.key in self._pending:
            self._pending[game_def.key].append(callback)
            return

        self._pending[game_def.key] = [callback]
        worker = ArtworkDownloadWorker(game_def.key, game_def.header_image_url)
        worker.downloaded.connect(lambda key, data: self._on_downloaded(key, data, game_def.steam_app_id))
        self._workers.append(worker)
        worker.start()

    def _on_downloaded(self, game_key: str, data: bytes, app_id: int) -> None:
        callbacks = self._pending.pop(game_key, [])
        if not data:
            return

        cache_path = self._cache_dir / f"{app_id}.jpg"
        try:
            cache_path.write_bytes(data)
        except OSError:
            pass

        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return

        for cb in callbacks:
            cb(game_key, pixmap)
