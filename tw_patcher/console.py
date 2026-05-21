from contextlib import contextmanager
from typing import Generator

from rich.console import Console as RichConsole
from rich.theme import Theme


_theme = Theme({
    "error": "bold red",
    "warning": "yellow",
    "success": "bold green",
    "info": "dim",
    "header": "bold",
    "hint": "dim italic",
    "item": "default",
})


class Console:
    def __init__(self):
        self._console = RichConsole(theme=_theme, highlight=False)
        self._err = RichConsole(theme=_theme, stderr=True, highlight=False)
        self.verbose = False

    def error(self, msg: str) -> None:
        self._err.print(f"[error]✗[/error] {msg}", style="error")

    def warning(self, msg: str) -> None:
        self._err.print(f"[warning]⚠[/warning] {msg}", style="warning")

    def success(self, msg: str) -> None:
        self._console.print(f"[success]✓[/success] {msg}", style="success")

    def info(self, msg: str) -> None:
        if self.verbose:
            self._console.print(msg, style="info")

    def header(self, msg: str) -> None:
        self._console.print(msg, style="header")

    def hint(self, msg: str) -> None:
        self._console.print(f"  {msg}", style="hint")

    def item(self, msg: str) -> None:
        self._console.print(f"  {msg}")

    @contextmanager
    def status(self, msg: str) -> Generator[None, None, None]:
        if self.verbose:
            with self._console.status(msg, spinner="dots"):
                yield
        else:
            with self._console.status(msg, spinner="dots"):
                yield


console = Console()
