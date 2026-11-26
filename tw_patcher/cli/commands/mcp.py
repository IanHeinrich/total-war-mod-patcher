"""``tw-patcher mcp``: serve the workspace tools to an MCP client over stdio."""

from ...console import console
from ..main import cli


@cli.command("mcp")
def mcp_cmd() -> None:
    """Run tw-patcher's MCP server on stdio, for Claude Code, Claude Desktop and other MCP clients.

    Register it once (Claude Code):\b

        claude mcp add tw-patcher -- tw-patcher mcp

    `tw-patcher scaffold` writes a .mcp.json that registers it (and RPFM 5's own MCP endpoint) for a
    modding folder. Logs go to stderr; stdout carries the protocol.
    """
    try:
        from ...mcp_server import run
    except ModuleNotFoundError as e:
        if e.name and e.name.split(".")[0] == "mcp":
            console.error("The MCP server needs the 'mcp' package: pip install \"tw-mod-patcher[mcp]\"")
            raise SystemExit(1) from None
        raise
    run()
