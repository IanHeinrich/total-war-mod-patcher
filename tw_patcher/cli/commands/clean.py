import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ..main import cli


@cli.command()
@click.option(
    "--sources-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override sources directory to clean",
)
@click.option(
    "--output-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override output directory to clean",
)
@click.option("--yes", "-y", is_flag=True, help="Delete without asking for confirmation")
@click.option("--dry-run", is_flag=True, help="List what would be deleted, without deleting")
def clean(sources_dir: Path | None, output_dir: Path | None, yes: bool, dry_run: bool) -> None:
    """Remove all extracted sources and built packs (sources/ and output/) to start fresh.

    Patch mods in workspace/ are never touched. Asks for confirmation unless
    --yes is given; non-interactive callers must pass --yes.
    """
    import shutil

    settings.ensure_dirs()
    dirs_to_clean = [sources_dir or settings.sources_dir, output_dir or settings.output_dir]
    targets = [
        child for directory in dirs_to_clean for child in sorted(directory.iterdir()) if not child.name.startswith(".")
    ]

    if not targets:
        console.success("Nothing to clean: sources/ and output/ are already empty")
        return

    console.header(f"{'Would delete' if dry_run else 'Will delete'} {len(targets)} item(s):")
    for child in targets:
        console.item(f"{child}{'/' if child.is_dir() else ''}")

    if dry_run:
        return

    if not yes and not click.confirm("Delete these?", default=False):
        console.warning("Nothing deleted")
        sys.exit(1)

    for child in targets:
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    console.success(f"Cleaned {len(targets)} item(s) from sources/ and output/")
