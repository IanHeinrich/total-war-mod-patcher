import asyncio
import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ...services.extraction import ExtractionService
from .._helpers import create_client, create_system_service, require_game
from ..main import cli


@cli.command()
@click.option(
    '--source', '-s',
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help='Source .pack file (can specify up to 6 times)'
)
@click.option(
    '--output', '-o',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Output directory (default: sources/)'
)
@click.option(
    '--sources-dir',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Override sources directory (alternative to --output)'
)
def extract(source: tuple[Path, ...], output: Path | None, sources_dir: Path | None) -> None:
    """Extract one or more mod pack files to TSV format.

    Examples:\b

        tw-patcher extract -s mod1.pack -s mod2.pack
        tw-patcher extract -s mod.pack --sources-dir D:\\Modding\\sources
    """
    if not source:
        console.error("At least one --source is required.")
        sys.exit(1)
    if len(source) > settings.max_mods:
        console.error(f"Maximum {settings.max_mods} source mods allowed.")
        sys.exit(1)

    require_game()
    settings.ensure_dirs()
    target_dir = output or sources_dir or settings.sources_dir

    async def _run() -> list:
        system = create_system_service()
        client = create_client()
        await system.connect_client(client)
        try:
            service = ExtractionService(settings, client)
            return await service.extract_batch(list(source), target_dir)
        finally:
            await client.disconnect()

    try:
        results = asyncio.run(_run())

        total_tables = sum(len(r.tables_exported) for r in results)
        total_scripts = sum(len(r.scripts_extracted) for r in results)
        console.success(
            f"Extracted {len(source)} mod(s): {total_tables} tables, "
            f"{total_scripts} scripts to: {target_dir}"
        )
        console.header("\nNext steps:")
        console.hint("1. Compare extracted tables/scripts in sources/")
        console.hint("2. Create a patch mod: mkdir workspace\\<name>\\db")
        console.hint("3. Repack: tw-patcher repack --patch <name>")

    except Exception as e:
        console.error(f"Extraction failed: {e}")
        sys.exit(1)
