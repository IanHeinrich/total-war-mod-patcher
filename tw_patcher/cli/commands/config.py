from pathlib import Path

import click

from ...config import settings
from ...console import console
from .._rich import RichGroup
from ..main import cli


@cli.group(cls=RichGroup)
def config() -> None:
    """View or update configuration settings."""
    pass


@config.command("show")
def config_show() -> None:
    """Display current configuration."""
    console.item(f"Config file:      {settings.config_file}")
    console.item(f"Selected game:    {settings.selected_game or '(none)'}")
    console.item(f"Modding root:     {settings.modding_root or '(default)'}")
    console.item(f"RPFM path:        {settings.rpfm_path or '(auto-detect)'}")
    if settings.game_dirs:
        console.item("Game directories:")
        for key, path in settings.game_dirs.items():
            console.item(f"  {key}: {path}")


@config.command("set-rpfm")
@click.argument("path", type=click.Path(exists=True))
def config_set_rpfm(path: str) -> None:
    """Set the path to the RPFM installation directory or executable."""
    rpfm_path = Path(path).resolve()
    settings.rpfm_path = rpfm_path
    settings.save_user_config()
    console.success(f"RPFM path set to: {rpfm_path}")
