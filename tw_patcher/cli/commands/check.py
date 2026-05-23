import asyncio
import sys

from ...config import settings
from ...console import console
from ...models.game import GAMES
from .._helpers import create_client, create_system_service
from ..main import cli


@cli.command()
def check() -> None:
    """Check RPFM installation and server status."""
    try:
        system = create_system_service()
        system.check_system()

        if settings.selected_game:
            game_def = GAMES[settings.selected_game]
            console.info(f"Selected game: {game_def.display_name} ({settings.selected_game})")
        else:
            console.warning("No game selected (use --game to set one)")

        async def _run():
            client = create_client()
            await system.connect_client(client)
            await client.disconnect()
            console.success("RPFM server connectivity OK")

        asyncio.run(_run())
        console.success("All checks passed!")

    except Exception as e:
        console.error(f"Check failed: {e}")
        sys.exit(1)
