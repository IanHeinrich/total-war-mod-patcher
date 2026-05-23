import sys

from ...console import console
from ..main import cli


@cli.command()
def ui() -> None:
    """Launch the graphical user interface."""
    try:
        from ...ui import launch_ui
        launch_ui()
    except ImportError:
        console.error("PyQt6 is required for the UI.")
        console.hint("Install it: pip install PyQt6")
        sys.exit(1)
