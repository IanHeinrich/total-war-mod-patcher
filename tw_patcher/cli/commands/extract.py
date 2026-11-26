import asyncio
import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ...services.extraction import ExtractionService
from .._helpers import create_client, create_system_service, report_failures, require_game
from ..main import cli


@cli.command()
@click.option(
    "--source",
    "-s",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Source .pack file (can specify up to 6 times)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (default: sources/)",
)
@click.option(
    "--sources-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override sources directory (alternative to --output)",
)
@click.option("--dry-run", is_flag=True, help="List what would be extracted and replaced, without writing anything")
def extract(source: tuple[Path, ...], output: Path | None, sources_dir: Path | None, dry_run: bool) -> None:
    """Extract one or more mod pack files to TSV format.

    Exits with status 1 if any table or script failed to extract (the rest are
    still written), so scripts and LLM tools can tell a partial extraction apart.

    Examples:

        tw-patcher extract -s mod1.pack -s mod2.pack
        tw-patcher extract -s mod.pack --sources-dir D:\\Modding\\sources
        tw-patcher extract -s mod.pack --dry-run
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

    async def _run(action):
        system = create_system_service()
        client = create_client()
        await system.connect_client(client)
        try:
            return await action(ExtractionService(settings, client))
        finally:
            await client.disconnect()

    if dry_run:
        try:
            plans = asyncio.run(_run(lambda svc: svc.plan_batch(list(source), target_dir)))
        except Exception as e:
            console.error(f"Extraction dry run failed: {e}")
            sys.exit(1)
        console.header("Dry run: nothing was written.")
        for plan in plans:
            note = " (replaces existing folder)" if plan.replaces_existing else ""
            console.item(
                f"{plan.pack_path.name} → {plan.output_dir}{note}: "
                f"{len(plan.tables)} tables, {len(plan.scripts)} scripts"
            )
        return

    try:
        results = asyncio.run(_run(lambda svc: svc.extract_batch(list(source), target_dir)))
    except Exception as e:
        console.error(f"Extraction failed: {e}")
        report_failures(getattr(e, "failed_tables", []), "item(s)")
        sys.exit(1)

    total_tables = sum(len(r.tables_exported) for r in results)
    total_scripts = sum(len(r.scripts_extracted) for r in results)
    failures = [f for r in results for f in r.failures]
    summary = f"{len(results)} mod(s): {total_tables} tables, {total_scripts} scripts to: {target_dir}"
    if failures:
        console.warning(f"Extracted {summary}")
        report_failures(failures, "table(s)/script(s)")
        sys.exit(1)

    console.success(f"Extracted {summary}")
    console.header("\nNext steps:")
    console.hint("1. Compare extracted tables/scripts in sources/")
    console.hint("2. Create a patch mod folder: workspace/<name>/db/")
    console.hint("3. Repack: tw-patcher repack --patch <name>")
