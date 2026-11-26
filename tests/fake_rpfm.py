"""A stand-in for RPFM's headless WebSocket server, for outside-in tests.

It speaks the same envelope as ``tw_patcher/clients/rpfm.py`` (``{"id", "data"}``,
``SessionConnected`` greeting, externally-tagged commands) and implements just
the commands tw-patcher sends. Packs are JSON files on disk::

    {"fake_rpfm_pack": 1, "files": {"db/units_tables/mod": "<tsv text>", "script/x.lua": "..."}}

so a test can build an input pack with :func:`write_pack` and inspect what
tw-patcher produced with :func:`read_pack`. Table contents are kept as TSV text;
real RPFM converts them to binary, which tw-patcher never sees.
"""

from __future__ import annotations

import itertools
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from websockets.sync.server import Server, ServerConnection, serve

PACK_MARKER = "fake_rpfm_pack"


def write_pack(path: Path, files: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({PACK_MARKER: 1, "files": files}, indent=2), encoding="utf-8")
    return path


def read_pack(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get(PACK_MARKER) == 1, f"{path} is not a fake RPFM pack"
    return data["files"]


@dataclass
class _OpenPack:
    path: Path | None
    files: dict[str, str] = field(default_factory=dict)


class FakeRPFM:
    """Run with ``start()``/``stop()``; ``port`` is chosen by the OS."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        # (command, substring of the JSON-encoded params) -> error message
        self.failures: dict[tuple[str, str], str] = {}
        self.game: str | None = None
        self._packs: dict[str, _OpenPack] = {}
        self._handles = itertools.count(1)
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> FakeRPFM:
        self._server = serve(self._handle_connection, "127.0.0.1", 0)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.socket.getsockname()[1]

    # ------------------------------------------------------------------ test helpers
    def fail(self, command: str, match: str = "", message: str = "simulated RPFM failure") -> None:
        """Make ``command`` return an RPFM ``Error`` when its params contain ``match``."""
        self.failures[(command, match)] = message

    def commands(self) -> list[str]:
        return [name for name, _ in self.calls]

    @property
    def open_handles(self) -> list[str]:
        return list(self._packs)

    # ------------------------------------------------------------------ protocol
    def _handle_connection(self, ws: ServerConnection) -> None:
        ws.send(json.dumps({"id": 0, "data": {"SessionConnected": 1}}))
        for raw in ws:
            msg = json.loads(raw)
            data = msg["data"]
            if isinstance(data, str):
                name, params = data, None
            else:
                ((name, params),) = data.items()
            with self._lock:
                self.calls.append((name, params))
                if name == "ClientDisconnecting":  # notification, no reply
                    continue
                reply = self._dispatch(name, params)
            ws.send(json.dumps({"id": msg["id"], "data": reply}))

    def _dispatch(self, name: str, params: Any) -> Any:
        encoded = json.dumps(params)
        for (command, match), message in self.failures.items():
            if command == name and match in encoded:
                return {"Error": message}
        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            return {"Error": f"FakeRPFM does not implement {name}"}
        try:
            return handler(params)
        except Exception as e:  # surface fake bugs as RPFM errors, not hangs
            return {"Error": f"FakeRPFM {name} crashed: {e!r}"}

    def _new_handle(self, pack: _OpenPack) -> str:
        handle = f"pack_{next(self._handles)}"
        self._packs[handle] = pack
        return handle

    def _save(self, pack: _OpenPack, path: Path) -> str:
        write_pack(path, pack.files)
        return "Success"

    # ------------------------------------------------------------------ commands
    def _cmd_SetGameSelected(self, params: list) -> str:
        self.game = params[0]
        return "Success"

    def _cmd_OpenPackFiles(self, params: list[str]) -> dict:
        path = Path(params[0])
        handle = self._new_handle(_OpenPack(path, dict(read_pack(path))))
        return {"StringContainerInfo": [handle, {"file_name": path.name}]}

    def _cmd_NewPack(self, _params: None) -> dict:
        return {"String": self._new_handle(_OpenPack(None))}

    def _cmd_ClosePack(self, handle: str) -> str:
        self._packs.pop(handle)
        return "Success"

    def _cmd_GetPackFileDataForTreeView(self, handle: str) -> dict:
        files = [{"path": p} for p in sorted(self._packs[handle].files)]
        return {"ContainerInfoVecRFileInfo": [{}, files]}

    def _cmd_ExportTSV(self, params: list) -> str:
        handle, table_path, output_path, _source = params
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self._packs[handle].files[table_path], encoding="utf-8")
        return "Success"

    def _cmd_ImportTSV(self, params: list) -> str:
        handle, table_path, tsv_path = params
        pack = self._packs[handle]
        if table_path not in pack.files:
            return {"Error": f"Table not found in pack: {table_path}"}  # type: ignore[return-value]
        pack.files[table_path] = Path(tsv_path).read_text(encoding="utf-8")
        return "Success"

    def _cmd_AddPackedFiles(self, params: list) -> dict:
        handle, sources, dests, _ = params
        pack = self._packs[handle]
        added = []
        for src, dest in zip(sources, dests, strict=True):
            container_path = dest["File"]
            pack.files[container_path] = Path(src).read_text(encoding="utf-8")
            added.append({"File": container_path})
        return {"VecContainerPathOptionString": [added, None]}

    def _cmd_ExtractPackedFiles(self, params: list) -> str:
        handle, sources, dest_dir, _ = params
        pack = self._packs[handle]
        for entry in sources["PackFile"]:
            container_path = entry["File"]
            out = Path(dest_dir) / container_path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(pack.files[container_path], encoding="utf-8")
        return "Success"

    def _cmd_DeletePackedFiles(self, params: list) -> str:
        handle, paths = params
        for entry in paths:
            self._packs[handle].files.pop(entry["File"], None)
        return "Success"

    def _cmd_SavePack(self, handle: str) -> str:
        pack = self._packs[handle]
        assert pack.path is not None, "SavePack on a pack that was never saved"
        return self._save(pack, pack.path)

    def _cmd_SavePackAs(self, params: list) -> str:
        handle, output_path = params
        pack = self._packs[handle]
        pack.path = Path(output_path)
        return self._save(pack, pack.path)
