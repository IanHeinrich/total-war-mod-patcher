"""Rich-formatted Click command and group classes."""

import click
from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.table import Table

from ..config import settings
from ..models.game import GAMES

_rich = RichConsole(highlight=False)


class RichCommand(click.Command):
    """Click command with Rich-formatted help output."""

    def _parse_help(self, help_text: str) -> tuple[str, str]:
        """Split help text into description and examples."""
        text = help_text.replace("\b", "")
        lines = text.splitlines()
        desc_lines: list[str] = []
        example_lines: list[str] = []
        in_examples = False
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("example"):
                in_examples = True
                continue
            if in_examples:
                if stripped:
                    example_lines.append(stripped)
            else:
                if stripped:
                    desc_lines.append(stripped)
        return " ".join(desc_lines), "\n".join(example_lines)

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _rich.print()

        pieces = self.collect_usage_pieces(ctx)
        usage = " ".join(pieces)
        prog = ctx.command_path
        _rich.print(f"[bold]Usage:[/bold] [cyan]{prog}[/cyan] {usage}")

        help_text = self.help or ""
        desc, examples = self._parse_help(help_text)
        if desc:
            _rich.print(f"\n  {desc}")

        params = self.get_params(ctx)
        opts = [p for p in params if isinstance(p, click.Option) and p.name != "help"]
        if opts:
            table = Table(show_header=False, box=None, padding=(0, 2), expand=False)
            table.add_column("Option", style="cyan", no_wrap=True)
            table.add_column("Description")

            for param in opts:
                all_opts = param.opts + param.secondary_opts
                decls = ", ".join(all_opts)
                help_str = param.help or ""
                if param.required:
                    help_str += " [yellow](required)[/yellow]"
                elif param.default and not param.is_flag and param.multiple:
                    pass
                elif param.default and not param.is_flag and param.default != () and "default:" not in help_str:
                    help_str += f" [dim](default: {param.default})[/dim]"
                table.add_row(decls, help_str)

            table.add_row("--help", "Show this message and exit")
            _rich.print("\n[bold]Options:[/bold]")
            _rich.print(table)

        if examples:
            _rich.print("\n[bold]Examples:[/bold]")
            for line in examples.splitlines():
                line = line.strip()
                if line:
                    _rich.print(f"  [dim]$[/dim] [green]{line}[/green]")

        _rich.print()

    def get_help(self, ctx: click.Context) -> str:
        """Render Rich output directly and return empty to suppress Click's echo."""
        self.format_help(ctx, ctx.make_formatter())
        return ""


class RichGroup(click.Group):
    """Click group with Rich-formatted help output."""
    command_class = RichCommand

    def get_help(self, ctx: click.Context) -> str:
        """Render Rich output directly and return empty to suppress Click's echo."""
        self.format_help(ctx, ctx.make_formatter())
        return ""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        _rich.print()

        is_root = ctx.parent is None

        if is_root:
            _rich.print(Panel.fit(
                "[bold]Total War Mod Patcher[/bold]\n"
                "[dim]Extract, compare, and repack Total War mod pack files.[/dim]",
                border_style="blue",
            ))
        else:
            desc = self.help or ""
            prog = ctx.command_path
            _rich.print(f"[bold]Usage:[/bold] [cyan]{prog}[/cyan] [OPTIONS] COMMAND")
            if desc:
                _rich.print(f"\n  {desc}")

        commands = self.list_commands(ctx)
        if commands:
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
            table.add_column("Command", style="cyan", no_wrap=True)
            table.add_column("Description")

            for cmd_name in commands:
                cmd = self.get_command(ctx, cmd_name)
                if cmd and not cmd.hidden:
                    help_text = cmd.get_short_help_str(limit=60)
                    table.add_row(cmd_name, help_text)

            _rich.print("\n[bold]Commands:[/bold]")
            _rich.print(table)

        if is_root:
            _rich.print("\n[bold]Options:[/bold]")
            _rich.print("  [cyan]-v, --verbose[/]    Enable verbose logging")
            _rich.print("  [cyan]-g, --game[/]       Select game (persisted for future runs)")
            _rich.print("  [cyan]--help[/]           Show this message and exit")

            _rich.print("\n[bold]Status:[/bold]")
            game = settings.selected_game
            if game:
                game_def = GAMES[game]
                _rich.print(f"  Game:      [green]{game_def.display_name}[/green] ({game})")
            else:
                _rich.print("  Game:      [yellow]Not selected[/yellow] (use -g to set)")
            if settings.modding_root:
                _rich.print(f"  Workspace: {settings.modding_root}")
            else:
                _rich.print("  Workspace: [yellow]Not set[/yellow]")
            if settings.rpfm_path:
                _rich.print(f"  RPFM:      {settings.rpfm_path}")
            else:
                _rich.print("  RPFM:      [yellow]Not set[/yellow] (use 'tw-patcher config set-rpfm <path>')")
            _rich.print()

            _rich.print("[dim]Workflow: extract → compare → patch → repack[/dim]")
            _rich.print("[dim]Run 'tw-patcher <command> --help' for command details.[/dim]")
        else:
            _rich.print("\n  [cyan]--help[/]  Show this message and exit")

        _rich.print()
