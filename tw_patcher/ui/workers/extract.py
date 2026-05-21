import asyncio
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ...clients.rpfm import RPFMClient
from ...config import settings
from ...services.extraction import ExtractionService
from ...services.system import SystemService


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
