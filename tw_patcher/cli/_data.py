"""Shared plumbing for the offline table commands (tables, show, find-key, diff,
conflicts, validate, new-patch)."""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any, NoReturn

import click

from ..config import settings
from ..console import console
from ..data.index import Mod, ModIndex, ModNotFoundError
from ..data.schema import Schema, SchemaNotFoundError, load_schema

json_option = click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON instead of text")


def fail(message: str) -> NoReturn:
    console.error(message)
    sys.exit(1)


def open_index() -> ModIndex:
    return ModIndex(settings.sources_dir, settings.workspace_dir)


def resolve(index: ModIndex, name: str, kind: str | None = None) -> Mod:
    try:
        return index.resolve(name, kind)
    except ModNotFoundError as e:
        fail(str(e))


def open_schema(quiet: bool = False) -> Schema | None:
    """The selected game's RPFM schema, or None (with a warning) when unavailable.
    Without it, rows are keyed by their whole content and references aren't checked."""
    if not settings.selected_game:
        if not quiet:
            console.warning("No game selected, so no schema: keys and references are unknown (use --game)")
        return None
    try:
        return load_schema(settings.selected_game, settings.schema_dir, settings.cache_dir)
    except SchemaNotFoundError as e:
        if not quiet:
            console.warning(f"{e} Continuing without key/reference information.")
        return None


def table_name(name: str, mods: list[Mod]) -> str:
    """Accept ``units_tables``, ``units`` or ``db/units_tables``; prefer what the mods actually contain."""
    name = name.strip("/").removeprefix("db/").split("/")[0]
    known = {t for m in mods for t in m.tables()}
    if name in known or not name:
        return name
    if f"{name}_tables" in known:
        return f"{name}_tables"
    return name if name.endswith("_tables") else f"{name}_tables"


def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value) if not f.name.startswith("_")
        }
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if hasattr(value, "__fspath__"):
        return str(value)
    return value


def emit_json(value: Any) -> None:
    console.plain(json.dumps(jsonable(value), indent=2, ensure_ascii=False))


def capped(items: list[Any], limit: int) -> tuple[list[Any], int]:
    """(first ``limit`` items, how many were left out); limit 0 means no cap."""
    if limit <= 0 or len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit
