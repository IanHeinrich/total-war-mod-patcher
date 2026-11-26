"""Offline access to RPFM's DB table schemas (``schema_<game>.ron``).

The schema tells, for every DB table and table version, which columns it has, their types, which
columns form the key and which columns reference another table. RPFM keeps these files in its
config folder; :func:`load_schema` finds, parses and (optionally) caches them.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ron

TABLE_SUFFIX = "_tables"
SCHEMA_DIR_ENV = "TW_PATCHER_SCHEMA_DIR"
_CACHE_FORMAT = 2  # 2: fields carry their colour group

SCHEMA_FILES: dict[str, str] = {
    "pharaoh_dynasties": "schema_ph_dyn.ron",
    "pharaoh": "schema_ph.ron",
    "warhammer_3": "schema_wh3.ron",
    "troy": "schema_troy.ron",
    "three_kingdoms": "schema_3k.ron",
    "warhammer_2": "schema_wh2.ron",
    "warhammer": "schema_wh.ron",
    "thrones_of_britannia": "schema_tob.ron",
    "attila": "schema_att.ron",
    "rome_2": "schema_rom2.ron",
    "shogun_2": "schema_sho2.ron",
    "napoleon": "schema_nap.ron",
    "empire": "schema_emp.ron",
    "arena": "schema_are.ron",
}


@dataclass(frozen=True)
class Field:
    name: str
    field_type: str
    is_key: bool
    reference: tuple[str, str] | None
    # RPFM merges the r/g/b fields of one colour group into a single hex column in TSV exports
    colour_group: int | None = None


@dataclass(frozen=True)
class TableDefinition:
    table: str
    version: int
    fields: tuple[Field, ...]

    @property
    def key_columns(self) -> list[str]:
        return [f.name for f in self.fields if f.is_key]

    def field(self, name: str) -> Field | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def tsv_columns(self) -> list[tuple[str, str]]:
        """(column name, type) as RPFM writes them in a TSV export.

        Fields of one colour group (``x_r``, ``x_g``, ``x_b``) become a single
        ``x_hex`` column of type ``ColourHex`` holding ``RRGGBB``; groups with no
        common name prefix become ``unnamed colour group_<n>``.
        """
        columns: list[tuple[str, str]] = []
        done: set[int] = set()
        for f in self.fields:
            group = f.colour_group
            if group is None:
                columns.append((f.name, f.field_type))
                continue
            if group in done:
                continue
            done.add(group)
            names = [g.name for g in self.fields if g.colour_group == group]
            prefix = os.path.commonprefix(names)
            columns.append((f"{prefix}hex" if prefix else f"unnamed colour group_{group}", "ColourHex"))
        return columns


class SchemaNotFoundError(Exception):
    """No RPFM schema file for the requested game could be found."""


def full_table_name(table: str) -> str:
    return table if table.endswith(TABLE_SUFFIX) else table + TABLE_SUFFIX


class Schema:
    def __init__(self, game: str, source: Path, definitions: dict[str, dict[int, TableDefinition]]):
        self.game = game
        self.source = source
        self._definitions = definitions
        self._references: dict[str, list[tuple[str, str, str]]] | None = None

    def tables(self) -> list[str]:
        return sorted(self._definitions)

    def versions(self, table: str) -> list[int]:
        return sorted(self._definitions.get(full_table_name(table), {}))

    def definition(self, table: str, version: int | None = None) -> TableDefinition | None:
        by_version = self._definitions.get(full_table_name(table))
        if not by_version:
            return None
        if version is None:
            version = max(by_version)
        return by_version.get(version)

    def references_to(self, table: str) -> list[tuple[str, str, str]]:
        if self._references is None:
            index: dict[str, list[tuple[str, str, str]]] = {}
            for name in self.tables():
                latest = self.definition(name)
                if latest is None:
                    continue
                for f in latest.fields:
                    if f.reference is not None:
                        target, target_column = f.reference
                        index.setdefault(target, []).append((name, f.name, target_column))
            self._references = index
        return list(self._references.get(full_table_name(table), []))


def default_schema_dirs() -> list[Path]:
    override = os.environ.get(SCHEMA_DIR_ENV)
    if override:
        # An explicit override is the only place to look (no silent fallback to RPFM's folder)
        return [Path(override)]
    dirs: list[Path] = []
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        dirs.append(base / "FrodoWazEre" / "rpfm" / "config" / "schemas")
    elif sys.platform == "darwin":
        dirs.append(home / "Library" / "Application Support" / "com.FrodoWazEre.rpfm" / "schemas")
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        dirs.append(config_home / "rpfm" / "schemas")
        dirs.append(data_home / "rpfm" / "schemas")
    unique: list[Path] = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


def load_schema(game: str, schema_dir: Path | None = None, cache_dir: Path | None = None) -> Schema:
    file_name = SCHEMA_FILES.get(game)
    if file_name is None:
        raise ValueError(f"Unknown game key: '{game}'. Valid keys: {', '.join(SCHEMA_FILES)}")
    search = [schema_dir] if schema_dir is not None else default_schema_dirs()
    source = next((d / file_name for d in search if (d / file_name).is_file()), None)
    if source is None:
        searched = ", ".join(str(d) for d in search) or "(no folders)"
        raise SchemaNotFoundError(
            f"RPFM schema for {game} not found: expected {file_name} in {searched}. "
            f"Install RPFM and open it once (or update its schemas) so it downloads {file_name}, "
            f"or set {SCHEMA_DIR_ENV} to a folder containing it."
        )

    stat = source.stat()
    stamp = {"source": str(source.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    cache_file = _cache_file(cache_dir, source) if cache_dir is not None else None

    definitions = _read_cache(cache_file, stamp) if cache_file is not None else None
    if definitions is None:
        compact = _compact_definitions(ron.loads(source.read_text(encoding="utf-8-sig")), source)
        if cache_file is not None:
            _write_cache(cache_file, stamp, compact)
        definitions = _build_definitions(compact)
    return Schema(game, source, definitions)


# Compact form, shared by the parser and the cache:
#   {table: [[version, [[name, field_type, is_key, ref_table | None, ref_column | None], ...]], ...]}
_Compact = dict[str, list[list[Any]]]


def _compact_definitions(data: Any, source: Path) -> _Compact:
    definitions = data.get("definitions") if isinstance(data, dict) else None
    if not isinstance(definitions, dict):
        raise ValueError(f"{source} is not an RPFM schema: no 'definitions' map")
    patches = data.get("patches")
    if not isinstance(patches, dict):
        patches = {}

    compact: _Compact = {}
    try:
        for table, versions in definitions.items():
            table_patches = patches.get(table)
            if not isinstance(table_patches, dict):
                table_patches = {}
            entries: list[list[Any]] = []
            for definition in versions:
                fields = [_compact_field(f, table_patches.get(f["name"])) for f in definition["fields"]]
                entries.append([int(definition["version"]), fields])
            compact[str(table)] = entries
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"{source} is not a valid RPFM schema: {exc!r}") from exc
    return compact


def _compact_field(f: dict[str, Any], patch: Any) -> list[Any]:
    field_type = f["field_type"]
    if isinstance(field_type, dict):  # e.g. {"SequenceU32": <nested definition>}
        field_type = next(iter(field_type))
    is_key = bool(f.get("is_key"))
    reference = f.get("is_reference")
    ref_table, ref_column = (full_table_name(reference[0]), reference[1]) if reference else (None, None)

    # The schema's own patches section overrides fields the same way RPFM applies it.
    if isinstance(patch, dict):
        if "is_key" in patch:
            is_key = str(patch["is_key"]).strip().lower() == "true"
        if "is_reference" in patch:
            parts = str(patch["is_reference"]).split(";")
            if len(parts) == 2 and all(parts):
                ref_table, ref_column = full_table_name(parts[0]), parts[1]
            elif not patch["is_reference"]:
                ref_table, ref_column = None, None
    colour = f.get("is_part_of_colour")
    return [f["name"], str(field_type), is_key, ref_table, ref_column, colour if isinstance(colour, int) else None]


def _build_definitions(compact: _Compact) -> dict[str, dict[int, TableDefinition]]:
    definitions: dict[str, dict[int, TableDefinition]] = {}
    for table, entries in compact.items():
        by_version: dict[int, TableDefinition] = {}
        for version, fields in entries:
            by_version[version] = TableDefinition(
                table=table,
                version=version,
                fields=tuple(
                    Field(name, field_type, is_key, (ref_table, ref_column) if ref_table is not None else None, colour)
                    for name, field_type, is_key, ref_table, ref_column, colour in fields
                ),
            )
        definitions[table] = by_version
    return definitions


def _cache_file(cache_dir: Path, source: Path) -> Path:
    digest = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"{source.stem}-{digest}.json"


def _read_cache(cache_file: Path, stamp: dict[str, Any]) -> dict[str, dict[int, TableDefinition]] | None:
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        if payload.get("format") != _CACHE_FORMAT or payload.get("stamp") != stamp:
            return None
        return _build_definitions(payload["definitions"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _write_cache(cache_file: Path, stamp: dict[str, Any], compact: _Compact) -> None:
    payload = {"format": _CACHE_FORMAT, "stamp": stamp, "definitions": compact}
    tmp = cache_file.with_name(cache_file.name + ".tmp")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, cache_file)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
