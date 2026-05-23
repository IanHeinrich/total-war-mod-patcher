import asyncio
import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from .._helpers import create_client, create_system_service, require_game
from ..main import cli


@cli.command('replace-table')
@click.option(
    '--pack', '-p',
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help='.pack file containing the table to replace'
)
@click.option(
    '--tsv', '-t',
    required=True,
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help='Replacement TSV file(s) — must match a table already in the pack'
)
@click.option(
    '--output', '-o',
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help='Write to a new file instead of editing the pack in-place'
)
def replace_table(pack: Path, tsv: tuple[Path, ...], output: Path | None) -> None:
    """Swap one or more DB tables inside a .pack file, keeping all other content intact.

    Each TSV's metadata line (line 2) identifies which table in the pack it replaces.
    Only the specified table(s) are changed — models, textures, scripts, and other
    tables are left untouched. Edits the pack in-place unless --output is given.

    Examples:\b

        tw-patcher replace-table -p ovn_lost_world.pack -t lost_places_landmarks.tsv
        tw-patcher replace-table -p mod.pack -t fix1.tsv -t fix2.tsv
        tw-patcher replace-table -p mod.pack -t fix.tsv -o output/mod.pack
    """
    require_game()
    settings.ensure_dirs()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)

    def _read_table_path(tsv_path: Path) -> str:
        with open(tsv_path, 'r', encoding='utf-8') as f:
            _header = f.readline()
            metadata = f.readline().strip()
        if not metadata.startswith('#'):
            console.error(f"Invalid TSV metadata in {tsv_path.name}: line 2 must start with '#'")
            sys.exit(1)
        parts = metadata.lstrip('#').split(';')
        if len(parts) < 3:
            console.error(f"Invalid TSV metadata in {tsv_path.name}: expected 3 semicolon-separated fields")
            sys.exit(1)
        return parts[2].strip()

    table_entries: list[tuple[Path, str]] = []
    for tsv_path in tsv:
        table_path = _read_table_path(tsv_path)
        table_entries.append((tsv_path, table_path))
        console.info(f"  {tsv_path.name} → {table_path}")

    try:
        async def _run():
            from ...utils.rpfm_utils import normalize_rpfm_path

            system = create_system_service()
            client = create_client()
            await system.connect_client(client)
            try:
                await client.set_game_selected(settings.selected_game)  # type: ignore[arg-type]

                with console.status("Opening pack file..."):
                    pack_handle = await client.open_pack_file(
                        normalize_rpfm_path(pack)
                    )

                for tsv_path, table_path in table_entries:
                    with console.status(f"Replacing {table_path}..."):
                        await client.import_tsv(
                            pack_handle,
                            table_path,
                            normalize_rpfm_path(tsv_path),
                        )
                    console.info(f"Replaced: {table_path}")

                with console.status("Saving pack..."):
                    if output:
                        await client.save_pack_as(
                            pack_handle,
                            normalize_rpfm_path(output),
                        )
                    else:
                        await client.save_pack(pack_handle)
            finally:
                await client.disconnect()

        asyncio.run(_run())

        saved_to = output or pack
        console.success(f"Pack saved: {saved_to}")
        console.item(f"{len(table_entries)} table(s) replaced")

    except Exception as e:
        console.error(f"Replace failed: {e}")
        sys.exit(1)
