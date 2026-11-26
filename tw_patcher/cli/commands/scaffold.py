import sys
from pathlib import Path

import click

from ...config import settings
from ...console import console
from ..main import cli


@cli.command()
@click.option(
    "--target",
    "-t",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Target directory to scaffold (default: modding workspace root)",
)
@click.option("--update", is_flag=True, help="Refresh generated files that still carry tw-patcher's marker line")
@click.option("--force", is_flag=True, help="Overwrite generated files even if you edited them")
@click.option(
    "--rpfm-mcp/--no-rpfm-mcp",
    default=None,
    help="Register RPFM 5's MCP endpoint in .mcp.json (default: only if an RPFM 5 server is running)",
)
def scaffold(target: Path | None, update: bool, force: bool, rpfm_mcp: bool | None) -> None:
    """Set up a modding folder: sources/, workspace/, output/, docs, AI instructions and .mcp.json.

    Existing files are left alone unless --update (refresh files that still start with
    tw-patcher's marker line; delete that line to keep a file as yours) or --force.

    Examples:

        tw-patcher scaffold
        tw-patcher scaffold --update
        tw-patcher scaffold --target D:\\Modding --rpfm-mcp
    """
    from ...services.scaffold import ScaffoldService, probe_rpfm_mcp

    target_dir = target or settings.modding_root
    if not target_dir:
        console.error("No target directory. Use --target or set a modding workspace first.")
        sys.exit(1)

    url = None
    if rpfm_mcp is not False:
        url = probe_rpfm_mcp(settings.rpfm_host, settings.rpfm_port)
        if rpfm_mcp and not url:
            url = f"http://{settings.rpfm_host}:{settings.rpfm_port}/mcp"

    target_dir.mkdir(parents=True, exist_ok=True)
    result = ScaffoldService(target_dir).scaffold(update=update, force=force, rpfm_mcp_url=url)

    for label, paths in (("Created", result.created), ("Updated", result.updated)):
        if paths:
            console.success(f"{label} {len(paths)} file(s) in {target_dir}")
            for path in paths:
                console.item(str(path.relative_to(target_dir)))
    if result.kept:
        names = ", ".join(str(path.relative_to(target_dir)) for path in result.kept)
        console.warning(f"Left alone (edited by you, or not tw-patcher's; --force overwrites): {names}")
    if not (result.created or result.updated or result.kept):
        console.success(f"{target_dir} is already up to date")
    if url:
        console.hint(f"RPFM's MCP endpoint registered: {url}")
    elif rpfm_mcp is None:
        console.hint("RPFM 5 isn't running, so its MCP endpoint wasn't registered. Start it and run scaffold --update.")
