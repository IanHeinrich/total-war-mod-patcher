import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import settings
from .console import console
from .clients.rpfm import RPFMClient
from .models.game import GAME_KEYS, GAMES
from .services.system import SystemService
from .services.extraction import ExtractionService
from .services.repacking import RepackingService

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
            _rich.print()


            _rich.print("[dim]Workflow: extract → compare → patch → repack[/dim]")
            _rich.print("[dim]Run 'tw-patcher <command> --help' for command details.[/dim]")
        else:
            _rich.print("\n  [cyan]--help[/]  Show this message and exit")

        _rich.print()


def _create_system_service() -> SystemService:
    return SystemService(settings)


def _create_client() -> RPFMClient:
    return RPFMClient(settings.rpfm_host, settings.rpfm_port, settings.rpfm_timeout)


def _require_game() -> None:
    if not settings.selected_game:
        console.error("No game selected. Use --game <key> or select a game in the UI.")
        console.hint("Available games:")
        for key, game in GAMES.items():
            console.item(f"  {key:25s} {game.display_name}")
        sys.exit(1)


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


@cli.command()
@click.option(
    '--source', '-s',
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help='Source .pack file (can specify up to 6 times)'
)
@click.option(
    '--output', '-o',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=f'Output directory (default: sources/)'
)
@click.option(
    '--sources-dir',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Override sources directory (alternative to --output)'
)
def extract(source: tuple[Path, ...], output: Path | None, sources_dir: Path | None) -> None:
    """Extract one or more mod pack files to TSV format.

    Examples:\b

        tw-patcher extract -s mod1.pack -s mod2.pack
        tw-patcher extract -s mod.pack --sources-dir D:\\Modding\\sources
    """
    if not source:
        console.error("At least one --source is required.")
        sys.exit(1)
    if len(source) > settings.max_mods:
        console.error(f"Maximum {settings.max_mods} source mods allowed.")
        sys.exit(1)

    _require_game()
    settings.ensure_dirs()
    target_dir = output or sources_dir or settings.sources_dir

    async def _run() -> list:
        system = _create_system_service()
        client = _create_client()
        await system.connect_client(client)
        try:
            service = ExtractionService(settings, client)
            return await service.extract_batch(list(source), target_dir)
        finally:
            await client.disconnect()

    try:
        results = asyncio.run(_run())

        total = sum(r.success_count for r in results)
        console.success(f"Extracted {len(source)} mod(s), {total} tables to: {target_dir}")
        console.header("\nNext steps:")
        console.hint("1. Compare extracted tables in sources/")
        console.hint("2. Create a patch mod: mkdir workspace\\<name>\\db")
        console.hint("3. Repack: tw-patcher repack --patch <name>")

    except Exception as e:
        console.error(f"Extraction failed: {e}")
        sys.exit(1)


@cli.command('list')
@click.option(
    '--workspace-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override workspace directory to list patch mods from'
)
def list_cmd(workspace_dir: Path | None) -> None:
    """List available patch mods in the workspace."""
    settings.ensure_dirs()
    ws = workspace_dir or settings.workspace_dir

    mods = sorted(
        d.name for d in ws.iterdir()
        if d.is_dir() and not d.name.startswith('.')
    ) if ws.exists() else []

    if not mods:
        console.warning(f"No patch mods found in {ws}")
        console.hint("Create one: mkdir workspace\\my_patch\\db")
        return

    console.header(f"Patch mods in {ws} ({len(mods)}):\n")
    for mod_name in mods:
        mod_path = ws / mod_name
        tsv_count = len(list(mod_path.glob("**/*.tsv")))
        console.item(f"{mod_name}/ — {tsv_count} table(s)")


@cli.command()
@click.option(
    '--patch', '-p',
    required=True,
    type=str,
    help='Name of the patch mod in workspace/ to repack'
)
@click.option(
    '--output', '-o',
    type=click.Path(path_type=Path),
    default=None,
    help='Output .pack file path (default: output/<patch_name>.pack)'
)
@click.option(
    '--name', '-n',
    type=str,
    default=None,
    help='Custom output filename (without .pack extension)'
)
@click.option(
    '--workspace-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override workspace directory containing the patch mod'
)
@click.option(
    '--output-dir',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Override output directory for the .pack file'
)
def repack(patch: str, output: Path | None, name: str | None,
           workspace_dir: Path | None, output_dir: Path | None) -> None:
    """Repack a patch mod from workspace/ into a .pack file.

    Examples:\b

        tw-patcher repack --patch empire_rebalance
        tw-patcher repack --patch elf_fix --workspace-dir D:\\Modding\\workspace
    """
    _require_game()
    settings.ensure_dirs()

    ws = workspace_dir or settings.workspace_dir
    patch_path = ws / patch
    if not patch_path.exists():
        available = sorted(
            d.name for d in ws.iterdir()
            if d.is_dir() and not d.name.startswith('.')
        ) if ws.exists() else []
        console.error(f"Patch mod '{patch}' not found in {ws}")
        if available:
            console.hint(f"Available: {', '.join(available)}")
        else:
            console.hint(f"No patch mods exist yet. Create one: mkdir workspace\\{patch}\\db")
        sys.exit(1)

    out_dir = output_dir or settings.output_dir
    effective_output = output
    if not effective_output:
        out_dir.mkdir(parents=True, exist_ok=True)
        pack_name = name or patch
        effective_output = out_dir / f"{pack_name}.pack"

    try:
        async def _run():
            system = _create_system_service()
            client = _create_client()
            await system.connect_client(client)
            try:
                service = RepackingService(settings, client)
                return await service.repack(patch, effective_output, name,
                                            workspace_dir=ws)
            finally:
                await client.disconnect()

        result = asyncio.run(_run())

        console.success(f"Pack file created: {result.output_path}")
        console.item(f"{result.success_count}/{result.total_count} tables imported")

    except Exception as e:
        console.error(f"Repacking failed: {e}")
        sys.exit(1)


@cli.command()
def check() -> None:
    """Check RPFM installation and server status."""
    try:
        system = _create_system_service()
        system.check_system()

        if settings.selected_game:
            game_def = GAMES[settings.selected_game]
            console.info(f"Selected game: {game_def.display_name} ({settings.selected_game})")
        else:
            console.warning("No game selected (use --game to set one)")

        async def _run():
            client = _create_client()
            await system.connect_client(client)
            await client.disconnect()
            console.success("RPFM server connectivity OK")

        asyncio.run(_run())
        console.success("All checks passed!")

    except Exception as e:
        console.error(f"Check failed: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    '--sources-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override sources directory to clean'
)
@click.option(
    '--output-dir',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Override output directory to clean'
)
def clean(sources_dir: Path | None, output_dir: Path | None) -> None:
    """Remove all files from sources/ and output/ to start fresh."""
    import shutil

    settings.ensure_dirs()
    removed = 0

    dirs_to_clean = [
        sources_dir or settings.sources_dir,
        output_dir or settings.output_dir,
    ]

    for directory in dirs_to_clean:
        for child in directory.iterdir():
            if child.name.startswith('.'):
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1

    console.success(f"Cleaned {removed} item(s) from sources/ and output/")


@cli.command()
@click.option(
    '--target', '-t',
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help='Target directory to scaffold (default: modding workspace root)'
)
def scaffold(target: Path | None) -> None:
    """Generate modding docs and AI helper files in the workspace."""
    from .services.scaffold import ScaffoldService

    target_dir = target or settings.modding_root
    if not target_dir:
        console.error("No target directory. Use --target or set a modding workspace first.")
        sys.exit(1)

    target_dir.mkdir(parents=True, exist_ok=True)
    service = ScaffoldService(target_dir)
    created = service.scaffold()

    if created:
        console.success(f"Generated {len(created)} file(s) in {target_dir}")
        for path in created:
            console.item(f"  {path.relative_to(target_dir)}")
    else:
        console.info("All helper files already exist — nothing to generate.")


@cli.command()
def ui() -> None:
    """Launch the graphical user interface."""
    try:
        from .ui import launch_ui
        launch_ui()
    except ImportError:
        console.error("PyQt6 is required for the UI.")
        console.hint("Install it: pip install PyQt6")
        sys.exit(1)


@cli.group(cls=RichGroup)
def config() -> None:
    """View or update configuration settings."""
    pass


@config.command("show")
def config_show() -> None:
    """Display current configuration."""
    console.item(f"Config file:      {settings.config_file}")
    console.item(f"Selected game:    {settings.selected_game or '(none)'}")
    console.item(f"Modding root:     {settings.modding_root or '(default)'}")
    console.item(f"RPFM path:        {settings.rpfm_path or '(auto-detect)'}")
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


if __name__ == '__main__':
    cli() # type: ignore
