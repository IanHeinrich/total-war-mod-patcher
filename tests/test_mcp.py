"""Outside-in tests of `tw-patcher mcp`: the server runs as a subprocess and is
driven over stdio by a real MCP client, exactly as Claude Code would."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

from .conftest import Workspace, tsv
from .fake_rpfm import FakeRPFM, read_pack, write_pack

mcp_client = pytest.importorskip("mcp.client.client")
mcp_stdio = pytest.importorskip("mcp.client.stdio")

FIELD = (
    '(name: "{name}", field_type: {type}, is_key: {key}, default_value: None, is_filename: false, '
    'filename_relative_path: None, is_reference: {ref}, lookup: None, description: "", ca_order: 0, '
    "is_bitwise: 0, enum_values: {{}}, is_part_of_colour: None)"
)


def _table(name: str, version: int, fields: list[tuple[str, str, bool, str | None]]) -> str:
    rendered = ",\n".join(
        FIELD.format(
            name=n, type=t, key=str(k).lower(), ref=f'Some(("{r.split(".")[0]}", "{r.split(".")[1]}"))' if r else "None"
        )
        for n, t, k, r in fields
    )
    return f'"{name}": [(version: {version}, fields: [{rendered}], localised_fields: [], localised_key_order: [])]'


SCHEMA = (
    "(version: 5, definitions: {"
    + ",\n".join(
        [
            _table(
                "units_tables",
                0,
                [
                    ("key", "StringU8", True, None),
                    ("faction", "StringU8", False, "factions.key"),
                    ("cost", "I32", False, None),
                ],
            ),
            _table("factions_tables", 0, [("key", "StringU8", True, None), ("name", "StringU8", False, None)]),
            _table(
                "unit_effects_tables",
                0,
                [
                    ("unit", "StringU8", True, "units.key"),
                    ("effect", "StringU8", True, None),
                    ("value", "F32", False, None),
                ],
            ),
            _table(
                "twad_key_deletes_tables", 0, [("key", "StringU8", True, None), ("table_name", "StringU8", True, None)]
            ),
        ]
    )
    + "}, patches: {})"
)

UNITS = tsv(
    "units_tables", "mod_a", ["key", "faction", "cost"], [["unit_a", "fac_a", "800"], ["unit_b", "fac_a", "600"]]
)
FACTIONS = tsv("factions_tables", "mod_a", ["key", "name"], [["fac_a", "Faction A"]])
EFFECTS = tsv(
    "unit_effects_tables",
    "mod_a",
    ["unit", "effect", "value"],
    [["unit_a", "speed", "1.5"], ["unit_b", "armour", "2.0"]],
)


def setup_workspace(ws: Workspace) -> None:
    (ws.schemas / "schema_wh3.ron").write_text(SCHEMA, encoding="utf-8")
    ws.write("sources/mod_a/db/units_tables/mod_a.tsv", UNITS)
    ws.write("sources/mod_a/db/factions_tables/mod_a.tsv", FACTIONS)
    ws.write("sources/mod_a/db/unit_effects_tables/mod_a.tsv", EFFECTS)
    (ws.workspace / "my_patch" / "db").mkdir(parents=True)


class Session(Protocol):
    """Call a tool: returns (is_error, structured result or error text)."""

    def __call__(self, name: str, args: dict[str, Any] | None = None) -> Awaitable[tuple[bool, Any]]: ...

    list_tools: Callable[[], Awaitable[Any]]


def run_session(ws: Workspace, script: Callable[[Session], Awaitable[None]]) -> None:
    """Start `python -m tw_patcher mcp` in ws's environment and run ``script`` against it."""

    async def main() -> None:
        params = mcp_stdio.StdioServerParameters(
            command=sys.executable, args=["-m", "tw_patcher", "mcp"], env=ws.env, cwd=str(ws.root)
        )
        async with mcp_client.Client(params) as client:

            async def call(name: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
                result = await client.call_tool(name, args or {})
                if result.is_error:
                    return True, result.content[0].text if result.content else ""
                data = getattr(result, "structured_content", None)
                if data is None and result.content:
                    data = json.loads(result.content[0].text)
                if isinstance(data, dict) and set(data) == {"result"}:
                    data = data["result"]
                return False, data

            call.list_tools = client.list_tools  # type: ignore[attr-defined]
            await script(cast(Session, call))

    asyncio.run(asyncio.wait_for(main(), timeout=120))


def patch_file(ws: Workspace, rel: str) -> str:
    return (ws.workspace / "my_patch" / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- discovery and reads


def test_server_lists_its_tools(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        tools = await call.list_tools()
        names = {t.name for t in tools.tools}
        assert {
            "workspace_status",
            "list_tables",
            "describe_table",
            "query_rows",
            "find_key",
            "diff",
            "find_conflicts",
            "validate_patch",
            "new_patch",
            "upsert_rows",
            "delete_rows",
            "copy_rows",
            "add_key_deletes",
            "rpfm_status",
            "extract_packs",
            "repack",
        } <= names

    run_session(offline_ws, script)


def test_workspace_status_and_reads(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        err, status = await call("workspace_status")
        assert not err
        assert status["game"] == "warhammer_3"
        assert {"name": "sources/mod_a", "kind": "source", "tables": 3} in status["mods"]
        assert status["schema"].endswith("schema_wh3.ron")

        err, desc = await call("describe_table", {"table": "units", "mod": "mod_a"})
        assert not err
        assert desc["schema"]["key_columns"] == ["key"]
        assert {"name": "faction", "type": "StringU8", "key": False, "references": "factions_tables.key"} in desc[
            "schema"
        ]["columns"]
        assert desc["in_mod"]["header"] == ["key", "faction", "cost"]

        err, rows = await call("query_rows", {"table": "units", "mod": "mod_a", "columns": ["key", "cost"], "limit": 1})
        assert not err
        assert rows["total"] == 2 and rows["truncated"] is True
        assert rows["rows"][0]["values"] == {"key": "unit_a", "cost": "800"}

        err, rows = await call("query_rows", {"table": "unit_effects", "mod": "mod_a", "keys": ["unit_b|armour"]})
        assert not err
        assert [r["values"]["value"] for r in rows["rows"]] == ["2.0"]

        err, found = await call("find_key", {"key": "fac_a"})
        assert not err
        assert found["tables"]["factions_tables"][0]["mod"] == "sources/mod_a"

    run_session(offline_ws, script)


def test_errors_reach_the_model_with_their_reason(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        err, message = await call("query_rows", {"table": "buildings", "mod": "mod_a"})
        assert err
        assert "has no buildings_tables" in message

        err, message = await call("query_rows", {"table": "units", "mod": "nope"})
        assert err
        assert "No extracted mod or patch named 'nope'" in message

    run_session(offline_ws, script)


# ---------------------------------------------------------------------------- patch editing


def test_copy_upsert_delete_round_trip(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        err, res = await call(
            "copy_rows", {"source": "mod_a", "patch": "my_patch", "table": "units", "keys": ["unit_b"]}
        )
        assert not err, res
        assert res == {
            "file": "db/units_tables/my_patch.tsv",
            "inserted": 1,
            "updated": 0,
            "deleted": 0,
            "unchanged": 0,
        }

        err, res = await call(
            "upsert_rows",
            {
                "patch": "my_patch",
                "table": "units",
                "rows": [{"key": "unit_b", "cost": "650"}, {"key": "unit_c", "faction": "fac_a", "cost": "1"}],
            },
        )
        assert not err, res
        assert (res["inserted"], res["updated"]) == (1, 1)

        err, res = await call("delete_rows", {"patch": "my_patch", "table": "units", "keys": ["unit_c"]})
        assert not err, res
        assert res["files"][0]["deleted"] == 1

    run_session(offline_ws, script)
    assert patch_file(offline_ws, "db/units_tables/my_patch.tsv") == tsv(
        "units_tables", "my_patch", ["key", "faction", "cost"], [["unit_b", "fac_a", "650"]]
    )


def test_upsert_creates_a_table_from_the_schema(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        err, res = await call(
            "upsert_rows", {"patch": "my_patch", "table": "factions_tables", "rows": [{"key": "fac_b", "name": "B"}]}
        )
        assert not err, res

    run_session(offline_ws, script)
    assert patch_file(offline_ws, "db/factions_tables/my_patch.tsv") == tsv(
        "factions_tables", "my_patch", ["key", "name"], [["fac_b", "B"]]
    )


def test_bad_edits_are_refused_without_touching_files(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)
    offline_ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    before = patch_file(offline_ws, "db/units_tables/my_patch.tsv")

    async def script(call: Session) -> None:
        for args, expected in [
            ({"rows": [{"key": "x", "speed": "1"}]}, "Unknown column(s) for units_tables: speed"),
            ({"rows": [{"cost": "1"}]}, "missing key column(s) key"),
            ({"rows": [{"key": "x\ty"}]}, "can't contain tabs or line breaks"),
        ]:
            err, message = await call("upsert_rows", {"patch": "my_patch", "table": "units", **args})
            assert err and expected in message, message

    run_session(offline_ws, script)
    assert patch_file(offline_ws, "db/units_tables/my_patch.tsv") == before


def test_write_tools_only_touch_workspace_patches(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)
    source = offline_ws.sources / "mod_a" / "db" / "units_tables" / "mod_a.tsv"

    async def script(call: Session) -> None:
        for patch in ("../sources/mod_a", "sources/mod_a", "mod_a"):
            err, message = await call("upsert_rows", {"patch": patch, "table": "units", "rows": [{"key": "z"}]})
            assert err, patch
        err, message = await call("delete_rows", {"patch": "..", "table": "units", "keys": ["unit_a"]})
        assert err

    run_session(offline_ws, script)
    assert source.read_text(encoding="utf-8") == UNITS


def test_add_key_deletes_uses_rpfm_format(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        err, res = await call(
            "add_key_deletes", {"patch": "my_patch", "table": "unit_effects", "keys": ["unit_a|speed", "unit_b|armour"]}
        )
        assert not err, res

    run_session(offline_ws, script)
    # Composite keys are concatenated without a separator and the table name is the short form, like RPFM writes.
    assert patch_file(offline_ws, "db/twad_key_deletes_tables/my_patch.tsv") == tsv(
        "twad_key_deletes_tables",
        "my_patch",
        ["key", "table_name"],
        [["unit_aspeed", "unit_effects"], ["unit_barmour", "unit_effects"]],
    )


def test_new_patch_and_validate(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)

    async def script(call: Session) -> None:
        err, res = await call("new_patch", {"name": "fix", "from_mod": "mod_a", "tables": ["units"]})
        assert not err, res
        assert res["copied"] == ["db/units_tables/mod_a.tsv"]

        err, report = await call("validate_patch", {"patch": "fix"})
        assert not err
        assert report["errors"] == 0

        err, _ = await call(
            "upsert_rows", {"patch": "fix", "table": "units", "rows": [{"key": "unit_a", "cost": "lots"}]}
        )
        assert not err
        err, report = await call("validate_patch", {"patch": "fix"})
        assert not err
        assert report["errors"] == 1
        assert "cost='lots' is not a valid I32" in report["issues"][0]["message"]

    run_session(offline_ws, script)


def test_conflicts_and_diff(offline_ws: Workspace) -> None:
    setup_workspace(offline_ws)
    offline_ws.write(
        "sources/mod_b/db/units_tables/!mod_b.tsv",
        tsv("units_tables", "!mod_b", ["key", "faction", "cost"], [["unit_a", "fac_missing", "999"]]),
    )

    async def script(call: Session) -> None:
        err, report = await call("find_conflicts", {"mods": ["mod_b", "mod_a"]})
        assert not err
        assert report["collisions"][0]["winner"] == "mod_b:units_tables/!mod_b"
        assert report["dangling"][0]["value"] == "fac_missing"

        err, d = await call("diff", {"mod_a": "mod_a", "mod_b": "mod_b", "shared": True})
        assert not err
        (units,) = d["tables"]
        assert units["removed_total"] == 1
        assert units["changed"][0]["key"] == ["unit_a"]

    run_session(offline_ws, script)


# ---------------------------------------------------------------------------- RPFM-backed tools


def test_extract_and_repack_through_rpfm(ws: Workspace, rpfm: FakeRPFM) -> None:
    pack = write_pack(ws.root / "packs" / "mod_a.pack", {"db/units_tables/mod_a": UNITS})
    (ws.workspace / "my_patch" / "db" / "units_tables").mkdir(parents=True)
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)

    async def script(call: Session) -> None:
        err, status = await call("rpfm_status")
        assert not err
        assert status["protocol"] == rpfm.dialect

        err, res = await call("extract_packs", {"packs": [str(pack)]})
        assert not err, res
        assert res["mods"] == [{"mod": "sources/mod_a", "tables": 1, "scripts": 0, "locs": 0, "failed": []}]

        err, res = await call("repack", {"patch": "my_patch"})
        assert not err, res
        assert res["saved"] is True

    run_session(ws, script)
    assert (ws.sources / "mod_a" / "db" / "units_tables" / "mod_a.tsv").read_text(encoding="utf-8") == UNITS
    assert read_pack(ws.output / "my_patch.pack") == {"db/units_tables/my_patch": UNITS}


def test_repack_refuses_an_invalid_patch(ws: Workspace, rpfm: FakeRPFM) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", "key\tcost\nnot metadata\n")

    async def script(call: Session) -> None:
        err, res = await call("repack", {"patch": "my_patch"})
        assert not err
        assert res["saved"] is False
        assert res["validation"]["errors"] >= 1

    run_session(ws, script)
    assert not Path(ws.output / "my_patch.pack").exists()
    assert "NewPack" not in rpfm.commands() and "pack.new" not in rpfm.commands()
