"""Read queries and safe patch edits shared by the CLI and the MCP server.

Everything returns plain dicts/lists (JSON-ready). Reads work on any extracted
mod or patch; writes only ever touch ``workspace/<patch>`` and go through
:class:`~tw_patcher.data.tsv.TableFile`, so tabs, column order, the metadata
line and line endings can't be corrupted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis import key_columns, merge_rows, row_key
from .index import Fragment, Mod, ModIndex
from .schema import Schema
from .tsv import Metadata, TableFile

KEY_DELETES_TABLE = "twad_key_deletes_tables"


class QueryError(ValueError):
    """A request that can't be served as asked (unknown table/column, bad edit, ...)."""


def resolve_table(name: str, mods: list[Mod], schema: Schema | None = None) -> str:
    """Accept ``units_tables``, ``units`` or ``db/units_tables``; prefer what the mods (or schema) contain."""
    name = name.strip("/").removeprefix("db/").split("/")[0]
    known = {t for m in mods for t in m.tables()} | (set(schema.tables()) if schema else set())
    if name in known or not name:
        return name
    if f"{name}_tables" in known:
        return f"{name}_tables"
    return name if name.endswith("_tables") else f"{name}_tables"


def table_list(mod: Mod, limit: int = 20) -> str:
    """Short list of a mod's tables for error messages (a vanilla extraction has ~1600)."""
    tables = mod.tables()
    if not tables:
        return "(none)"
    shown = ", ".join(tables[:limit])
    return shown if len(tables) <= limit else f"{shown}, ... ({len(tables)} in total; see list_tables)"


def join_key(key: tuple[str, ...] | list[str]) -> str:
    return "|".join(key)


# ---------------------------------------------------------------------------- reads


def list_mods(index: ModIndex) -> list[dict[str, Any]]:
    return [{"name": m.qualified, "kind": m.kind, "tables": len(m.tables())} for m in index.mods]


def list_tables(mod: Mod) -> list[dict[str, Any]]:
    out = []
    for table, fragments in mod.fragments.items():
        for frag in fragments:
            try:
                tf = frag.load()
                count, version = len(tf.rows), tf.version
            except Exception:
                count, version = -1, None
            out.append({"table": table, "fragment": frag.name, "version": version, "rows": count})
    return out


def describe_table(table: str, schema: Schema | None, mod: Mod | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {"table": table, "schema": None, "in_mod": None}
    definition = schema.definition(table) if schema else None
    if schema and definition:
        info["schema"] = {
            "versions": schema.versions(table),
            "latest_version": definition.version,
            "key_columns": definition.key_columns,
            "columns": [
                {
                    "name": f.name,
                    "type": f.field_type,
                    "key": f.is_key,
                    "references": f"{f.reference[0]}.{f.reference[1]}" if f.reference else None,
                }
                for f in definition.fields
            ],
            "tsv_columns": [name for name, _ in definition.tsv_columns()],
            "referenced_by": [f"{t}.{c}" for t, c, _ in schema.references_to(table)][:50],
        }
    if mod and mod.fragments.get(table):
        frags = mod.fragments[table]
        first = frags[0].load()
        info["in_mod"] = {
            "mod": mod.qualified,
            "fragments": [f.name for f in frags],
            "version": first.version,
            "header": first.header,
        }
    return info


def query_rows(
    mod: Mod,
    table: str,
    schema: Schema | None,
    keys: list[str] | None = None,
    where: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    fragments = mod.fragments.get(table)
    if not fragments:
        raise QueryError(f"{mod.qualified} has no {table}. Tables: {table_list(mod)}")
    merged = merge_rows(fragments, schema)
    sample = next(iter(merged.values()))[0].table_file if merged else fragments[0].load()
    header = sample.header
    wanted = columns or header
    for name in [*wanted, *(where or {})]:
        if name not in header:
            raise QueryError(f"No column {name!r} in {table}. Columns: {', '.join(header)}")
    selected = []
    for key, refs in merged.items():
        if keys and join_key(key) not in keys:
            continue
        values = refs[0].as_dict()
        if all(values.get(c) == v for c, v in (where or {}).items()):
            selected.append({"key": list(key), "from": refs[0].fragment.name, "values": {c: values[c] for c in wanted}})
    page = selected[offset : offset + limit] if limit > 0 else selected[offset:]
    return {
        "mod": mod.qualified,
        "table": table,
        "key_columns": key_columns(schema, sample),
        "columns": wanted,
        "total": len(selected),
        "offset": offset,
        "truncated": offset + len(page) < len(selected),
        "rows": page,
    }


def find_key(index: ModIndex, key: str, tables: list[str] | None, schema: Schema | None) -> dict[str, Any]:
    mods = index.mods
    wanted = tables or sorted({t for m in mods for t in m.tables()})
    hits: dict[str, list[dict[str, str]]] = {}
    for table in wanted:
        fragments = sorted(
            (f for m in mods for f in m.fragments.get(table, [])), key=lambda f: (f.name.encode("utf-8"), f.mod.name)
        )
        for frag in fragments:
            try:
                tf = frag.load()
            except Exception:
                continue
            cols = key_columns(schema, tf)
            for row in tf.rows:
                k = row_key(tf, row, cols) if cols else (row[0],)
                if join_key(k) == key:
                    hits.setdefault(table, []).append(
                        {"mod": frag.mod.qualified, "fragment": frag.name, "path": str(frag.path)}
                    )
    return {"key": key, "tables": hits}


# ---------------------------------------------------------------------------- patch edits


def create_patch(patch_dir: Path, source: Mod | None = None, tables: list[str] | None = None) -> list[str]:
    """Create ``patch_dir/db/`` and copy every fragment of ``tables`` from ``source`` byte for byte.
    Checks everything before writing anything. Returns the copied pack paths (``db/<table>/<file>.tsv``)."""
    import shutil

    if tables and source is None:
        raise QueryError("Copying tables needs a source mod to copy from")
    if source is not None and not tables:
        raise QueryError("Name at least one table to copy from the source")
    if patch_dir.exists() and any(patch_dir.iterdir()):
        raise QueryError(f"{patch_dir} already exists and is not empty")
    plan: list[Fragment] = []
    for t in tables or []:
        assert source is not None
        table = resolve_table(t, [source])
        frags = source.fragments.get(table)
        if not frags:
            raise QueryError(f"{source.qualified} has no {table}. Tables: {table_list(source)}")
        plan.extend(frags)
    copied = []
    for frag in plan:
        target = patch_dir / "db" / frag.table / frag.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frag.path, target)
        copied.append(f"db/{frag.table}/{frag.path.name}")
    (patch_dir / "db").mkdir(parents=True, exist_ok=True)
    return copied


@dataclass
class EditResult:
    file: str
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "inserted": self.inserted,
            "updated": self.updated,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
        }


def _patch_fragment(patch: Mod, table: str, fragment: str | None) -> Fragment | None:
    frags = patch.fragments.get(table, [])
    if fragment:
        return next((f for f in frags if f.name == fragment), None)
    if len(frags) > 1:
        names = ", ".join(f.name for f in frags)
        raise QueryError(f"{patch.qualified} has several {table} fragments ({names}); say which one with fragment=")
    return frags[0] if frags else None


def _new_table_file(
    patch: Mod, table: str, fragment: str, schema: Schema | None, template: TableFile | None
) -> TableFile:
    path = patch.root / "db" / table / f"{fragment}.tsv"
    pack_path = f"db/{table}/{fragment}"
    if template is not None:
        tf = TableFile.new(table, template.version, pack_path, template.header)
        tf.newline, tf.bom = template.newline, template.bom
    else:
        definition = schema.definition(table) if schema else None
        if not definition:
            raise QueryError(
                f"Can't create {table} in {patch.qualified}: it isn't in the patch and the schema doesn't define it. "
                "Copy it from a source first (copy_rows / new-patch --from)."
            )
        tf = TableFile.new(table, definition.version, pack_path, [name for name, _ in definition.tsv_columns()])
    tf.path = path
    return tf


def _load_or_create(
    patch: Mod, table: str, fragment: str | None, schema: Schema | None, template: TableFile | None = None
) -> TableFile:
    frag = _patch_fragment(patch, table, fragment)
    if frag:
        return TableFile.read(frag.path)
    return _new_table_file(patch, table, fragment or patch.name, schema, template)


def upsert_rows(
    patch: Mod,
    table: str,
    rows: list[dict[str, str]],
    schema: Schema | None,
    fragment: str | None = None,
    template: TableFile | None = None,
) -> EditResult:
    """Insert rows, or replace the row with the same primary key. Unlisted columns of an
    updated row keep their values; of a new row they are left empty."""
    if not rows:
        raise QueryError("No rows given")
    tf = _load_or_create(patch, table, fragment, schema, template)
    cols = key_columns(schema, tf)
    if not cols:
        raise QueryError(f"Primary key of {table} v{tf.version} is unknown (no schema), so rows can't be matched")
    index = {row_key(tf, r, cols): i for i, r in enumerate(tf.rows)}
    result = EditResult(file=_rel(patch, tf))
    for values in rows:
        values = {k: "" if v is None else str(v) for k, v in values.items()}
        unknown = set(values) - set(tf.header)
        if unknown:
            raise QueryError(
                f"Unknown column(s) for {table}: {', '.join(sorted(unknown))}. Columns: {', '.join(tf.header)}"
            )
        missing = [c for c in cols if c not in values]
        if missing:
            raise QueryError(f"Row is missing key column(s) {', '.join(missing)}: {values}")
        for v in values.values():
            if "\t" in v or "\n" in v or "\r" in v:
                raise QueryError(f"Values can't contain tabs or line breaks: {v!r}")
        key = tuple(values[c] for c in cols)
        if key in index:
            current = tf.as_dict(tf.rows[index[key]])
            merged = {**current, **values}
            if merged == current:
                result.unchanged += 1
                continue
            tf.rows[index[key]] = tf.from_dict(merged)
            result.updated += 1
        else:
            index[key] = len(tf.rows)
            tf.rows.append(tf.from_dict(values))
            result.inserted += 1
    tf.write()
    return result


def delete_rows(patch: Mod, table: str, keys: list[str], schema: Schema | None) -> list[EditResult]:
    """Remove rows (by ``a|b`` primary key) from every fragment of ``table`` in the patch."""
    frags = patch.fragments.get(table)
    if not frags:
        raise QueryError(f"{patch.qualified} has no {table}")
    wanted = set(keys)
    results = []
    for frag in frags:
        tf = TableFile.read(frag.path)
        cols = key_columns(schema, tf)
        if not cols:
            raise QueryError(f"Primary key of {table} v{tf.version} is unknown (no schema), so rows can't be matched")
        before = len(tf.rows)
        tf.rows = [r for r in tf.rows if join_key(row_key(tf, r, cols)) not in wanted]
        if len(tf.rows) != before:
            tf.write()
        results.append(EditResult(file=_rel(patch, tf), deleted=before - len(tf.rows)))
    return results


def copy_rows(
    source: Mod, patch: Mod, table: str, keys: list[str] | None, schema: Schema | None, fragment: str | None = None
) -> EditResult:
    """Copy the winning rows for ``keys`` (all rows if None) of ``source``'s table into the patch."""
    fragments = source.fragments.get(table)
    if not fragments:
        raise QueryError(f"{source.qualified} has no {table}")
    merged = merge_rows(fragments, schema)
    wanted = set(keys) if keys else None
    picked = [refs[0] for k, refs in merged.items() if wanted is None or join_key(k) in wanted]
    if wanted is not None:
        found = {join_key(row_key(r.table_file, r.row, key_columns(schema, r.table_file))) for r in picked}
        missing = sorted(wanted - found)
        if missing:
            raise QueryError(f"Not in {source.qualified} {table}: {', '.join(missing[:20])}")
    if not picked:
        raise QueryError(f"{source.qualified} {table} has no rows to copy")
    template = picked[0].table_file
    target = _load_or_create(patch, table, fragment, schema, template)
    if target.header != template.header:
        # Same table, different version/column order: copy by column name.
        rows = [{c: v for c, v in r.as_dict().items() if c in target.header} for r in picked]
    else:
        rows = [r.as_dict() for r in picked]
    return upsert_rows(patch, table, rows, schema, fragment=target.metadata.fragment, template=template)


def add_key_deletes(patch: Mod, table: str, keys: list[str], schema: Schema | None) -> EditResult:
    """Add rows to the patch's ``twad_key_deletes_tables`` (Warhammer 3, patch 6.3+) so the game
    deletes those keys of ``table`` at load. ``keys`` use ``a|b`` for composite keys; the table
    stores them concatenated with no separator and the short table name, as RPFM writes them."""
    if not schema or not schema.definition(KEY_DELETES_TABLE):
        raise QueryError("This game's schema has no twad_key_deletes_tables (it is Warhammer 3 6.3+ only)")
    short = table.removesuffix("_tables")
    rows = [{"key": k.replace("|", ""), "table_name": short} for k in keys]
    return upsert_rows(patch, KEY_DELETES_TABLE, rows, schema)


def _rel(patch: Mod, tf: TableFile) -> str:
    assert tf.path is not None
    return Path(tf.path).relative_to(patch.root).as_posix()


__all__ = [
    "KEY_DELETES_TABLE",
    "EditResult",
    "Metadata",
    "QueryError",
    "add_key_deletes",
    "copy_rows",
    "create_patch",
    "delete_rows",
    "describe_table",
    "find_key",
    "list_mods",
    "list_tables",
    "query_rows",
    "resolve_table",
    "upsert_rows",
]
