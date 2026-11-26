"""Outside-in tests of how tw-patcher picks between RPFM's legacy and JSON-RPC protocols."""

from __future__ import annotations

from .conftest import Workspace
from .fake_rpfm import VERSION, FakeRPFM, write_pack


def test_check_reports_the_detected_protocol(ws: Workspace, rpfm: FakeRPFM) -> None:
    result = ws.run("check")

    assert result.exit_code == 0, result.output
    assert "RPFM server connectivity OK" in result.output
    if rpfm.dialect == "jsonrpc":
        assert "RPFM protocol: JSON-RPC 2.0" in result.output
        assert f"RPFM server version: {VERSION}" in result.output
    else:
        assert "RPFM protocol: legacy WebSocket commands" in result.output
        assert "RPFM server version" not in result.output


def test_extract_reports_a_failed_game_selection(ws: Workspace, rpfm: FakeRPFM) -> None:
    # In the JSON-RPC dialect selecting a game is a job, so the failure arrives through job.wait.
    pack = write_pack(ws.root / "packs" / "mod_a.pack", {"script/a.lua": "-- a\n"})
    rpfm.fail("SetGameSelected", message="schema for warhammer_3 not found")

    result = ws.run("extract", "-s", str(pack))

    assert result.exit_code == 1
    assert "schema for warhammer_3 not found" in result.output


def test_check_says_goodbye_in_the_servers_own_protocol(ws: Workspace, rpfm: FakeRPFM) -> None:
    result = ws.run("check")

    assert result.exit_code == 0, result.output
    expected = "session.disconnect" if rpfm.dialect == "jsonrpc" else "ClientDisconnecting"
    assert rpfm.commands() == [expected]
