import asyncio
import sys

from ...config import settings
from ...console import console
from ...models.game import GAMES
from .._helpers import create_client, create_system_service
from ..main import cli

PROTOCOL_NAMES = {
    "legacy": "legacy WebSocket commands (RPFM 4.x)",
    "jsonrpc": "JSON-RPC 2.0 (RPFM 5.x)",
}


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
            protocol, version = client.protocol, client.server_version
            await client.disconnect()
            console.success("RPFM server connectivity OK")
            console.item(f"RPFM protocol: {PROTOCOL_NAMES.get(protocol or '', protocol)}")
            if version:
                console.item(f"RPFM server version: {version}")

        asyncio.run(_run())
        console.success("All checks passed!")

    except Exception as e:
        console.error(f"Check failed: {e}")
        sys.exit(1)
