from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ...clients.steam import SteamWorkshopClient


class WorkshopMetadataWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, workshop_ids: list[str], cache_file: Path):
        super().__init__()
        self._ids = workshop_ids
        self._cache_file = cache_file

    def run(self) -> None:
        client = SteamWorkshopClient(self._cache_file)
        details = client.get_details(self._ids)
        self.finished.emit(details)
