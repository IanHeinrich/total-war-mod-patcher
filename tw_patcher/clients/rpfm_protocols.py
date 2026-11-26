"""
The two wire protocols RPFM's headless server has spoken, behind one interface.

Legacy (RPFM <= 4.7 style), externally-tagged serde enums:
  Send:    {"id": <u64>, "data": {"CommandName": params}}
  Receive: {"id": <u64>, "data": <Response>}
  Greeting: {"id": 0, "data": {"SessionConnected": <session_id>}}

JSON-RPC 2.0 (current RPFM manual, server/ws-protocol):
  Send:    {"jsonrpc": "2.0", "id": n, "method": "pack.open", "params": {...}}
  Receive: {"jsonrpc": "2.0", "id": n, "result": ...} or {..., "error": {"code", "message", "data"}}
  Greeting: {"jsonrpc": "2.0", "method": "session.connected", "params": {"session_id": n}}
  Long-running methods answer {"job": n}; their outcome is fetched with job.wait.

``RPFMClient`` reads the greeting and picks one of these classes.
"""

import asyncio
import json
import logging
from typing import Any

from websockets import ClientConnection

from ..exceptions import RPFMError

logger = logging.getLogger(__name__)

LEGACY = "legacy"
JSONRPC = "jsonrpc"

DIAGNOSTICS_UNSUPPORTED = "RPFM diagnostics need RPFM 5 or newer (found legacy protocol)"
DIAGNOSTICS_TIMEOUT = 600  # seconds; loading dependencies and checking a large pack can take minutes
DIAGNOSTIC_LEVELS: tuple[str, ...] = ("info", "warning", "error")


class RPFMRequestError(RPFMError):
    """A JSON-RPC ``error`` reply (or failed job), keeping its ``code`` and ``data.kind``."""

    def __init__(self, error: Any):
        super().__init__(_error_message(error))
        self.code = error.get("code") if isinstance(error, dict) else None
        data = error.get("data") if isinstance(error, dict) else None
        self.kind = data.get("kind") if isinstance(data, dict) else None


def detect_protocol(greeting: Any) -> tuple[str | None, int | None]:
    """Return (protocol, session_id) for the server's first frame, or (None, None) if unrecognised."""
    if not isinstance(greeting, dict):
        return None, None
    if "jsonrpc" in greeting or greeting.get("method") == "session.connected":
        params = greeting.get("params")
        session_id = params.get("session_id") if isinstance(params, dict) else None
        return JSONRPC, session_id
    data = greeting.get("data")
    if isinstance(data, dict) and "SessionConnected" in data:
        return LEGACY, data["SessionConnected"]
    return None, None


class RPFMProtocol:
    name: str

    def __init__(self, connection: ClientConnection, timeout: int):
        self.connection = connection
        self.timeout = timeout
        self._message_id = 0

    def _next_id(self) -> int:
        self._message_id += 1
        return self._message_id

    async def goodbye(self) -> None:
        raise NotImplementedError

    async def set_game_selected(self, game_key: str) -> None:
        raise NotImplementedError

    async def open_pack_file(self, pack_path: str) -> str:
        raise NotImplementedError

    async def close_pack_file(self, pack_handle: str) -> None:
        raise NotImplementedError

    async def list_paths(self, pack_handle: str) -> list[str]:
        raise NotImplementedError

    async def extract_packed_files(self, pack_handle: str, paths: list[str], dest_path: str) -> None:
        raise NotImplementedError

    async def export_tsv(self, pack_handle: str, table_path: str, output_path: str) -> None:
        raise NotImplementedError

    async def import_tsv(self, pack_handle: str, table_path: str, tsv_path: str) -> None:
        raise NotImplementedError

    async def delete_packed_files(self, pack_handle: str, paths: list[str]) -> None:
        raise NotImplementedError

    async def save_pack(self, pack_handle: str) -> None:
        raise NotImplementedError

    async def save_pack_as(self, pack_handle: str, output_path: str) -> None:
        raise NotImplementedError

    async def add_packed_file(self, pack_handle: str, source_path: str, dest_path: str) -> None:
        raise NotImplementedError

    async def new_pack(self) -> str:
        raise NotImplementedError

    async def run_diagnostics(self, pack_handle: str, levels: list[str] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError


class LegacyProtocol(RPFMProtocol):
    name = LEGACY

    async def goodbye(self) -> None:
        await self._send_notify("ClientDisconnecting")

    async def _send_notify(self, command: str) -> None:
        message: dict[str, Any] = {"id": self._next_id(), "data": command}
        await self.connection.send(json.dumps(message))

    async def send_command(self, command: str, params: Any = None) -> Any:
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
                raw = await asyncio.wait_for(self.connection.recv(), timeout=self.timeout)
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
            raise TimeoutError(f"Command '{command}' timed out after {self.timeout}s") from None
        except Exception as e:
            raise RuntimeError(f"Error executing '{command}': {e}") from e

    async def set_game_selected(self, game_key: str) -> None:
        await self.send_command("SetGameSelected", [game_key, False])

    async def open_pack_file(self, pack_path: str) -> str:
        result = await self.send_command("OpenPackFiles", [pack_path])
        if isinstance(result, dict) and "StringContainerInfo" in result:
            handle_and_info: Any = result["StringContainerInfo"]
            return str(handle_and_info[0])
        raise RPFMError(f"Unexpected response from OpenPackFiles: {result}")

    async def close_pack_file(self, pack_handle: str) -> None:
        await self.send_command("ClosePack", pack_handle)

    async def list_paths(self, pack_handle: str) -> list[str]:
        result = await self.send_command("GetPackFileDataForTreeView", pack_handle)
        if isinstance(result, dict) and "ContainerInfoVecRFileInfo" in result:
            container_and_files: Any = result["ContainerInfoVecRFileInfo"]
            _container_info, file_list = container_and_files
            return [f["path"] for f in file_list if isinstance(f, dict) and f.get("path")]
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

    async def save_pack_as(self, pack_handle: str, output_path: str) -> None:
        await self.send_command("SavePackAs", [pack_handle, output_path])

    async def add_packed_file(self, pack_handle: str, source_path: str, dest_path: str) -> None:
        result = await self.send_command("AddPackedFiles", [pack_handle, [source_path], [{"File": dest_path}], None])
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

    async def run_diagnostics(self, pack_handle: str, levels: list[str] | None = None) -> list[dict[str, Any]]:
        raise RPFMError(DIAGNOSTICS_UNSUPPORTED)


class JsonRpcProtocol(RPFMProtocol):
    name = JSONRPC
    PAGE_SIZE = 500
    GOODBYE_TIMEOUT = 5  # seconds

    async def goodbye(self) -> None:
        await self.call("session.disconnect", {}, timeout=min(self.timeout, self.GOODBYE_TIMEOUT))

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        """Send one request and return its ``result``; raise RPFMError for an ``error`` reply."""
        timeout = self.timeout if timeout is None else timeout
        message_id = self._next_id()
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = params

        try:
            logger.debug(f"-> {method} (id={message_id})")
            await self.connection.send(json.dumps(message))

            while True:
                raw = await asyncio.wait_for(self.connection.recv(), timeout=timeout)
                response = json.loads(raw)
                if isinstance(response, dict) and response.get("id") == message_id:
                    break
                if isinstance(response, dict) and "id" not in response:
                    logger.debug(f"Skipping notification {response.get('method')}")
                else:
                    logger.debug(f"Discarding message with id={response.get('id')}")

            if "error" in response:
                raise RPFMRequestError(response["error"])

            logger.debug(f"<- {method} OK")
            return response.get("result")

        except RPFMError:
            raise
        except asyncio.TimeoutError:
            raise TimeoutError(f"Command '{method}' timed out after {timeout:g}s") from None
        except Exception as e:
            raise RuntimeError(f"Error executing '{method}': {e}") from e

    async def call_job(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        """Run a job-style method to completion within ``timeout`` (default ``self.timeout``) and return its result."""
        timeout = self.timeout if timeout is None else timeout
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        started = await self.call(method, params)
        if not (isinstance(started, dict) and "job" in started):
            return started  # answered directly instead of as a job
        job = started["job"]

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"Command '{method}' timed out after {timeout:g}s")
            wait_secs = max(1, int(remaining))
            # job.wait blocks server-side for up to wait_secs, so give the reply a little longer to arrive.
            status = await self.call("job.wait", {"job": job, "timeout_secs": wait_secs}, timeout=wait_secs + 5)
            state = status.get("state") if isinstance(status, dict) else None
            if state == "finished":
                return status.get("result")
            if state == "failed":
                raise RPFMRequestError(status.get("error"))
            if state == "cancelled":
                raise RPFMError(f"RPFM job '{method}' was cancelled")
            if state not in ("queued", "running"):
                raise RPFMError(f"Unexpected response from job.wait: {status}")

    async def set_game_selected(self, game_key: str) -> None:
        await self.call_job("session.set_game", {"game": game_key, "rebuild_dependencies": False})

    async def open_pack_file(self, pack_path: str) -> str:
        return self._pack_key("pack.open", await self.call("pack.open", {"paths": [pack_path]}))

    async def new_pack(self) -> str:
        return self._pack_key("pack.new", await self.call("pack.new", {"name": None}))

    @staticmethod
    def _pack_key(method: str, summary: Any) -> str:
        if isinstance(summary, dict) and summary.get("key"):
            return str(summary["key"])
        raise RPFMError(f"Unexpected response from {method}: {summary}")

    async def close_pack_file(self, pack_handle: str) -> None:
        await self.call("pack.close", {"pack": pack_handle})

    async def list_paths(self, pack_handle: str) -> list[str]:
        paths: list[str] = []
        while True:
            page = await self.call(
                "files.list",
                {
                    "source": {"pack": pack_handle},
                    "path_prefix": "",
                    "recursive": True,
                    "offset": len(paths),
                    "limit": self.PAGE_SIZE,
                },
            )
            if not (isinstance(page, dict) and isinstance(page.get("files"), list)):
                raise RPFMError(f"Unexpected response from files.list: {page}")
            files: list[Any] = page["files"]
            paths += [f["path"] for f in files if isinstance(f, dict) and f.get("path")]
            if not files or len(paths) >= int(page.get("total", 0)):
                return paths

    async def extract_packed_files(self, pack_handle: str, paths: list[str], dest_path: str) -> None:
        # Verified against RPFM 5.3.3: each file lands at <dest_path>/<pack path>, as with legacy ExtractPackedFiles.
        await self.call("files.extract", {"source": {"pack": pack_handle}, "paths": paths, "destination": dest_path})

    async def export_tsv(self, pack_handle: str, table_path: str, output_path: str) -> None:
        await self.call(
            "table.export_tsv",
            {"file": {"source": {"pack": pack_handle}, "path": table_path}, "destination": output_path},
        )

    async def import_tsv(self, pack_handle: str, table_path: str, tsv_path: str) -> None:
        await self.call("table.import_tsv", {"pack": pack_handle, "path": table_path, "tsv_path": tsv_path})

    async def delete_packed_files(self, pack_handle: str, paths: list[str]) -> None:
        await self.call("files.delete", {"pack": pack_handle, "paths": paths})

    async def save_pack(self, pack_handle: str) -> None:
        await self.call("pack.save", {"pack": pack_handle})

    async def save_pack_as(self, pack_handle: str, output_path: str) -> None:
        await self.call("pack.save", {"pack": pack_handle, "path": output_path})

    async def add_packed_file(self, pack_handle: str, source_path: str, dest_path: str) -> None:
        # Verified against RPFM 5.3.3: a .tsv added at a db/ path becomes a binary DB table (file_type "DB"),
        # exactly like legacy AddPackedFiles.
        result = await self.call(
            "files.add_from_disk",
            {"pack": pack_handle, "paths": [source_path], "folder": "", "pack_paths": [dest_path]},
        )
        if not isinstance(result, dict):
            raise RPFMError(f"Unexpected response from files.add_from_disk: {result}")
        if result.get("error"):
            raise RPFMError(str(result["error"]))
        if dest_path not in (result.get("added") or []):
            raise RPFMError(f"RPFM did not add {dest_path} (not added: {result.get('not_added') or [source_path]})")

    async def run_diagnostics(self, pack_handle: str, levels: list[str] | None = None) -> list[dict[str, Any]]:
        # Shapes follow the RPFM manual (server/methods/diagnostics, session, ws-protocol); not yet checked
        # against a live RPFM 5.3.3: the SessionStatus.dependencies fields, dependencies.rebuild loading a
        # cache that set_game (rebuild_dependencies=false) skipped, and DiagnosticResult.pack being the pack key.
        await self._ensure_dependencies()
        try:
            # Checks every open pack; we only ever have this one open.
            await self.call_job("diagnostics.run", {}, timeout=max(self.timeout, DIAGNOSTICS_TIMEOUT))
        except RPFMRequestError as e:
            if e.kind == "dependencies_not_loaded":
                raise RPFMError(_dependencies_hint(str(e))) from e
            raise

        items: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"pack": pack_handle, "offset": len(items), "limit": self.PAGE_SIZE}
            if levels:
                params["levels"] = levels
            try:
                page = await self.call("diagnostics.list", params)
            except RPFMRequestError as e:
                if e.kind == "diagnostics_not_run":
                    raise RPFMError(
                        "RPFM has no diagnostics results (the check was cancelled or never ran); try again"
                    ) from e
                raise
            if not (isinstance(page, dict) and isinstance(page.get("results"), list)):
                raise RPFMError(f"Unexpected response from diagnostics.list: {page}")
            results: list[Any] = page["results"]
            items += [_normalize_diagnostic(r) for r in results if isinstance(r, dict)]
            if not results or len(items) >= int(page.get("total", 0)):
                return items

    async def _ensure_dependencies(self) -> None:
        """Load the game's dependencies (skipped by set_game for speed) so references can be checked."""
        status = await self.call("session.status", {})
        deps = status.get("dependencies") if isinstance(status, dict) else None
        if isinstance(deps, dict) and deps.get("vanilla_loaded"):
            return
        status = await self.call_job("dependencies.rebuild", {}, timeout=max(self.timeout, DIAGNOSTICS_TIMEOUT))
        deps = status.get("dependencies") if isinstance(status, dict) else None
        if isinstance(deps, dict) and not deps.get("vanilla_loaded"):
            raise RPFMError(_dependencies_hint(deps.get("error") or "vanilla files not loaded"))


def _dependencies_hint(reason: str) -> str:
    return (
        f"RPFM could not load the game's dependencies, which diagnostics need: {reason}. "
        "Generate the dependencies cache in RPFM (Special Stuff > your game > Generate Dependencies Cache) "
        "and try again."
    )


def _normalize_diagnostic(result: dict[str, Any]) -> dict[str, Any]:
    """A DiagnosticResult as {path, level, report_type, message, columns?, cells?}."""
    item: dict[str, Any] = {
        "path": str(result.get("path") or ""),
        "level": str(result.get("level") or "info").lower(),
        "report_type": str(result.get("report_type") or ""),
        "message": str(result.get("message") or ""),
    }
    if result.get("columns"):
        item["columns"] = list(result["columns"])
    if result.get("cells"):
        item["cells"] = result["cells"]
    return item


def _error_message(error: Any) -> str:
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return f"RPFM error: {error}"
