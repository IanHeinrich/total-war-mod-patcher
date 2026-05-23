from pathlib import Path

import click

from ...config import settings
from ...console import console
from ..main import cli


@cli.command()
@click.option(
    '--sources-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override sources directory to clean'
)
@click.option(
    '--output-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override output directory to clean'
)
def clean(sources_dir: Path | None, output_dir: Path | None) -> None:
    """Remove all files from sources/ and output/ to start fresh."""
    import shutil

    settings.ensure_dirs()
    removed = 0

    dirs_to_clean = [
        sources_dir or settings.sources_dir,
        output_dir or settings.output_dir,
    ]

    for directory in dirs_to_clean:
        for child in directory.iterdir():
            if child.name.startswith('.'):
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1

    console.success(f"Cleaned {removed} item(s) from sources/ and output/")
