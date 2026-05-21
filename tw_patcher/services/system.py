import asyncio
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..clients.rpfm import RPFMClient
from ..config import Settings
from ..console import console
from ..exceptions import ConfigurationError


class SystemService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def find_rpfm_executable(self) -> Optional[Path]:
        for path in self.settings.rpfm_search_paths:
            if path.exists() and path.is_file():
                console.info(f"Found RPFM at: {path}")
                return path
        return None

    def _is_port_open(self) -> bool:
        try:
            with socket.create_connection(
                (self.settings.rpfm_host, self.settings.rpfm_port), timeout=2
            ):
                return True
        except OSError:
            return False

    def _launch_rpfm(self) -> None:
        rpfm_exe = self.find_rpfm_executable()
        if not rpfm_exe:
            raise ConfigurationError(
                "Cannot find RPFM installation. Please install RPFM from "
                "https://github.com/Frodo45127/rpfm/releases"
            )

        server_exe = rpfm_exe.parent / "rpfm_server.exe"
        launch_exe = server_exe if server_exe.exists() else rpfm_exe
        console.info(f"Launching: {launch_exe}")

        if platform.system() == "Windows":
            subprocess.Popen([str(launch_exe)], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([str(launch_exe)])

    async def connect_client(self, client: RPFMClient) -> None:
        """Connect the given client, starting RPFM server if needed."""
        try:
            with console.status("Connecting to RPFM..."):
                await client.connect()
            return
        except ConnectionError:
            console.info("RPFM server not running, attempting to start...")

        self._launch_rpfm()

        with console.status("Starting RPFM server..."):
            for _ in range(self.settings.rpfm_startup_attempts):
                await asyncio.sleep(self.settings.rpfm_startup_wait_seconds)
                if self._is_port_open():
                    await client.connect()
                    console.success("RPFM server is ready")
                    return

        raise ConfigurationError("RPFM server did not start in time")

    def check_system(self) -> None:
        console.info("Checking system requirements...")

        if sys.version_info < (3, 10):
            raise ConfigurationError(
                f"Python 3.10+ required, found {sys.version_info.major}.{sys.version_info.minor}"
            )
        console.info(f"Python {sys.version_info.major}.{sys.version_info.minor} OK")

        if not self.find_rpfm_executable():
            console.warning("RPFM not found in common installation paths")
        else:
            console.info("RPFM installation found")
