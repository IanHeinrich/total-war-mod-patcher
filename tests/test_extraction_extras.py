"""Outside-in tests of the extraction extras: vanilla db.pack, --table filtering,
loc files, Workshop IDs, staleness tracking (``status``) and ``extract --refresh``."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .conftest import GAME, Workspace, tsv
from .fake_rpfm import FakeRPFM, read_pack, write_pack

APP_ID = "1142710"

UNITS = tsv("units_tables", "mod_a", ["key", "cost"], [["unit_a", "800"], ["unit_b", "600"]])
FACTIONS = tsv("factions_tables", "mod_a", ["key", "name"], [["fac_a", "Faction A"]])
LAND_UNITS = tsv("land_units_tables", "data__", ["key", "num_men"], [["wh_inf", "120"]])
LOC = "key\ttext\ttooltip\n#Loc;1;text/db/mod_a.loc\t\t\nunits_name_unit_a\tUnit A\tfalse\n"
SCRIPT = "-- mod_a script\n"


def make_pack(ws: Workspace, name: str = "mod_a.pack", files: dict[str, str] | None = None) -> Path:
    return write_pack(
        ws.root / "packs" / name,
        files
        or {
            "db/units_tables/mod_a": UNITS,
            "db/factions_tables/mod_a": FACTIONS,
            "script/campaign/mod/mod_a.lua": SCRIPT,
            "text/db/mod_a.loc": LOC,
        },
    )


def configure_game(ws: Workspace, tmp_path: Path, workshop: bool = True, db_pack: bool = True) -> Path:
    """A Steam-like layout: <steamapps>/common/<game>/data and <steamapps>/workshop/content/<app id>."""
    steamapps = tmp_path / "steam" / "steamapps"
    game_dir = steamapps / "common" / "Total War WARHAMMER III"
    (game_dir / "data").mkdir(parents=True)
    if db_pack:
        write_pack(
            game_dir / "data" / "db.pack",
            {
                "db/land_units_tables/data__": LAND_UNITS,
                "db/units_tables/data__": tsv("units_tables", "data__", ["key", "cost"], [["vanilla_unit", "500"]]),
                "db/factions_tables/data__": tsv("factions_tables", "data__", ["key", "name"], [["wh_main", "E"]]),
            },
        )
    if workshop:
        (steamapps / "workshop" / "content" / APP_ID).mkdir(parents=True)
    config = {"selected_game": GAME, "modding_root": str(ws.root), "game_dirs": {GAME: str(game_dir)}}
    (ws.home / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return steamapps


def export_calls(rpfm: FakeRPFM) -> int:
    return sum(1 for name in rpfm.commands() if name in ("ExportTSV", "table.export_tsv"))


def source_info(ws: Workspace, mod: str) -> dict:
    return json.loads((ws.sources / mod / ".tw-source.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- vanilla


def test_extract_vanilla_exports_only_the_requested_tables(ws: Workspace, rpfm: FakeRPFM, tmp_path: Path) -> None:
    configure_game(ws, tmp_path)

    result = ws.run("extract", "--vanilla", "--table", "land_units")

    assert result.exit_code == 0, result.output
    vanilla = ws.sources / "vanilla"
    assert (vanilla / "db/land_units_tables/data__.tsv").read_text(encoding="utf-8") == LAND_UNITS
    assert not (vanilla / "db/units_tables").exists()
    assert export_calls(rpfm) == 1, "unwanted tables must not be exported at all"
    assert source_info(ws, "vanilla")["table_filter"] == ["land_units_tables"]


def test_extract_vanilla_without_a_game_dir_explains(ws: Workspace) -> None:
    result = ws.run("extract", "--vanilla")

    assert result.exit_code == 1
    assert "No game directory configured" in result.stderr


def test_extract_vanilla_without_db_pack_explains(ws: Workspace, tmp_path: Path) -> None:
    configure_game(ws, tmp_path, db_pack=False)

    result = ws.run("extract", "--vanilla")

    assert result.exit_code == 1
    assert "Vanilla db.pack not found" in result.stderr


def test_vanilla_does_not_count_toward_the_pack_limit(ws: Workspace, tmp_path: Path) -> None:
    configure_game(ws, tmp_path)
    args = [arg for i in range(6) for arg in ("-s", str(make_pack(ws, f"mod_{i}.pack")))]

    result = ws.run("extract", *args, "--vanilla", "--dry-run")

    assert result.exit_code == 0, result.output
    assert "db.pack" in result.stdout
    assert str(ws.sources / "vanilla") in result.stdout
    assert result.stdout.count("loc files") == 7


def test_table_filter_applies_to_source_packs(ws: Workspace) -> None:
    pack = make_pack(ws)

    result = ws.run("extract", "-s", str(pack), "-t", "units_tables", "-t", "no_such")

    assert result.exit_code == 0, result.output
    mod_dir = ws.sources / "mod_a"
    assert (mod_dir / "db/units_tables/mod_a.tsv").exists()
    assert not (mod_dir / "db/factions_tables").exists()
    assert "No pack contained a no_such_tables table" in result.stderr


# ---------------------------------------------------------------------- loc files


def test_extract_exports_loc_files_and_counts_them(ws: Workspace) -> None:
    pack = make_pack(ws)

    result = ws.run("extract", "-s", str(pack))

    assert result.exit_code == 0, result.output
    assert (ws.sources / "mod_a/text/db/mod_a.tsv").read_text(encoding="utf-8") == LOC
    assert "2 tables, 1 scripts, 1 loc files" in result.stdout
    assert "mod_a/: 2 tables, 1 scripts, 1 loc files" in (ws.sources / "README.txt").read_text()


def test_repack_imports_loc_tsvs_as_loc_files(ws: Workspace) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    ws.write("workspace/my_patch/text/db/my_patch.tsv", LOC)

    result = ws.run("repack", "--patch", "my_patch")

    assert result.exit_code == 0, result.output
    assert read_pack(ws.output / "my_patch.pack") == {
        "db/units_tables/my_patch": UNITS,
        "text/db/my_patch.loc": LOC,
    }


# ---------------------------------------------------------------------- workshop


def test_extract_by_workshop_id_extracts_every_pack_in_the_item(ws: Workspace, tmp_path: Path) -> None:
    steamapps = configure_game(ws, tmp_path)
    item = steamapps / "workshop" / "content" / APP_ID / "2789857397"
    write_pack(item / "sfo_main.pack", {"db/units_tables/sfo": UNITS})
    write_pack(item / "sfo_extra.pack", {"db/factions_tables/sfo": FACTIONS})

    result = ws.run("extract", "--workshop-id", "2789857397")

    assert result.exit_code == 0, result.output
    assert (ws.sources / "sfo_main/db/units_tables/sfo.tsv").exists()
    assert (ws.sources / "sfo_extra/db/factions_tables/sfo.tsv").exists()
    assert source_info(ws, "sfo_main")["workshop_id"] == "2789857397"


def test_workshop_id_without_a_workshop_folder_explains(ws: Workspace, tmp_path: Path) -> None:
    configure_game(ws, tmp_path, workshop=False)

    result = ws.run("extract", "--workshop-id", "123")

    assert result.exit_code == 1
    assert "No Steam Workshop folder found" in result.stderr


def test_workshop_item_without_a_pack_explains(ws: Workspace, tmp_path: Path) -> None:
    steamapps = configure_game(ws, tmp_path)
    (steamapps / "workshop" / "content" / APP_ID / "123").mkdir()

    result = ws.run("extract", "--workshop-id", "123")

    assert result.exit_code == 1
    assert "Workshop item 123 has no .pack file" in result.stderr


# ---------------------------------------------------------------------- staleness


def test_extract_records_where_each_source_came_from(ws: Workspace) -> None:
    pack = make_pack(ws)

    result = ws.run("extract", "-s", str(pack))

    assert result.exit_code == 0, result.output
    info = source_info(ws, "mod_a")
    assert info["pack"] == str(pack.resolve())
    assert info["size"] == pack.stat().st_size
    assert info["mtime"] == pack.stat().st_mtime
    assert info["workshop_id"] is None
    assert (info["tables"], info["scripts"], info["locs"]) == (2, 1, 1)
    assert info["extracted_at"] and info["tw_patcher_version"]


def _tracked_source(ws: Workspace, name: str, pack: Path, size: int, mtime: float) -> None:
    ws.write(f"sources/{name}/db/units_tables/{name}.tsv", UNITS)
    info = {"pack": str(pack), "size": size, "mtime": mtime, "extracted_at": "2026-01-01T00:00:00+00:00"}
    ws.write(f"sources/{name}/.tw-source.json", json.dumps(info))


def test_status_reports_each_sources_state(offline_ws: Workspace) -> None:
    ws = offline_ws
    current = ws.write("packs/current.pack", "same")
    changed = ws.write("packs/changed.pack", "old")
    _tracked_source(ws, "current", current, current.stat().st_size, current.stat().st_mtime)
    _tracked_source(ws, "changed", changed, changed.stat().st_size + 5, changed.stat().st_mtime)
    _tracked_source(ws, "missing", ws.root / "packs" / "gone.pack", 1, 1.0)
    ws.write("sources/untracked/db/units_tables/untracked.tsv", UNITS)

    result = ws.run("status")

    assert result.exit_code == 0, result.output
    assert "current: current" in result.stdout
    assert "changed: changed" in result.stdout
    assert "missing: missing" in result.stdout
    assert "untracked: unknown" in result.stdout
    assert "Summary: 1 current, 1 changed, 1 missing, 1 unknown" in result.stdout

    data = json.loads(ws.run("status", "--json").stdout)
    assert {s["name"]: s["state"] for s in data["sources"]} == {
        "changed": "changed",
        "current": "current",
        "missing": "missing",
        "untracked": "unknown",
    }
    assert data["summary"] == {"current": 1, "changed": 1, "missing": 1, "unknown": 1}


def test_status_with_no_sources_exits_zero(offline_ws: Workspace) -> None:
    result = offline_ws.run("status")

    assert result.exit_code == 0, result.output
    assert "No extracted sources" in result.stderr


def test_refresh_reextracts_changed_sources_and_summarises_patch_tables(ws: Workspace) -> None:
    pack = make_pack(ws)
    assert ws.run("extract", "-s", str(pack)).exit_code == 0
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    new_units = tsv("units_tables", "mod_a", ["key", "cost"], [["unit_a", "900"], ["unit_b", "600"], ["unit_c", "1"]])
    new_factions = tsv("factions_tables", "mod_a", ["key", "name"], [["fac_b", "Faction B"]])
    make_pack(ws, files={"db/units_tables/mod_a": new_units, "db/factions_tables/mod_a": new_factions})
    os.utime(pack, (pack.stat().st_atime, pack.stat().st_mtime + 10))

    assert "mod_a: changed" in ws.run("status").stdout

    dry = ws.run("extract", "--refresh", "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "mod_a" in dry.stdout
    assert (ws.sources / "mod_a/db/units_tables/mod_a.tsv").read_text(encoding="utf-8") == UNITS

    result = ws.run("extract", "--refresh")

    assert result.exit_code == 0, result.output
    assert (ws.sources / "mod_a/db/units_tables/mod_a.tsv").read_text(encoding="utf-8") == new_units
    # No schema installed, so a row is keyed by its whole content: unit_a's new cost is a removed + added row.
    assert "units_tables: +2 -1 ~0" in result.stdout
    assert "factions_tables" not in result.stdout, "only tables a patch also has are summarised"
    assert not any(p.name.startswith(".") for p in ws.sources.iterdir()), "the old copy is cleaned up"
    assert "mod_a: current" in ws.run("status").stdout


def test_refresh_with_nothing_changed_does_nothing(ws: Workspace, rpfm: FakeRPFM) -> None:
    pack = make_pack(ws)
    assert ws.run("extract", "-s", str(pack)).exit_code == 0
    calls_before = len(rpfm.calls)

    result = ws.run("extract", "--refresh")

    assert result.exit_code == 0, result.output
    assert "Nothing to refresh" in result.stdout
    assert len(rpfm.calls) == calls_before


def test_refresh_cannot_be_combined_with_sources(ws: Workspace) -> None:
    pack = make_pack(ws)

    result = ws.run("extract", "--refresh", "-s", str(pack))

    assert result.exit_code == 1
    assert "don't combine it with --source" in result.stderr
