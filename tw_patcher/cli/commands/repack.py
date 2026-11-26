import asyncio
import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ...services.repacking import RepackingService
from .._helpers import create_client, create_system_service, report_failures, require_game
from ..main import cli


@cli.command()
@click.option("--patch", "-p", required=True, type=str, help="Name of the patch mod in workspace/ to repack")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output .pack file path (default: output/<patch_name>.pack)",
)
@click.option("--name", "-n", type=str, default=None, help="Custom output filename (without .pack extension)")
@click.option(
    "--workspace-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override workspace directory containing the patch mod",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override output directory for the .pack file",
)
@click.option("--no-validate", is_flag=True, help="Skip the pre-repack checks (tw-patcher validate)")
@click.option(
    "--allow-partial",
    is_flag=True,
    help="Save the pack even if some files failed to import (by default nothing is saved)",
)
def repack(
    patch: str,
    output: Path | None,
    name: str | None,
    workspace_dir: Path | None,
    output_dir: Path | None,
    allow_partial: bool,
    no_validate: bool,
) -> None:
    """Repack a patch mod from workspace/ into a .pack file.

    Examples:\b

        tw-patcher repack --patch empire_rebalance
        tw-patcher repack --patch elf_fix --workspace-dir D:\\Modding\\workspace
    """
    require_game()
    settings.ensure_dirs()

    ws = workspace_dir or settings.workspace_dir
    try:
        patch_path = settings.get_patch_mod_path(patch, ws)
    except ValueError as e:
        console.error(str(e))
        sys.exit(1)
    if not patch_path.exists():
        available = (
            sorted(d.name for d in ws.iterdir() if d.is_dir() and not d.name.startswith(".")) if ws.exists() else []
        )
        console.error(f"Patch mod '{patch}' not found in {ws}")
        if available:
            console.hint(f"Available: {', '.join(available)}")
        else:
            console.hint(f"No patch mods exist yet. Create one: tw-patcher new-patch {patch}")
        sys.exit(1)

    if not no_validate:
        _validate_first(patch_path)

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
                return await service.repack(
                    patch, effective_output, name, workspace_dir=ws, allow_partial=allow_partial
                )
            finally:
                await client.disconnect()

        result = asyncio.run(_run())
    except Exception as e:
        console.error(f"Repacking failed: {e}")
        report_failures(getattr(e, "failed_tables", []), "file(s)")
        sys.exit(1)

    counts = f"{len(result.tables_imported)} tables, {len(result.scripts_imported)} scripts imported"
    if result.failures:  # only reachable with --allow-partial
        console.warning(f"Partial pack saved: {result.output_path} ({counts})")
        report_failures(result.failures, "file(s)")
        sys.exit(1)

    console.success(f"Pack file created: {result.output_path}")
    console.item(counts)


def _validate_first(patch_path: Path) -> None:
    """Run the same checks as `tw-patcher validate` and stop before RPFM on errors."""
    from ...data.analysis import validate_patch
    from ...data.index import Mod, ModIndex
    from .._data import open_schema

    schema = open_schema()
    sources = ModIndex(settings.sources_dir, patch_path.parent).sources
    issues = validate_patch(Mod(patch_path.name, "patch", patch_path), schema, sources)
    errors = [i for i in issues if i.level == "error"]
    for i in issues:
        where = f"{i.file}:{i.line}" if i.line else i.file
        (console.error if i.level == "error" else console.warning)(f"{where}: {i.message}")
    if errors:
        console.error(f"Not repacking: {len(errors)} validation error(s). Fix them, or pass --no-validate to skip.")
        sys.exit(1)
