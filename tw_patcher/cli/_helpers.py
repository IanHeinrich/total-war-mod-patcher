"""Shared helpers for CLI commands."""

import sys

from ..clients.rpfm import RPFMClient
from ..config import settings
from ..console import console
from ..models.game import GAMES
from ..services.system import SystemService


def create_system_service() -> SystemService:
    return SystemService(settings)


def create_client() -> RPFMClient:
    return RPFMClient(settings.rpfm_host, settings.rpfm_port, settings.rpfm_timeout)


def require_game() -> None:
    if not settings.selected_game:
        console.error("No game selected. Use --game <key> or select a game in the UI.")
        console.hint("Available games:")
        for key, game in GAMES.items():
            console.item(f"  {key:25s} {game.display_name}")
        sys.exit(1)
