"""``tw-patcher new-patch``: start a patch mod in workspace/, optionally seeded with tables."""

from __future__ import annotations

import click

from ...config import settings
from ...console import console
from ...data import queries
from .._data import fail, open_index, resolve
from ..main import cli


@cli.command("new-patch")
@click.argument("name")
@click.option("--from", "from_mod", default=None, help="Extracted mod to copy tables from")
@click.option("--table", "-t", "tables", multiple=True, help="Table to copy from --from (repeatable)")
def new_patch_cmd(name: str, from_mod: str | None, tables: tuple[str, ...]) -> None:
    """Create workspace/NAME/db/, optionally seeded with tables from an extracted mod.

    Copied tables keep their file names and metadata exactly, so they mirror the
    source layout that repack expects. Edit the copies, then run
    tw-patcher validate NAME and tw-patcher repack --patch NAME.

    Examples:\b

        tw-patcher new-patch my_fix
        tw-patcher new-patch sfo_roc_compat --from roc_sfo/sfo_grimhammer_3_main -t land_units -t main_units
    """
    if tables and not from_mod:
        fail("--table needs --from <mod> to copy from")
    if from_mod and not tables:
        fail("--from needs at least one --table to copy")

    settings.ensure_dirs()
    try:
        patch_dir = settings.get_patch_mod_path(name)
    except ValueError as e:
        fail(str(e))
    source = resolve(open_index(), from_mod, kind="source") if from_mod else None
    try:
        copied = queries.create_patch(patch_dir, source, list(tables))
    except queries.QueryError as e:
        fail(str(e))

    console.success(f"Created {patch_dir}")
    for c in copied:
        console.item(f"copied {c}")
    console.header("\nNext steps:")
    console.hint(f"1. Edit the tables in {patch_dir / 'db'}")
    console.hint(f"2. tw-patcher validate {name}")
    console.hint(f"3. tw-patcher repack --patch {name}")
