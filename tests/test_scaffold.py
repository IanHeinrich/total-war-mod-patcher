"""Outside-in tests of `tw-patcher scaffold`: generated docs, AI instructions and .mcp.json."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from .conftest import Workspace
from .fake_rpfm import FakeRPFM

MARKER = "<!-- tw-patcher:generated"


def read_mcp(target: Path) -> dict:
    return json.loads((target / ".mcp.json").read_text(encoding="utf-8"))


def test_scaffold_writes_mcp_config_for_this_tw_patcher(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"

    result = offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    server = read_mcp(target)["mcpServers"]["tw-patcher"]
    assert server == {"type": "stdio", "command": sys.executable, "args": ["-m", "tw_patcher", "mcp"]}
    assert "rpfm" not in read_mcp(target)["mcpServers"]


def test_mcp_config_entry_starts_a_working_server(offline_ws: Workspace, tmp_path: Path) -> None:
    client_mod = pytest.importorskip("mcp.client.client")
    stdio = pytest.importorskip("mcp.client.stdio")
    target = tmp_path / "project"
    offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")
    entry = read_mcp(target)["mcpServers"]["tw-patcher"]

    async def list_tool_names() -> set[str]:
        params = stdio.StdioServerParameters(command=entry["command"], args=entry["args"], env=offline_ws.env)
        async with client_mod.Client(params) as client:
            return {t.name for t in (await client.list_tools()).tools}

    names = asyncio.run(asyncio.wait_for(list_tool_names(), timeout=60))
    assert {"workspace_status", "query_rows", "upsert_rows", "repack"} <= names


def test_scaffold_keeps_other_mcp_servers(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    (target / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")

    result = offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    servers = read_mcp(target)["mcpServers"]
    assert servers["other"] == {"command": "x"}
    assert "tw-patcher" in servers


def test_scaffold_leaves_an_invalid_mcp_json_alone(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    (target / ".mcp.json").write_text("{ not json", encoding="utf-8")

    result = offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    assert (target / ".mcp.json").read_text(encoding="utf-8") == "{ not json"
    assert ".mcp.json" in result.stderr


def test_rpfm_mcp_endpoint_registered_only_for_a_running_rpfm_5(ws: Workspace, rpfm: FakeRPFM, tmp_path: Path) -> None:
    target = tmp_path / "project"

    result = ws.run("scaffold", "--target", str(target))

    assert result.exit_code == 0, result.output
    servers = read_mcp(target)["mcpServers"]
    if rpfm.dialect == "jsonrpc":  # RPFM 5 answers GET /version
        assert servers["rpfm"] == {"type": "http", "url": f"http://127.0.0.1:{rpfm.port}/mcp"}
    else:  # RPFM 4 has no MCP endpoint
        assert "rpfm" not in servers
        assert "RPFM 5 isn't running" in result.stdout


def test_no_rpfm_mcp_wins_over_detection(ws: Workspace, rpfm: FakeRPFM, tmp_path: Path) -> None:
    target = tmp_path / "project"

    result = ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    assert "rpfm" not in read_mcp(target)["mcpServers"]


def test_generated_instructions_describe_the_tools_and_format(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"
    offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")

    claude = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith(MARKER)
    for tool in ("query_rows", "upsert_rows", "find_conflicts", "validate_patch", "add_key_deletes"):
        assert f"`{tool}`" in claude or tool in claude
    assert "Line 1 holds the column names, line 2 RPFM's metadata" in claude
    tsv_doc = (target / "modding_docs" / "TSV_FORMAT.md").read_text(encoding="utf-8")
    assert "**Line 2**: metadata" in tsv_doc
    assert (target / ".github" / "copilot-instructions.md").read_text(encoding="utf-8") == claude


def test_update_refreshes_generated_files_and_keeps_edited_ones(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"
    offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")
    workflow = target / "modding_docs" / "WORKFLOW.md"
    fresh = workflow.read_text(encoding="utf-8")
    workflow.write_text(MARKER + " 0.1.0 -->\nold generated text\n", encoding="utf-8")
    (target / "CLAUDE.md").write_text("# my own notes\n", encoding="utf-8")

    plain = offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")
    assert workflow.read_text(encoding="utf-8").endswith("old generated text\n"), "no --update: nothing replaced"
    assert plain.exit_code == 0

    result = offline_ws.run("scaffold", "--target", str(target), "--update", "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    assert workflow.read_text(encoding="utf-8") == fresh
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "# my own notes\n"
    assert "Left alone" in result.stderr and "CLAUDE.md" in result.stderr


def test_force_overwrites_edited_files(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"
    offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")
    (target / "CLAUDE.md").write_text("# my own notes\n", encoding="utf-8")

    result = offline_ws.run("scaffold", "--target", str(target), "--force", "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    assert (target / "CLAUDE.md").read_text(encoding="utf-8").startswith(MARKER)


def test_rerun_reports_up_to_date(offline_ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "project"
    offline_ws.run("scaffold", "--target", str(target), "--no-rpfm-mcp")

    result = offline_ws.run("scaffold", "--target", str(target), "--update", "--no-rpfm-mcp")

    assert result.exit_code == 0, result.output
    assert "already up to date" in result.stdout
