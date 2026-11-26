import asyncio
import sys
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

import click

from ...config import settings
from ...console import console
from ...data.index import ModIndex
from ...services.extraction import ExtractionService, source_statuses, vanilla_pack_path, workshop_pack_paths
from .._data import open_schema
from .._helpers import create_client, create_system_service, report_failures, require_game
from ..main import cli

Runner = Callable[[Callable[[ExtractionService], Awaitable[Any]]], Coroutine[Any, Any, Any]]


@cli.command()
@click.option(
    "--source",
    "-s",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Source .pack file (can specify up to 6 times)",
)
@click.option(
    "--workshop-id",
    "workshop_ids",
    multiple=True,
    help="Steam Workshop item ID: extracts every .pack in its Workshop folder (repeatable)",
)
@click.option(
    "--vanilla", is_flag=True, help="Also extract the game's data/db.pack to sources/vanilla/ (not counted in the 6)"
)
@click.option(
    "--table",
    "-t",
    "tables",
    multiple=True,
    help="Only export these db tables, e.g. land_units or land_units_tables (repeatable)",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Re-extract every source whose pack changed since it was extracted (see tw-patcher status)",
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
def extract(
    source: tuple[Path, ...],
    workshop_ids: tuple[str, ...],
    vanilla: bool,
    tables: tuple[str, ...],
    refresh: bool,
    output: Path | None,
    sources_dir: Path | None,
    dry_run: bool,
) -> None:
    """Extract one or more mod pack files to TSV format.

    Exports db tables and text/**/*.loc files as TSV and copies scripts.
    Exits with status 1 if anything failed to extract (the rest is still
    written), so scripts and LLM tools can tell a partial extraction apart.

    Examples:

        tw-patcher extract -s mod1.pack -s mod2.pack
        tw-patcher extract --workshop-id 2789857397 --vanilla -t land_units
        tw-patcher extract -s mod.pack --sources-dir D:\\Modding\\sources
        tw-patcher extract -s mod.pack --dry-run
        tw-patcher extract --refresh
    """
    if refresh:
        if source or workshop_ids or vanilla or tables:
            console.error(
                "--refresh re-extracts the sources recorded in sources/; "
                "don't combine it with --source, --workshop-id, --vanilla or --table."
            )
            sys.exit(1)
    elif not source and not workshop_ids and not vanilla:
        console.error("At least one --source is required (or --workshop-id, --vanilla, --refresh).")
        sys.exit(1)

    if len(source) > settings.max_mods:
        console.error(f"Maximum {settings.max_mods} source mods allowed.")
        sys.exit(1)

    require_game()
    settings.ensure_dirs()

    target_dir = output or sources_dir or settings.sources_dir

    async def _run(action: Callable[[ExtractionService], Awaitable[Any]]) -> Any:
        system = create_system_service()
        client = create_client()
        await system.connect_client(client)
        try:
            return await action(ExtractionService(settings, client))
        finally:
            await client.disconnect()

    if refresh:
        _refresh(target_dir, dry_run, _run)
        return

    try:
        packs = list(source) + workshop_pack_paths(settings, list(workshop_ids))
        vanilla_pack = vanilla_pack_path(settings) if vanilla else None
    except ValueError as e:
        console.error(str(e))
        sys.exit(1)

    if len(packs) > settings.max_mods:
        console.error(f"Maximum {settings.max_mods} source mods allowed.")
        sys.exit(1)

    table_filter = list(tables) or None

    if dry_run:
        try:
            plans = asyncio.run(_run(lambda svc: svc.plan_batch(packs, target_dir, table_filter, vanilla_pack)))
        except Exception as e:
            console.error(f"Extraction dry run failed: {e}")
            sys.exit(1)
        console.header("Dry run: nothing was written.")
        for plan in plans:
            note = " (replaces existing folder)" if plan.replaces_existing else ""
            console.item(
                f"{plan.pack_path.name} → {plan.output_dir}{note}: "
                f"{len(plan.tables)} tables, {len(plan.scripts)} scripts, {len(plan.locs)} loc files"
            )
        return

    try:
        results = asyncio.run(_run(lambda svc: svc.extract_batch(packs, target_dir, table_filter, vanilla_pack)))
    except Exception as e:
        console.error(f"Extraction failed: {e}")
        report_failures(getattr(e, "failed_tables", []), "item(s)")
        sys.exit(1)

    total_tables = sum(len(r.tables_exported) for r in results)
    total_scripts = sum(len(r.scripts_extracted) for r in results)
    total_locs = sum(len(r.locs_exported) for r in results)
    failures = [f for r in results for f in r.failures]
    counts = f"{total_tables} tables, {total_scripts} scripts, {total_locs} loc files"
    summary = f"{len(results)} mod(s): {counts} to: {target_dir}"
    if failures:
        console.warning(f"Extracted {summary}")
        report_failures(failures, "table(s)/script(s)")
        sys.exit(1)

    console.success(f"Extracted {summary}")
    console.header("\nNext steps:")
    console.hint("1. Compare: tw-patcher conflicts <mod> <mod> / tw-patcher diff <mod> <mod>")
    console.hint("2. Create a patch: tw-patcher new-patch <name> --from <mod> --table <table>")
    console.hint("3. Check and build: tw-patcher validate <name>, then tw-patcher repack --patch <name>")


def _refresh(target_dir: Path, dry_run: bool, run: Runner) -> None:
    index = ModIndex(target_dir, settings.workspace_dir)
    changed = [s for s in source_statuses(index) if s.state == "changed"]
    if not changed:
        console.success(f"Nothing to refresh: no source in {target_dir} changed since it was extracted")
        console.hint("tw-patcher status lists every source and its state")
        return

    if dry_run:
        console.header("Dry run: nothing was written. Would re-extract:")
        for status in changed:
            console.item(f"{status.name} ← {status.pack}")
        return

    schema = open_schema(quiet=True)
    try:
        outcomes = asyncio.run(run(lambda svc: svc.refresh(changed, index, schema)))
    except Exception as e:
        console.error(f"Refresh failed: {e}")
        sys.exit(1)

    failures: list[tuple[str, str]] = []
    for outcome in outcomes:
        name = outcome.source.name
        if outcome.result is None:
            failures.append((name, outcome.error or "unknown error"))
            continue
        r = outcome.result
        failures.extend(r.failures)
        console.success(
            f"Refreshed {name}: {len(r.tables_exported)} tables, {len(r.scripts_extracted)} scripts, "
            f"{len(r.locs_exported)} loc files"
        )
        if outcome.table_changes:
            console.header(f"  Row changes in {name} tables your patches also use:")
            for change in outcome.table_changes:
                console.item(f"  {change.table}: +{change.added} -{change.removed} ~{change.changed}")
        else:
            console.hint(f"No row changes in {name} tables your patches use")

    if failures:
        report_failures(failures, "item(s)")
        sys.exit(1)
