import asyncio
import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ...services.repacking import RepackingService
from .._helpers import create_client, create_system_service, require_game
from ..main import cli


@cli.command()
@click.option(
    '--patch', '-p',
    required=True,
    type=str,
    help='Name of the patch mod in workspace/ to repack'
)
@click.option(
    '--output', '-o',
    type=click.Path(path_type=Path),
    default=None,
    help='Output .pack file path (default: output/<patch_name>.pack)'
)
@click.option(
    '--name', '-n',
    type=str,
    default=None,
    help='Custom output filename (without .pack extension)'
)
@click.option(
    '--workspace-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override workspace directory containing the patch mod'
)
@click.option(
    '--output-dir',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Override output directory for the .pack file'
)
def repack(patch: str, output: Path | None, name: str | None,
           workspace_dir: Path | None, output_dir: Path | None) -> None:
    """Repack a patch mod from workspace/ into a .pack file.

    Examples:\b

        tw-patcher repack --patch empire_rebalance
        tw-patcher repack --patch elf_fix --workspace-dir D:\\Modding\\workspace
    """
    require_game()
    settings.ensure_dirs()

    ws = workspace_dir or settings.workspace_dir
    patch_path = ws / patch
    if not patch_path.exists():
        available = sorted(
            d.name for d in ws.iterdir()
            if d.is_dir() and not d.name.startswith('.')
        ) if ws.exists() else []
        console.error(f"Patch mod '{patch}' not found in {ws}")
        if available:
            console.hint(f"Available: {', '.join(available)}")
        else:
            console.hint(f"No patch mods exist yet. Create one: mkdir workspace\\{patch}\\db")
        sys.exit(1)

    out_dir = output_dir or settings.output_dir
    effective_output = output
    if not effective_output:
        out_dir.mkdir(parents=True, exist_ok=True)
        pack_name = name or patch
        effective_output = out_dir / f"{pack_name}.pack"

    try:
        async def _run():
            system = create_system_service()
            client = create_client()
            await system.connect_client(client)
            try:
                service = RepackingService(settings, client)
                return await service.repack(patch, effective_output, name,
                                            workspace_dir=ws)
            finally:
                await client.disconnect()

        result = asyncio.run(_run())

        console.success(f"Pack file created: {result.output_path}")
        console.item(
            f"{len(result.tables_imported)} tables, "
            f"{len(result.scripts_imported)} scripts imported"
        )

    except Exception as e:
        console.error(f"Repacking failed: {e}")
        sys.exit(1)
