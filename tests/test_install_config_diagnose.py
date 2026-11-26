"""Outside-in tests of `repack --install`, the config setters and `diagnose`."""

from __future__ import annotations

import json
from pathlib import Path

from .conftest import GAME, Workspace, tsv
from .fake_rpfm import FakeRPFM, read_pack, write_pack

UNITS = tsv("units_tables", "my_patch", ["key", "cost"], [["unit_a", "800"]])

BAD_REFERENCE = {
    "path": "db/units_tables/my_patch",
    "checked": "db",
    "report_type": "InvalidReference",
    "level": "error",
    "message": "Invalid reference to land_units_tables: unit_a",
    "cells": [[0, 0]],
    "columns": ["key"],
}
OUTDATED = {
    "path": "db/units_tables/my_patch",
    "checked": "db",
    "report_type": "OutdatedTable",
    "level": "warning",
    "message": "Table is outdated",
}
NO_ICON = {"path": "", "checked": "pack", "report_type": "MissingPackIcon", "level": "info", "message": "No icon"}


def configure_game_dir(ws: Workspace, game_dir: Path, game: str = GAME) -> None:
    config_file = ws.home / "config.json"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    data["game_dirs"] = {game: str(game_dir)}
    config_file.write_text(json.dumps(data), encoding="utf-8")


def make_game_dir(tmp_path: Path) -> Path:
    game_dir = tmp_path / "game"
    (game_dir / "data").mkdir(parents=True)
    return game_dir


def read_config(ws: Workspace) -> dict:
    return json.loads((ws.home / "config.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- repack --install


def test_repack_install_copies_the_pack_into_data(ws: Workspace, tmp_path: Path) -> None:
    game_dir = make_game_dir(tmp_path)
    configure_game_dir(ws, game_dir)
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)

    result = ws.run("repack", "--patch", "my_patch", "--install")

    assert result.exit_code == 0, result.output
    installed = game_dir / "data" / "my_patch.pack"
    assert read_pack(installed) == {"db/units_tables/my_patch": UNITS}
    assert installed.read_bytes() == (ws.output / "my_patch.pack").read_bytes()
    assert str(installed) in result.stdout


def test_repack_install_replaces_an_existing_pack(ws: Workspace, tmp_path: Path) -> None:
    game_dir = make_game_dir(tmp_path)
    configure_game_dir(ws, game_dir)
    write_pack(game_dir / "data" / "my_patch.pack", {"db/old_tables/x": "old"})
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)

    result = ws.run("repack", "--patch", "my_patch", "--install")

    assert result.exit_code == 0, result.output
    assert "Replaced my_patch.pack in data/" in result.stdout
    assert read_pack(game_dir / "data" / "my_patch.pack") == {"db/units_tables/my_patch": UNITS}


def test_repack_install_without_a_game_dir_keeps_the_built_pack(ws: Workspace) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)

    result = ws.run("repack", "--patch", "my_patch", "--install")

    assert result.exit_code == 1
    assert "Not installed" in result.stderr
    assert "set-game-dir" in result.stdout
    assert read_pack(ws.output / "my_patch.pack") == {"db/units_tables/my_patch": UNITS}


# ---------------------------------------------------------------------- config


def test_set_modding_root_creates_and_saves_it(offline_ws: Workspace, tmp_path: Path) -> None:
    new_root = tmp_path / "elsewhere" / "modding"

    result = offline_ws.run("config", "set-modding-root", str(new_root))

    assert result.exit_code == 0, result.output
    assert new_root.is_dir()
    assert read_config(offline_ws)["modding_root"] == str(new_root.resolve())
    shown = offline_ws.run("config", "show")
    assert str(new_root.resolve() / "workspace") in shown.stdout


def test_set_game_dir_requires_a_data_folder(offline_ws: Workspace, tmp_path: Path) -> None:
    not_a_game = tmp_path / "not_a_game"
    not_a_game.mkdir()

    result = offline_ws.run("config", "set-game-dir", str(not_a_game))

    assert result.exit_code == 1
    assert "no data/ folder" in result.stderr
    assert "game_dirs" not in read_config(offline_ws)


def test_set_game_dir_saves_for_the_selected_or_given_game(offline_ws: Workspace, tmp_path: Path) -> None:
    game_dir = make_game_dir(tmp_path)

    selected = offline_ws.run("config", "set-game-dir", str(game_dir))
    other = offline_ws.run("config", "set-game-dir", "--game", "attila", str(game_dir))

    assert selected.exit_code == 0, selected.output
    assert other.exit_code == 0, other.output
    assert read_config(offline_ws)["game_dirs"] == {GAME: str(game_dir.resolve()), "attila": str(game_dir.resolve())}
    shown = offline_ws.run("config", "show")
    assert f"Game data folder: {game_dir.resolve() / 'data'}" in shown.stdout


def test_config_show_lists_resolved_folders(offline_ws: Workspace) -> None:
    result = offline_ws.run("config", "show")

    assert result.exit_code == 0, result.output
    for folder in (offline_ws.sources, offline_ws.workspace, offline_ws.output):
        assert str(folder) in result.stdout
    assert "Game data folder: (not set)" in result.stdout
    assert "Schema folder:    (RPFM default)" in result.stdout


def test_config_show_json(offline_ws: Workspace, tmp_path: Path) -> None:
    game_dir = make_game_dir(tmp_path)
    configure_game_dir(offline_ws, game_dir)

    result = offline_ws.run("config", "show", "--json")

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["selected_game"] == GAME
    assert data["workspace_dir"] == str(offline_ws.workspace)
    assert data["game_data_dir"] == str(game_dir / "data")
    assert data["schema_dir"] is None


# ---------------------------------------------------------------------- diagnose


def test_diagnose_patch_reports_problems_grouped_by_path(ws: Workspace, rpfm: FakeRPFM) -> None:
    ws.write("workspace/my_patch/db/units_tables/my_patch.tsv", UNITS)
    rpfm.diagnostics = [BAD_REFERENCE, OUTDATED, NO_ICON]

    result = ws.run("diagnose", "--patch", "my_patch")

    assert result.exit_code == 1
    if rpfm.dialect == "legacy":
        assert "RPFM diagnostics need RPFM 5 or newer" in result.stderr
        return
    assert "db/units_tables/my_patch" in result.stdout
    assert "error   InvalidReference: Invalid reference to land_units_tables: unit_a [columns: key]" in result.stdout
    assert "warning OutdatedTable: Table is outdated" in result.stdout
    assert "(whole pack)" in result.stdout
    assert "1 error(s), 1 warning(s), 1 info(s)" in result.stderr
    assert "dependencies.rebuild" in rpfm.commands(), "dependencies are loaded before checking"
    assert rpfm.open_handles == []
    assert not list(ws.output.glob("*.pack")), "the temporary pack is not left in output/"


def test_diagnose_pack_with_only_warnings_passes(ws: Workspace, rpfm: FakeRPFM) -> None:
    pack = write_pack(ws.root / "packs" / "mod_a.pack", {"db/units_tables/my_patch": UNITS})
    rpfm.diagnostics = [OUTDATED]

    result = ws.run("diagnose", "--pack", str(pack))

    if rpfm.dialect == "legacy":
        assert result.exit_code == 1
        assert "RPFM diagnostics need RPFM 5 or newer" in result.stderr
        return
    assert result.exit_code == 0, result.output
    assert "OutdatedTable" in result.stdout
    assert rpfm.game == GAME
    assert rpfm.open_handles == []


def test_diagnose_level_filters_lower_levels(ws: Workspace, rpfm: FakeRPFM) -> None:
    if rpfm.dialect == "legacy":
        return
    pack = write_pack(ws.root / "packs" / "mod_a.pack", {"db/units_tables/my_patch": UNITS})
    rpfm.diagnostics = [OUTDATED, NO_ICON]

    result = ws.run("diagnose", "--pack", str(pack), "--level", "error")

    assert result.exit_code == 0, result.output
    assert "No problems reported" in result.stdout
    assert "OutdatedTable" not in result.stdout


def test_diagnose_json(ws: Workspace, rpfm: FakeRPFM) -> None:
    if rpfm.dialect == "legacy":
        return
    pack = write_pack(ws.root / "packs" / "mod_a.pack", {"db/units_tables/my_patch": UNITS})
    rpfm.diagnostics = [BAD_REFERENCE, NO_ICON]

    result = ws.run("diagnose", "--pack", str(pack), "--json")

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["counts"] == {"error": 1, "warning": 0, "info": 1}
    assert data["diagnostics"][0] == {
        "path": "db/units_tables/my_patch",
        "level": "error",
        "report_type": "InvalidReference",
        "message": "Invalid reference to land_units_tables: unit_a",
        "columns": ["key"],
        "cells": [[0, 0]],
    }


def test_diagnose_explains_missing_dependencies(ws: Workspace, rpfm: FakeRPFM) -> None:
    if rpfm.dialect == "legacy":
        return
    pack = write_pack(ws.root / "packs" / "mod_a.pack", {"db/units_tables/my_patch": UNITS})
    rpfm.dependencies_error = "dependencies cache is outdated"

    result = ws.run("diagnose", "--pack", str(pack))

    assert result.exit_code == 1
    assert "dependencies cache is outdated" in result.stderr
    assert "Generate Dependencies Cache" in result.stderr
    assert rpfm.open_handles == []


def test_diagnose_needs_exactly_one_target(offline_ws: Workspace) -> None:
    result = offline_ws.run("diagnose")

    assert result.exit_code == 1
    assert "exactly one of --pack or --patch" in result.stderr
