"""Entry point for PyInstaller and `python -m tw_patcher`."""

from tw_patcher.cli import cli

if __name__ == "__main__":
    cli()  # type: ignore[call-arg]  # Click handles arg parsing from sys.argv
