import sys
from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console as RichConsole
from rich.markup import escape
from rich.theme import Theme


def _force_utf8_streams() -> None:
    """Output uses characters such as ✓ and →. On Windows a redirected stdout
    (a pipe, a file, an LLM tool capturing output) defaults to cp1252 and
    crashes on them, so switch non-UTF-8 streams to UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            except (OSError, ValueError):
                pass


_force_utf8_streams()

_theme = Theme(
    {
        "error": "bold red",
        "warning": "yellow",
        "success": "bold green",
        "info": "dim",
        "header": "bold",
        "hint": "dim italic",
        "item": "default",
    }
)


class Console:
    def __init__(self):
        self._console = RichConsole(theme=_theme, highlight=False, soft_wrap=True)
        self._err = RichConsole(theme=_theme, stderr=True, highlight=False, soft_wrap=True)
        self.verbose = False

    def error(self, msg: str) -> None:
        self._err.print(f"[error]✗[/error] {escape(msg)}", style="error")

    def warning(self, msg: str) -> None:
        self._err.print(f"[warning]⚠[/warning] {escape(msg)}", style="warning")

    def success(self, msg: str) -> None:
        self._console.print(f"[success]✓[/success] {escape(msg)}", style="success")

    def info(self, msg: str) -> None:
        if self.verbose:
            self._console.print(escape(msg), style="info")

    def header(self, msg: str) -> None:
        self._console.print(escape(msg), style="header")

    def hint(self, msg: str) -> None:
        self._console.print(f"  {escape(msg)}", style="hint")

    def item(self, msg: str) -> None:
        self._console.print(f"  {escape(msg)}")

    def plain(self, text: str = "") -> None:
        """Print verbatim to stdout: no markup, no wrapping (tables, JSON, data an LLM will parse)."""
        self._console.file.write(text + "\n")

    @contextmanager
    def status(self, msg: str) -> Generator[None, None, None]:
        if self.verbose:
            with self._console.status(msg, spinner="dots"):
                yield
        else:
            with self._console.status(msg, spinner="dots"):
                yield


console = Console()
