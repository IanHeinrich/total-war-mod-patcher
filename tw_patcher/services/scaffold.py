"""``tw-patcher scaffold``: set up a modding folder for people and LLMs.

Creates ``sources/``, ``workspace/``, ``output/``, background docs, AI instruction
files (CLAUDE.md, Copilot, Cursor) and a ``.mcp.json`` registering tw-patcher's
MCP server (and RPFM 5's, when one is running).

Generated files start with a marker line. ``update=True`` refreshes files that
still carry it and leaves the rest alone: deleting the marker line is how a user
says "this file is mine now". ``force=True`` overwrites regardless.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from . import scaffold_templates as t

MARKER_PREFIX = "<!-- tw-patcher:generated"
MCP_FILE = ".mcp.json"


def marker() -> str:
    return (
        f"{MARKER_PREFIX} {__version__}: `tw-patcher scaffold --update` refreshes this file while this line is "
        "here. Delete the line to keep your own edits. -->"
    )


def _files() -> dict[str, str]:
    m = marker()
    core = t.AI_CORE.format(marker=m)
    return {
        "modding_docs/README.md": t.DOCS_README.format(marker=m),
        "modding_docs/WORKFLOW.md": t.DOCS_WORKFLOW.format(marker=m),
        "modding_docs/TSV_FORMAT.md": t.DOCS_TSV_FORMAT.format(marker=m),
        "modding_docs/SCHEMA_BASICS.md": t.DOCS_SCHEMA_BASICS.format(marker=m),
        "CLAUDE.md": core,
        ".github/copilot-instructions.md": core,
        ".cursorrules": core,
    }


@dataclass
class ScaffoldResult:
    created: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)  # user-owned (no marker), left alone on --update
    mcp_servers: list[str] = field(default_factory=list)  # entries tw-patcher wrote into .mcp.json
    rpfm_mcp_url: str | None = None


def tw_patcher_command() -> dict[str, object]:
    """How an MCP client should launch *this* tw-patcher: the frozen executable for installer builds,
    otherwise the interpreter running now. (Not whatever `tw-patcher` is first on PATH, which may be an
    older install without the MCP server.)"""
    if getattr(sys, "frozen", False):
        return {"command": sys.executable, "args": ["mcp"]}
    return {"command": sys.executable, "args": ["-m", "tw_patcher", "mcp"]}


def probe_rpfm_mcp(host: str, port: int, timeout: float = 1.0) -> str | None:
    """RPFM 5's MCP URL if an RPFM 5 server answers on host:port, else None. (RPFM 4 has no HTTP endpoints.)"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/version", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and str(data.get("version", "")).split(".")[0].isdigit():
        if int(str(data["version"]).split(".")[0]) >= 5:
            return f"http://{host}:{port}/mcp"
    return None


class ScaffoldService:
    def __init__(self, target: Path):
        self._target = target

    def scaffold(self, update: bool = False, force: bool = False, rpfm_mcp_url: str | None = None) -> ScaffoldResult:
        result = ScaffoldResult(rpfm_mcp_url=rpfm_mcp_url)
        for name in ("sources", "workspace", "output", "modding_docs"):
            (self._target / name).mkdir(parents=True, exist_ok=True)
        for rel_path, content in _files().items():
            self._write(rel_path, content, update, force, result)
        self._write_mcp_json(rpfm_mcp_url, result)
        return result

    def _write(self, rel_path: str, content: str, update: bool, force: bool, result: ScaffoldResult) -> None:
        path = self._target / rel_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            result.created.append(path)
            return
        if not (update or force):
            return
        current = path.read_text(encoding="utf-8", errors="replace")
        if not force and not current.startswith(MARKER_PREFIX):
            result.kept.append(path)
            return
        if current != content:
            path.write_text(content, encoding="utf-8", newline="\n")
            result.updated.append(path)

    def _write_mcp_json(self, rpfm_mcp_url: str | None, result: ScaffoldResult) -> None:
        path = self._target / MCP_FILE
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result.kept.append(path)  # not valid JSON: someone else's file, don't touch it
                return
        servers = data.setdefault("mcpServers", {})
        before = json.dumps(data, sort_keys=True)
        servers["tw-patcher"] = {"type": "stdio", **tw_patcher_command()}
        result.mcp_servers.append("tw-patcher")
        if rpfm_mcp_url:
            servers["rpfm"] = {"type": "http", "url": rpfm_mcp_url}
            result.mcp_servers.append("rpfm")
        if json.dumps(data, sort_keys=True) == before and path.exists():
            return
        existed = path.exists()
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        (result.updated if existed else result.created).append(path)
