"""Outside-in tests of the tw-patcher CLI as it behaves today.

Each test runs ``python -m tw_patcher`` in a subprocess against a temporary
modding root and the fake RPFM server, and asserts only on what a user sees:
exit code, output, and files on disk (including the contents of packs).
"""

from __future__ import annotations

import re
from pathlib import Path

from .conftest import GAME, Workspace, tsv
from .fake_rpfm import FakeRPFM, read_pack, write_pack

ROOT = Path(__file__).resolve().parent.parent

UNITS = tsv(
    "units_tables",
    "mod_a",
    ["key", "cost"],
    [["unit_a", "800"], ["unit_b", "600"]],
)
FACTIONS = tsv("factions_tables", "mod_a", ["key", "name"], [["fac_a", "Faction A"]])
SCRIPT = "-- mod_a script\nout('hello')\n"


def make_source_pack(ws: Workspace, name: str = "mod_a.pack") -> Path:
    return write_pack(
        ws.root / "packs" / name,
        {
            "db/units_tables/mod_a": UNITS,
            "db/factions_tables/mod_a": FACTIONS,
            "script/campaign/mod/mod_a.lua": SCRIPT,
            "ui/skins/ignored.png": "binary-ish",
        },
    )


# ---------------------------------------------------------------------- basics


def test_help_works_when_output_is_captured(ws: Workspace) -> None:
    # Regression: on Windows a piped stdout is cp1252 and the help's arrows crashed it.
    result = ws.run("--help")
    assert result.exit_code == 0, result.output
    for command in ("extract", "repack", "replace-table", "list", "clean", "scaffold"):
        assert command in result.stdout


def test_version_matches_pyproject(ws: Workspace) -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert match
    expected = match.group(1)
    result = ws.run("--version")
    assert result.exit_code == 0, result.output
    assert expected in result.stdout


def test_config_show_reports_isolated_config(ws: Workspace) -> None:
    result = ws.run("config", "show")
    assert result.exit_code == 0, result.output
    assert GAME in result.stdout
    assert str(ws.home / "config.json") in result.stdout


def test_list_shows_patches_and_table_counts(ws: Workspace) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    ws.write("workspace/my_patch/db/factions_tables/my_patch.tsv", FACTIONS)
    ws.write("workspace/empty_patch/.keep", "")

    result = ws.run("list")

    assert result.exit_code == 0, result.output
    assert "my_patch/ — 2 table(s)" in result.stdout
    assert "empty_patch/ — 0 table(s)" in result.stdout


# ---------------------------------------------------------------------- extract


def test_extract_writes_tables_and_scripts(ws: Workspace, rpfm: FakeRPFM) -> None:
    pack = make_source_pack(ws)

    result = ws.run("extract", "-s", str(pack))

    assert result.exit_code == 0, result.output
    mod_dir = ws.sources / "mod_a"
    assert (mod_dir / "db/units_tables/mod_a.tsv").read_text(encoding="utf-8") == UNITS
    assert (mod_dir / "db/factions_tables/mod_a.tsv").read_text(encoding="utf-8") == FACTIONS
    assert (mod_dir / "script/campaign/mod/mod_a.lua").read_text(encoding="utf-8") == SCRIPT
    assert not (mod_dir / "ui").exists(), "only db/ and script/ are extracted"
    assert "mod_a/: 2 tables, 1 scripts" in (ws.sources / "README.txt").read_text()
    assert rpfm.game == GAME


def test_extract_replaces_a_previous_extraction(ws: Workspace) -> None:
    pack = make_source_pack(ws)
    stale = ws.write("sources/mod_a/db/old_tables/gone.tsv", "stale")

    result = ws.run("extract", "-s", str(pack))

    assert result.exit_code == 0, result.output
    assert not stale.exists()


def test_extract_rejects_more_than_six_packs(ws: Workspace) -> None:
    packs = [str(make_source_pack(ws, f"mod_{i}.pack")) for i in range(7)]
    args = [arg for p in packs for arg in ("-s", p)]

    result = ws.run("extract", *args)

    assert result.exit_code == 1
    assert "Maximum 6" in result.output


# ---------------------------------------------------------------------- repack


def test_repack_builds_a_pack_from_the_workspace(ws: Workspace) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    ws.write("workspace/my_patch/script/campaign/mod/my_patch.lua", SCRIPT)

    result = ws.run("repack", "--patch", "my_patch")

    assert result.exit_code == 0, result.output
    files = read_pack(ws.output / "my_patch.pack")
    assert files == {
        "db/units_tables/my_patch": UNITS,
        "script/campaign/mod/my_patch.lua": SCRIPT,
    }


def test_repack_honours_custom_name(ws: Workspace) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)

    result = ws.run("repack", "--patch", "my_patch", "--name", "!my_patch_first")

    assert result.exit_code == 0, result.output
    assert (ws.output / "!my_patch_first.pack").exists()


def test_repack_unknown_patch_lists_available(ws: Workspace) -> None:
    ws.write("workspace/real_patch/db/units_tables/x.tsv", UNITS)

    result = ws.run("repack", "--patch", "nope")

    assert result.exit_code == 1
    assert "Patch mod 'nope' not found" in result.output
    assert "real_patch" in result.output


def test_repack_reports_rpfm_failure(ws: Workspace, rpfm: FakeRPFM) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    rpfm.fail("AddPackedFiles", "units_tables", "schema mismatch")

    result = ws.run("repack", "--patch", "my_patch")

    assert result.exit_code == 1
    assert "Repacking failed" in result.output
    assert not (ws.output / "my_patch.pack").exists()


# ---------------------------------------------------------------------- replace-table


def test_replace_table_to_new_file_leaves_original_untouched(ws: Workspace) -> None:
    pack = make_source_pack(ws)
    original = read_pack(pack)
    fixed = tsv("units_tables", "mod_a", ["key", "cost"], [["unit_a", "1"]])
    fix_file = ws.write("fix.tsv", fixed)
    out = ws.output / "mod_a_fixed.pack"

    result = ws.run("replace-table", "-p", str(pack), "-t", str(fix_file), "-o", str(out))

    assert result.exit_code == 0, result.output
    assert read_pack(out) == {**original, "db/units_tables/mod_a": fixed}
    assert read_pack(pack) == original


def test_replace_table_in_place(ws: Workspace) -> None:
    pack = make_source_pack(ws)
    fixed = tsv("factions_tables", "mod_a", ["key", "name"], [["fac_a", "Renamed"]])

    result = ws.run("replace-table", "-p", str(pack), "-t", str(ws.write("fix.tsv", fixed)))

    assert result.exit_code == 0, result.output
    assert read_pack(pack)["db/factions_tables/mod_a"] == fixed


def test_replace_table_rejects_tsv_without_metadata(ws: Workspace) -> None:
    pack = make_source_pack(ws)
    bad = ws.write("bad.tsv", "key\tcost\nunit_a\t1\n")

    result = ws.run("replace-table", "-p", str(pack), "-t", str(bad))

    assert result.exit_code == 1
    assert "line 2 must start with '#'" in result.output


# ---------------------------------------------------------------------- scaffold / clean


def test_scaffold_creates_layout_and_ai_docs(ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "new_project"

    result = ws.run("scaffold", "--target", str(target))

    assert result.exit_code == 0, result.output
    for rel in ("sources", "workspace", "output", "modding_docs/WORKFLOW.md", "CLAUDE.md", ".cursorrules"):
        assert (target / rel).exists(), rel


def test_scaffold_keeps_existing_files(ws: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "new_project"
    target.mkdir()
    (target / "CLAUDE.md").write_text("my own notes", encoding="utf-8")

    result = ws.run("scaffold", "--target", str(target))

    assert result.exit_code == 0, result.output
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "my own notes"


def test_clean_empties_sources_and_output_but_not_workspace(ws: Workspace) -> None:
    ws.write("sources/mod_a/db/x.tsv", UNITS)
    ws.write("output/old.pack", "{}")
    patch = ws.write("workspace/my_patch/db/units_tables/x.tsv", UNITS)

    result = ws.run("clean")

    assert result.exit_code == 0, result.output
    assert list(ws.sources.iterdir()) == []
    assert list(ws.output.iterdir()) == []
    assert patch.exists()
