import asyncio
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ...clients.rpfm import RPFMClient
from ...config import settings
from ...services.repacking import RepackingService
from ...services.system import SystemService


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
