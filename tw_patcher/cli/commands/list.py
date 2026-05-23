from pathlib import Path

import click

from ...config import settings
from ...console import console
from ..main import cli


@cli.command('list')
@click.option(
    '--workspace-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override workspace directory to list patch mods from'
)
def list_cmd(workspace_dir: Path | None) -> None:
    """List available patch mods in the workspace."""
    settings.ensure_dirs()
    ws = workspace_dir or settings.workspace_dir

    mods = sorted(
        d.name for d in ws.iterdir()
        if d.is_dir() and not d.name.startswith('.')
    ) if ws.exists() else []

    if not mods:
        console.warning(f"No patch mods found in {ws}")
        console.hint("Create one: mkdir workspace\\my_patch\\db")
        return

    console.header(f"Patch mods in {ws} ({len(mods)}):\n")
    for mod_name in mods:
        mod_path = ws / mod_name
        tsv_count = len(list(mod_path.glob("**/*.tsv")))
        console.item(f"{mod_name}/ — {tsv_count} table(s)")
