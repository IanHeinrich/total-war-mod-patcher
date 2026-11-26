"""Outside-in tests of the offline table commands: tables, show, find-key, diff,
conflicts, validate, new-patch and repack's pre-repack validation.

Each test runs ``python -m tw_patcher`` in a subprocess against a temporary modding
root. The offline commands never talk to RPFM, so they use ``offline_ws`` (and ``sws``,
the same workspace with a small RPFM schema installed); only the repack tests need the
fake RPFM server. Mods are plain TSV files written under ``sources/`` and ``workspace/``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from .conftest import Workspace, tsv
from .fake_rpfm import FakeRPFM, read_pack

# ---------------------------------------------------------------------- fixtures and builders


def _field(
    name: str,
    field_type: str = "StringU8",
    key: bool = False,
    ref: tuple[str, str] | None = None,
    colour: int | None = None,
) -> str:
    reference = f'Some(("{ref[0]}", "{ref[1]}"))' if ref else "None"
    part_of_colour = f"Some({colour})" if colour is not None else "None"
    return (
        f'(name: "{name}", field_type: {field_type}, is_key: {str(key).lower()}, default_value: None, '
        f"is_filename: false, filename_relative_path: None, is_reference: {reference}, lookup: None, "
        f'description: "", ca_order: 0, is_bitwise: 0, enum_values: {{}}, is_part_of_colour: {part_of_colour}),'
    )


def _definition(table: str, fields: list[str], version: int = 0) -> str:
    body = "\n".join(fields)
    return f'"{table}": [(version: {version}, fields: [\n{body}\n], localised_fields: [], localised_key_order: [])],'


SCHEMA = (
    "(\n    version: 5,\n    definitions: {\n"
    + "\n".join(
        [
            _definition(
                "units_tables",
                [_field("key", key=True), _field("faction", ref=("factions", "key")), _field("cost", "I32")],
            ),
            _definition("factions_tables", [_field("key", key=True), _field("name")]),
            _definition(
                "stats_tables",
                [_field("key", key=True), _field("speed", "F32"), _field("active", "Boolean"), _field("count", "I32")],
            ),
            _definition(
                "colours_tables",
                [
                    _field("key", key=True),
                    _field("r", "I32", colour=1),
                    _field("g", "I32", colour=1),
                    _field("b", "I32", colour=1),
                    _field("colour_r", "I32", colour=2),
                    _field("colour_g", "I32", colour=2),
                    _field("colour_b", "I32", colour=2),
                ],
            ),
            _definition("pairs_tables", [_field("a", key=True), _field("b", key=True), _field("value")]),
            _definition("links_tables", [_field("key", key=True), _field("tier", "I32", ref=("tiers", "key"))]),
            _definition("tiers_tables", [_field("key", "I32", key=True)]),
        ]
    )
    + "\n    },\n    patches: {},\n)\n"
)

UNITS_HEADER = ["key", "faction", "cost"]
FACTIONS_HEADER = ["key", "name"]
STATS_HEADER = ["key", "speed", "active", "count"]
COLOURS_HEADER = ["key", "unnamed colour group_1", "colour_hex"]


def install_schema(ws: Workspace) -> Workspace:
    (ws.schemas / "schema_wh3.ron").write_text(SCHEMA, encoding="utf-8")
    return ws


@pytest.fixture
def sws(offline_ws: Workspace) -> Workspace:
    """Offline workspace whose game (warhammer_3) has a small schema."""
    return install_schema(offline_ws)


def put(
    ws: Workspace,
    mod: str,
    table: str,
    fragment: str,
    header: list[str],
    rows: Sequence[Sequence[str]],
    version: int = 0,
) -> Path:
    """Write ``<mod>/db/<table>/<fragment>.tsv``; ``mod`` is e.g. ``sources/mod_a`` or ``workspace/patch``."""
    text = tsv(table, fragment, header, [list(r) for r in rows], version)
    return ws.write(f"{mod}/db/{table}/{fragment}.tsv", text)


def units(ws: Workspace, mod: str, fragment: str, *rows: tuple[str, str, str]) -> Path:
    return put(ws, mod, "units_tables", fragment, UNITS_HEADER, rows)


def factions(ws: Workspace, mod: str, fragment: str, *keys: str) -> Path:
    return put(ws, mod, "factions_tables", fragment, FACTIONS_HEADER, [(k, k.upper()) for k in keys])


def data_rows(stdout: str) -> list[list[str]]:
    """Rows of ``show`` output: everything between the column line and the trailing summary hint."""
    return [line.split("\t") for line in stdout.splitlines()[1:-1]]


# ---------------------------------------------------------------------- tables


def test_tables_lists_sources_and_patches_with_table_counts(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    factions(offline_ws, "sources/mod_a", "mod_a", "f1")
    units(offline_ws, "workspace/my_patch", "my_patch", ("u1", "f1", "150"))

    result = offline_ws.run("tables")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert "sources/mod_a\t2 table(s)" in lines
    assert "workspace/my_patch\t1 table(s)" in lines


def test_tables_warns_when_nothing_is_extracted(offline_ws: Workspace) -> None:
    result = offline_ws.run("tables")

    assert result.exit_code == 0, result.output
    assert "Nothing extracted yet" in result.stderr


def test_tables_shows_grouped_mods_by_their_group_path(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/group/mod_a", "mod_a", ("u1", "f1", "100"))
    units(offline_ws, "sources/group/mod_b", "mod_b", ("u1", "f1", "100"))

    result = offline_ws.run("tables")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert "sources/group/mod_a\t1 table(s)" in lines
    assert "sources/group/mod_b\t1 table(s)" in lines
    assert not any(line.startswith("sources/group\t") for line in lines)


def test_tables_finds_a_grouped_mod_literally_named_db(offline_ws: Workspace) -> None:
    # Vanilla's db.pack extracts to <group>/db/db/<table>/...: the group folder holds a mod named "db".
    units(offline_ws, "sources/group/db", "vanilla", ("u1", "f1", "100"))
    units(offline_ws, "sources/group/mod_a", "mod_a", ("u1", "f1", "100"))

    result = offline_ws.run("tables")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert "sources/group/db\t1 table(s)" in lines
    assert "sources/group/mod_a\t1 table(s)" in lines


def test_tables_for_one_mod_lists_fragments_with_row_counts(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "part1", ("u1", "f1", "100"), ("u2", "f1", "200"))
    units(offline_ws, "sources/mod_a", "part2", ("u3", "f1", "300"))
    factions(offline_ws, "sources/mod_a", "mod_a", "f1")

    result = offline_ws.run("tables", "mod_a")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert "sources/mod_a: 2 table(s)" in lines
    assert "units_tables/part1\t2 row(s)" in lines
    assert "units_tables/part2\t1 row(s)" in lines
    assert "factions_tables/mod_a\t1 row(s)" in lines


def test_tables_marks_an_unreadable_fragment(offline_ws: Workspace) -> None:
    offline_ws.write("sources/mod_a/db/units_tables/broken.tsv", "key\tfaction\tcost\n")

    result = offline_ws.run("tables", "mod_a")

    assert result.exit_code == 0, result.output
    assert "units_tables/broken\tunreadable" in result.stdout.splitlines()


def test_tables_json_shapes(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"), ("u2", "f1", "200"))
    units(offline_ws, "workspace/my_patch", "my_patch", ("u1", "f1", "150"))

    listing = json.loads(offline_ws.run("tables", "--json").stdout)
    one = json.loads(offline_ws.run("tables", "mod_a", "--json").stdout)

    assert listing == [
        {"name": "sources/mod_a", "kind": "source", "tables": 1},
        {"name": "workspace/my_patch", "kind": "patch", "tables": 1},
    ]
    assert one["mod"] == "sources/mod_a"
    [entry] = one["tables"]
    assert (entry["table"], entry["fragment"], entry["rows"]) == ("units_tables", "mod_a", 2)
    assert Path(entry["path"]) == offline_ws.sources / "mod_a" / "db" / "units_tables" / "mod_a.tsv"


def test_tables_unknown_mod_lists_the_known_ones(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(offline_ws, "workspace/my_patch", "my_patch", ("u1", "f1", "100"))

    result = offline_ws.run("tables", "nope")

    assert result.exit_code == 1
    assert "No extracted mod or patch named 'nope'" in result.stderr
    assert "sources/mod_a" in result.stderr
    assert "workspace/my_patch" in result.stderr


def test_tables_ambiguous_suffix_is_an_error_until_made_unique(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/group_a/common", "x", ("u1", "f1", "100"))
    units(offline_ws, "sources/group_b/common", "x", ("u1", "f1", "100"))

    ambiguous = offline_ws.run("tables", "common")
    unique = offline_ws.run("tables", "group_a/common")

    assert ambiguous.exit_code == 1
    assert "ambiguous" in ambiguous.stderr
    assert "sources/group_a/common" in ambiguous.stderr
    assert "sources/group_b/common" in ambiguous.stderr
    assert unique.exit_code == 0, unique.output
    assert "sources/group_a/common: 1 table(s)" in unique.stdout


def test_tables_prefixes_pick_between_a_source_and_a_patch_of_the_same_name(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/shared", "from_source", ("u1", "f1", "100"))
    units(offline_ws, "workspace/shared", "from_patch", ("u1", "f1", "100"))

    plain = offline_ws.run("tables", "shared")
    source = offline_ws.run("tables", "sources/shared")
    patch = offline_ws.run("tables", "workspace/shared")

    assert plain.exit_code == 1
    assert "ambiguous" in plain.stderr
    assert "units_tables/from_source" in source.stdout
    assert "units_tables/from_patch" not in source.stdout
    assert "units_tables/from_patch" in patch.stdout


# ---------------------------------------------------------------------- show


def _show_fixture(ws: Workspace) -> None:
    units(
        ws,
        "sources/mod_a",
        "mod_a",
        ("u1", "f1", "100"),
        ("u2", "f1", "200"),
        ("u3", "f2", "200"),
    )


@pytest.mark.parametrize("name", ["units_tables", "units", "db/units_tables"])
def test_show_accepts_every_table_name_form(sws: Workspace, name: str) -> None:
    _show_fixture(sws)

    result = sws.run("show", name, "--mod", "mod_a")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "key\tfaction\tcost"
    assert [r[0] for r in data_rows(result.stdout)] == ["u1", "u2", "u3"]
    assert "3 row(s); key: key" in result.stdout


def test_show_filters_by_key(sws: Workspace) -> None:
    _show_fixture(sws)

    result = sws.run("show", "units", "-m", "mod_a", "--key", "u2")

    assert result.exit_code == 0, result.output
    assert data_rows(result.stdout) == [["u2", "f1", "200"]]


def test_show_filters_by_composite_key(sws: Workspace) -> None:
    put(sws, "sources/mod_a", "pairs_tables", "mod_a", ["a", "b", "value"], [("x", "1", "p"), ("x", "2", "q")])

    result = sws.run("show", "pairs", "-m", "mod_a", "--key", "x|2")

    assert result.exit_code == 0, result.output
    assert data_rows(result.stdout) == [["x", "2", "q"]]
    assert "key: a, b" in result.stdout


def test_show_where_clauses_are_anded(sws: Workspace) -> None:
    _show_fixture(sws)

    one = sws.run("show", "units", "-m", "mod_a", "--where", "cost=200")
    both = sws.run("show", "units", "-m", "mod_a", "-w", "cost=200", "-w", "faction=f2")

    assert [r[0] for r in data_rows(one.stdout)] == ["u2", "u3"]
    assert data_rows(both.stdout) == [["u3", "f2", "200"]]


def test_show_columns_limits_the_printed_columns(sws: Workspace) -> None:
    _show_fixture(sws)

    result = sws.run("show", "units", "-m", "mod_a", "--columns", "key,cost", "--key", "u1")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "key\tcost"
    assert data_rows(result.stdout) == [["u1", "100"]]


def test_show_limit_notes_hidden_rows_and_zero_means_all(sws: Workspace) -> None:
    _show_fixture(sws)

    limited = sws.run("show", "units", "-m", "mod_a", "--limit", "2")
    everything = sws.run("show", "units", "-m", "mod_a", "--limit", "0")

    assert len(data_rows(limited.stdout)) == 2
    assert "3 row(s), 1 not shown" in limited.stdout
    assert len(data_rows(everything.stdout)) == 3
    assert "not shown" not in everything.stdout


def test_show_json_reports_keys_totals_and_truncation(sws: Workspace) -> None:
    _show_fixture(sws)

    out = json.loads(sws.run("show", "units", "-m", "mod_a", "--limit", "2", "--json").stdout)

    assert out["mod"] == "sources/mod_a"
    assert out["table"] == "units_tables"
    assert out["key_columns"] == ["key"]
    assert out["columns"] == ["key", "faction", "cost"]
    assert out["total"] == 3
    assert out["truncated"] is True
    assert [r["key"] for r in out["rows"]] == [["u1"], ["u2"]]
    assert out["rows"][0]["values"] == {"key": "u1", "faction": "f1", "cost": "100"}


def test_show_merges_fragments_in_file_name_byte_order(sws: Workspace) -> None:
    # Byte order puts "Zeta" before "alpha" (a case-insensitive sort would not).
    units(sws, "sources/mod_a", "alpha", ("u1", "f1", "111"), ("u2", "f1", "20"))
    units(sws, "sources/mod_a", "Zeta", ("u1", "f1", "999"))

    result = sws.run("show", "units", "-m", "mod_a", "--json")

    rows = {tuple(r["key"]): r for r in json.loads(result.stdout)["rows"]}
    assert rows[("u1",)]["values"]["cost"] == "999"
    assert rows[("u1",)]["from"] == "Zeta"
    assert rows[("u2",)]["from"] == "alpha"


def test_show_without_a_schema_still_works_and_says_the_key_is_unknown(offline_ws: Workspace) -> None:
    _show_fixture(offline_ws)

    result = offline_ws.run("show", "units", "-m", "mod_a")

    assert result.exit_code == 0, result.output
    assert len(data_rows(result.stdout)) == 3
    assert "key: unknown (no schema)" in result.stdout


def test_show_rejects_unknown_columns_and_tables(sws: Workspace) -> None:
    _show_fixture(sws)

    bad_column = sws.run("show", "units", "-m", "mod_a", "--columns", "key,nope")
    bad_where = sws.run("show", "units", "-m", "mod_a", "--where", "nope=1")
    bad_table = sws.run("show", "factions", "-m", "mod_a")

    assert bad_column.exit_code == 1
    assert "No column 'nope' in units_tables" in bad_column.stderr
    assert bad_where.exit_code == 1
    assert "No column 'nope'" in bad_where.stderr
    assert bad_table.exit_code == 1
    assert "has no factions_tables" in bad_table.stderr


# ---------------------------------------------------------------------- find-key


def test_find_key_lists_mods_and_patches_in_merge_order_and_marks_the_winner(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "zeta", ("u1", "f1", "100"))
    units(sws, "workspace/my_patch", "Alpha", ("u1", "f1", "150"))
    units(sws, "sources/mod_b", "other", ("u9", "f1", "1"))

    result = sws.run("find-key", "u1")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "units_tables"
    assert lines[1].strip().startswith("workspace/my_patch:Alpha")
    assert lines[1].rstrip().endswith("wins")
    assert lines[2].strip() == "sources/mod_a:zeta"
    assert "mod_b" not in result.stdout


def test_find_key_a_single_definition_is_not_marked_as_winning(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))

    result = sws.run("find-key", "u1")

    assert "sources/mod_a:mod_a" in result.stdout
    assert "wins" not in result.stdout


def test_find_key_table_filter_and_json(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("shared", "f1", "100"))
    factions(sws, "sources/mod_a", "mod_a", "shared")

    everywhere = json.loads(sws.run("find-key", "shared", "--json").stdout)
    filtered = json.loads(sws.run("find-key", "shared", "-t", "factions", "--json").stdout)

    assert sorted(everywhere["tables"]) == ["factions_tables", "units_tables"]
    assert everywhere["key"] == "shared"
    assert list(filtered["tables"]) == ["factions_tables"]
    [hit] = filtered["tables"]["factions_tables"]
    assert (hit["mod"], hit["fragment"]) == ("sources/mod_a", "mod_a")


def test_find_key_matches_composite_keys(sws: Workspace) -> None:
    put(sws, "sources/mod_a", "pairs_tables", "mod_a", ["a", "b", "value"], [("x", "1", "p"), ("x", "2", "q")])

    found = sws.run("find-key", "x|2")
    partial = sws.run("find-key", "x")

    assert "sources/mod_a:mod_a" in found.stdout
    assert "No extracted mod or patch defines 'x'" in partial.stderr


def test_find_key_reports_when_nothing_defines_it(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))

    result = sws.run("find-key", "ghost")

    assert result.exit_code == 0, result.output
    assert "No extracted mod or patch defines 'ghost'" in result.stderr


# ---------------------------------------------------------------------- diff


def test_diff_reports_added_removed_and_changed_rows_by_key(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"), ("u2", "f1", "200"), ("u4", "f1", "400"))
    units(sws, "workspace/my_patch", "my_patch", ("u1", "f1", "150"), ("u3", "f1", "300"), ("u4", "f1", "400"))

    result = sws.run("diff", "mod_a", "my_patch")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert "units_tables: +1 -1 ~1" in lines
    assert "  + u3" in lines
    assert "  - u2" in lines
    assert "  ~ u1: cost: '100' -> '150'" in lines
    assert "u4" not in result.stdout


def test_diff_of_identical_mods_reports_no_differences(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "mod_b", ("u1", "f1", "100"))

    result = sws.run("diff", "mod_a", "mod_b")

    assert result.exit_code == 0, result.output
    assert "No row differences" in result.stdout


def test_diff_flags_tables_present_on_one_side_only(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "mod_b", ("u1", "f1", "100"))
    factions(sws, "sources/mod_b", "mod_b", "f1")

    result = sws.run("diff", "mod_a", "mod_b")

    assert result.exit_code == 0, result.output
    assert "factions_tables (only in sources/mod_b): +1 -0 ~0" in result.stdout.splitlines()
    assert "units_tables" not in result.stdout  # identical, so not listed


def test_diff_shared_limits_the_comparison_to_common_tables(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "mod_b", ("u1", "f1", "101"))
    factions(sws, "sources/mod_b", "mod_b", "f1")

    result = sws.run("diff", "mod_a", "mod_b", "--shared", "--json")

    tables = [t["table"] for t in json.loads(result.stdout)["tables"]]
    assert tables == ["units_tables"]


def test_diff_table_option_selects_tables(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "mod_b", ("u1", "f1", "101"))
    factions(sws, "sources/mod_b", "mod_b", "f1")

    result = sws.run("diff", "mod_a", "mod_b", "-t", "factions", "--json")

    tables = [t["table"] for t in json.loads(result.stdout)["tables"]]
    assert tables == ["factions_tables"]


def test_diff_limit_caps_the_listing_but_json_keeps_the_totals(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u0", "f1", "1"))
    units(sws, "sources/mod_b", "mod_b", ("u0", "f1", "1"), *[(f"n{i}", "f1", "1") for i in range(5)])

    text = sws.run("diff", "mod_a", "mod_b", "--limit", "2")
    as_json = json.loads(sws.run("diff", "mod_a", "mod_b", "--limit", "2", "--json").stdout)

    assert text.stdout.count("  + n") == 2
    assert "... 3 more added" in text.stdout
    [table] = as_json["tables"]
    assert table["key_columns"] == ["key"]
    assert table["added_total"] == 5
    assert len(table["added"]) == 2
    assert table["removed_total"] == 0
    assert table["changed_total"] == 0
    assert (as_json["a"], as_json["b"]) == ("sources/mod_a", "sources/mod_b")


def test_diff_without_a_schema_warns_and_treats_edited_rows_as_remove_plus_add(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(offline_ws, "sources/mod_b", "mod_b", ("u1", "f1", "150"))

    result = offline_ws.run("diff", "mod_a", "mod_b")

    assert result.exit_code == 0, result.output
    assert "Continuing without key/reference information" in result.stderr
    assert "units_tables: +1 -1 ~0" in result.stdout.splitlines()


# ---------------------------------------------------------------------- conflicts


def test_conflicts_whole_file_override_goes_to_the_first_listed_mod(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "shared", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "shared", ("u1", "f1", "200"))

    forward = sws.run("conflicts", "mod_a", "mod_b", "--no-references")
    backward = sws.run("conflicts", "mod_b", "mod_a", "--no-references")

    assert forward.exit_code == 0, forward.output
    assert "Whole-file overrides: 1" in forward.stdout
    assert "units_tables/shared: mod_a shadows mod_b" in forward.stdout
    assert "units_tables/shared: mod_b shadows mod_a" in backward.stdout
    # The shadowed file is never loaded, so the two rows do not collide.
    assert "Key collisions: 0" in forward.stdout


def test_conflicts_reports_key_collisions_with_the_differing_columns(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"), ("u2", "f1", "5"))
    units(sws, "sources/mod_b", "mod_b", ("u1", "f1", "200"), ("u2", "f1", "5"))

    result = sws.run("conflicts", "mod_a", "mod_b", "--no-references")

    assert result.exit_code == 0, result.output
    assert "Key collisions: 2 (1 with differing values)" in result.stdout
    assert "units_tables u1: mod_a:units_tables/mod_a beats mod_b:units_tables/mod_b  [cost: '100' vs '200']" in (
        result.stdout
    )
    assert "u2" not in result.stdout.split("Key collisions")[1]  # the identical row is counted, not listed


def test_conflicts_collision_winner_follows_fragment_name_then_mod_order(sws: Workspace) -> None:
    # mod_a is listed first, but "Alpha" sorts before "zeta" in byte order, so mod_b's row wins.
    units(sws, "sources/mod_a", "zeta", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "Alpha", ("u1", "f1", "200"))

    result = sws.run("conflicts", "mod_a", "mod_b", "--no-references")

    assert "mod_b:units_tables/Alpha beats mod_a:units_tables/zeta" in result.stdout


def test_conflicts_none_when_mods_touch_different_keys(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "mod_b", ("u2", "f1", "100"))

    result = sws.run("conflicts", "mod_a", "mod_b", "--no-references")

    assert "Whole-file overrides: 0" in result.stdout
    assert "Key collisions: 0 (0 with differing values)" in result.stdout


def test_conflicts_detects_dangling_references(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"), ("u2", "ghost", "100"))
    factions(sws, "sources/mod_b", "mod_b", "f1")

    result = sws.run("conflicts", "mod_a", "mod_b")

    assert result.exit_code == 0, result.output
    assert "Dangling references: 1" in result.stdout
    assert "mod_a:units_tables/mod_a u2: faction='ghost' not in factions_tables.key" in result.stdout


def test_conflicts_context_mod_resolves_references_but_is_not_itself_checked(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f2", "100"))
    factions(sws, "sources/mod_b", "mod_b", "f1")  # keeps factions_tables "known" without vanilla
    # vanilla defines f2, redefines u1 and has a dangling reference of its own
    units(sws, "sources/vanilla", "vanilla", ("u1", "f2", "1"), ("u7", "nowhere", "1"))
    factions(sws, "sources/vanilla", "vanilla", "f2")

    without = sws.run("conflicts", "mod_a", "mod_b")
    with_context = sws.run("conflicts", "mod_a", "mod_b", "--context", "vanilla")

    assert "Dangling references: 1" in without.stdout
    assert "faction='f2'" in without.stdout
    assert "Dangling references: 0" in with_context.stdout
    assert "nowhere" not in with_context.stdout  # vanilla's own bad reference is not reported
    assert "Key collisions: 0" in with_context.stdout  # u1 clashes with vanilla only, which is context


def test_conflicts_integer_reference_zero_is_not_dangling(sws: Workspace) -> None:
    put(sws, "sources/mod_a", "links_tables", "mod_a", ["key", "tier"], [("l0", "0"), ("l1", "1"), ("l7", "7")])
    put(sws, "sources/mod_b", "tiers_tables", "mod_b", ["key"], [("1",)])

    result = sws.run("conflicts", "mod_a", "mod_b")

    assert result.exit_code == 0, result.output
    assert "Dangling references: 1" in result.stdout
    assert "tier='7' not in tiers_tables.key" in result.stdout
    assert "tier='0'" not in result.stdout


def test_conflicts_no_references_skips_the_dangling_check(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "ghost", "100"))
    factions(sws, "sources/mod_b", "mod_b", "f1")

    result = sws.run("conflicts", "mod_a", "mod_b", "--no-references")

    assert result.exit_code == 0, result.output
    assert "Dangling references" not in result.stdout
    assert "ghost" not in result.stdout


def test_conflicts_hints_at_referenced_tables_that_no_mod_provides(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    units(sws, "sources/mod_b", "mod_b", ("u2", "f1", "100"))

    result = sws.run("conflicts", "mod_a", "mod_b")

    assert result.exit_code == 0, result.output
    assert "Dangling references: 0" in result.stdout
    assert "Not checked (1 referenced tables are in none of these mods" in result.stdout
    assert "factions_tables" in result.stdout


def test_conflicts_json(sws: Workspace) -> None:
    units(sws, "sources/mod_a", "shared", ("u1", "ghost", "100"))
    units(sws, "sources/mod_b", "shared", ("u1", "f1", "200"))
    units(sws, "sources/mod_a", "mod_a", ("u2", "f1", "1"))
    units(sws, "sources/mod_b", "mod_b", ("u2", "f1", "2"))
    factions(sws, "sources/mod_b", "mod_b", "f1")

    out = json.loads(sws.run("conflicts", "mod_a", "mod_b", "--json").stdout)

    assert out["mods"] == ["sources/mod_a", "sources/mod_b"]
    assert [(o["table"], o["fragment"], o["winner"], o["shadowed"]) for o in out["overrides"]] == [
        ("units_tables", "shared", "mod_a", ["mod_b"])
    ]
    assert out["collisions_total"] == 1
    [collision] = out["collisions"]
    assert collision["key"] == ["u2"]
    assert collision["identical"] is False
    assert collision["differences"] == {"cost": ["1", "2"]}
    assert out["dangling_total"] == 1
    assert out["dangling"][0]["value"] == "ghost"
    assert out["unchecked_targets"] == []


# ---------------------------------------------------------------------- validate


def _stats_patch(ws: Workspace, rows: Sequence[Sequence[str]], name: str = "p") -> None:
    put(ws, f"workspace/{name}", "stats_tables", name, STATS_HEADER, rows)


def test_validate_clean_patch_succeeds(sws: Workspace) -> None:
    _stats_patch(sws, [("s1", "1.5", "true", "3"), ("s2", "-2", "0", "-7")])
    put(sws, "workspace/p", "colours_tables", "p", COLOURS_HEADER, [("c1", "E58E3B", "00ff7f")])

    result = sws.run("validate", "p")

    assert result.exit_code == 0, result.output
    assert "workspace/p: no errors (0 warning(s))" in result.stdout


STATS_H = "\t".join(STATS_HEADER)
GOOD_CELLS: list[str] = ["s1", "1.5", "true", "3"]
GOOD_ROW = "\t".join(GOOD_CELLS)

ERROR_CASES = [
    pytest.param(
        "stats_tables",
        f"{STATS_H}\n{GOOD_ROW}\n",
        2,
        "line 2 must be RPFM's '#table;version;path' metadata line",
        id="edited-metadata-line",
    ),
    pytest.param(
        "stats_tables",
        f"{STATS_H}\n",
        2,
        "expected a column-name line and a metadata line",
        id="missing-metadata-line",
    ),
    pytest.param(
        "stats_tables",
        "key\tfaction\tcost\n#units_tables;0;db/units_tables/p\t\t\ns1\tf1\t5\n",
        2,
        "metadata says table 'units_tables' but the file is in stats_tables/",
        id="metadata-table-differs-from-folder",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", STATS_HEADER, [GOOD_ROW.split("\t")], version=9),
        2,
        "stats_tables version 9 is not in the warhammer_3 schema (known: [0])",
        id="unknown-table-version",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", ["key", "speed", "active"], [["s1", "1.5", "true"]]),
        1,
        "missing column(s): count",
        id="missing-column",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", [*STATS_HEADER, "bogus"], [[*GOOD_ROW.split("\t"), "x"]]),
        1,
        "unknown column(s): bogus",
        id="unknown-column",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", STATS_HEADER, [["s1", "1.5", "true"]]),
        3,
        "3 cell(s) but 4 columns",
        id="wrong-cell-count",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", STATS_HEADER, [["s1", "1.5", "true", "abc"]]),
        3,
        "count='abc' is not a valid I32",
        id="bad-i32",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", STATS_HEADER, [["s1", "1.5", "true", "3"], ["s2", "fast", "true", "3"]]),
        4,
        "speed='fast' is not a valid F32",
        id="bad-f32",
    ),
    pytest.param(
        "stats_tables",
        tsv("stats_tables", "p", STATS_HEADER, [["s1", "1.5", "maybe", "3"]]),
        3,
        "active='maybe' is not a valid Boolean",
        id="bad-boolean",
    ),
    pytest.param(
        "colours_tables",
        tsv("colours_tables", "p", COLOURS_HEADER, [["c1", "E58E3B", "12345"]]),
        3,
        "colour_hex='12345' is not a valid ColourHex",
        id="bad-colour-hex",
    ),
    pytest.param(
        "colours_tables",
        tsv("colours_tables", "p", COLOURS_HEADER, [["c1", "GGGGGG", "112233"]]),
        3,
        "unnamed colour group_1='GGGGGG' is not a valid ColourHex",
        id="non-hex-digits-in-colour",
    ),
    pytest.param(
        "colours_tables",
        tsv("colours_tables", "p", ["key", "r", "g", "b", "colour_r", "colour_g", "colour_b"], []),
        1,
        "missing column(s): unnamed colour group_1, colour_hex",
        id="colour-channels-must-be-one-hex-column",
    ),
]


@pytest.mark.parametrize(("table", "content", "line", "message"), ERROR_CASES)
def test_validate_reports_errors_with_file_and_line(
    sws: Workspace, table: str, content: str, line: int, message: str
) -> None:
    sws.write(f"workspace/p/db/{table}/p.tsv", content)

    result = sws.run("validate", "p")

    assert result.exit_code == 1, result.output
    assert f"db/{table}/p.tsv:{line}: {message}" in result.stderr
    assert "workspace/p:" in result.stderr
    assert "error(s)" in result.stderr


def test_validate_flags_duplicate_keys_across_fragments_of_the_patch(sws: Workspace) -> None:
    put(sws, "workspace/p", "stats_tables", "a", STATS_HEADER, [("s0", "1", "true", "1"), ("s1", "1", "true", "1")])
    put(sws, "workspace/p", "stats_tables", "b", STATS_HEADER, [("s2", "1", "true", "1"), ("s1", "2", "true", "2")])

    result = sws.run("validate", "p")

    assert result.exit_code == 1, result.output
    assert "db/stats_tables/b.tsv:4: duplicate key ['s1'] (also at db/stats_tables/a.tsv:4)" in result.stderr


def test_validate_warns_about_references_found_in_neither_patch_nor_sources(sws: Workspace) -> None:
    factions(sws, "sources/base", "base", "f1")
    units(sws, "workspace/p", "p", ("u1", "f1", "1"), ("u2", "ghost", "1"))

    result = sws.run("validate", "p")

    assert result.exit_code == 0, result.output
    assert "faction='ghost' (row ['u2']) not found in factions_tables.key in this patch or the sources" in (
        result.stderr
    )
    assert "f1'" not in result.stderr
    assert "workspace/p: no errors (1 warning(s))" in result.stdout


def test_validate_resolves_references_against_the_patch_itself(sws: Workspace) -> None:
    factions(sws, "sources/base", "base", "f_other")
    units(sws, "workspace/p", "p", ("u1", "mine", "1"))
    factions(sws, "workspace/p", "p", "mine")

    result = sws.run("validate", "p")

    assert result.exit_code == 0, result.output
    assert "(0 warning(s))" in result.stdout


def test_validate_against_limits_which_sources_references_resolve_in(sws: Workspace) -> None:
    factions(sws, "sources/has_f1", "has_f1", "f1")
    factions(sws, "sources/other", "other", "f2")
    units(sws, "workspace/p", "p", ("u1", "f1", "1"))

    everything = sws.run("validate", "p")
    limited = sws.run("validate", "p", "--against", "other")

    assert "(0 warning(s))" in everything.stdout
    assert limited.exit_code == 0, limited.output
    assert "faction='f1'" in limited.stderr
    assert "(1 warning(s))" in limited.stdout


def test_validate_warns_when_metadata_path_differs_from_the_file_location(sws: Workspace) -> None:
    text = tsv("stats_tables", "elsewhere", STATS_HEADER, [GOOD_ROW.split("\t")])
    sws.write("workspace/p/db/stats_tables/p.tsv", text)

    result = sws.run("validate", "p")

    assert result.exit_code == 0, result.output
    assert "db/stats_tables/p.tsv:2: metadata path 'db/stats_tables/elsewhere' differs from the file location" in (
        result.stderr
    )


def test_validate_warns_about_tables_the_schema_does_not_know(sws: Workspace) -> None:
    put(sws, "workspace/p", "mystery_tables", "p", ["key"], [("m1",)])

    result = sws.run("validate", "p")

    assert result.exit_code == 0, result.output
    assert "mystery_tables is not in the warhammer_3 schema" in result.stderr


def test_validate_json_counts_errors_and_warnings(sws: Workspace) -> None:
    factions(sws, "sources/base", "base", "f1")
    units(sws, "workspace/p", "p", ("u1", "ghost", "1"))
    _stats_patch(sws, [("s1", "1.5", "true", "abc")])

    result = sws.run("validate", "p", "--json")

    assert result.exit_code == 1, result.output
    out = json.loads(result.stdout)
    assert out["patch"] == "workspace/p"
    assert out["schema"].endswith("schema_wh3.ron")
    assert (out["errors"], out["warnings"]) == (1, 1)
    assert sorted((i["level"], i["file"]) for i in out["issues"]) == [
        ("error", "db/stats_tables/p.tsv"),
        ("warning", "db/units_tables/p.tsv"),
    ]
    [error] = [i for i in out["issues"] if i["level"] == "error"]
    assert error["line"] == 3


def test_validate_looks_in_workspace_only(sws: Workspace) -> None:
    units(sws, "sources/only_source", "x", ("u1", "f1", "1"))

    result = sws.run("validate", "only_source")

    assert result.exit_code == 1
    assert "No extracted mod or patch named 'only_source'" in result.stderr
    assert "workspace/" not in result.stderr.split("Known:")[1]  # no patches exist, none are offered


def test_validate_without_a_schema_still_catches_structural_errors(offline_ws: Workspace) -> None:
    offline_ws.write("workspace/p/db/stats_tables/p.tsv", tsv("stats_tables", "p", STATS_HEADER, [["s1", "1"]]))

    result = offline_ws.run("validate", "p")

    assert result.exit_code == 1
    assert "Continuing without key/reference information" in result.stderr
    assert "db/stats_tables/p.tsv:3: 2 cell(s) but 4 columns" in result.stderr


# ---------------------------------------------------------------------- new-patch


def test_new_patch_creates_an_empty_patch(offline_ws: Workspace) -> None:
    result = offline_ws.run("new-patch", "my_patch")

    assert result.exit_code == 0, result.output
    assert "Created" in result.stdout
    assert (offline_ws.workspace / "my_patch" / "db").is_dir()
    assert list((offline_ws.workspace / "my_patch" / "db").iterdir()) == []
    assert "workspace/my_patch" in offline_ws.run("tables").stdout


def test_new_patch_from_copies_the_tables_fragments_byte_for_byte(offline_ws: Workspace) -> None:
    # A BOM, CRLF line endings and no final newline must survive the copy untouched.
    raw = "﻿key\tfaction\tcost\r\n#units_tables;0;db/units_tables/part1\t\t\r\nu1\tf1\t100\r\nu2\tf1\t200".encode()
    part1 = units(offline_ws, "sources/mod_a", "part1", ("u1", "f1", "100"))
    part1.write_bytes(raw)
    part2 = units(offline_ws, "sources/mod_a", "part2", ("u3", "f1", "300"))
    factions(offline_ws, "sources/mod_a", "mod_a", "f1")

    result = offline_ws.run("new-patch", "my_patch", "--from", "mod_a", "-t", "units")

    assert result.exit_code == 0, result.output
    target = offline_ws.workspace / "my_patch" / "db" / "units_tables"
    assert (target / "part1.tsv").read_bytes() == raw
    assert (target / "part2.tsv").read_bytes() == part2.read_bytes()
    assert not (offline_ws.workspace / "my_patch" / "db" / "factions_tables").exists()
    assert "copied db/units_tables/part1.tsv" in result.stdout
    assert "copied db/units_tables/part2.tsv" in result.stdout
    assert part1.read_bytes() == raw  # the source is untouched


def test_new_patch_from_accepts_several_tables_and_qualified_sources(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))
    factions(offline_ws, "sources/mod_a", "mod_a", "f1")
    units(offline_ws, "workspace/mod_a", "mod_a", ("u1", "f1", "999"))

    result = offline_ws.run("new-patch", "my_patch", "--from", "sources/mod_a", "-t", "units", "-t", "factions_tables")

    assert result.exit_code == 0, result.output
    base = offline_ws.workspace / "my_patch" / "db"
    assert sorted(p.name for p in base.iterdir()) == ["factions_tables", "units_tables"]
    assert "999" not in (base / "units_tables" / "mod_a.tsv").read_text(encoding="utf-8")


def test_new_patch_table_without_from_is_an_error(offline_ws: Workspace) -> None:
    result = offline_ws.run("new-patch", "my_patch", "--table", "units")

    assert result.exit_code == 1
    assert "--table needs --from" in result.stderr
    assert not (offline_ws.workspace / "my_patch").exists()


def test_new_patch_from_without_table_is_an_error(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))

    result = offline_ws.run("new-patch", "my_patch", "--from", "mod_a")

    assert result.exit_code == 1
    assert "--from needs at least one --table" in result.stderr
    assert not (offline_ws.workspace / "my_patch").exists()


def test_new_patch_unknown_table_lists_the_mods_tables_and_creates_nothing(offline_ws: Workspace) -> None:
    units(offline_ws, "sources/mod_a", "mod_a", ("u1", "f1", "100"))

    result = offline_ws.run("new-patch", "my_patch", "--from", "mod_a", "-t", "nothing")

    assert result.exit_code == 1
    assert "has no nothing_tables" in result.stderr
    assert "units_tables" in result.stderr
    assert not (offline_ws.workspace / "my_patch").exists()


def test_new_patch_unknown_source_mod(offline_ws: Workspace) -> None:
    result = offline_ws.run("new-patch", "my_patch", "--from", "nope", "-t", "units")

    assert result.exit_code == 1
    assert "No extracted mod or patch named 'nope'" in result.stderr


def test_new_patch_refuses_an_existing_non_empty_patch(offline_ws: Workspace) -> None:
    keep = offline_ws.write("workspace/my_patch/notes.txt", "keep me")

    result = offline_ws.run("new-patch", "my_patch")

    assert result.exit_code == 1
    assert "already exists and is not empty" in result.stderr
    assert keep.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("name", ["../x", "a/b", "..\\x"])
def test_new_patch_rejects_names_that_escape_the_workspace(offline_ws: Workspace, name: str) -> None:
    result = offline_ws.run("new-patch", name)

    assert result.exit_code == 1
    assert "Invalid patch mod name" in result.stderr
    assert not (offline_ws.root / "x").exists()


# ---------------------------------------------------------------------- repack validation


def _no_pack_was_created(rpfm: FakeRPFM) -> bool:
    return not any(c in rpfm.commands() for c in ("NewPack", "pack.new"))


def test_repack_does_not_repack_a_patch_that_fails_validation(ws: Workspace, rpfm: FakeRPFM) -> None:
    install_schema(ws)
    _stats_patch(ws, [("s1", "1.5", "true", "abc")], name="my_patch")

    result = ws.run("repack", "--patch", "my_patch")

    assert result.exit_code == 1
    assert "db/stats_tables/my_patch.tsv:3: count='abc' is not a valid I32" in result.stderr
    assert "Not repacking: 1 validation error(s)" in result.stderr
    assert not (ws.output / "my_patch.pack").exists()
    assert _no_pack_was_created(rpfm)


def test_repack_no_validate_repacks_the_invalid_patch_anyway(ws: Workspace, rpfm: FakeRPFM) -> None:
    install_schema(ws)
    _stats_patch(ws, [("s1", "1.5", "true", "abc")], name="my_patch")

    result = ws.run("repack", "--patch", "my_patch", "--no-validate")

    assert result.exit_code == 0, result.output
    assert "Not repacking" not in result.output
    assert list(read_pack(ws.output / "my_patch.pack")) == ["db/stats_tables/my_patch"]
    assert not _no_pack_was_created(rpfm)


def test_repack_goes_ahead_when_validation_only_warns(ws: Workspace) -> None:
    install_schema(ws)
    factions(ws, "sources/base", "base", "f1")
    units(ws, "workspace/my_patch", "my_patch", ("u1", "ghost", "1"))

    result = ws.run("repack", "--patch", "my_patch")

    assert result.exit_code == 0, result.output
    assert "faction='ghost'" in result.stderr
    assert (ws.output / "my_patch.pack").exists()
