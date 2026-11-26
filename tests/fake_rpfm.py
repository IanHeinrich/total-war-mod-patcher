"""A stand-in for RPFM's headless WebSocket server, for outside-in tests.

It speaks either protocol ``tw_patcher/clients/rpfm.py`` understands, chosen by
``dialect``:

- ``"legacy"``: the ``{"id", "data"}`` envelope, ``SessionConnected`` greeting,
  externally-tagged commands;
- ``"jsonrpc"``: JSON-RPC 2.0 with a ``session.connected`` greeting, job-style
  ``session.set_game`` (answered via ``job.wait``) and ``GET /version``;

and implements just the commands tw-patcher sends. Packs are JSON files on disk::

    {"fake_rpfm_pack": 1, "files": {"db/units_tables/mod": "<tsv text>", "script/x.lua": "..."}}

so a test can build an input pack with :func:`write_pack` and inspect what
tw-patcher produced with :func:`read_pack`. Table contents are kept as TSV text;
real RPFM converts them to binary, which tw-patcher never sees.
"""

from __future__ import annotations

import itertools
import json
import threading
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any

from websockets.http11 import Request, Response
from websockets.sync.server import Server, ServerConnection, serve

PACK_MARKER = "fake_rpfm_pack"
VERSION = "5.3.3-fake"

# Legacy command name -> JSON-RPC method that replaces it, so ``fail()`` works in both dialects.
LEGACY_TO_METHOD = {
    "SetGameSelected": "session.set_game",
    "OpenPackFiles": "pack.open",
    "NewPack": "pack.new",
    "ClosePack": "pack.close",
    "GetPackFileDataForTreeView": "files.list",
    "ExportTSV": "table.export_tsv",
    "ImportTSV": "table.import_tsv",
    "AddPackedFiles": "files.add_from_disk",
    "ExtractPackedFiles": "files.extract",
    "DeletePackedFiles": "files.delete",
    "SavePack": "pack.save",
    "SavePackAs": "pack.save",
}

# JSON-RPC methods that answer {"job": n} and report their outcome through job.wait.
JOB_METHODS = {"session.set_game", "dependencies.rebuild", "diagnostics.run"}


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


class _RpcError(Exception):
    def __init__(self, code: int, kind: str, message: str):
        super().__init__(message)
        self.error = {"code": code, "message": message, "data": {"kind": kind, "details": message}}


class FakeRPFM:
    """Run with ``start()``/``stop()``; ``port`` is chosen by the OS."""

    def __init__(self, dialect: str = "legacy") -> None:
        assert dialect in ("legacy", "jsonrpc"), dialect
        self.dialect = dialect
        self.calls: list[tuple[str, Any]] = []
        # (command, substring of the JSON-encoded params) -> error message
        self.failures: dict[tuple[str, str], str] = {}
        self.game: str | None = None
        # jsonrpc only. Results diagnostics.run reports for every open pack, in DiagnosticResult shape
        # minus "pack" (filled in with each pack's key), e.g. {"path", "checked", "report_type", "level", "message"}.
        self.diagnostics: list[dict[str, Any]] = []
        self.dependencies_loaded = False
        # When set, loading dependencies fails with this reason (as a missing dependencies cache would).
        self.dependencies_error: str | None = None
        self._diagnosed: list[dict[str, Any]] | None = None
        self._packs: dict[str, _OpenPack] = {}
        self._handles = itertools.count(1)
        self._jobs: dict[int, dict[str, Any]] = {}
        self._job_ids = itertools.count(1)
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> FakeRPFM:
        self._server = serve(self._handle_connection, "127.0.0.1", 0, process_request=self._process_request)
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
        """Make ``command`` fail when its params contain ``match``. ``command`` may be a legacy
        command name or a JSON-RPC method name; either works in both dialects."""
        self.failures[(command, match)] = message

    def commands(self) -> list[str]:
        return [name for name, _ in self.calls]

    @property
    def open_handles(self) -> list[str]:
        return list(self._packs)

    def _injected_failure(self, name: str, params: Any) -> str | None:
        aliases = {name, LEGACY_TO_METHOD.get(name)} | {k for k, v in LEGACY_TO_METHOD.items() if v == name}
        encoded = json.dumps(params)
        for (command, match), message in self.failures.items():
            if command in aliases and match in encoded:
                return message
        return None

    # ------------------------------------------------------------------ connection
    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        if request.path == "/version" and self.dialect == "jsonrpc":
            # Same shape as RPFM 5.3.3's GET /version
            return connection.respond(HTTPStatus.OK, json.dumps({"pid": 1234, "version": VERSION}))
        return None

    def _handle_connection(self, ws: ServerConnection) -> None:
        if self.dialect == "jsonrpc":
            self._serve_jsonrpc(ws)
        else:
            self._serve_legacy(ws)

    # ------------------------------------------------------------------ legacy protocol
    def _serve_legacy(self, ws: ServerConnection) -> None:
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
        message = self._injected_failure(name, params)
        if message is not None:
            return {"Error": message}
        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            return {"Error": f"FakeRPFM does not implement {name}"}
        try:
            return handler(params)
        except Exception as e:  # surface fake bugs as RPFM errors, not hangs
            return {"Error": f"FakeRPFM {name} crashed: {e!r}"}

    # ------------------------------------------------------------------ JSON-RPC protocol
    def _serve_jsonrpc(self, ws: ServerConnection) -> None:
        ws.send(json.dumps({"jsonrpc": "2.0", "method": "session.connected", "params": {"session_id": 1}}))
        for raw in ws:
            msg = json.loads(raw)
            method, params = msg["method"], msg.get("params")
            with self._lock:
                self.calls.append((method, params))
                if method in JOB_METHODS:
                    job = self._start_job(method, params)
                    replies = [
                        {"jsonrpc": "2.0", "id": msg["id"], "result": {"job": job}},
                        # unsolicited progress notification the client has to skip
                        {"jsonrpc": "2.0", "method": "job.updated", "params": {**self._jobs[job]}},
                    ]
                else:
                    replies = [self._rpc_reply(msg["id"], method, params)]
            for reply in replies:
                ws.send(json.dumps(reply))

    def _rpc_reply(self, message_id: int, method: str, params: Any) -> dict[str, Any]:
        try:
            return {"jsonrpc": "2.0", "id": message_id, "result": self._rpc_dispatch(method, params)}
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": message_id, "error": e.error}

    def _rpc_dispatch(self, method: str, params: Any) -> Any:
        message = self._injected_failure(method, params)
        if message is not None:
            raise _RpcError(-32603, "internal", message)
        handler = getattr(self, "_rpc_" + method.replace(".", "_"), None)
        if handler is None:
            raise _RpcError(-32601, "method_not_found", f"FakeRPFM does not implement {method}")
        try:
            return handler(params or {})
        except _RpcError:
            raise
        except Exception as e:  # surface fake bugs as RPFM errors, not hangs
            raise _RpcError(-32603, "internal", f"FakeRPFM {method} crashed: {e!r}") from e

    def _start_job(self, method: str, params: Any) -> int:
        job = next(self._job_ids)
        try:
            self._jobs[job] = {
                "job": job,
                "method": method,
                "state": "finished",
                "result": self._rpc_dispatch(method, params),
            }
        except _RpcError as e:
            self._jobs[job] = {"job": job, "method": method, "state": "failed", "error": e.error}
        return job

    def _pack(self, key: str) -> _OpenPack:
        if key not in self._packs:
            raise _RpcError(-32001, "pack_not_found", f"Pack not found: {key}")
        return self._packs[key]

    def _summary(self, key: str) -> dict[str, Any]:
        pack = self._packs[key]
        return {
            "key": key,
            "name": pack.path.name if pack.path else "new_pack.pack",
            "path": str(pack.path) if pack.path else None,
            "pack_type": "Mod",
            "file_count": len(pack.files),
        }

    def _new_key(self, pack: _OpenPack) -> str:
        key = str(uuid.uuid4())
        self._packs[key] = pack
        return key

    def _rpc_session_set_game(self, params: dict) -> dict:
        self.game = params["game"]
        if params.get("rebuild_dependencies", True) and self.dependencies_error is None:
            self.dependencies_loaded = True
        return {"game": self.game, "schema_loaded": True, "dependencies": None, "packs": []}

    def _session_status(self) -> dict:
        return {
            "game": self.game,
            "schema_loaded": True,
            "dependencies": {
                "vanilla_loaded": self.dependencies_loaded,
                "assembly_kit_loaded": False,
                "parent_files": 0,
                "error": None if self.dependencies_loaded else self.dependencies_error,
            },
            "packs": [self._summary(key) for key in self._packs],
        }

    def _rpc_session_status(self, _params: dict) -> dict:
        return self._session_status()

    def _rpc_dependencies_rebuild(self, _params: dict) -> dict:
        if self.dependencies_error is None:
            self.dependencies_loaded = True
        return self._session_status()

    def _rpc_diagnostics_run(self, _params: dict) -> dict:
        if not self.dependencies_loaded:
            raise _RpcError(-32005, "dependencies_not_loaded", "The dependencies of the selected game aren't loaded")
        self._diagnosed = [{**item, "pack": key} for key in self._packs for item in self.diagnostics]
        by_level: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for item in self._diagnosed:
            by_level[item["level"]] = by_level.get(item["level"], 0) + 1
            by_type[item["report_type"]] = by_type.get(item["report_type"], 0) + 1
        return {"total": len(self._diagnosed), "by_level": by_level, "by_type": by_type}

    def _rpc_diagnostics_list(self, params: dict) -> dict:
        if self._diagnosed is None:
            raise _RpcError(-32009, "diagnostics_not_run", "No diagnostics have been run")
        results = [
            r
            for r in self._diagnosed
            if (params.get("pack") is None or r["pack"] == params["pack"])
            and (not params.get("levels") or r["level"] in params["levels"])
            and r["path"].startswith(params.get("path_prefix", ""))
        ]
        offset, limit = params.get("offset", 0), params.get("limit") or 100
        return {"results": results[offset : offset + limit], "total": len(results)}

    def _rpc_session_disconnect(self, _params: dict) -> dict:
        return {}

    def _rpc_job_wait(self, params: dict) -> dict:
        if params["job"] not in self._jobs:
            raise _RpcError(-32602, "invalid_params", f"Job not found: {params['job']}")
        return self._jobs[params["job"]]

    def _rpc_pack_open(self, params: dict) -> dict:
        path = Path(params["paths"][0])
        return self._summary(self._new_key(_OpenPack(path, dict(read_pack(path)))))

    def _rpc_pack_new(self, _params: dict) -> dict:
        return self._summary(self._new_key(_OpenPack(None)))

    def _rpc_pack_close(self, params: dict) -> dict:
        self._pack(params["pack"])
        self._packs.pop(params["pack"])
        return {}

    def _rpc_pack_save(self, params: dict) -> dict:
        pack = self._pack(params["pack"])
        if params.get("path"):
            pack.path = Path(params["path"])
        assert pack.path is not None, "pack.save without a path on a pack that was never saved"
        write_pack(pack.path, pack.files)
        return self._summary(params["pack"])

    def _rpc_files_list(self, params: dict) -> dict:
        prefix = params.get("path_prefix", "")
        paths = [p for p in sorted(self._pack(params["source"]["pack"]).files) if p.startswith(prefix)]
        offset, limit = params.get("offset", 0), params.get("limit") or 500
        page = paths[offset : offset + limit]
        return {
            "files": [{"path": p, "file_type": "DB" if p.startswith("db/") else "Text"} for p in page],
            "folders": [],
            "total": len(paths),
        }

    def _rpc_files_extract(self, params: dict) -> dict:
        pack = self._pack(params["source"]["pack"])
        extracted = []
        for container_path in params["paths"]:
            if container_path not in pack.files:
                raise _RpcError(-32002, "file_not_found", f"File not found: {container_path}")
            out = Path(params["destination"]) / container_path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(pack.files[container_path], encoding="utf-8")
            extracted.append(str(out))
        return {"extracted": extracted}

    def _rpc_files_add_from_disk(self, params: dict) -> dict:
        pack = self._pack(params["pack"])
        added = []
        for src, dest in zip(params["paths"], params["pack_paths"], strict=True):
            pack.files[dest] = Path(src).read_text(encoding="utf-8")
            added.append(dest)
        return {"added": added, "not_added": [], "error": None}

    def _rpc_files_delete(self, params: dict) -> dict:
        pack = self._pack(params["pack"])
        deleted = [p for p in params["paths"] if pack.files.pop(p, None) is not None]
        return {"deleted": deleted}

    def _rpc_table_export_tsv(self, params: dict) -> dict:
        file_ref = params["file"]
        pack = self._pack(file_ref["source"]["pack"])
        if file_ref["path"] not in pack.files:
            raise _RpcError(-32002, "file_not_found", f"File not found: {file_ref['path']}")
        out = Path(params["destination"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(pack.files[file_ref["path"]], encoding="utf-8")
        return {}

    def _rpc_table_import_tsv(self, params: dict) -> dict:
        pack = self._pack(params["pack"])
        if params["path"] not in pack.files:
            raise _RpcError(-32002, "file_not_found", f"Table not found in pack: {params['path']}")
        text = Path(params["tsv_path"]).read_text(encoding="utf-8")
        pack.files[params["path"]] = text
        return {"row_count": max(0, len(text.splitlines()) - 2)}

    # ------------------------------------------------------------------ legacy commands
    def _new_handle(self, pack: _OpenPack) -> str:
        handle = f"pack_{next(self._handles)}"
        self._packs[handle] = pack
        return handle

    def _save(self, pack: _OpenPack, path: Path) -> str:
        write_pack(path, pack.files)
        return "Success"

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
