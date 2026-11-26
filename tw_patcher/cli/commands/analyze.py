"""Offline table commands: look inside extracted mods and patches without RPFM."""

from __future__ import annotations

import click

from ...console import console
from ...data import queries
from ...data.analysis import diff_mods, find_conflicts, validate_patch
from .._data import capped, emit_json, fail, json_option, open_index, open_schema, resolve, table_name
from ..main import cli

# ---------------------------------------------------------------------------- tables


@cli.command("tables")
@click.argument("mod", required=False)
@json_option
def tables_cmd(mod: str | None, as_json: bool) -> None:
    """List extracted mods and patches, or the tables (and fragments) of one MOD.

    MOD is a name under sources/ or workspace/ (a unique trailing part is enough;
    prefix with sources/ or workspace/ if a source and a patch share a name).

    Examples:\b

        tw-patcher tables
        tw-patcher tables sfo_grimhammer_3_main
        tw-patcher tables workspace/my_patch --json
    """
    index = open_index()
    if not mod:
        mods = [{"name": m.qualified, "kind": m.kind, "tables": len(m.tables())} for m in index.mods]
        if as_json:
            emit_json(mods)
            return
        if not mods:
            console.warning("Nothing extracted yet. Run: tw-patcher extract -s <mod.pack>")
            return
        for m in mods:
            console.plain(f"{m['name']}\t{m['tables']} table(s)")
        return

    target = resolve(index, mod)
    rows = []
    for table, fragments in target.fragments.items():
        for frag in fragments:
            try:
                count = len(frag.load().rows)
            except Exception:
                count = -1
            rows.append({"table": table, "fragment": frag.name, "rows": count, "path": str(frag.path)})
    if as_json:
        emit_json({"mod": target.qualified, "tables": rows})
        return
    console.header(f"{target.qualified}: {len(target.fragments)} table(s)")
    for r in rows:
        count = "unreadable" if r["rows"] < 0 else f"{r['rows']} row(s)"
        console.plain(f"{r['table']}/{r['fragment']}\t{count}")


# ---------------------------------------------------------------------------- show


@cli.command("show")
@click.argument("table")
@click.option("--mod", "-m", "mod_name", required=True, help="Extracted mod or patch to read from")
@click.option("--key", "-k", "keys", multiple=True, help="Only rows with this primary key (composite keys: a|b)")
@click.option(
    "--where", "-w", "wheres", multiple=True, help="Only rows where COLUMN=VALUE (repeatable, all must match)"
)
@click.option("--columns", "-c", default=None, help="Comma-separated columns to print")
@click.option("--limit", "-n", default=50, show_default=True, help="Maximum rows to print (0 = all)")
@json_option
def show_cmd(
    table: str,
    mod_name: str,
    keys: tuple[str, ...],
    wheres: tuple[str, ...],
    columns: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Print rows of TABLE from one mod, as the game would merge its fragments.

    TABLE may be given as units_tables, units or db/units_tables.

    Examples:\b

        tw-patcher show main_units --mod sfo_grimhammer_3_main --key wh_main_emp_inf_halberdiers
        tw-patcher show land_units -m my_patch -w category=infantry -c key,num_men --json
    """
    index = open_index()
    mod = resolve(index, mod_name)
    table = table_name(table, [mod])

    where: dict[str, str] = {}
    for w in wheres:
        if "=" not in w:
            fail(f"--where expects COLUMN=VALUE, got {w!r}")
        col, _, val = w.partition("=")
        where[col.strip()] = val

    wanted_columns = [c.strip() for c in columns.split(",")] if columns else None
    try:
        result = queries.query_rows(
            mod, table, open_schema(quiet=True), list(keys) or None, where or None, wanted_columns, limit=limit
        )
    except queries.QueryError as e:
        fail(str(e))
    kcols, wanted, shown = result["key_columns"], result["columns"], result["rows"]
    hidden = result["total"] - len(shown)

    if as_json:
        emit_json({k: result[k] for k in ("mod", "table", "key_columns", "columns", "total", "truncated", "rows")})
        return
    console.plain("\t".join(wanted))
    for row in shown:
        console.plain("\t".join(row["values"][c] for c in wanted))
    note = f"{result['total']} row(s)" + (f", {hidden} not shown (use --limit 0 for all)" if hidden else "")
    console.hint(f"{note}; key: {', '.join(kcols) or 'unknown (no schema)'}")


# ---------------------------------------------------------------------------- find-key


@cli.command("find-key")
@click.argument("key")
@click.option("--table", "-t", "tables", multiple=True, help="Only search these tables (much faster)")
@json_option
def find_key_cmd(key: str, tables: tuple[str, ...], as_json: bool) -> None:
    """Find every extracted mod and patch that defines KEY (composite keys: a|b).

    Within each table the rows are listed in merge order: the first one is the
    row the game uses when those fragments are loaded together.

    Examples:\b

        tw-patcher find-key wh_main_emp_inf_halberdiers
        tw-patcher find-key wh3_main_ksl_the_ice_court -t factions --json
    """
    index = open_index()
    mods = index.mods
    wanted = [table_name(t, mods) for t in tables] if tables else sorted({t for m in mods for t in m.tables()})
    hits = queries.find_key(index, key, wanted, open_schema(quiet=True))["tables"]
    if as_json:
        emit_json({"key": key, "tables": hits})
        return
    if not hits:
        console.warning(f"No extracted mod or patch defines {key!r}")
        return
    for table, found in hits.items():
        console.header(table)
        for i, h in enumerate(found):
            marker = "wins" if i == 0 and len(found) > 1 else ""
            console.plain(f"  {h['mod']}:{h['fragment']}\t{marker}".rstrip())


# ---------------------------------------------------------------------------- diff


@cli.command("diff")
@click.argument("mod_a")
@click.argument("mod_b")
@click.option("--table", "-t", "tables", multiple=True, help="Only compare these tables")
@click.option("--shared", is_flag=True, help="Only tables both sides contain (e.g. a patch against its source)")
@click.option("--limit", "-n", default=20, show_default=True, help="Rows listed per table and change type (0 = all)")
@json_option
def diff_cmd(mod_a: str, mod_b: str, tables: tuple[str, ...], shared: bool, limit: int, as_json: bool) -> None:
    """Row-level differences from MOD_A to MOD_B, matched by primary key.

    Works between any two extracted mods or patches, e.g. a patch and the mod it
    patches, or two versions of a mod extracted to different folders.

    Examples:\b

        tw-patcher diff sfo_grimhammer_3_main workspace/my_patch --shared
        tw-patcher diff roc_sfo/db roc_sfo/!b_mixer -t units --json
    """
    index = open_index()
    a, b = resolve(index, mod_a), resolve(index, mod_b)
    schema = open_schema()
    names = [table_name(t, [a, b]) for t in tables] or None
    if shared:
        names = [t for t in (names or a.tables()) if t in set(b.tables()) and t in set(a.tables())]
    diffs = diff_mods(a, b, schema, names)
    if as_json:
        out = []
        for d in diffs:
            entry = {"table": d.table, "key_columns": d.key_columns, "only_in": d.only_in}
            for kind in ("added", "removed", "changed"):
                items, hidden = capped(getattr(d, kind), limit)
                entry[kind] = items
                entry[f"{kind}_total"] = len(getattr(d, kind))
            out.append(entry)
        emit_json({"a": a.qualified, "b": b.qualified, "tables": out})
        return
    if not diffs:
        console.success(f"No row differences between {a.qualified} and {b.qualified}")
        return
    for d in diffs:
        side = {"a": f" (only in {a.qualified})", "b": f" (only in {b.qualified})"}.get(d.only_in or "", "")
        console.header(f"{d.table}{side}: +{len(d.added)} -{len(d.removed)} ~{len(d.changed)}")
        kc = d.key_columns
        for kind, sign in (("added", "+"), ("removed", "-")):
            items, hidden = capped(getattr(d, kind), limit)
            for row in items:
                label = "|".join(row[c] for c in kc) if kc else "\t".join(row.values())
                console.plain(f"  {sign} {label}")
            if hidden:
                console.hint(f"... {hidden} more {kind}")
        items, hidden = capped(d.changed, limit)
        for change in items:
            cells = ", ".join(f"{c.column}: {c.old!r} -> {c.new!r}" for c in change.changes)
            console.plain(f"  ~ {'|'.join(change.key)}: {cells}")
        if hidden:
            console.hint(f"... {hidden} more changed")


# ---------------------------------------------------------------------------- conflicts


@cli.command("conflicts")
@click.argument("mods", nargs=-1, required=True)
@click.option(
    "--context",
    "context",
    multiple=True,
    help="Also resolve references against this mod (e.g. an extracted vanilla db) without reporting its conflicts",
)
@click.option("--no-references", is_flag=True, help="Skip the dangling-reference check (faster)")
@click.option("--limit", "-n", default=50, show_default=True, help="Items listed per section (0 = all)")
@json_option
def conflicts_cmd(
    mods: tuple[str, ...], context: tuple[str, ...], no_references: bool, limit: int, as_json: bool
) -> None:
    """Find where MODS step on each other, in load order (first = highest priority).

    Reports whole-file overrides (same table file in two packs), primary keys
    defined by more than one mod (and which row wins), and references from
    their rows to keys that none of the mods (or --context mods) define.

    Examples:\b

        tw-patcher conflicts roc_sfo/!!roc_realms_ie roc_sfo/!b_mixer roc_sfo/sfo_grimhammer_3_main --context roc_sfo/db
    """
    index = open_index()
    selected = [resolve(index, m) for m in mods]
    extra = [resolve(index, m) for m in context]
    schema = open_schema()
    report = find_conflicts(selected, schema, check_references=not no_references, context=extra)
    if as_json:
        emit_json(
            {
                "mods": [m.qualified for m in selected],
                "overrides": report.overrides,
                "collisions_total": len(report.collisions),
                "collisions": capped(report.collisions, limit)[0],
                "dangling_total": len(report.dangling),
                "dangling": capped(report.dangling, limit)[0],
                "unchecked_targets": report.unchecked_targets,
                "broken_by_deletes_total": len(report.broken_by_deletes),
                "broken_by_deletes": capped(report.broken_by_deletes, limit)[0],
                "deletes_without_match": report.deletes_without_match,
            }
        )
        return

    console.header(f"Load order (first wins): {', '.join(m.qualified for m in selected)}")
    console.header(f"\nWhole-file overrides: {len(report.overrides)}")
    for o in capped(report.overrides, limit)[0]:
        console.plain(f"  {o.table}/{o.fragment}: {o.winner} shadows {', '.join(o.shadowed)}")
    real = [c for c in report.collisions if not c.identical]
    console.header(f"\nKey collisions: {len(report.collisions)} ({len(real)} with differing values)")
    shown, hidden = capped(real, limit)
    for c in shown:
        diffs = "; ".join(f"{col}: {' vs '.join(repr(v) for v in vals)}" for col, vals in c.differences.items())
        console.plain(f"  {c.table} {'|'.join(c.key)}: {c.winner} beats {', '.join(c.others)}  [{diffs}]")
    if hidden:
        console.hint(f"... {hidden} more")
    if not no_references:
        console.header(f"\nDangling references: {len(report.dangling)}")
        shown, hidden = capped(report.dangling, limit)
        for d in shown:
            console.plain(f"  {d.source} {'|'.join(d.key)}: {d.column}={d.value!r} not in {d.target}")
        if hidden:
            console.hint(f"... {hidden} more")
        console.header(f"\nKey deletes that break references: {len(report.broken_by_deletes)}")
        shown, hidden = capped(report.broken_by_deletes, limit)
        for b in shown:
            console.plain(
                f"  {b.delete} deletes {b.table} {b.key!r}, still used by {b.referenced_by} "
                f"{'|'.join(b.referencing_key)} ({b.column})"
            )
        if hidden:
            console.hint(f"... {hidden} more")
        if report.broken_by_deletes:
            console.hint("The game crashes on load when a deleted row is still referenced.")
        if report.deletes_without_match:
            console.header(f"\nKey deletes that match nothing: {len(report.deletes_without_match)}")
            for u in capped(report.deletes_without_match, limit)[0]:
                console.plain(f"  {u.delete}: {u.table} {u.key!r}")
        if report.unchecked_targets:
            console.hint(
                f"Not checked ({len(report.unchecked_targets)} referenced tables are in none of these mods; "
                "add an extracted vanilla db with --context): " + ", ".join(report.unchecked_targets[:10])
            )


# ---------------------------------------------------------------------------- validate


@cli.command("validate")
@click.argument("patch")
@click.option(
    "--against",
    "against",
    multiple=True,
    help="Resolve references against these mods (default: everything in sources/)",
)
@json_option
def validate_cmd(patch: str, against: tuple[str, ...], as_json: bool) -> None:
    """Check a patch in workspace/ before repacking it.

    Errors (exit status 1): unreadable/edited metadata lines, tables or versions
    the schema doesn't know, missing or extra columns, rows with the wrong
    number of cells, values of the wrong type, duplicate primary keys.
    Warnings: references to keys not found in the patch or the sources,
    metadata paths that differ from the file location.

    Examples:\b

        tw-patcher validate my_patch
        tw-patcher validate my_patch --against sfo_grimhammer_3_main --json
    """
    index = open_index()
    target = resolve(index, patch, kind="patch")
    sources = [resolve(index, m) for m in against] if against else index.sources
    schema = open_schema()
    issues = validate_patch(target, schema, sources)
    errors = [i for i in issues if i.level == "error"]
    if as_json:
        emit_json(
            {
                "patch": target.qualified,
                "schema": str(schema.source) if schema else None,
                "errors": len(errors),
                "warnings": len(issues) - len(errors),
                "issues": issues,
            }
        )
    else:
        for i in issues:
            where = f"{i.file}:{i.line}" if i.line else i.file
            (console.error if i.level == "error" else console.warning)(f"{where}: {i.message}")
        if errors:
            console.error(f"{target.qualified}: {len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
        else:
            console.success(f"{target.qualified}: no errors ({len(issues)} warning(s))")
    if errors:
        raise SystemExit(1)
