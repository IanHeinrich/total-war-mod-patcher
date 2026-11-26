"""``tw-patcher mcp``: an MCP server (stdio) for LLM-driven patching.

It covers the layer RPFM doesn't: the multi-mod workspace on disk (extracted
sources and patch projects), cross-mod analysis in load order, safe row-level
edits to patches, and the extract/validate/repack lifecycle. Pack-level work
(decoding arbitrary files, schema edits, diagnostics inside one pack) is left to
RPFM 5's own MCP endpoint, which `tw-patcher scaffold` registers alongside this
one.

Every tool returns JSON-ready dicts with results capped by ``limit`` and a
``truncated`` flag, so a 30 MB table never lands in the model's context.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import socket
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .config import settings
from .constants import PORT_CHECK_TIMEOUT
from .data import queries
from .data.analysis import diff_mods, validate_patch
from .data.analysis import find_conflicts as analyze_conflicts
from .data.index import Mod, ModIndex
from .data.schema import Schema, SchemaNotFoundError, load_schema
from .exceptions import TWPatcherError

INSTRUCTIONS = """\
Tools for a Total War modding workspace managed by tw-patcher.

Layout: sources/<mod>/ holds tables extracted from mod packs (read-only reference);
workspace/<patch>/ holds patch mods you edit; output/ holds built packs.
Mods are named like "sources/sfo_grimhammer_3_main" or "workspace/my_patch"; a unique
trailing part ("sfo_grimhammer_3_main") also works.

Typical flow: workspace_status -> extract_packs (if needed) -> list_tables / describe_table /
query_rows / find_conflicts to understand the problem -> new_patch -> copy_rows / upsert_rows /
delete_rows / add_key_deletes -> validate_patch -> repack.

Never read or write the TSV files directly: use query_rows to read and the row tools to edit, which
keep RPFM's format intact. Composite primary keys are written "a|b". Results are capped; raise
`limit` or use `offset` to page.
"""

server = MCPServer(name="tw-patcher", version=__version__, instructions=INSTRUCTIONS)

# Problems the model can act on (unknown mod/table/column, bad edit, missing file, RPFM said no) go back as
# tool errors with their message. Anything else is a crash and stays a generic error with a server-side log.
_EXPECTED = (ValueError, LookupError, FileNotFoundError, TWPatcherError, ConnectionError, TimeoutError)


def tool(name: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``server.tool`` that turns expected failures into ToolError so the model sees the reason."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except _EXPECTED as e:
                    raise ToolError(str(e)) from e

            server.tool(name=name or fn.__name__)(async_wrapper)
        else:

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return fn(*args, **kwargs)
                except _EXPECTED as e:
                    raise ToolError(str(e)) from e

            server.tool(name=name or fn.__name__)(wrapper)
        return fn

    return register


# ---------------------------------------------------------------------------- helpers


def _index() -> ModIndex:
    # Fresh per call: the workspace changes underneath a long-running server.
    return ModIndex(settings.sources_dir, settings.workspace_dir)


def _schema() -> Schema | None:
    if not settings.selected_game:
        return None
    try:
        return load_schema(settings.selected_game, settings.schema_dir, settings.cache_dir)
    except (SchemaNotFoundError, ValueError):
        return None


def _mod(index: ModIndex, name: str, kind: str | None = None) -> Mod:
    return index.resolve(name, kind)


def _patch(index: ModIndex, name: str) -> Mod:
    """A patch in workspace/, by plain name; refuses anything that could escape it."""
    path = settings.get_patch_mod_path(name.removeprefix("workspace/"))
    if not path.is_dir():
        raise ValueError(f"No patch named {name!r} in {settings.workspace_dir}; create it with new_patch")
    return Mod(path.name, "patch", path)


def _cap(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    if limit <= 0 or len(items) <= limit:
        return items, False
    return items[:limit], True


def _rpfm_listening() -> bool:
    try:
        with socket.create_connection((settings.rpfm_host, settings.rpfm_port), timeout=PORT_CHECK_TIMEOUT):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------- read tools


@tool()
def workspace_status() -> dict[str, Any]:
    """Selected game, folders, schema availability, RPFM reachability and every extracted mod / patch."""
    schema = _schema()
    return {
        "tw_patcher_version": __version__,
        "game": settings.selected_game,
        "sources_dir": str(settings.sources_dir),
        "workspace_dir": str(settings.workspace_dir),
        "output_dir": str(settings.output_dir),
        "schema": str(schema.source) if schema else None,
        "rpfm_listening": _rpfm_listening(),
        "mods": queries.list_mods(_index()),
    }


@tool()
def list_tables(mod: str) -> dict[str, Any]:
    """Tables of one extracted mod or patch, with each fragment's table version and row count."""
    target = _mod(_index(), mod)
    return {"mod": target.qualified, "tables": queries.list_tables(target)}


@tool()
def describe_table(table: str, mod: str | None = None) -> dict[str, Any]:
    """Columns, types, primary key and references of TABLE from the game schema (all versions known),
    plus the version and header a given mod uses. TABLE may be "land_units" or "land_units_tables"."""
    index = _index()
    target = _mod(index, mod) if mod else None
    schema = _schema()
    name = queries.resolve_table(table, [target] if target else index.mods, schema)
    return queries.describe_table(name, schema, target)


@tool()
def query_rows(
    table: str,
    mod: str,
    keys: list[str] | None = None,
    where: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Rows of TABLE from MOD as the game merges its fragments. Filter by primary keys ("a|b" for composite),
    exact column values (where={"col": "value"}), and pick columns. Paged by limit/offset."""
    index = _index()
    target = _mod(index, mod)
    schema = _schema()
    name = queries.resolve_table(table, [target], schema)
    return queries.query_rows(target, name, schema, keys, where, columns, limit, offset)


@tool()
def find_key(key: str, tables: list[str] | None = None) -> dict[str, Any]:
    """Every extracted mod and patch that defines KEY ("a|b" for composite), per table in merge order
    (the first entry is the row the game uses). Pass tables=[...] to make it fast."""
    index = _index()
    schema = _schema()
    names = [queries.resolve_table(t, index.mods, schema) for t in tables] if tables else None
    return queries.find_key(index, key, names, schema)


@tool()
def diff(
    mod_a: str, mod_b: str, tables: list[str] | None = None, shared: bool = False, limit: int = 50
) -> dict[str, Any]:
    """Row differences from MOD_A to MOD_B keyed by primary key: added, removed, changed (column old -> new).
    shared=True compares only tables both contain (e.g. a patch against the mod it patches)."""
    index = _index()
    a, b = _mod(index, mod_a), _mod(index, mod_b)
    schema = _schema()
    names = [queries.resolve_table(t, [a, b], schema) for t in tables] if tables else None
    if shared:
        names = [t for t in (names or a.tables()) if t in set(a.tables()) and t in set(b.tables())]
    out = []
    for d in diff_mods(a, b, schema, names):
        entry: dict[str, Any] = {"table": d.table, "key_columns": d.key_columns, "only_in": d.only_in}
        for kind in ("added", "removed", "changed"):
            items = getattr(d, kind)
            shown, truncated = _cap(items, limit)
            if kind == "changed":
                shown = [{"key": c.key, "changes": [vars(x) for x in c.changes]} for c in shown]
            entry[kind] = shown
            entry[f"{kind}_total"] = len(items)
            entry[f"{kind}_truncated"] = truncated
        out.append(entry)
    return {"a": a.qualified, "b": b.qualified, "tables": out}


@tool()
def find_conflicts(
    mods: list[str], context: list[str] | None = None, check_references: bool = True, limit: int = 100
) -> dict[str, Any]:
    """Where MODS (load order, first wins) step on each other: whole-file overrides, primary keys defined by
    several mods (with the winner and differing columns), references to keys none of them define, and
    twad_key_deletes rows that remove something still referenced (a load crash) or match nothing.
    context=[...] adds mods (e.g. an extracted vanilla db) used only to resolve references."""
    index = _index()
    selected = [_mod(index, m) for m in mods]
    extra = [_mod(index, m) for m in context or []]
    report = analyze_conflicts(selected, _schema(), check_references=check_references, context=extra)
    collisions = [vars(c) for c in report.collisions if not c.identical]
    dangling = [vars(d) for d in report.dangling]
    shown_c, trunc_c = _cap(collisions, limit)
    shown_d, trunc_d = _cap(dangling, limit)
    return {
        "load_order": [m.qualified for m in selected],
        "overrides": [vars(o) for o in report.overrides],
        "collisions_total": len(report.collisions),
        "collisions_differing_total": len(collisions),
        "collisions": shown_c,
        "collisions_truncated": trunc_c,
        "dangling_total": len(dangling),
        "dangling": shown_d,
        "dangling_truncated": trunc_d,
        "unchecked_reference_targets": report.unchecked_targets,
        "broken_by_deletes_total": len(report.broken_by_deletes),
        "broken_by_deletes": [vars(b) for b in _cap(report.broken_by_deletes, limit)[0]],
        "deletes_without_match": [vars(u) for u in report.deletes_without_match],
    }


@tool(name="validate_patch")
def validate_patch_tool(patch: str, against: list[str] | None = None) -> dict[str, Any]:
    """Pre-repack checks for a patch: metadata lines, schema versions, columns, cell counts, value types,
    duplicate keys (errors) and unresolved references (warnings). against=[...] limits the sources used."""
    index = _index()
    target = _patch(index, patch)
    sources = [_mod(index, m) for m in against] if against else index.sources
    schema = _schema()
    issues = validate_patch(target, schema, sources)
    errors = sum(1 for i in issues if i.level == "error")
    return {
        "patch": target.qualified,
        "schema": str(schema.source) if schema else None,
        "errors": errors,
        "warnings": len(issues) - errors,
        "issues": [vars(i) for i in issues],
    }


# ---------------------------------------------------------------------------- patch editing tools


@tool()
def new_patch(name: str, from_mod: str | None = None, tables: list[str] | None = None) -> dict[str, Any]:
    """Create workspace/NAME/db/, optionally copying whole tables (all fragments, byte for byte) from an
    extracted mod. Use copy_rows instead to take only some rows."""
    settings.ensure_dirs()
    path = settings.get_patch_mod_path(name)
    source = _mod(_index(), from_mod, kind="source") if from_mod else None
    copied = queries.create_patch(path, source, tables)
    return {"patch": f"workspace/{name}", "path": str(path), "copied": copied}


@tool()
def upsert_rows(patch: str, table: str, rows: list[dict[str, str]], fragment: str | None = None) -> dict[str, Any]:
    """Insert rows into PATCH's TABLE, or update the row with the same primary key (unlisted columns of an
    updated row keep their values). Creates the table file from the schema if the patch lacks it.
    Each row is {"column": "value"}; key columns are required."""
    index = _index()
    target = _patch(index, patch)
    schema = _schema()
    name = queries.resolve_table(table, [target], schema)
    return queries.upsert_rows(target, name, rows, schema, fragment).as_dict()


@tool()
def delete_rows(patch: str, table: str, keys: list[str]) -> dict[str, Any]:
    """Remove rows (by primary key, "a|b" for composite) from PATCH's TABLE. This only edits the patch;
    to delete rows of another mod or vanilla at load time use add_key_deletes."""
    index = _index()
    target = _patch(index, patch)
    schema = _schema()
    name = queries.resolve_table(table, [target], schema)
    return {"files": [r.as_dict() for r in queries.delete_rows(target, name, keys, schema)]}


@tool()
def copy_rows(
    source: str, patch: str, table: str, keys: list[str] | None = None, fragment: str | None = None
) -> dict[str, Any]:
    """Copy rows of TABLE from an extracted SOURCE mod into PATCH (all rows if keys is omitted), creating the
    table file with the source's version and header if needed, then edit them with upsert_rows."""
    index = _index()
    src = _mod(index, source, kind="source")
    target = _patch(index, patch)
    schema = _schema()
    name = queries.resolve_table(table, [src], schema)
    return queries.copy_rows(src, target, name, keys, schema, fragment).as_dict()


@tool()
def add_key_deletes(patch: str, table: str, keys: list[str]) -> dict[str, Any]:
    """Make the game delete rows of another mod's or vanilla's TABLE at load (Warhammer 3 6.3+,
    twad_key_deletes_tables). Check first that nothing else references those keys: a deleted row that is
    still referenced crashes the game on load."""
    index = _index()
    target = _patch(index, patch)
    schema = _schema()
    name = queries.resolve_table(table, index.mods, schema)
    return queries.add_key_deletes(target, name, keys, schema).as_dict()


# ---------------------------------------------------------------------------- RPFM-backed tools


async def _with_client(action):
    from .clients.rpfm import RPFMClient
    from .services.system import SystemService

    client = RPFMClient(settings.rpfm_host, settings.rpfm_port, settings.rpfm_timeout)
    await SystemService(settings).connect_client(client)
    try:
        return await action(client)
    finally:
        await client.disconnect()


@tool()
async def rpfm_status() -> dict[str, Any]:
    """Connect to RPFM (starting rpfm_server if needed) and report its protocol and version. On RPFM 5 its own
    MCP endpoint (for pack-level work) is at mcp_url."""

    async def run(client):
        return {
            "protocol": client.protocol,
            "server_version": client.server_version,
            "mcp_url": f"http://{settings.rpfm_host}:{settings.rpfm_port}/mcp"
            if client.protocol == "jsonrpc"
            else None,
        }

    return await _with_client(run)


@tool()
async def extract_packs(
    packs: list[str] | None = None,
    workshop_ids: list[str] | None = None,
    vanilla: bool = False,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Extract mods into sources/<mod>/: db tables and text/*.loc as TSV, scripts as files. Give .pack paths
    (absolute) and/or Steam Workshop item IDs (up to 6 packs in total). vanilla=True also extracts the game's
    data/db.pack into sources/vanilla/ (needed to check references against the base game; use tables=[...]
    to export only some tables, it has ~1600). Replaces a previous extraction of the same pack."""
    from pathlib import Path

    from .services.extraction import ExtractionService, vanilla_pack_path, workshop_pack_paths

    paths = [Path(p) for p in packs or []]
    for p in paths:
        if not p.is_file():
            raise ValueError(f"Not a file: {p}")
    paths += workshop_pack_paths(settings, list(workshop_ids or []))
    vanilla_pack = vanilla_pack_path(settings) if vanilla else None
    if not paths and not vanilla_pack:
        raise ValueError("Give packs, workshop_ids or vanilla=True")
    settings.ensure_dirs()
    results = await _with_client(
        lambda c: ExtractionService(settings, c).extract_batch(
            paths, settings.sources_dir, tables or None, vanilla_pack
        )
    )
    return {
        "mods": [
            {
                "mod": f"sources/{r.mod_name}",
                "tables": len(r.tables_exported),
                "scripts": len(r.scripts_extracted),
                "locs": len(r.locs_exported),
                "failed": [{"path": p, "error": e} for p, e in r.failures],
            }
            for r in results
        ]
    }


@tool()
async def repack(
    patch: str, name: str | None = None, validate: bool = True, allow_partial: bool = False
) -> dict[str, Any]:
    """Build output/<name or patch>.pack from workspace/<patch>. Runs validate_patch first and refuses on errors
    (validate=False skips it). A pack with failed imports isn't saved unless allow_partial."""
    from .exceptions import RepackError
    from .services.repacking import RepackingService

    index = _index()
    target = _patch(index, patch)
    if validate:
        report = validate_patch_tool(target.name)
        if report["errors"]:
            return {"saved": False, "reason": "validation errors", "validation": report}
    settings.ensure_dirs()
    output = settings.output_dir / f"{name or target.name}.pack"
    try:
        result = await _with_client(
            lambda c: RepackingService(settings, c).repack(target.name, output, name, allow_partial=allow_partial)
        )
    except RepackError as e:
        return {"saved": False, "reason": str(e), "failed": [{"path": p, "error": m} for p, m in e.failed_tables]}
    return {
        "saved": True,
        "output": str(result.output_path),
        "tables": len(result.tables_imported),
        "scripts": len(result.scripts_imported),
        "failed": [{"path": p, "error": m} for p, m in result.failures],
    }


def run() -> None:
    asyncio.run(server.run_stdio_async())
