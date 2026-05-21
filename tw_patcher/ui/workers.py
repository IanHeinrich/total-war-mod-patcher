import asyncio
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..clients.rpfm import RPFMClient
from ..clients.steam import SteamWorkshopClient, WorkshopDetails
from ..config import settings
from ..services.extraction import ExtractionService
from ..services.repacking import RepackingService
from ..services.system import SystemService


class ExtractWorker(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, sources: list[str], output: Optional[str] = None):
        super().__init__()
        self.sources = sources
        self.output = output

    def run(self) -> None:
        try:
            async def _run():
                system = SystemService(settings)
                client = RPFMClient(settings.rpfm_host, settings.rpfm_port, settings.rpfm_timeout)
                self.progress.emit("Connecting to RPFM server...")
                await system.connect_client(client)
                try:
                    service = ExtractionService(settings, client)
                    output_dir = Path(self.output) if self.output else settings.sources_dir
                    self.progress.emit(f"Extracting {len(self.sources)} mod(s)...")
                    pack_paths = [Path(s) for s in self.sources]
                    return await service.extract_batch(pack_paths, output_dir)
                finally:
                    await client.disconnect()

            results = asyncio.run(_run())
            total = sum(r.success_count for r in results)
            self.finished.emit(True, f"Extracted {len(self.sources)} mod(s), {total} tables")
        except Exception as e:
            self.finished.emit(False, f"Extraction failed: {e}\n{traceback.format_exc()}")


class RepackWorker(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, patch_name: str, output: Optional[str] = None, name: Optional[str] = None):
        super().__init__()
        self.patch_name = patch_name
        self.output = output
        self.name = name

    def run(self) -> None:
        try:
            async def _run():
                system = SystemService(settings)
                client = RPFMClient(settings.rpfm_host, settings.rpfm_port, settings.rpfm_timeout)
                self.progress.emit("Connecting to RPFM server...")
                await system.connect_client(client)
                try:
                    service = RepackingService(settings, client)
                    output_path = Path(self.output) if self.output else None
                    self.progress.emit(f"Repacking '{self.patch_name}'...")
                    return await service.repack(self.patch_name, output_path, self.name)
                finally:
                    await client.disconnect()

            result = asyncio.run(_run())
            self.finished.emit(
                True, f"Repacked '{self.patch_name}': {result.success_count} tables -> {result.output_path}"
            )
        except Exception as e:
            self.finished.emit(False, f"Repacking failed: {e}\n{traceback.format_exc()}")


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
