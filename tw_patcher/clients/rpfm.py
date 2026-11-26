"""
WebSocket client for RPFM headless server.

Speaks both the legacy command protocol and the JSON-RPC 2.0 protocol of newer
RPFM releases (see ``rpfm_protocols``); which one is chosen from the server's
first frame at connect time and exposed as ``client.protocol``.
"""

import asyncio
import json
import logging
import types
import urllib.request

import websockets
from websockets import ClientConnection

from ..constants import RPFM_DEFAULT_PORT, RPFM_DEFAULT_TIMEOUT, RPFM_WS_MAX_SIZE
from .rpfm_protocols import LEGACY, JsonRpcProtocol, LegacyProtocol, RPFMProtocol, detect_protocol

logger = logging.getLogger(__name__)

VERSION_TIMEOUT = 2  # seconds; the /version lookup is best effort


class RPFMClient:
    def __init__(self, host: str = "127.0.0.1", port: int = RPFM_DEFAULT_PORT, timeout: int = RPFM_DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ws_url = f"ws://{host}:{port}/ws"
        self.connection: ClientConnection | None = None
        self.session_id: int | None = None
        self.server_version: str | None = None
        self._protocol: RPFMProtocol | None = None

    @property
    def protocol(self) -> str | None:
        """``"legacy"`` or ``"jsonrpc"`` once connected, else None."""
        return self._protocol.name if self._protocol else None

    async def connect(self) -> None:
        try:
            logger.info(f"Connecting to RPFM server at {self.ws_url}...")
            self.connection = await asyncio.wait_for(
                websockets.connect(self.ws_url, max_size=RPFM_WS_MAX_SIZE), timeout=self.timeout
            )
            raw = await asyncio.wait_for(self.connection.recv(), timeout=self.timeout)
            msg = json.loads(raw)
            protocol, self.session_id = detect_protocol(msg)
            if protocol is None:
                logger.warning(f"Unexpected first message from RPFM server: {msg}")
                protocol = LEGACY
            if protocol == LEGACY:
                self._protocol = LegacyProtocol(self.connection, self.timeout)
            else:
                self._protocol = JsonRpcProtocol(self.connection, self.timeout)
                self.server_version = await asyncio.to_thread(self._fetch_server_version)
            logger.info(f"Connected to RPFM server (protocol={protocol}, session_id={self.session_id})")
        except asyncio.TimeoutError:
            raise ConnectionError(f"Timed out connecting to RPFM server ({self.timeout}s)") from None
        except Exception as e:
            raise ConnectionError(f"Failed to connect to RPFM server: {e}") from e

    def _fetch_server_version(self) -> str | None:
        """GET /version (response shape undocumented): a "version" field if JSON, else the raw body. Never raises."""
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://{self.host}:{self.port}/version", timeout=VERSION_TIMEOUT) as response:
                body = response.read(4096).decode("utf-8", errors="replace").strip()
        except Exception as e:
            logger.debug(f"Could not read RPFM server version: {e}")
            return None
        try:
            data = json.loads(body)
        except ValueError:
            data = body
        if isinstance(data, dict):
            data = data.get("version") or data.get("server_version")
        if isinstance(data, (str, int, float)) and str(data).strip():
            text = str(data).strip()
            return text if len(text) <= 100 and "\n" not in text else None
        return None

    async def disconnect(self) -> None:
        if self.connection:
            if self._protocol:
                try:
                    await self._protocol.goodbye()
                except Exception:
                    pass
            await self.connection.close()
            logger.info("Disconnected from RPFM server")

    @property
    def _proto(self) -> RPFMProtocol:
        if not self._protocol:
            raise RuntimeError("Not connected to RPFM server")
        return self._protocol

    async def set_game_selected(self, game_key: str) -> None:
        await self._proto.set_game_selected(game_key)
        logger.info(f"Game set to: {game_key}")

    async def open_pack_file(self, pack_path: str) -> str:
        return await self._proto.open_pack_file(pack_path)

    async def close_pack_file(self, pack_handle: str) -> None:
        await self._proto.close_pack_file(pack_handle)

    async def list_paths(self, pack_handle: str) -> list[str]:
        """Every file path in the pack, fetched once (callers filter by prefix)."""
        return await self._proto.list_paths(pack_handle)

    async def list_db_table_paths(self, pack_handle: str) -> list[str]:
        return [p for p in await self.list_paths(pack_handle) if p.startswith("db/")]

    async def list_script_paths(self, pack_handle: str) -> list[str]:
        return [p for p in await self.list_paths(pack_handle) if p.startswith("script/")]

    async def extract_packed_files(self, pack_handle: str, paths: list[str], dest_path: str) -> None:
        await self._proto.extract_packed_files(pack_handle, paths, dest_path)

    async def export_tsv(self, pack_handle: str, table_path: str, output_path: str) -> None:
        await self._proto.export_tsv(pack_handle, table_path, output_path)

    async def import_tsv(self, pack_handle: str, table_path: str, tsv_path: str) -> None:
        await self._proto.import_tsv(pack_handle, table_path, tsv_path)

    async def delete_packed_files(self, pack_handle: str, paths: list[str]) -> None:
        await self._proto.delete_packed_files(pack_handle, paths)

    async def save_pack(self, pack_handle: str) -> None:
        await self._proto.save_pack(pack_handle)

    async def add_packed_file(self, pack_handle: str, source_path: str, dest_path: str) -> None:
        await self._proto.add_packed_file(pack_handle, source_path, dest_path)

    async def new_pack(self) -> str:
        return await self._proto.new_pack()

    async def save_pack_as(self, pack_handle: str, output_path: str) -> None:
        await self._proto.save_pack_as(pack_handle, output_path)


class RPFMConnection:
    def __init__(self, host: str = "127.0.0.1", port: int = RPFM_DEFAULT_PORT, timeout: int = RPFM_DEFAULT_TIMEOUT):
        self.client = RPFMClient(host, port, timeout)

    async def __aenter__(self) -> RPFMClient:
        await self.client.connect()
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.client.disconnect()
