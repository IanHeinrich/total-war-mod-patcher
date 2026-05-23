import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ..main import cli


@cli.command()
@click.option(
    '--target', '-t',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Target directory to scaffold (default: modding workspace root)'
)
def scaffold(target: Path | None) -> None:
    """Generate modding docs and AI helper files in the workspace."""
    from ...services.scaffold import ScaffoldService

    target_dir = target or settings.modding_root
    if not target_dir:
        console.error("No target directory. Use --target or set a modding workspace first.")
        sys.exit(1)

    target_dir.mkdir(parents=True, exist_ok=True)
    service = ScaffoldService(target_dir)
    created = service.scaffold()

    if created:
        console.success(f"Generated {len(created)} file(s) in {target_dir}")
        for path in created:
            console.item(f"  {path.relative_to(target_dir)}")
    else:
        console.info("All helper files already exist — nothing to generate.")
