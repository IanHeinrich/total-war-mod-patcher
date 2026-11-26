from pathlib import Path

import click

from ...config import settings
from ...console import console
from ...models.game import GAME_KEYS
from .._data import emit_json, fail, json_option
from .._rich import RichGroup
from ..main import cli


@cli.group(cls=RichGroup)
def config() -> None:
    """View or update configuration settings."""
    pass


@config.command("show")
@json_option
def config_show(as_json: bool) -> None:
    """Display current configuration."""
    if as_json:
        emit_json(
            {
                "config_file": settings.config_file,
                "selected_game": settings.selected_game,
                "modding_root": settings.modding_root,
                "rpfm_path": settings.rpfm_path,
                "game_dirs": settings.game_dirs,
                "sources_dir": settings.sources_dir,
                "workspace_dir": settings.workspace_dir,
                "output_dir": settings.output_dir,
                "game_data_dir": settings.game_data_dir,
                "schema_dir": settings.schema_dir,
            }
        )
        return
    console.item(f"Config file:      {settings.config_file}")
    console.item(f"Selected game:    {settings.selected_game or '(none)'}")
    console.item(f"Modding root:     {settings.modding_root or '(default)'}")
    console.item(f"  sources/:       {settings.sources_dir}")
    console.item(f"  workspace/:     {settings.workspace_dir}")
    console.item(f"  output/:        {settings.output_dir}")
    console.item(f"Game data folder: {settings.game_data_dir or '(not set)'}")
    console.item(f"RPFM path:        {settings.rpfm_path or '(auto-detect)'}")
    console.item(f"Schema folder:    {settings.schema_dir or '(RPFM default)'}")
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


@config.command("set-modding-root")
@click.argument("path", type=click.Path(file_okay=False, path_type=Path))
def config_set_modding_root(path: Path) -> None:
    """Set the folder holding sources/, workspace/ and output/ (created if missing)."""
    root = path.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        fail(f"Could not create {root}: {e}")
    settings.modding_root = root
    settings.save_user_config()
    console.success(f"Modding root set to: {root}")


@config.command("set-game-dir")
@click.option(
    "--game",
    "game",
    type=click.Choice(GAME_KEYS, case_sensitive=False),
    default=None,
    help="Game to set the folder for (default: the selected game)",
)
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
def config_set_game_dir(game: str | None, path: Path) -> None:
    """Set a game's install folder (the one containing data/)."""
    key = game.lower() if game else settings.selected_game
    if not key:
        fail("No game selected. Pass --game <key>.")
    game_dir = path.resolve()
    if not (game_dir / "data").is_dir():
        fail(f"{game_dir} has no data/ folder; pick the game's install folder (the one containing data/)")
    settings.game_dirs[key] = game_dir
    settings.save_user_config()
    console.success(f"Game folder for {key} set to: {game_dir}")
