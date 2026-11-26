"""Cross-mod table analysis: keyed diffs, load-order conflicts, dangling
references and pre-repack validation.

Merge rules (how the game combines DB tables from several packs):

1. If two packs contain the same table file (``db/<table>/<fragment>``), only
   the one from the higher-priority pack is loaded (a whole-file override).
2. The surviving fragments of a table are merged in fragment-name byte order;
   when several define the same primary key, the first one wins.

"Priority" is the order mods are given in (first = highest), mirroring a load
order where earlier packs win. All results are plain dataclasses of strings
and ints so the CLI and the MCP server can print them or emit JSON.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .index import Fragment, Mod
from .schema import Schema, TableDefinition
from .tsv import TableFile, TableFormatError

Key = tuple[str, ...]

INT_TYPES = {"I16", "I32", "I64"}
FLOAT_TYPES = {"F32", "F64"}
OPTIONAL_INT_TYPES = {"OptionalI16", "OptionalI32", "OptionalI64"}


# ---------------------------------------------------------------------------- merged views


@dataclass
class RowRef:
    fragment: Fragment
    row: list[str]

    @property
    def table_file(self) -> TableFile:
        return self.fragment.load()

    def as_dict(self) -> dict[str, str]:
        return self.table_file.as_dict(self.row)


def definition_for(schema: Schema | None, tf: TableFile) -> TableDefinition | None:
    return schema.definition(tf.table, tf.version) if schema else None


def key_columns(schema: Schema | None, tf: TableFile) -> list[str]:
    """Schema key columns present in this file; empty when unknown (then the whole row is the key)."""
    definition = definition_for(schema, tf)
    if not definition:
        return []
    return [c for c in definition.key_columns if tf.has_column(c)]


def row_key(tf: TableFile, row: list[str], columns: list[str]) -> Key:
    return tuple(tf.cell(row, c) for c in columns) if columns else tuple(row)


def effective_fragments(mods: list[Mod], table: str) -> tuple[list[Fragment], list[tuple[str, list[Fragment]]]]:
    """Fragments of ``table`` the game would load from ``mods`` (priority order),
    in merge order, plus the whole-file overrides as (fragment name, [winner, *shadowed])."""
    by_name: dict[str, list[Fragment]] = {}
    for mod in mods:
        for frag in mod.fragments.get(table, []):
            by_name.setdefault(frag.name, []).append(frag)
    winners = [frags[0] for frags in by_name.values()]
    winners.sort(key=lambda f: (f.name.encode("utf-8"), mods.index(f.mod)))
    overrides = [(name, frags) for name, frags in sorted(by_name.items()) if len(frags) > 1]
    return winners, overrides


def merge_rows(fragments: Iterable[Fragment], schema: Schema | None) -> dict[Key, list[RowRef]]:
    """key -> every row defining it, in merge order (index 0 is the one the game uses)."""
    merged: dict[Key, list[RowRef]] = {}
    for frag in fragments:
        try:
            tf = frag.load()
        except (TableFormatError, OSError, UnicodeDecodeError):
            continue
        cols = key_columns(schema, tf)
        for row in tf.rows:
            merged.setdefault(row_key(tf, row, cols), []).append(RowRef(frag, row))
    return merged


def column_values(mods: list[Mod], table: str, column: str, schema: Schema | None) -> set[str] | None:
    """All values of ``table.column`` across the merged mods; None if no mod has that table."""
    fragments, _ = effective_fragments(mods, table)
    if not fragments:
        return None
    values: set[str] = set()
    for refs in merge_rows(fragments, schema).values():
        tf = refs[0].table_file
        if tf.has_column(column):
            values.add(tf.cell(refs[0].row, column))
    return values


# ---------------------------------------------------------------------------- diff


@dataclass
class CellChange:
    column: str
    old: str
    new: str


@dataclass
class RowChange:
    key: list[str]
    changes: list[CellChange]


@dataclass
class TableDiff:
    table: str
    key_columns: list[str]
    added: list[dict[str, str]] = field(default_factory=list)
    removed: list[dict[str, str]] = field(default_factory=list)
    changed: list[RowChange] = field(default_factory=list)
    only_in: str | None = None  # "a" | "b" when the table exists on one side only

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_mods(a: Mod, b: Mod, schema: Schema | None, tables: list[str] | None = None) -> list[TableDiff]:
    """Row-level differences from ``a`` to ``b`` per table (rows keyed by the schema's primary key)."""
    names = tables or sorted(set(a.tables()) | set(b.tables()))
    result: list[TableDiff] = []
    for table in names:
        rows_a = merge_rows(a.fragments.get(table, []), schema)
        rows_b = merge_rows(b.fragments.get(table, []), schema)
        sample = next((r[0].table_file for r in [*rows_a.values(), *rows_b.values()]), None)
        diff = TableDiff(table=table, key_columns=key_columns(schema, sample) if sample else [])
        if not a.fragments.get(table):
            diff.only_in = "b"
        elif not b.fragments.get(table):
            diff.only_in = "a"
        for key, refs in rows_b.items():
            if key not in rows_a:
                diff.added.append(refs[0].as_dict())
        for key, refs in rows_a.items():
            if key not in rows_b:
                diff.removed.append(refs[0].as_dict())
                continue
            old, new = refs[0].as_dict(), rows_b[key][0].as_dict()
            changes = [CellChange(c, old[c], new[c]) for c in old if c in new and old[c] != new[c]]
            if changes:
                diff.changed.append(RowChange(list(key), changes))
        if not diff.is_empty:
            result.append(diff)
    return result


# ---------------------------------------------------------------------------- conflicts


@dataclass
class FileOverride:
    table: str
    fragment: str
    winner: str  # mod name
    shadowed: list[str]


@dataclass
class KeyCollision:
    table: str
    key: list[str]
    winner: str  # fragment label mod:table/fragment
    others: list[str]
    identical: bool
    differences: dict[str, list[str]] = field(default_factory=dict)  # column -> [winner value, other values...]


@dataclass
class DanglingReference:
    source: str  # fragment label
    key: list[str]
    column: str
    value: str
    target: str  # table.column


@dataclass
class ConflictReport:
    mods: list[str]
    overrides: list[FileOverride] = field(default_factory=list)
    collisions: list[KeyCollision] = field(default_factory=list)
    dangling: list[DanglingReference] = field(default_factory=list)
    unchecked_targets: list[str] = field(default_factory=list)  # referenced tables no loaded mod provides
    broken_by_deletes: list[BrokenByDelete] = field(default_factory=list)
    deletes_without_match: list[UnmatchedDelete] = field(default_factory=list)


def find_conflicts(
    mods: list[Mod], schema: Schema | None, check_references: bool = True, context: list[Mod] | None = None
) -> ConflictReport:
    """Overrides and key collisions between ``mods`` (priority order), plus references
    from their rows that resolve nowhere in ``mods + context`` (context: e.g. vanilla)."""
    report = ConflictReport(mods=[m.name for m in mods])
    tables = sorted({t for m in mods for t in m.tables()})
    for table in tables:
        fragments, overrides = effective_fragments(mods, table)
        for name, frags in overrides:
            report.overrides.append(FileOverride(table, name, frags[0].mod.name, [f.mod.name for f in frags[1:]]))
        for key, refs in merge_rows(fragments, schema).items():
            if len({r.fragment.mod.name for r in refs}) < 2:
                continue
            first = refs[0].as_dict()
            others = [r.as_dict() for r in refs[1:]]
            diffs = {
                c: [first[c], *[o.get(c, "") for o in others]]
                for c in first
                if any(o.get(c) != first[c] for o in others)
            }
            report.collisions.append(
                KeyCollision(
                    table=table,
                    key=list(key),
                    winner=refs[0].fragment.label,
                    others=[r.fragment.label for r in refs[1:]],
                    identical=not diffs,
                    differences=diffs,
                )
            )
    if check_references and schema:
        dangling, unchecked = dangling_references(mods, mods + (context or []), schema)
        report.dangling, report.unchecked_targets = dangling, unchecked
        report.broken_by_deletes, report.deletes_without_match = key_delete_effects(
            mods, mods + (context or []), schema
        )
    return report


# ---------------------------------------------------------------------------- key deletes (Warhammer 3)

KEY_DELETES_TABLE = "twad_key_deletes_tables"


@dataclass
class BrokenByDelete:
    delete: str  # fragment label of the twad_key_deletes file
    table: str  # table the row is deleted from
    key: str  # deleted key as written in twad_key_deletes (key columns concatenated)
    referenced_by: str  # fragment label of a row that still points at the deleted row
    referencing_key: list[str]
    column: str  # referencing_table.column


@dataclass
class UnmatchedDelete:
    delete: str
    table: str
    key: str


def _concat_key(tf: TableFile, row: list[str], schema: Schema) -> str | None:
    definition = definition_for(schema, tf)
    if not definition or not definition.key_columns:
        return None
    return "".join(tf.cell(row, c) for c in definition.ca_key_columns if tf.has_column(c))


def key_delete_effects(
    deleters: list[Mod], universe: list[Mod], schema: Schema
) -> tuple[list[BrokenByDelete], list[UnmatchedDelete]]:
    """What the ``twad_key_deletes_tables`` rows of ``deleters`` remove from ``universe``, and which remaining
    rows still reference a removed one (the game crashes on load when that happens). Deletes that match no row
    of ``universe`` are returned too: usually a typo or a key from a mod that isn't loaded."""
    deletes: list[tuple[str, str, str]] = []  # (delete label, full table, concatenated key)
    for mod in deleters:
        for frag in mod.fragments.get(KEY_DELETES_TABLE, []):
            try:
                tf = frag.load()
            except (TableFormatError, OSError, UnicodeDecodeError):
                continue
            if not (tf.has_column("key") and tf.has_column("table_name")):
                continue
            for row in tf.rows:
                table = tf.cell(row, "table_name").strip()
                if table:
                    table = table if table.endswith("_tables") else f"{table}_tables"
                    deletes.append((frag.label, table, tf.cell(row, "key")))
    if not deletes:
        return [], []

    broken: list[BrokenByDelete] = []
    unmatched: list[UnmatchedDelete] = []
    merged_cache: dict[str, dict[Key, list[RowRef]]] = {}

    def merged(table: str) -> dict[Key, list[RowRef]]:
        if table not in merged_cache:
            merged_cache[table] = merge_rows(effective_fragments(universe, table)[0], schema)
        return merged_cache[table]

    by_table: dict[str, list[tuple[str, str]]] = {}
    for label, table, key in deletes:
        by_table.setdefault(table, []).append((label, key))

    # Pass 1: which rows every delete removes (so pass 2 can ignore references from removed rows too)
    removed_by_table: dict[str, list[tuple[str, str, RowRef]]] = {}
    for table, wanted in by_table.items():
        rows_by_concat: dict[str, RowRef] = {}
        for refs in merged(table).values():
            concat = _concat_key(refs[0].table_file, refs[0].row, schema)
            if concat is not None:
                rows_by_concat[concat] = refs[0]
        for label, key in wanted:
            ref = rows_by_concat.get(key)
            if ref is None:
                unmatched.append(UnmatchedDelete(label, table, key))
            else:
                removed_by_table.setdefault(table, []).append((label, key, ref))
    removed_rows = {id(ref.row) for removed in removed_by_table.values() for _, _, ref in removed}

    # Pass 2: rows that survive and still point at a removed row
    for table, removed in removed_by_table.items():
        for ref_table, ref_column, target_column in schema.references_to(table):
            if ref_table == KEY_DELETES_TABLE:
                continue
            referencing = merged(ref_table)
            if not referencing:
                continue
            for label, key, ref in removed:
                target_tf = ref.table_file
                if not target_tf.has_column(target_column):
                    continue
                value = target_tf.cell(ref.row, target_column)
                if not value:
                    continue
                for refs in referencing.values():
                    other = refs[0]
                    tf = other.table_file
                    if id(other.row) in removed_rows or not tf.has_column(ref_column):
                        continue
                    if tf.cell(other.row, ref_column) == value:
                        broken.append(
                            BrokenByDelete(
                                delete=label,
                                table=table,
                                key=key,
                                referenced_by=other.fragment.label,
                                referencing_key=list(row_key(tf, other.row, key_columns(schema, tf))),
                                column=f"{ref_table}.{ref_column}",
                            )
                        )
    return broken, unmatched


def dangling_references(
    check: list[Mod], universe: list[Mod], schema: Schema, tables: list[str] | None = None
) -> tuple[list[DanglingReference], list[str]]:
    """References in ``check``'s rows whose target value no mod in ``universe`` defines."""
    found: list[DanglingReference] = []
    unchecked: set[str] = set()
    targets: dict[tuple[str, str], set[str] | None] = {}
    for mod in check:
        for table, fragments in mod.fragments.items():
            if tables and table not in tables:
                continue
            for frag in fragments:
                try:
                    tf = frag.load()
                except (TableFormatError, OSError, UnicodeDecodeError):
                    continue
                definition = definition_for(schema, tf)
                if not definition:
                    continue
                cols = key_columns(schema, tf)
                for fld in definition.fields:
                    if not fld.reference or not tf.has_column(fld.name):
                        continue
                    target = fld.reference
                    if target not in targets:
                        targets[target] = column_values(universe, target[0], target[1], schema)
                    known = targets[target]
                    if known is None:
                        unchecked.add(target[0])
                        continue
                    # CA data uses 0 in integer reference columns to mean "no reference"
                    null_values = {"", "0"} if fld.field_type in INT_TYPES | OPTIONAL_INT_TYPES else {""}
                    for row in tf.rows:
                        value = tf.cell(row, fld.name)
                        if value not in null_values and value not in known:
                            found.append(
                                DanglingReference(
                                    frag.label,
                                    list(row_key(tf, row, cols)),
                                    fld.name,
                                    value,
                                    f"{target[0]}.{target[1]}",
                                )
                            )
    return found, sorted(unchecked)


# ---------------------------------------------------------------------------- validate


@dataclass
class Issue:
    level: str  # "error" | "warning"
    file: str  # path relative to the patch root
    message: str
    line: int | None = None


def _type_ok(field_type: str, value: str) -> bool:
    try:
        if field_type in INT_TYPES:
            int(value)
        elif field_type in OPTIONAL_INT_TYPES:
            if value:
                int(value)
        elif field_type in FLOAT_TYPES:
            float(value)
        elif field_type == "ColourHex":
            return len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value)
        elif field_type == "Boolean":
            return value.lower() in ("true", "false", "1", "0")
    except ValueError:
        return False
    return True


def validate_patch(patch: Mod, schema: Schema | None, sources: list[Mod] | None = None) -> list[Issue]:
    """Problems that would break a repack or the game, found before RPFM sees the files."""
    issues: list[Issue] = []

    def rel(frag: Fragment) -> str:
        return frag.path.relative_to(patch.root).as_posix()

    for table, fragments in patch.fragments.items():
        loaded: list[tuple[Fragment, TableFile]] = []
        for frag in fragments:
            try:
                tf = frag.load()
            except (TableFormatError, UnicodeDecodeError) as e:
                issues.append(Issue("error", rel(frag), str(e).split(": ", 1)[-1], line=2))
                continue
            loaded.append((frag, tf))
            expected_path = f"db/{table}/{frag.name}"
            if tf.table != table:
                issues.append(
                    Issue("error", rel(frag), f"metadata says table {tf.table!r} but the file is in {table}/", line=2)
                )
            elif tf.metadata.pack_path != expected_path:
                issues.append(
                    Issue(
                        "warning",
                        rel(frag),
                        f"metadata path {tf.metadata.pack_path!r} differs from the file location ({expected_path}); "
                        "repack uses the file location",
                        line=2,
                    )
                )
            issues.extend(_check_columns_and_rows(rel(frag), tf, schema))

        # Duplicate keys inside the patch itself
        seen: dict[Key, str] = {}
        for frag, tf in loaded:
            cols = key_columns(schema, tf)
            if not cols:
                continue
            for i, row in enumerate(tf.rows):
                key = row_key(tf, row, cols)
                where = f"{rel(frag)}:{i + 3}"
                if key in seen:
                    issues.append(
                        Issue("error", rel(frag), f"duplicate key {list(key)} (also at {seen[key]})", line=i + 3)
                    )
                else:
                    seen[key] = where

    issues.extend(_override_and_order_issues(patch, schema, sources or []))

    if schema:
        broken, unmatched = key_delete_effects([patch], [patch, *(sources or [])], schema)
        for b in broken:
            issues.append(
                Issue(
                    "warning",
                    f"db/{KEY_DELETES_TABLE}/{b.delete.rsplit('/', 1)[-1]}.tsv",
                    f"deleting {b.table} {b.key!r} breaks {b.column} in {b.referenced_by} (row {b.referencing_key}): "
                    "the game crashes on load if both are loaded",
                )
            )
        for u in unmatched:
            issues.append(
                Issue(
                    "warning",
                    f"db/{KEY_DELETES_TABLE}/{u.delete.rsplit('/', 1)[-1]}.tsv",
                    f"deletes {u.table} {u.key!r}, which no source defines (typo, or a mod that isn't extracted?)",
                )
            )
        dangling, _ = dangling_references([patch], [patch, *(sources or [])], schema)
        for d in dangling:
            file = d.source.split(":", 1)[1]
            issues.append(
                Issue(
                    "warning",
                    f"db/{file}.tsv",
                    f"{d.column}={d.value!r} (row {d.key}) not found in {d.target} in this patch or the sources",
                )
            )
    return issues


def _override_and_order_issues(patch: Mod, schema: Schema | None, sources: list[Mod]) -> list[Issue]:
    """Warnings about how the patch will combine with the sources in the game's merge:
    whole-file overrides (incl. vanilla datacores) and rows that lose to a source fragment sorting first."""
    issues: list[Issue] = []
    for table, fragments in patch.fragments.items():
        if table == KEY_DELETES_TABLE:
            continue
        source_frags = [f for m in sources for f in m.fragments.get(table, [])]
        for frag in fragments:
            rel = frag.path.relative_to(patch.root).as_posix()
            same_name = sorted({f.mod.name for f in source_frags if f.name == frag.name})
            if frag.name == "data__":
                hint = (
                    " On Warhammer 3 prefer twad_key_deletes_tables to remove rows."
                    if schema and schema.definition(KEY_DELETES_TABLE)
                    else ""
                )
                issues.append(
                    Issue(
                        "warning",
                        rel,
                        f"replaces vanilla's entire {table} (a datacore): rows added by later game patches or other "
                        f"mods' changes to it are lost.{hint}",
                    )
                )
            elif same_name:
                issues.append(
                    Issue(
                        "warning",
                        rel,
                        f"same file name as {', '.join(same_name)}: if your pack loads first, it replaces their whole "
                        f"db/{table}/{frag.name}; if theirs does, your file is ignored",
                    )
                )

            # Rows the patch redefines but a source fragment sorting earlier would win
            try:
                tf = frag.load()
            except (TableFormatError, OSError, UnicodeDecodeError):
                continue
            cols = key_columns(schema, tf)
            if not cols:
                continue
            mine = {row_key(tf, r, cols): tf.as_dict(r) for r in tf.rows}
            for other in source_frags:
                if other.name == frag.name or other.name.encode("utf-8") >= frag.name.encode("utf-8"):
                    continue
                try:
                    otf = other.load()
                except (TableFormatError, OSError, UnicodeDecodeError):
                    continue
                ocols = key_columns(schema, otf)
                if ocols != cols:
                    continue
                losing = [
                    k
                    for r in otf.rows
                    if (k := row_key(otf, r, ocols)) in mine
                    and any(mine[k].get(c) != v for c, v in otf.as_dict(r).items() if c in mine[k])
                ]
                if losing:
                    sample = ", ".join("|".join(k) for k in losing[:3])
                    more = f" and {len(losing) - 3} more" if len(losing) > 3 else ""
                    issues.append(
                        Issue(
                            "warning",
                            rel,
                            f"{len(losing)} row(s) lose to {other.label} because its file name sorts first "
                            f"({sample}{more}); rename your file to sort before {other.name!r} (e.g. start it with '!')",
                        )
                    )
    return issues


def _check_columns_and_rows(file: str, tf: TableFile, schema: Schema | None) -> list[Issue]:
    issues: list[Issue] = []
    definition = definition_for(schema, tf)
    if schema and not definition:
        versions = schema.versions(tf.table)
        if versions:
            issues.append(
                Issue(
                    "error",
                    file,
                    f"{tf.table} version {tf.version} is not in the {schema.game} schema (known: {versions}); "
                    "re-export it from a current source",
                    line=2,
                )
            )
        else:
            issues.append(Issue("warning", file, f"{tf.table} is not in the {schema.game} schema", line=2))
    columns = definition.tsv_columns() if definition else []
    if definition:
        expected = [name for name, _ in columns]
        missing = [c for c in expected if c not in tf.header]
        extra = [c for c in tf.header if c not in expected]
        if missing:
            issues.append(Issue("error", file, f"missing column(s): {', '.join(missing)}", line=1))
        if extra:
            issues.append(Issue("error", file, f"unknown column(s): {', '.join(extra)}", line=1))

    width = len(tf.header)
    types = dict(columns)
    for i, row in enumerate(tf.rows):
        line = i + 3
        if row == [""]:
            issues.append(Issue("warning", file, "blank line", line=line))
            continue
        if len(row) != width:
            issues.append(Issue("error", file, f"{len(row)} cell(s) but {width} columns (tabs vs spaces?)", line=line))
            continue
        for col, value in zip(tf.header, row, strict=True):  # lengths checked above
            field_type = types.get(col)
            if field_type and not _type_ok(field_type, value):
                issues.append(Issue("error", file, f"{col}={value!r} is not a valid {field_type}", line=line))
    return issues
