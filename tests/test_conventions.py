"""Outside-in tests for Total War conventions tw-patcher understands: twad_key_deletes (Warhammer 3),
datacores and whole-file overrides, and the fragment-name merge order."""

from __future__ import annotations

import json

from .conftest import Workspace, tsv

FIELD = (
    '(name: "{name}", field_type: {type}, is_key: {key}, default_value: None, is_filename: false, '
    'filename_relative_path: None, is_reference: {ref}, lookup: None, description: "", ca_order: {ca}, '
    "is_bitwise: 0, enum_values: {{}}, is_part_of_colour: None)"
)


def _table(name: str, fields: list[tuple[str, bool, str | None, int]]) -> str:
    rendered = ",\n".join(
        FIELD.format(
            name=n,
            type="StringU8",
            key=str(k).lower(),
            ref=f'Some(("{r.split(".")[0]}", "{r.split(".")[1]}"))' if r else "None",
            ca=ca,
        )
        for n, k, r, ca in fields
    )
    return f'"{name}": [(version: 0, fields: [{rendered}], localised_fields: [], localised_key_order: [])]'


# chain_items is keyed (chain, set) in file order, but CA order puts `set` first: deletes write set+chain.
SCHEMA = (
    "(version: 5, definitions: {"
    + ",\n".join(
        [
            _table("nodes_tables", [("key", True, None, 0), ("label", False, None, 1)]),
            _table("node_links_tables", [("parent", True, "nodes.key", 0), ("child", True, "nodes.key", 1)]),
            _table("chain_items_tables", [("chain", True, None, 1), ("set", True, None, 0), ("note", False, None, 2)]),
            _table("twad_key_deletes_tables", [("key", True, None, 0), ("table_name", True, None, 1)]),
        ]
    )
    + "}, patches: {})"
)

NODES = tsv("nodes_tables", "data__", ["key", "label"], [["n1", "One"], ["n2", "Two"], ["n3", "Three"]])
LINKS = tsv("node_links_tables", "data__", ["parent", "child"], [["n1", "n2"]])
CHAINS = tsv("chain_items_tables", "data__", ["chain", "set", "note"], [["c1", "s1", "x"], ["c2", "s1", "y"]])


def deletes(name: str, rows: list[list[str]]) -> str:
    return tsv("twad_key_deletes_tables", name, ["key", "table_name"], rows)


def setup(ws: Workspace) -> None:
    (ws.schemas / "schema_wh3.ron").write_text(SCHEMA, encoding="utf-8")
    ws.write("sources/vanilla/db/nodes_tables/data__.tsv", NODES)
    ws.write("sources/vanilla/db/node_links_tables/data__.tsv", LINKS)
    ws.write("sources/vanilla/db/chain_items_tables/data__.tsv", CHAINS)


# ---------------------------------------------------------------------------- conflicts


def test_conflicts_flags_a_delete_that_breaks_a_reference(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write("sources/mod_a/db/twad_key_deletes_tables/mod_a.tsv", deletes("mod_a", [["n2", "nodes"]]))

    result = offline_ws.run("conflicts", "mod_a", "--context", "vanilla")

    assert result.exit_code == 0, result.output
    assert "Key deletes that break references: 1" in result.stdout
    assert "deletes nodes_tables 'n2', still used by vanilla:node_links_tables/data__ n1|n2" in result.stdout
    assert "node_links_tables.child" in result.stdout
    assert "crashes on load" in result.stdout


def test_conflicts_matches_composite_deletes_in_ca_order(offline_ws: Workspace) -> None:
    setup(offline_ws)
    # s1+c1 (CA order) matches the row chain=c1,set=s1; c2s1 (file order) matches nothing.
    offline_ws.write(
        "sources/mod_a/db/twad_key_deletes_tables/mod_a.tsv",
        deletes("mod_a", [["s1c1", "chain_items"], ["c2s1", "chain_items"]]),
    )

    result = offline_ws.run("conflicts", "mod_a", "--context", "vanilla", "--json")

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["deletes_without_match"] == [
        {"delete": "mod_a:twad_key_deletes_tables/mod_a", "table": "chain_items_tables", "key": "c2s1"}
    ]
    assert report["broken_by_deletes_total"] == 0


def test_delete_of_an_unreferenced_row_is_fine(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write("sources/mod_a/db/twad_key_deletes_tables/mod_a.tsv", deletes("mod_a", [["n3", "nodes"]]))

    result = offline_ws.run("conflicts", "mod_a", "--context", "vanilla")

    assert result.exit_code == 0, result.output
    assert "Key deletes that break references: 0" in result.stdout
    assert "match nothing" not in result.stdout


def test_a_reference_from_a_row_that_is_also_deleted_does_not_count(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write(
        "sources/mod_a/db/twad_key_deletes_tables/mod_a.tsv",
        deletes("mod_a", [["n2", "nodes"], ["n1n2", "node_links"]]),
    )

    result = offline_ws.run("conflicts", "mod_a", "--context", "vanilla", "--json")

    report = json.loads(result.stdout)
    assert report["broken_by_deletes_total"] == 0, report["broken_by_deletes"]


# ---------------------------------------------------------------------------- validate


def test_validate_warns_about_patch_deletes(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write(
        "workspace/fix/db/twad_key_deletes_tables/fix.tsv", deletes("fix", [["n2", "nodes"], ["nope", "nodes"]])
    )

    result = offline_ws.run("validate", "fix")

    assert result.exit_code == 0, result.output
    assert (
        "deleting nodes_tables 'n2' breaks node_links_tables.child in vanilla:node_links_tables/data__" in result.stderr
    )
    assert "the game crashes on load" in result.stderr
    assert "deletes nodes_tables 'nope', which no source defines" in result.stderr


def test_validate_warns_about_a_datacore(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write(
        "workspace/fix/db/nodes_tables/data__.tsv", tsv("nodes_tables", "data__", ["key", "label"], [["n1", "One"]])
    )

    result = offline_ws.run("validate", "fix")

    assert result.exit_code == 0, result.output
    assert "replaces vanilla's entire nodes_tables (a datacore)" in result.stderr
    assert "prefer twad_key_deletes_tables" in result.stderr


def test_validate_warns_about_a_whole_file_override_of_a_mod(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write(
        "sources/mod_a/db/nodes_tables/mod_a.tsv", tsv("nodes_tables", "mod_a", ["key", "label"], [["n9", "Nine"]])
    )
    offline_ws.write(
        "workspace/fix/db/nodes_tables/mod_a.tsv", tsv("nodes_tables", "mod_a", ["key", "label"], [["n9", "9"]])
    )

    result = offline_ws.run("validate", "fix")

    assert result.exit_code == 0, result.output
    assert "same file name as mod_a" in result.stderr
    assert "replaces their whole db/nodes_tables/mod_a" in result.stderr


def test_validate_warns_when_patch_rows_lose_in_merge_order(offline_ws: Workspace) -> None:
    setup(offline_ws)
    # vanilla's data__ sorts before "fix", so vanilla's n1 wins over the patch's n1.
    offline_ws.write(
        "workspace/fix/db/nodes_tables/fix.tsv",
        tsv("nodes_tables", "fix", ["key", "label"], [["n1", "Changed"], ["n9", "New"]]),
    )

    result = offline_ws.run("validate", "fix")

    assert result.exit_code == 0, result.output
    assert "1 row(s) lose to vanilla:nodes_tables/data__ because its file name sorts first (n1)" in result.stderr
    assert "start it with '!'" in result.stderr


def test_a_patch_fragment_that_sorts_first_wins(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write(
        "workspace/fix/db/nodes_tables/!fix.tsv", tsv("nodes_tables", "!fix", ["key", "label"], [["n1", "Changed"]])
    )

    result = offline_ws.run("validate", "fix")

    assert result.exit_code == 0, result.output
    assert "lose to" not in result.stderr


def test_identical_rows_are_not_reported_as_losing(offline_ws: Workspace) -> None:
    setup(offline_ws)
    offline_ws.write(
        "workspace/fix/db/nodes_tables/fix.tsv", tsv("nodes_tables", "fix", ["key", "label"], [["n1", "One"]])
    )

    result = offline_ws.run("validate", "fix")

    assert "lose to" not in result.stderr


def test_mcp_add_key_deletes_writes_keys_in_ca_order(offline_ws: Workspace) -> None:
    from .test_mcp import Session, run_session

    setup(offline_ws)
    (offline_ws.workspace / "fix" / "db").mkdir(parents=True)

    async def script(call: Session) -> None:
        # Given in key-column order (chain|set), as query_rows shows it
        err, res = await call("add_key_deletes", {"patch": "fix", "table": "chain_items", "keys": ["c1|s1"]})
        assert not err, res

    run_session(offline_ws, script)
    written = (offline_ws.workspace / "fix" / "db" / "twad_key_deletes_tables" / "fix.tsv").read_text(encoding="utf-8")
    assert written == deletes("fix", [["s1c1", "chain_items"]])

    # ...and the analysis agrees it removes the intended row
    result = offline_ws.run("validate", "fix")
    assert "which no source defines" not in result.stderr
