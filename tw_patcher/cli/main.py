"""Root CLI group definition."""

import click

from ..config import settings
from ..console import console
from ..models.game import GAME_KEYS
from ._rich import RichGroup


@click.group(cls=RichGroup)
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose logging')
@click.option('-g', '--game', type=click.Choice(GAME_KEYS, case_sensitive=False),
              default=None, help='Select game (persisted for future runs)')
def cli(verbose: bool, game: str | None) -> None:
    """Total War Mod Patcher - Extract and repack Total War mod pack files."""
    if verbose:
        console.verbose = True
    if game:
        settings.select_game(game)
        settings.save_user_config()


# Import commands to register them on the cli group
from . import commands as _commands  # noqa: E402, F401
