"""
WebSocket client for RPFM headless server.

Protocol uses externally-tagged serde enums:
  Send:    {"id": <u64>, "data": {"CommandName": params}}
  Receive: {"id": <u64>, "data": <Response>}

On connect the server sends: {"id": 0, "data": {"SessionConnected": <session_id>}}
"""

import asyncio
import json
import logging
import types
from typing import Any, Optional

import websockets
from websockets import ClientConnection

from ..constants import RPFM_DEFAULT_PORT, RPFM_DEFAULT_TIMEOUT, RPFM_WS_MAX_SIZE
from ..exceptions import RPFMError

logger = logging.getLogger(__name__)


class RPFMClient:
    def __init__(self, host: str = "127.0.0.1", port: int = RPFM_DEFAULT_PORT, timeout: int = RPFM_DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ws_url = f"ws://{host}:{port}/ws"
        self.connection: Optional[ClientConnection] = None
        self.session_id: Optional[int] = None
        self._message_id = 0

    async def connect(self) -> None:
        try:
            logger.info(f"Connecting to RPFM server at {self.ws_url}...")
            self.connection = await asyncio.wait_for(
                websockets.connect(self.ws_url, max_size=RPFM_WS_MAX_SIZE),
                timeout=self.timeout
            )
            raw = await asyncio.wait_for(self.connection.recv(), timeout=self.timeout)
            msg = json.loads(raw)
            data = msg.get("data")
            if isinstance(data, dict) and "SessionConnected" in data:
                self.session_id = data["SessionConnected"]
                logger.info(f"Connected to RPFM server (session_id={self.session_id})")
            else:
                logger.warning(f"Unexpected first message from RPFM server: {msg}")
        except asyncio.TimeoutError:
            raise ConnectionError(f"Timed out connecting to RPFM server ({self.timeout}s)")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to RPFM server: {e}")

    async def disconnect(self) -> None:
        if self.connection:
            try:
                await self._send_notify("ClientDisconnecting")
            except Exception:
                pass
            await self.connection.close()
            logger.info("Disconnected from RPFM server")

    def _next_id(self) -> int:
        self._message_id += 1
        return self._message_id

    async def _send_notify(self, command: str) -> None:
        if not self.connection:
            raise RuntimeError("Not connected to RPFM server")
        message: dict[str, Any] = {"id": self._next_id(), "data": command}
        await self.connection.send(json.dumps(message))

    async def send_command(self, command: str, params: Any = None) -> Any:
        if not self.connection:
            raise RuntimeError("Not connected to RPFM server")

        message_id = self._next_id()

        if params is None:
            data: Any = command
        else:
            data = {command: params}

        message: dict[str, Any] = {"id": message_id, "data": data}

        try:
            logger.debug(f"-> {command} (id={message_id})")
            await self.connection.send(json.dumps(message))

            while True:
                raw = await asyncio.wait_for(
                    self.connection.recv(),
                    timeout=self.timeout
                )
                response = json.loads(raw)
                if response.get("id") == message_id:
                    break
                logger.debug(f"Discarding message with id={response.get('id')}")

            resp_data = response.get("data")

            if isinstance(resp_data, dict) and "Error" in resp_data:
                raise RPFMError(resp_data["Error"])

            logger.debug(f"<- {command} OK")
            return resp_data

        except RPFMError:
            raise
        except asyncio.TimeoutError:
            raise TimeoutError(f"Command '{command}' timed out after {self.timeout}s")
        except Exception as e:
            raise RuntimeError(f"Error executing '{command}': {e}")

    async def set_game_selected(self, game_key: str) -> None:
        await self.send_command("SetGameSelected", [game_key, False])
        logger.info(f"Game set to: {game_key}")

    async def open_pack_file(self, pack_path: str) -> str:
        result = await self.send_command("OpenPackFiles", [pack_path])
        if isinstance(result, dict) and "StringContainerInfo" in result:
            handle_and_info: Any = result["StringContainerInfo"]
            return str(handle_and_info[0])
        raise RPFMError(f"Unexpected response from OpenPackFiles: {result}")

    async def close_pack_file(self, pack_handle: str) -> None:
        await self.send_command("ClosePack", pack_handle)

    async def list_db_table_paths(self, pack_handle: str) -> list[str]:
        result = await self.send_command("GetPackFileDataForTreeView", pack_handle)
        if isinstance(result, dict) and "ContainerInfoVecRFileInfo" in result:
            container_and_files: Any = result["ContainerInfoVecRFileInfo"]
            _container_info, file_list = container_and_files
            return [
                f["path"] for f in file_list
                if isinstance(f, dict) and f.get("path", "").startswith("db/")
            ]
        raise RPFMError(f"Unexpected response from GetPackFileDataForTreeView: {result}")

    async def list_script_paths(self, pack_handle: str) -> list[str]:
        result = await self.send_command("GetPackFileDataForTreeView", pack_handle)
        if isinstance(result, dict) and "ContainerInfoVecRFileInfo" in result:
            container_and_files: Any = result["ContainerInfoVecRFileInfo"]
            _container_info, file_list = container_and_files
            return [
                f["path"] for f in file_list
                if isinstance(f, dict) and f.get("path", "").startswith("script/")
            ]
        raise RPFMError(f"Unexpected response from GetPackFileDataForTreeView: {result}")

    async def extract_packed_files(self, pack_handle: str, paths: list[str], dest_path: str) -> None:
        container_paths = [{"File": p} for p in paths]
        sources = {"PackFile": container_paths}
        await self.send_command("ExtractPackedFiles", [pack_handle, sources, dest_path, False])

    async def export_tsv(self, pack_handle: str, table_path: str, output_path: str) -> None:
        await self.send_command("ExportTSV", [pack_handle, table_path, output_path, "PackFile"])

    async def import_tsv(self, pack_handle: str, table_path: str, tsv_path: str) -> None:
        await self.send_command("ImportTSV", [pack_handle, table_path, tsv_path])

    async def delete_packed_files(self, pack_handle: str, paths: list[str]) -> None:
        container_paths = [{"File": p} for p in paths]
        await self.send_command("DeletePackedFiles", [pack_handle, container_paths])

    async def save_pack(self, pack_handle: str) -> None:
        await self.send_command("SavePack", pack_handle)

    async def add_packed_file(self, pack_handle: str, source_path: str, dest_path: str) -> None:
        result = await self.send_command(
            "AddPackedFiles",
            [pack_handle, [source_path], [{"File": dest_path}], None]
        )
        if isinstance(result, dict) and "VecContainerPathOptionString" in result:
            paths_and_error: Any = result["VecContainerPathOptionString"]
            _added_paths, error_message = paths_and_error
            if error_message:
                raise RPFMError(str(error_message))
            return
        raise RPFMError(f"Unexpected response from AddPackedFiles: {result}")

    async def new_pack(self) -> str:
        result = await self.send_command("NewPack")
        if isinstance(result, dict) and "String" in result:
            return str(result["String"])
        raise RPFMError(f"Unexpected response from NewPack: {result}")

    async def save_pack_as(self, pack_handle: str, output_path: str) -> None:
        await self.send_command("SavePackAs", [pack_handle, output_path])


class RPFMConnection:
    def __init__(self, host: str = "127.0.0.1", port: int = RPFM_DEFAULT_PORT, timeout: int = RPFM_DEFAULT_TIMEOUT):
        self.client = RPFMClient(host, port, timeout)

    async def __aenter__(self) -> RPFMClient:
        await self.client.connect()
        return self.client

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> None:
        await self.client.disconnect()
