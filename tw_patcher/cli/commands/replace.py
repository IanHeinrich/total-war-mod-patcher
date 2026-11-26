import asyncio
import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ...services.replace import ReplaceResult, ReplaceService
from .._helpers import create_client, create_system_service, require_game
from ..main import cli


@cli.command("replace-table")
@click.option(
    "--pack",
    "-p",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=".pack file containing the table to replace",
)
@click.option(
    "--tsv",
    "-t",
    required=True,
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Replacement TSV file(s) — must match a table already in the pack",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write to a new file instead of editing the pack in-place",
)
@click.option(
    "--no-backup",
    is_flag=True,
    help="When editing in place, skip copying the original to <pack>.bak first",
)
def replace_table(pack: Path, tsv: tuple[Path, ...], output: Path | None, no_backup: bool) -> None:
    """Swap one or more DB tables inside a .pack file, keeping all other content intact.

    Each TSV's metadata line (line 2) identifies which table in the pack it replaces.
    Only the specified table(s) are changed — models, textures, scripts, and other
    tables are left untouched. Edits the pack in-place unless --output is given;
    in-place edits first copy the original pack to <pack>.bak.

    Examples:

        tw-patcher replace-table -p ovn_lost_world.pack -t lost_places_landmarks.tsv
        tw-patcher replace-table -p mod.pack -t fix1.tsv -t fix2.tsv
        tw-patcher replace-table -p mod.pack -t fix.tsv -o output/mod.pack
    """
    require_game()
    settings.ensure_dirs()

    async def _run() -> ReplaceResult:
        system = create_system_service()
        client = create_client()
        await system.connect_client(client)
        try:
            service = ReplaceService(settings, client)
            return await service.replace_tables(pack, list(tsv), output, backup=not no_backup)
        finally:
            await client.disconnect()

    try:
        result = asyncio.run(_run())
    except Exception as e:
        console.error(f"Replace failed: {e}")
        sys.exit(1)

    console.success(f"Pack saved: {result.saved_to}")
    console.item(f"{len(result.replaced)} table(s) replaced")
    if result.backup:
        console.item(f"Original kept at: {result.backup}")
